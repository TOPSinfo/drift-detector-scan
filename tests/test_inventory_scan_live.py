import os
import shutil
import sys
import pytest

from agent.inventory_scan import scan_folder

_ENGINE = (shutil.which("opengrep") or shutil.which("semgrep")
           or next((p for p in [os.path.join(os.path.dirname(sys.executable), n)
                                 for n in ("opengrep", "semgrep")] if os.path.exists(p)), None))
_CORPUS = ("/tmp/claude-1000/-home-tops-Projects-tops-deprication-agent/"
           "fa30e593-ae4a-40f9-876e-558d40625a62/scratchpad/marketplace-repos")


@pytest.mark.skipif(_ENGINE is None or not os.path.isdir(_CORPUS),
                    reason="no engine or no cloned corpus")
def test_live_scan_marketplace_repos(tmp_path):
    out = scan_folder(_CORPUS, str(tmp_path / "state"), "2026-07-14", engine=_ENGINE)
    doc = out["doc"]
    assert doc["scope"]["reposScanned"] >= 10                  # the 12 cloned repos
    # these SDK repos hard-code marketplace endpoints -> real APIs detected
    assert "Amazon SP-API" in doc["unique_apis"] or "eBay" in doc["unique_apis"]
    assert (tmp_path / "state" / "inventory.json").exists()
    assert out["doc"]["repos"]
