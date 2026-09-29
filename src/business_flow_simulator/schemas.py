"""A small JSON Schema subset validator (type, required, properties,
additionalProperties, items, enum, const, minimum, maximum, minItems, pattern) so the
published schemas in ``schemas/*.json`` can be enforced without a third-party package."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from business_flow_simulator.paths import schemas_dir

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list, tuple),
    "null": (type(None),),
}


class SchemaError(ValueError):
    """Raised with the JSON path of the first violation."""


def load_schema(name: str) -> dict[str, Any]:
    p = Path(name) if name.endswith(".json") else schemas_dir() / f"{name}.schema.json"
    if not p.is_file():
        raise SchemaError(f"schema not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _type_ok(value: Any, type_name: str) -> bool:
    if type_name == "integer" and isinstance(value, bool):
        return False
    if type_name == "number" and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[type_name])


def validate(instance: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    if "const" in schema and instance != schema["const"]:
        raise SchemaError(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{path}: {instance!r} not in enum {schema['enum']}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(instance, t) for t in types):
            raise SchemaError(f"{path}: expected type {types}, got {type(instance).__name__}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            raise SchemaError(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            raise SchemaError(f"{path}: {instance} > maximum {schema['maximum']}")
    if isinstance(instance, str) and "pattern" in schema and not re.search(schema["pattern"], instance):
        raise SchemaError(f"{path}: {instance!r} does not match pattern {schema['pattern']!r}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                raise SchemaError(f"{path}: missing required property {key!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in instance:
                validate(instance[key], sub, f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(instance) - set(props))
            if extra:
                raise SchemaError(f"{path}: unexpected properties {extra}")
    if isinstance(instance, (list, tuple)):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise SchemaError(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(instance):
                validate(item, schema["items"], f"{path}[{i}]")


def validate_against(name: str, instance: Any) -> None:
    validate(instance, load_schema(name))
