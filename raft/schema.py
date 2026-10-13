"""Load and validate the JSON contract files every stage hands to the next."""
import json
from functools import cache
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator

NAMES = ("extraction", "method", "manifest", "results", "review", "reference")


class ContractError(Exception):
    """A contract file is missing, not JSON, or does not match its schema."""


@cache
def _validator(name: str) -> Draft202012Validator:
    if name not in NAMES:
        raise KeyError(f"unknown contract {name!r}; expected one of {NAMES}")
    text = files("raft.contracts").joinpath(f"{name}.schema.json").read_text()
    return Draft202012Validator(json.loads(text))


def errors(name: str, obj) -> list[str]:
    found = sorted(_validator(name).iter_errors(obj), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in found]


def check(name: str, obj) -> None:
    errs = errors(name, obj)
    if errs:
        raise ContractError(f"{name} does not match its schema:\n  " + "\n  ".join(errs))


def load(name: str, path: Path) -> dict:
    path = Path(path)
    try:
        obj = json.loads(path.read_text())
    except FileNotFoundError:
        raise ContractError(f"{path}: file not found") from None
    except json.JSONDecodeError as e:
        raise ContractError(f"{path}: not valid JSON ({e})") from None
    errs = errors(name, obj)
    if errs:
        raise ContractError(f"{path}:\n  " + "\n  ".join(errs))
    return obj
