import numpy as np
import pytest

from raft import cli, graders
from raft.graders import checks, claims, table


def test_checks_reject_junk():
    with pytest.raises(ValueError, match="keys"):
        checks.require_keys([1, 2], ["y"])
    with pytest.raises(ValueError, match="shape"):
        checks.array({"y": [1, 2]}, "y", (3,))
    with pytest.raises(ValueError, match="non-finite"):
        checks.array({"y": [1, np.nan]}, "y", (2,))
    assert checks.array({"y": [0, -np.inf]}, "y", (2,), allow_neg_inf=True)[1] == -np.inf
    with pytest.raises(ValueError, match="non-finite"):
        checks.array({"y": [0, np.inf]}, "y", (2,), allow_neg_inf=True)


def test_table_match():
    ok = table.match([1.0, 2.0], [1.0, 2.005], 0.01, name="u")
    assert ok["pass"] and ok["errors"]["u_max"] == pytest.approx(0.005)
    assert not table.match([1.0, 2.0], [1.0, 2.5], 0.01)["pass"]
    assert not table.match([np.nan, 2.0], [1.0, 2.0], 0.01)["pass"]
    with pytest.raises(ValueError, match="shape"):
        table.match([1.0], [1.0, 2.0], 0.01)


def test_exact_and_lower_bound():
    assert claims.exact([1.0, 2.0], [1.0, 2.0 + 1e-12], 1e-9)["pass"]
    assert not claims.exact([1.0, 2.1], [1.0, 2.0], 1e-9)["pass"]
    assert not claims.exact([np.inf], [1.0], 1e-9)["pass"]
    assert claims.lower_bound([0.9, 1.0], [1.0, 1.0], 1e-9)["pass"]
    assert not claims.lower_bound([1.1], [1.0], 1e-9)["pass"]


def test_unbiased_accepts_honest_noise_and_rejects_bias_and_constant():
    rng = np.random.default_rng(0)
    truth = np.array([2.0, 3.0])
    honest = truth[:, None] * rng.lognormal(-0.02, 0.2, size=(2, 256))
    assert claims.unbiased(honest, truth, 4.0)["pass"]
    biased = honest * 1.2
    assert not claims.unbiased(biased, truth, 4.0)["pass"]
    perfect = np.repeat(truth[:, None], 8, axis=1)
    assert claims.unbiased(perfect, truth, 4.0)["pass"]
    assert not claims.unbiased(perfect, truth, 4.0, min_rel_sd=1e-6)["pass"]
    with pytest.raises(ValueError, match="2 seeds"):
        claims.unbiased(truth[:, None], truth, 4.0)


def test_error_falls():
    rng = np.random.default_rng(1)
    truth = np.array([1.0])
    m = np.array([16, 256])
    good = 1 + rng.normal(size=(1, 2, 64)) / np.sqrt(m)[None, :, None]
    assert claims.error_falls(good, truth)["pass"]
    flat = 1 + rng.normal(size=(1, 2, 64)) * 0.1
    flat[:, 1] = flat[:, 0] * 1.5 - 0.5
    assert not claims.error_falls(flat, truth)["pass"]


def test_within_budget():
    assert claims.within_budget([4, 8], [4, 8])["pass"]
    out = claims.within_budget([5, 8], [4, 8])
    assert not out["pass"] and out["errors"]["max_over_budget"] == 1


def test_add_copies_with_header_and_status(tiny_study):
    path = graders.add(tiny_study, "claims")
    first = path.read_text().splitlines()[0]
    assert first.startswith(f"# raft-grader claims v{graders.version('claims')} sha256:")
    assert (tiny_study / "problem" / "graders" / "__init__.py").is_file()
    assert graders.status(tiny_study) == []
    with pytest.raises(SystemExit, match="already"):
        graders.add(tiny_study, "claims")
    path.write_text(path.read_text() + "\n# local edit\n")
    assert graders.status(tiny_study) == ["problem/graders/claims.py: edited after copying; copy it again with --force"]


def test_status_reports_behind(tiny_study, monkeypatch):
    graders.add(tiny_study, "table")
    monkeypatch.setattr(graders, "version", lambda name: 99)
    (msg,) = graders.status(tiny_study)
    assert "behind the library (v1 → v99)" in msg


def test_unknown_grader(tiny_study):
    with pytest.raises(SystemExit, match="no grader named 'nope'"):
        graders.add(tiny_study, "nope")


def test_cli_grader_add(tiny_git_study, monkeypatch, capsys):
    monkeypatch.chdir(tiny_git_study.parents[1])
    monkeypatch.delenv("RAFT_ROOT", raising=False)
    assert cli.main(["grader", "add", "table", "--study", "tiny"]) == 0
    assert "problem/graders/table.py" in capsys.readouterr().out
