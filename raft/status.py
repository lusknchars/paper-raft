"""The one place that decides whether a run is verified, unverified or failed."""


def derive_status(results: dict, manifest: dict, review: dict | None) -> str:
    if results["status"] == "failed":
        return "failed"
    verified = (
        results["pass"]
        and not manifest["dirty"]
        and manifest["method_sha"] is not None
        and review is not None
        and review["verdict"] == "verified"
        and review["reviewed_sha"] == manifest["method_sha"]
    )
    return "verified" if verified else "unverified"
