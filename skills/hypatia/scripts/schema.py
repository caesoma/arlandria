"""Data contracts used by Python validation and Pi's tool declarations."""

from pathlib import Path

from jsonschema import Draft202012Validator

from storage import read_json


SCHEMAS = read_json(Path(__file__).resolve().parent.parent / "references" / "schemas.json")
VALIDATORS = {name: Draft202012Validator(schema) for name, schema in SCHEMAS.items()}


def parse(name: str, value):
    error = next(VALIDATORS[name].iter_errors(value), None)
    if error:
        raise ValueError(f"Invalid data: does not match the required schema ({name}: {error.message})")
    return value
