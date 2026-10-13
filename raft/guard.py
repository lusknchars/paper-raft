"""Static check that a method cannot see or touch the yardstick it is measured with.

Forbidden in a method folder's Python files (docstrings excepted): string literals that
mention the reference data, the measurement module, the shared problem folder, runs or
reviews; and importing anything named measure or reference. The runner adds a runtime
check (problem/ must be byte-identical after the run).
"""
import ast
from pathlib import Path

FORBIDDEN_TEXT = ("reference.json", "measure", "problem/", "problem\\", "runs/", "reviews/")
FORBIDDEN_MODULES = ("measure", "reference")


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def scan_method(method_dir: Path) -> list[str]:
    problems = []
    for f in sorted(Path(method_dir).rglob("*.py")):
        rel = f.relative_to(method_dir)
        try:
            tree = ast.parse(f.read_text(), filename=str(f))
        except SyntaxError as e:
            problems.append(f"{rel}:{e.lineno}: syntax error ({e.msg})")
            continue
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                hit = next((t for t in FORBIDDEN_TEXT if t in node.value), None)
                if hit:
                    problems.append(f"{rel}:{node.lineno}: string mentions {hit!r}")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names]
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
                for name in names:
                    if any(part in FORBIDDEN_MODULES for part in name.split(".")):
                        problems.append(f"{rel}:{node.lineno}: imports {name!r}")
    return problems
