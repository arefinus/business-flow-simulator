"""File writers. JSON is written with LF newlines and sorted keys where order does not
carry meaning, so the same run yields byte-identical files on every platform."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from business_flow_simulator.events import Event


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def write_text(path: str | Path, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return p


def write_json(path: str | Path, obj: Any, indent: int | None = 2) -> Path:
    return write_text(path, json.dumps(obj, indent=indent, ensure_ascii=True) + "\n")


def event_log_text(events: Iterable[Event]) -> str:
    """A JSON array with one event per line: valid JSON, diff-friendly, compact."""
    lines = [json.dumps(e.to_dict(), separators=(",", ":"), ensure_ascii=True) for e in events]
    if not lines:
        return "[]\n"
    return "[\n" + ",\n".join(lines) + "\n]\n"


def write_event_log(events: Iterable[Event], path: str | Path) -> Path:
    return write_text(path, event_log_text(events))


def read_event_log(path: str | Path) -> tuple[Event, ...]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"event log not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"event log must be a JSON array: {p}")
    return tuple(Event.from_dict(d) for d in data)


def read_json(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)
