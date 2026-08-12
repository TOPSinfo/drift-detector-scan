from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_the_side_car_renderers_are_gone():
    """Three AI surfaces became one. These two files ARE the second and third dashboards; leaving
    either importable invites a caller to resurrect it."""
    assert not (_ROOT / "agent" / "lib" / "probabilistic_render.py").exists()
    assert not (_ROOT / "agent" / "lib" / "adhoc_render.py").exists()


def test_nothing_still_imports_them():
    hits = []
    for p in list((_ROOT / "agent").rglob("*.py")) + list((_ROOT / "tests").rglob("*.py")):
        if p == Path(__file__).resolve():
            continue  # this guard's own source names the strings it searches for
        if "probabilistic_render" in p.read_text() or "adhoc_render" in p.read_text():
            hits.append(str(p.relative_to(_ROOT)))
    assert not hits, f"still referencing a deleted renderer: {hits}"


def test_the_compare_logic_survives():
    """Only the RENDERING is deleted. compare() produced the agree/AI-only/tool-only tally and is
    now what feeds leads.json."""
    from agent.lib.probabilistic import compare
    assert callable(compare)
