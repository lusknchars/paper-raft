from pathlib import Path

import pytest

from raft import runner

STUDY = Path(__file__).resolve().parents[1] / "studies" / "ghia-1982"
METHODS = runner.methods(STUDY)


@pytest.mark.parametrize("method", METHODS)
def test_golden_coarse_grid(method):
    _, results = runner.execute(STUDY, method, {"re": 100, "grid": 33}, timeout=600)
    assert results["status"] == "ok", results.get("reason")
    assert max(results["errors"]["u_max"], results["errors"]["v_max"]) <= 0.05
