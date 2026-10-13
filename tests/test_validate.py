import json

from raft import validate


def test_tiny_extraction_valid(tiny_study):
    assert validate.extraction(tiny_study) == []


def test_duplicate_ids(tiny_study):
    p = tiny_study / "extraction.json"
    data = json.loads(p.read_text())
    data["items"].append(dict(data["items"][0]))
    p.write_text(json.dumps(data))
    assert validate.extraction(tiny_study) == ["extraction.json: duplicate id 'tiny-method'"]


def test_missing_extraction(tiny_study):
    (tiny_study / "extraction.json").unlink()
    assert "file not found" in validate.extraction(tiny_study)[0]


def test_method_cites_unknown_id(tiny_study):
    p = tiny_study / "methods" / "exact" / "method.json"
    m = json.loads(p.read_text())
    m["implements"] = ["nope"]
    p.write_text(json.dumps(m))
    assert validate.methods_and_reviews(tiny_study) == ["methods/exact/method.json: implements unknown extraction id 'nope'"]


def test_review_by_implementer_rejected(tiny_study):
    (tiny_study / "reviews").mkdir()
    (tiny_study / "reviews" / "exact.json").write_text(json.dumps({
        "method": "exact", "reviewed_sha": "a" * 40, "reviewer_agent": "test:implementer#exact",
        "verdict": "verified", "discrepancies": []}))
    assert validate.methods_and_reviews(tiny_study) == ["reviews/exact.json: reviewer is the method's implementer"]


def test_review_for_unknown_method(tiny_study):
    (tiny_study / "reviews").mkdir()
    (tiny_study / "reviews" / "ghost.json").write_text(json.dumps({
        "method": "ghost", "reviewed_sha": "a" * 40, "reviewer_agent": "r",
        "verdict": "unverified", "discrepancies": []}))
    assert validate.methods_and_reviews(tiny_study) == ["reviews/ghost.json: no method named 'ghost'"]
