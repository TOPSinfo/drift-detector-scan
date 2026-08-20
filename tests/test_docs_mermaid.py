"""Mermaid diagrams in the docs site must actually parse.

`mkdocs build --strict` does NOT validate them — Material renders Mermaid client-side, so a
malformed diagram builds clean, deploys, and then shows a red "Syntax error in text" box to
every reader. That is exactly what shipped: `R[/drift-detector]` opened Mermaid's parallelogram
shape (`[/text/]`) with `[/` and closed it with a plain `]`, and the FAQ's trust-tier diagram
was broken on the public site until a human noticed it in a browser.

There is no offline Mermaid parser here (the runtime is stdlib + PyYAML), so this pins the
specific mistake rather than pretending to be a full validator: a node label that opens a shape
delimiter it never closes. A label containing `/`, `\\`, `(` or `{` must be quoted.
"""
import re
from pathlib import Path

_DOCS = Path(__file__).resolve().parent.parent / "docs"

# `id[` followed immediately by a shape-opening character, without a quote. Mermaid reads
# `[/`, `[\`, `[(` and `[{` as the start of a two-character shape delimiter, so an unquoted
# label starting with one of those is a parse error unless it closes symmetrically.
_UNQUOTED_SHAPE_OPEN = re.compile(r"\w+\[[/\\({](?!\")")


def _mermaid_blocks(text: str):
    return re.findall(r"```mermaid\n(.*?)```", text, re.S)


def test_no_mermaid_node_opens_a_shape_it_does_not_close():
    offenders = []
    for md in sorted(_DOCS.rglob("*.md")):
        for block in _mermaid_blocks(md.read_text(encoding="utf-8")):
            for line in block.splitlines():
                m = _UNQUOTED_SHAPE_OPEN.search(line)
                if m and not re.search(r"\[[/\\({].*[/\\)}]\]", line):
                    offenders.append(f"{md.relative_to(_DOCS)}: {line.strip()}")
    assert not offenders, (
        "unquoted Mermaid label opens a shape delimiter — quote it, e.g. R[\"/drift-detector\"]:\n"
        + "\n".join(offenders))
