"""Persistent request state for the host's Callimachus/Hypatia coordination."""

from pathlib import Path
import re

from schema import parse
from storage import atomic_write, digest, inside, json_text, read_json


def prepare_review(root, question=""):
    root = Path(root).resolve()
    if question:
        normalized = re.sub(r"\s+", " ", question.lower())
        root = root / "reviews" / f"hypatia-{digest(normalized)[:16]}"
    root.mkdir(parents=True, exist_ok=True)
    inside(root, ".hypatia").mkdir(exist_ok=True)
    return str(root)


def read_request(root):
    path = inside(root, ".hypatia/request.json")
    return parse("Request", read_json(path)) if path.exists() else None


def write_request(root, request):
    atomic_write(inside(root, ".hypatia/request.json"), json_text(parse("Request", request)))


def pause_request(root, question):
    current = read_request(root)
    if current and current["status"] == "awaiting_callimachus":
        return
    write_request(root, {"status": "paused", "question": question})
