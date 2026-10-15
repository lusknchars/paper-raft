"""Where a run came from: commits, dirty state, input hash, package versions."""
import hashlib
import json
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def git_sha(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD") or "unknown"


def _rel(root: Path, path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def method_sha(root: Path, method_dir: Path) -> str | None:
    return _git(root, "log", "-1", "--format=%H", "--", _rel(root, method_dir)) or None


def is_dirty(root: Path, paths: list[Path]) -> bool:
    out = _git(root, "status", "--porcelain", "--", *(_rel(root, p) for p in paths))
    return out is None or out != ""


def inputs_hash(params: dict, problem_dir: Path) -> str:
    h = hashlib.sha256(json.dumps(params, sort_keys=True).encode())
    for f in sorted(Path(problem_dir).rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
            h.update(str(f.relative_to(problem_dir)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def package_versions(names=("numpy", "scipy")) -> dict[str, str]:
    out = {}
    for n in names:
        try:
            out[n] = version(n)
        except PackageNotFoundError:
            out[n] = "not installed"
    return out


def tracked_hash(path: Path, exclude: tuple[str, ...] = ()) -> str:
    """sha256 over the git-tracked files under `path`, so ignored clutter (.DS_Store) never changes it.

    Falls back to every file (minus caches) outside git or when nothing under `path` is tracked yet.
    Top-level names in `exclude` are skipped.
    """
    path = Path(path)
    names = []
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=path, capture_output=True, check=True).stdout
        names = sorted(n for n in out.decode().split("\0") if n)
    except (OSError, subprocess.CalledProcessError):
        names = []
    if not names and path.is_dir():
        names = sorted(f.relative_to(path).as_posix() for f in path.rglob("*")
                       if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc")
    h = hashlib.sha256()
    for n in names:
        f = path / n
        if n.split("/")[0] in exclude or not f.is_file():
            continue
        h.update(n.encode() + b"\0")
        h.update(f.read_bytes())
    return h.hexdigest()
