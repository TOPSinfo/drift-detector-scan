"""The scan container is the deterministic, no-AI CI runner. Building the image needs
docker (not hermetic), but the two properties that MUST hold are checkable from the files
alone: the engine pin cannot drift from the plugin runner (the determinism landmine
CLAUDE.md warns about), and no AI path is packaged."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()
RUNNER = (ROOT / "bin" / "drift-scan").read_text()


def test_engine_pin_matches_the_plugin_runner():
    """Container and plugin must fetch the SAME ast-grep, or two machines get different
    scanners and 'deterministic, byte-identical' is a lie."""
    df = re.search(r"AST_GREP_VERSION=(\S+)", DOCKERFILE).group(1)
    runner = re.search(r"DRIFT_AST_GREP_VERSION:-([0-9.]+)", RUNNER).group(1)
    assert df == runner, f"Dockerfile pins {df} but bin/drift-scan pins {runner}"


def test_engine_is_sha256_verified():
    assert re.search(r"AST_GREP_SHA256=[0-9a-f]{64}", DOCKERFILE)
    assert "sha256sum -c -" in DOCKERFILE          # a mismatch FAILS the build


def test_no_latest_fallback_in_the_image():
    """bin/drift-scan may fall back to 'latest' for a dev's convenience; the IMAGE must not
    — a container silently running a different engine version breaks determinism."""
    assert "releases/latest" not in DOCKERFILE
    assert "falling back to latest" not in DOCKERFILE


def test_image_carries_no_ai_path():
    """Only agent/ is copied — no commands/ promptfiles — so the image is scan-only, no AI."""
    assert "COPY agent/" in DOCKERFILE
    assert not re.search(r"COPY\s+\S*commands", DOCKERFILE)     # no promptfiles packaged


def test_runtime_dep_is_pyyaml_only():
    assert "requirements-plugin.txt" in DOCKERFILE
    assert re.fullmatch(r"[^\n]*PyYAML[^\n]*", (ROOT / "requirements-plugin.txt")
                        .read_text().strip().splitlines()[-1])


def test_entrypoint_is_the_cli():
    assert 'ENTRYPOINT ["drift"]' in DOCKERFILE
    assert "python -m agent.cli" in DOCKERFILE
