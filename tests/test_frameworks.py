from agent.lib.frameworks import load_frameworks, is_framework


def test_catalog_has_expected_frameworks_per_ecosystem():
    cat = load_frameworks()
    assert "laravel/framework" in cat["composer"]
    assert "react" in cat["npm"] and "next" in cat["npm"] and "@nestjs/core" in cat["npm"]
    assert "django" in cat["python"] and "celery" in cat["python"]


def test_is_framework_case_insensitive_and_scoped_by_ecosystem():
    cat = load_frameworks()
    assert is_framework("composer", "Laravel/Framework", cat) is True     # case-insensitive
    assert is_framework("npm", "@nestjs/core", cat) is True
    assert is_framework("npm", "axios", cat) is False                     # a library, not a framework
    assert is_framework("composer", "react", cat) is False               # react is npm, not composer


def test_is_framework_loads_default_catalog_when_none():
    assert is_framework("npm", "express") is True                        # no catalog arg -> default
    assert is_framework("python", "requests") is False
