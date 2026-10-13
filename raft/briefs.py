"""Render a role prompt for a study (and method) so any agent tool can follow it."""
from pathlib import Path

import yaml


def render(root: Path, role: str, study: str, method: str = "") -> str:
    path = root / "roles" / f"{role}.md"
    if not path.is_file():
        raise SystemExit(f"raft: no role prompt at {path}")
    paper = yaml.safe_load((root / "studies" / study / "paper.yaml").read_text()) or {}
    values = {"study": study, "method": method, "study_dir": f"studies/{study}", "pdf": paper.get("pdf", "")}
    text = path.read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text
