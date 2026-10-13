from raft.status import derive_status

SHA = "c" * 40
OK = {"status": "ok", "pass": True}
MAN = {"dirty": False, "method_sha": SHA}
REV = {"verdict": "verified", "reviewed_sha": SHA}


def test_status_verified():
    assert derive_status(OK, MAN, REV) == "verified"


def test_status_failed_wins():
    assert derive_status({"status": "failed", "pass": False}, MAN, REV) == "failed"


def test_status_no_review():
    assert derive_status(OK, MAN, None) == "unverified"


def test_status_over_tolerance_is_unverified():
    assert derive_status({"status": "ok", "pass": False}, MAN, REV) == "unverified"


def test_status_review_for_other_commit():
    assert derive_status(OK, {**MAN, "method_sha": "d" * 40}, REV) == "unverified"


def test_status_dirty_never_verified():
    assert derive_status(OK, {**MAN, "dirty": True}, REV) == "unverified"


def test_status_uncommitted_method_never_verified():
    assert derive_status(OK, {**MAN, "method_sha": None}, REV) == "unverified"


def test_status_review_with_discrepancies():
    assert derive_status(OK, MAN, {**REV, "verdict": "discrepancies"}) == "unverified"
