import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from raft import schema

PROBLEM = Path(__file__).resolve().parents[1] / "studies" / "ghia-1982" / "problem"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"ghia_{name}", PROBLEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


setup_mod = _load("setup")
measure_mod = _load("measure")
REF = {"citation": "t", "doi": "t", "tolerance": 0.01,
       "cases": {"100": {"u_vertical": [[0, 0], [0.25, 0.25], [1, 1]],
                         "v_horizontal": [[0, 0], [0.5, 0.5], [1, 1]]}}}


def linear_fields(s, dv=0.0):
    y, x = np.meshgrid(s.nodes(), s.nodes(), indexing="ij")
    return {"u": y.copy(), "v": x + dv}


def test_reference_file_matches_schema_and_shape():
    ref = schema.load("reference", PROBLEM / "reference.json")
    for case in ref["cases"].values():
        for key, end in (("u_vertical", 1.0), ("v_horizontal", 0.0)):
            pts = np.array(case[key])
            assert pts.shape == (17, 2)
            assert np.all(np.diff(pts[:, 0]) > 0)
            assert pts[0, 1] == 0.0 and pts[-1, 1] == end


def test_make_setup_and_expand():
    s = setup_mod.make_setup({"re": 100, "grid": 33})
    assert s.h == pytest.approx(1 / 32) and s.nu == pytest.approx(0.01)
    assert setup_mod.expand({"re": 100}) == [{"re": 100, "grid": 33}, {"re": 100, "grid": 65}, {"re": 100, "grid": 129}]
    assert setup_mod.expand({"re": 1000, "grid": 65}) == [{"re": 1000, "grid": 65}]


@pytest.mark.parametrize("params", [{"re": 100, "grid": 64}, {"re": -1, "grid": 33}, {"re": 100, "grid": 33, "mach": 1}])
def test_make_setup_rejects_bad_params(params):
    with pytest.raises(ValueError):
        setup_mod.make_setup(params)


def test_measure_exact_fields_have_zero_error():
    s = setup_mod.make_setup({"re": 100, "grid": 33})
    m = measure_mod.measure(s, linear_fields(s), REF)
    assert m["errors"] == pytest.approx({"u_max": 0, "u_rms": 0, "v_max": 0, "v_rms": 0}, abs=1e-12)
    assert m["pass"] is True and m["tolerance"] == 0.01
    assert len(m["samples"]["u_vertical"]) == 33
    assert m["reference_samples"]["v_horizontal"] == [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]]
    json.dumps(m)  # plain Python types only


def test_measure_reports_offset():
    s = setup_mod.make_setup({"re": 100, "grid": 33})
    m = measure_mod.measure(s, linear_fields(s, dv=0.1), REF)
    assert m["errors"]["v_max"] == pytest.approx(0.1) and m["errors"]["v_rms"] == pytest.approx(0.1)
    assert m["pass"] is False


def test_streamfunction_of_uniform_u_is_y():
    s = setup_mod.make_setup({"re": 100, "grid": 9})
    psi = measure_mod.streamfunction(np.ones((9, 9)), s.h)
    assert psi[:, 4] == pytest.approx(s.nodes())


@pytest.mark.parametrize("fields, msg", [
    ({"u": np.zeros((33, 33))}, "keys"),
    ({"u": np.zeros((32, 33)), "v": np.zeros((33, 33))}, "shape"),
    ({"u": np.full((33, 33), np.nan), "v": np.zeros((33, 33))}, "non-finite"),
])
def test_measure_rejects_bad_fields(fields, msg):
    s = setup_mod.make_setup({"re": 100, "grid": 33})
    with pytest.raises(ValueError, match=msg):
        measure_mod.measure(s, fields, REF)


def test_measure_rejects_unknown_reynolds():
    s = setup_mod.make_setup({"re": 400, "grid": 33})
    with pytest.raises(ValueError, match="no reference data for Re = 400"):
        measure_mod.measure(s, linear_fields(s), REF)
