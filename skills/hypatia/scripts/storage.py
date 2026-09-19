"""Filesystem and JSON primitives shared by the skill scripts."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def digest(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def read_json(path):
    return json.loads(Path(path).read_bytes())


def inside(root, path) -> Path:
    path = Path(path)
    if path.is_absolute():
        raise ValueError("Artifact paths must be relative")
    base = Path(root).resolve(strict=True)
    result = Path(os.path.abspath(base / path))
    if result == base or not result.is_relative_to(base):
        raise ValueError("Artifact path escapes its root")
    current = base
    for part in result.relative_to(base).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Symlinks are not accepted for artifacts")
    return result


def atomic_write(path, data: str | bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid4()}.partial")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(data.encode("utf-8") if isinstance(data, str) else data)
    temporary.replace(path)
