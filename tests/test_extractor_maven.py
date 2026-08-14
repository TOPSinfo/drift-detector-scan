import pytest
from agent.lib.extractors import maven, extractor_for

# Real POMs carry the 4.0.0 namespace on EVERY tag. A namespace-blind parser matching
# bare `dependency` finds nothing here — which is why the fixture is namespaced.
POM = '''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.acme</groupId>
  <artifactId>shop</artifactId>
  <version>1.0.0</version>

  <properties>
    <jackson.version>2.15.2</jackson.version>
    <maven.compiler.source>17</maven.compiler.source>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-core</artifactId>
      <version>5.3.30</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>${jackson.version}</version>
    </dependency>
    <dependency>
      <groupId>org.apache.commons</groupId>
      <artifactId>commons-lang3</artifactId>
      <version>${undefined.version}</version>
    </dependency>
    <dependency>
      <groupId>junit</groupId>
      <artifactId>junit</artifactId>
      <version>4.13.2</version>
      <scope>test</scope>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-dependencies</artifactId>
      <version>3.2.0</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</project>
'''


def test_maven_registered():
    assert extractor_for("a/pom.xml") is maven.extract


def test_maven_extracts_compile_deps_and_skips_test_scope():
    """`scope=test` is the build's own tooling, not what this application ships — the same
    reason npm devDependencies and go `// indirect` are excluded."""
    by_key = {r.name: r for r in maven.extract("clients/a", "pom.xml", POM)
              if r.kind == "library"}
    assert "org.springframework:spring-core" in by_key
    assert "junit:junit" not in by_key
    assert by_key["org.springframework:spring-core"].declared_range == "5.3.30"
    assert by_key["org.springframework:spring-core"].ecosystem == "maven"


def test_maven_skips_bom_imports():
    """`type=pom` + `scope=import` is a BOM: a version manifest, not a package that ships.
    Auditing it would report a CVE against something no code links to."""
    names = {r.name for r in maven.extract("clients/a", "pom.xml", POM)}
    assert "org.springframework.boot:spring-boot-dependencies" not in names


def test_maven_resolves_properties_from_this_pom_only():
    by_key = {r.name: r for r in maven.extract("clients/a", "pom.xml", POM)}
    jackson = by_key["com.fasterxml.jackson.core:jackson-databind"]
    assert jackson.declared_range == "2.15.2"        # ${jackson.version} resolved locally


def test_maven_keeps_unresolved_properties_raw_as_best_effort():
    """An unresolved ${...} usually lives in a parent POM we deliberately do not fetch.
    Keeping the raw string and downgrading parse_quality says 'we could not resolve this'
    — guessing a version would invent a fact about the repo."""
    by_key = {r.name: r for r in maven.extract("clients/a", "pom.xml", POM)}
    commons = by_key["org.apache.commons:commons-lang3"]
    assert commons.declared_range == "${undefined.version}"
    assert commons.parse_quality == "best_effort"


def test_maven_purl_uses_a_slash_between_group_and_artifact():
    """pkg:maven/org.foo/bar@1 — NOT pkg:maven/org.foo:bar@1. Our inventory name carries a
    colon; the PURL spec does not. OSV will not match the colon form."""
    from agent.lib.purl import osv_ecosystem, to_purl
    assert osv_ecosystem("maven") == "Maven"
    assert to_purl("maven", "org.springframework:spring-core", "5.3.30") == \
        "pkg:maven/org.springframework/spring-core@5.3.30"


def test_maven_pom_with_no_dependencies_is_empty_of_libraries():
    bare = ('<project xmlns="http://maven.apache.org/POM/4.0.0">'
            '<artifactId>x</artifactId></project>')
    assert [r for r in maven.extract("clients/a", "pom.xml", bare) if r.kind == "library"] == []


def test_maven_invalid_xml_raises_valueerror():
    with pytest.raises(ValueError):
        maven.extract("clients/a", "pom.xml", "<project><unclosed>")
