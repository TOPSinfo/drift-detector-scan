"""Publish `llms.txt` and `llms-full.txt` alongside the site, for people who would rather ask
than read.

The docs site carries an "Ask Claude" button. A button that just opens a chat is useless — the
assistant on the other end knows nothing about this tool. So the site also publishes its own
documentation in a form an assistant can fetch in one request:

  /llms.txt        an index: what this is, and every page with a one-line description
  /llms-full.txt   every published page's markdown, concatenated

Both are GENERATED FROM THE BUILD'S OWN FILE SET (`on_files`), never from a hand-kept list.
That is the load-bearing part: `mkdocs.yml` excludes internal engineering material —
`superpowers/`, the positioning notes, the parked plans — and those pages were excluded because
a customer searching the site should not surface them. A hand-written manifest, or a walk of
`docs/`, would quietly hand exactly that material to an assistant instead, re-publishing through
a side door what the exclusion just closed. Deriving from `files` means anything excluded from
the site is excluded from here for free, and stays excluded when someone adds to the list.

`llms.txt` follows the convention at https://llmstxt.org — an index at a predictable path.
"""
from __future__ import annotations

import re

from mkdocs.structure.files import File

_INDEX = "llms.txt"
_FULL = "llms-full.txt"

# Order the reader (human or not) actually wants: what it is, then how it works, then the
# reference material. Anything not listed keeps its nav order after these.
_PREFERRED = ["index.md", "how-it-works.md", "reading-the-report.md", "glossary.md",
              "FAQ.md", "PLUGIN.md", "how-it-stays-honest.md"]


def _strip_front_matter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)


def _without_code(text: str) -> str:
    """Fenced blocks removed, so a shell comment cannot be mistaken for prose or a heading.

    drift-absorb.md opens with a bash block whose first line is `# version-aware runner
    locator …`. Scanning raw markdown for `^# ` picked that up as the page TITLE — the page was
    listed under a shell comment. Both the title and the description come from prose only.
    """
    return re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)


def _first_prose_line(text: str) -> str:
    """A one-line description: the first real sentence, with markup and HTML flattened."""
    for raw in _without_code(_strip_front_matter(text)).splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "<", "!", "|", "```", "---", ">", "-", "*", ":")):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)      # links -> their text
        line = re.sub(r"[*_`]", "", line)
        line = re.sub(r"<[^>]+>", "", line)
        return line[:200]
    return ""


def _title_of(page_file, text: str) -> str:
    m = re.search(r"^#\s+(.+)$", _without_code(_strip_front_matter(text)), flags=re.M)
    if m:
        return re.sub(r"[*_`]", "", m.group(1)).strip()
    return page_file.src_uri.rsplit("/", 1)[-1].removesuffix(".md")


def _ordered(docs):
    rank = {name: i for i, name in enumerate(_PREFERRED)}
    return sorted(docs, key=lambda f: (rank.get(f.src_uri, len(rank)), f.src_uri))


def _published(f) -> bool:
    """Is this page actually published to the site?

    `f.inclusion.is_included()` is the load-bearing test, and it is easy to get wrong: at
    `on_files` time the collection STILL CONTAINS the pages `exclude_docs` removes — they carry
    `InclusionLevel.EXCLUDED` and are dropped later in the build. Filtering only on
    `is_documentation_page()` therefore reads as correct, builds without a warning, and quietly
    writes every excluded internal page into llms-full.txt. That is not hypothetical: the first
    version of this hook did exactly that, putting the parked plans, the navigator protocol and
    the internal positioning notes into a public file, which is precisely the leak `exclude_docs`
    was added to close.
    """
    return (f.src_uri.endswith(".md") and f.is_documentation_page()
            and f.inclusion.is_included())


def on_files(files, config):
    docs = _ordered([f for f in files if _published(f)])
    site = str(config.get("site_url") or "").rstrip("/")
    name = config.get("site_name") or "Documentation"
    tagline = config.get("site_description") or ""

    index = [f"# {name}", ""]
    if tagline:
        index += [f"> {tagline}", ""]
    index += [
        "This file is for AI assistants and other machine readers. It indexes the public "
        "documentation; `/llms-full.txt` carries the full text of every page in one request.",
        "", "## Docs", "",
    ]
    full = [f"# {name} — full documentation", ""]
    if tagline:
        full += [f"> {tagline}", ""]
    full += [
        "Every published page of the documentation, concatenated. Generated at build time from "
        "the site's own file set, so it contains exactly what the site publishes — no more.",
        "",
    ]

    for f in docs:
        text = f.content_string
        # the homepage's own <h1> is the hero headline, and its filename is "index" — neither
        # is a useful label in a list, so it takes the site's name
        title = name if f.src_uri == "index.md" else _title_of(f, text)
        desc = _first_prose_line(text)
        url = f"{site}/{f.dest_uri}".replace("/index.html", "/").removesuffix("index.html")
        index.append(f"- [{title}]({url})" + (f": {desc}" if desc else ""))
        full += ["", "---", "", f"# {title}", f"Source: {url}", "",
                 _strip_front_matter(text).strip(), ""]

    index += ["", "## Source", "",
              f"- [Repository]({config.get('repo_url')})",
              f"- [Full documentation as one file]({site}/{_FULL})", ""]

    files.append(File.generated(config, _INDEX, content="\n".join(index)))
    files.append(File.generated(config, _FULL, content="\n".join(full)))
    return files
