"""Design-system invariants for the Cockpit stylesheet.

The CSS accreted across several tasks ("Task 2", "Task 3", "ported from the mockup") and the
seams showed: fifteen font sizes in half-pixel steps, nine font weights several of which no
font can distinguish, eleven radii beside a `--r` token used twice, and one class name serving
two unrelated components.

These are guards, not preferences. Uniformity that lives only in a reviewer's memory is
uniformity that decays on the next edit — the same reasoning `check_timeline_lanes` and the
runner-allowlist test already apply elsewhere in this repo. Each test below names the specific
defect it was written against, so a future edit that reintroduces one fails here rather than
shipping.

Pure text analysis of the committed assets. No rendering, no network.
"""
from __future__ import annotations

import collections
import pathlib
import re

_ASSETS = pathlib.Path(__file__).resolve().parent.parent / "agent" / "assets"
CSS = (_ASSETS / "dashboard.css").read_text(encoding="utf-8")
TEMPLATE = (_ASSETS / "dashboard.template.html").read_text(encoding="utf-8")


def _declared(prop: str) -> list[str]:
    """PX values only. Relative units (`code` is .86em, deliberately) scale with their parent
    and are not points on the pixel scale, so counting them would flag correct CSS."""
    return re.findall(rf"{prop}:\s*([0-9.]+)px", CSS)


def _strip_comments(css: str) -> str:
    """Prose is not code. A comment EXPLAINING why a literal was removed must not read as the
    literal coming back — the gutter guard fired on its own explanation once."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _strip_root(css: str) -> str:
    """Everything except the :root token block — where literal values are legitimate — and
    without comments, so these guards judge declarations rather than the text around them."""
    return re.sub(r":root\s*\{.*?\}", "", _strip_comments(css), flags=re.S)


# ── the collision ────────────────────────────────────────────────────────────────────────
#
# `.trk` named BOTH the timeline row (`<div class="trk">`) and the tracking-status pill
# (`<span class="trk" :data-trk="…">`). Both matched the pill's base rule, so every timeline
# row inherited a 1px border, a panel background, 1px 8px padding and white-space:nowrap that
# nothing in the timeline design asked for. The later rule overrode only border-radius, so the
# rest survived silently.

def test_no_class_name_serves_two_unrelated_components():
    """A bare `.foo{...}` declared twice is one class doing two jobs. Whichever component was
    written second inherits the first's box model, and nothing warns."""
    bare = collections.Counter(re.findall(r"(?m)^\.([a-zA-Z][\w-]*)\s*\{", CSS))
    assert {k: v for k, v in bare.items() if v > 1} == {}


def test_no_element_selector_is_declared_twice():
    """The class version of this guard caught `.trk` and `.pagefoot`; it did not catch a second
    bare `body{...}`, added while building the drawer, whose padding silently fought the
    original's. Element selectors are rarer and therefore easier to duplicate by accident."""
    els = collections.Counter(re.findall(r"(?m)^([a-z][\w]*)\s*\{", CSS))
    assert {k: v for k, v in els.items() if v > 1} == {}


def test_timeline_rows_do_not_reuse_the_status_pill_class():
    """The specific bug: the status pill is the element carrying `data-trk`. A timeline row is
    not a pill and must not be styled as one."""
    rows = re.findall(r'<div class="([\w-]+)"[^>]*v-for="\(pt, pi\) in vg\.items"', TEMPLATE)
    pills = set(re.findall(r'<span class="([\w-]+)"\s+:data-trk', TEMPLATE))
    assert rows, "the dated timeline row binding moved — update this guard with it"
    assert not (set(rows) & pills), f"timeline row and status pill share a class: {set(rows) & pills}"


# ── the scales ───────────────────────────────────────────────────────────────────────────

def test_type_scale_is_bounded():
    """Fifteen sizes with half-pixel steps is not a scale, it is a history of individual
    decisions. Nobody can hold it in their head, so the next edit invents a sixteenth."""
    sizes = sorted({float(v) for v in _declared("font-size")})
    assert len(sizes) <= 8, f"{len(sizes)} distinct font sizes: {sizes}"


def test_no_half_pixel_type_sizes():
    """12.5px vs 13px is a difference no reader perceives and every editor has to decide about."""
    halves = sorted({float(v) for v in _declared("font-size") if float(v) % 1})
    assert not halves, f"fractional font sizes: {halves}"


def test_font_weights_are_distinguishable():
    """620 / 640 / 650 / 660 render identically in the system stack this page ships with."""
    weights = sorted({int(v) for v in re.findall(r"font-weight:\s*(\d+)", CSS)})
    assert len(weights) <= 4, f"{len(weights)} font weights: {weights}"


def test_radii_come_from_the_token_set():
    """`--r` existed and was used twice out of eleven radii. A token nothing uses is a comment."""
    literals = sorted({float(v) for v in _declared("border-radius")})
    assert len(literals) <= 4, f"{len(literals)} literal radii: {literals}"


# ── colour discipline ────────────────────────────────────────────────────────────────────

def test_no_raw_hex_outside_the_token_block():
    """`#2e7d32` for 'tracked' green while `--low` sat unused, and `rgba(61,125,224,.09)`
    hardcoding --accent-2 where every neighbouring rule used color-mix. A colour outside
    :root cannot follow the light/dark theme."""
    body = _strip_root(CSS)
    # #fff / #000 are exempt: they appear only as achromatic endpoints inside color-mix()
    # (the brand mark's gradient, the dialog backdrop). Pure black and white carry no hue to
    # theme, so pulling them into :root would add tokens without adding meaning.
    hexes = {h for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
             if h.lower() not in ("#fff", "#000", "#ffffff", "#000000")}
    assert not hexes, f"raw colours outside :root: {sorted(hexes)}"


def test_no_rgba_literals_outside_the_token_block():
    """Same rule, other spelling — an rgba() literal is a hex that dodged the check above.
    Shadows are exempt: they are neutral black at low alpha, not themed colour."""
    body = re.sub(r"box-shadow:[^;}]*", "", _strip_root(CSS))
    assert not re.findall(r"rgba?\([^)]*\)", body)


def test_no_dead_fallbacks_on_defined_tokens():
    """`var(--sun,#b26a00)` — the fallback is brown, the token is purple, and the fallback can
    never fire. It cannot change what renders; it can only mislead whoever reads it next."""
    defined = set(re.findall(r"^\s*(--[\w-]+):", CSS, flags=re.M))
    bad = [t for t in re.findall(r"var\((--[\w-]+),\s*[^)]+\)", CSS) if t in defined]
    assert not bad, f"fallbacks on tokens that are always defined: {sorted(set(bad))}"


# ── shared geometry ──────────────────────────────────────────────────────────────────────

def test_the_timeline_gutter_is_a_single_source_of_truth():
    """260px appeared in .axis, .trk .lab and .todaywrap. The axis, the TODAY line and the row
    labels must share one gutter or the timeline silently misaligns — three literals means the
    next person changes one of them."""
    # the token DEFINITION necessarily holds the value; what must not recur is a literal
    # anywhere a rule consumes it.
    assert "--tl-gutter:" in CSS, "the gutter token is gone"
    assert "260px" not in _strip_root(CSS), "the timeline gutter is still a repeated literal"


def test_no_two_severity_pills_look_identical():
    """`.pill.soon` was byte-identical to `.pill.high`. Within ONE component family two names
    for one appearance is a trap: a later edit to one creates a difference nobody intended, and
    a reader cannot tell whether the sameness was deliberate.

    Scoped to the pill family on purpose. Parallel components legitimately share declarations —
    `.tab:hover` and `.subtab:hover` are both `color:var(--ink)` and should be — so a global
    no-duplicate-bodies rule would fire on correct code and teach everyone to ignore it. If two
    pill variants must look alike, say so by combining their selectors."""
    bodies = collections.defaultdict(list)
    for sel, body in re.findall(r"(?m)^(\.pill\.[\w-]+)\s*\{([^}]*)\}", CSS):
        norm = ";".join(sorted(d.strip() for d in body.split(";") if d.strip()))
        bodies[norm].append(sel)
    clashes = {b: s for b, s in bodies.items() if len(s) > 1}
    assert not clashes, f"pill variants with identical appearance: {list(clashes.values())}"


def test_there_is_one_radius_scale_not_two():
    """`--r:12px` survived alongside the new `--r-xs … --r-lg` scale for a while. Two token
    families for one property is the same defect as the eleven literals they replaced, just
    tidier-looking — a reader has to know which family a component belongs to."""
    families = {m for m in re.findall(r"^\s*(--r[\w-]*):", CSS, flags=re.M)}
    assert "--r" not in families, "the pre-scale --r token is back"
    assert families <= {"--r-xs", "--r-sm", "--r-md", "--r-lg", "--r-pill"}, families


def test_template_comments_are_balanced():
    """A restructure once carried a block's `-->` away with it, leaving `<!--` open. Everything
    after became one runaway comment, and the tails of later comments rendered as VISIBLE TEXT
    on the page — "AI Frontier has no sub-tabs … -->" sat above the table. Nothing caught it:
    the template still parsed, the counts still balanced, and every test passed."""
    depth = 0
    for m in re.finditer(r"<!--|-->", TEMPLATE):
        depth += 1 if m.group(0) == "<!--" else -1
        assert depth in (0, 1), "nested or orphaned HTML comment near offset %d" % m.start()
    assert depth == 0, "unclosed HTML comment"


def test_no_comment_tail_can_render_as_text():
    """The symptom, guarded directly: a line ending in `-->` that never opened a comment."""
    depth = 0
    for i, line in enumerate(TEMPLATE.split("\n"), 1):
        for m in re.finditer(r"<!--|-->", line):
            if m.group(0) == "-->":
                assert depth > 0, "line %d closes a comment that was never opened" % i
                depth -= 1
            else:
                depth += 1


def test_no_dead_css_rules():
    """The restructuring left 31 orphaned rules behind — a whole `dialog` block for a dialog
    that does not exist, the status strip's styles after it moved into the drawer, the footer
    after it was emptied. Dead CSS is not inert: it is what the next reader takes for a
    description of the page, and every one of these described a component that had gone.

    `sev-*` is exempt: those class names are composed at runtime (`'sev-' + row.worst`), so
    they never appear literally in the markup."""
    app_js = (_ASSETS / "dashboard.app.js").read_text(encoding="utf-8")
    used = TEMPLATE + app_js
    declared = set(re.findall(r"\.([a-zA-Z][\w-]*)", _strip_comments(CSS)))
    dead = sorted(c for c in declared
                  if not c.startswith("sev-")
                  and not re.search(r"\b" + re.escape(c) + r"\b", used))
    assert not dead, "CSS classes nothing uses: %s" % dead


def test_no_unused_app_state_or_methods():
    """Five orphans survived the restructure — `sumView` after the JSON pane went, `targetText`
    and `actionLabel` after per-plane columns replaced the generic ones, `driftJsonText` after
    the download replaced the inline view. Vue never complains about an unused computed, so
    these are invisible until someone reads them and assumes the feature still exists."""
    js = (_ASSETS / "dashboard.app.js").read_text(encoding="utf-8")
    block = re.search(r"data: function\(\)\{\s*return \{(.*?)\n      \};", js, re.S)
    assert block, "the data() block moved — update this guard with it"
    after = js[block.end():] + TEMPLATE

    unused_state = [k for k in re.findall(r"^\s{8}(\w+):", block.group(1), re.M)
                    if not re.search(r"\b" + k + r"\b", after)]
    assert not unused_state, "data keys nothing reads: %s" % unused_state

    unused_fns = [f for f in re.findall(r"^      (\w+): function\(", js, re.M)
                  if len(re.findall(r"\b" + f + r"\b", js + TEMPLATE)) <= 1]
    assert not unused_fns, "computeds/methods nothing calls: %s" % unused_fns


def test_spacing_comes_from_the_scale():
    """`--s-1 … --s-7` existed but only covered the components that had been touched; nineteen
    literal px values were still in padding/margin/gap elsewhere. A scale half-applied is not a
    scale — the next edit copies whichever neighbour it happens to sit beside."""
    body = _strip_comments(CSS)
    left = sorted({tok for m in re.finditer(r"\b(?:padding|margin|gap)(?:-\w+)?:([^;}\n]+)", body)
                   for tok in m.group(1).split() if re.fullmatch(r"\d+px", tok)})
    assert not left, "hardcoded spacing outside the scale: %s" % left


def test_every_interactive_control_shows_focus():
    """Nine controls had no focus style at all, so a keyboard user could not see where they
    were. Uniformity here is not cosmetic: an invisible focus ring makes the page unusable
    without a mouse."""
    interactive = {cls for _, cls in
                   re.findall(r'<(button|select|input|a)\b[^>]*class="([\w-]+)', TEMPLATE)}
    styled = set(re.findall(r"\.([\w-]+):focus(?:-visible)?", _strip_comments(CSS)))
    missing = sorted(interactive - styled)
    assert not missing, "interactive classes with no focus style: %s" % missing
