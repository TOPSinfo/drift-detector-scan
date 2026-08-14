"""Gemfile.lock extractor: directly-declared gems + the Ruby runtime.

A Bundler repo produced NO inventory records, so its Supply Chain plane was silently
empty. We parse the LOCK, never the Gemfile: a Gemfile is a Ruby DSL that can only be
read by running it, while Gemfile.lock is structured text with resolved versions.

Two sections are joined:
  DEPENDENCIES  what this repo actually declares  -> the set we report
  GEM specs     what Bundler resolved             -> where the exact version comes from

A gem present in the specs but absent from DEPENDENCIES is transitive — excluded for the
same reason go `// indirect` and npm devDependencies are, since reporting it attributes
another gem's choices to this repo.

Indentation is load-bearing in the specs block:

    specs:
      rails (7.1.3)          <- 4 spaces: a SPEC, with its resolved version
        actionpack (= 7.1.3) <- 6 spaces: rails' OWN requirement, not a spec

A parser that ignores the indent reads that second line as a spec whose version is
"= 7.1.3", and silently poisons the version of a real gem.
"""
from __future__ import annotations

import re

from agent.lib.inventory_models import InventoryRecord, library_techkey
from agent.lib.extractors import register

# A spec line: exactly 4 leading spaces, `name (1.2.3)`.
_SPEC = re.compile(r"^ {4}(\S+) \(([^)]+)\)\s*$")
# A DEPENDENCIES entry: 2 spaces, `name`, optional ` (requirement)`, optional trailing `!`.
_DEP = re.compile(r"^ {2}(\S+?)!?(?: \([^)]*\))?!?\s*$")
_RUBY = re.compile(r"^\s*ruby\s+(\S+)")
# A section header sits at column 0.
_HEADER = re.compile(r"^\S")


@register("Gemfile.lock")
def extract(repo: str, path: str, content: str) -> list:
    section = ""
    specs: dict = {}
    declared: list = []
    ruby: str = ""

    for line in (content or "").splitlines():
        if not line.strip():
            continue
        if _HEADER.match(line):
            section = line.strip().rstrip(":")
            continue
        if section == "GEM":
            m = _SPEC.match(line)
            if m:
                specs.setdefault(m.group(1), m.group(2))
        elif section == "DEPENDENCIES":
            m = _DEP.match(line)
            if m:
                declared.append(m.group(1))
        elif section == "RUBY VERSION":
            # `ruby 3.3.0` — the version only. BUNDLED WITH is Bundler's version, not
            # Ruby's, and reading it here would assert a runtime the file never states.
            m = _RUBY.match(line)
            if m:
                ruby = m.group(1)

    out: list = []
    for name in declared:
        version = specs.get(name, "")
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="bundler",
            tech_key=library_techkey("bundler", name), name=name, kind="library",
            declared_range=version,
            # A declared gem with no resolved spec came from a git/path source, which this
            # order leaves alone — say "we could not resolve it" rather than pin nothing.
            parse_quality="exact" if version else "best_effort",
        ))
    if ruby:
        out.append(InventoryRecord(
            repo=repo, manifest_path=path, ecosystem="bundler",
            tech_key="runtime:ruby", name="ruby", kind="runtime",
            version_hint=ruby, parse_quality="exact",
        ))
    return out
