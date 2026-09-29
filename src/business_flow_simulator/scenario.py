"""Scenario definition, YAML loading, validation, and the compact URL-safe codec used
by ``export-scenario`` / ``import-scenario``."""
from __future__ import annotations

import base64
import binascii
import json
import zlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import yaml

from business_flow_simulator.paths import scenarios_dir

SCENARIO_SCHEMA_VERSION = 1
CODEC_PREFIX = "bfs1."
FAULT_KEYS = ("delayed_shipment", "duplicate_invoice", "failed_payment_step",
              "price_variance", "cancellation")


class ScenarioError(ValueError):
    """Raised for a malformed or unknown scenario."""


class ScenarioCodecError(ValueError):
    """Raised when an exported scenario string cannot be decoded."""


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    description: str
    horizon_minutes: int
    seed: int
    workload: Mapping[str, Any]
    faults: Mapping[str, Mapping[str, Any]]
    retry_policy: Mapping[str, int]
    schema_version: int = SCENARIO_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "description": self.description,
            "horizon_minutes": self.horizon_minutes,
            "seed": self.seed,
            "workload": json.loads(json.dumps(self.workload)),
            "faults": json.loads(json.dumps(self.faults)),
            "retry_policy": dict(self.retry_policy),
        }

    def with_seed(self, seed: int) -> "Scenario":
        return replace(self, seed=int(seed))

    def with_orders(self, orders: int) -> "Scenario":
        wl = dict(self.workload)
        wl["orders"] = int(orders)
        return replace(self, workload=wl)


def _check_int(d: Mapping[str, Any], key: str, where: str, minimum: int = 0) -> int:
    if key not in d:
        raise ScenarioError(f"{where} missing key {key!r}")
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ScenarioError(f"{where}.{key} must be an int >= {minimum}, got {v!r}")
    return v


def _check_prob(d: Mapping[str, Any], key: str, where: str) -> float:
    v = d.get(key, 0.0)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0:
        raise ScenarioError(f"{where}.{key} must be a probability in [0, 1], got {v!r}")
    return float(v)


def scenario_from_dict(data: Mapping[str, Any]) -> Scenario:
    if not isinstance(data, Mapping):
        raise ScenarioError("scenario must be a mapping")
    sid = data.get("scenario_id")
    if not isinstance(sid, str) or not sid or not all(c.isalnum() or c in "_-" for c in sid):
        raise ScenarioError(f"scenario_id must be a non-empty slug, got {sid!r}")
    wl = data.get("workload")
    if not isinstance(wl, Mapping):
        raise ScenarioError("scenario.workload must be a mapping")
    for key in ("orders", "arrival_mean_gap_minutes", "skus", "initial_stock_per_sku",
                "reorder_point", "reorder_qty", "customers", "customer_opening_balance_cents",
                "min_items_per_order", "max_items_per_order", "min_qty_per_line",
                "max_qty_per_line", "min_unit_price_cents", "max_unit_price_cents"):
        _check_int(wl, key, "workload", 1 if key in ("orders", "skus", "customers") else 0)
    if wl["min_items_per_order"] > wl["max_items_per_order"]:
        raise ScenarioError("workload.min_items_per_order exceeds max_items_per_order")
    if wl["min_qty_per_line"] > wl["max_qty_per_line"]:
        raise ScenarioError("workload.min_qty_per_line exceeds max_qty_per_line")
    faults = data.get("faults", {})
    if not isinstance(faults, Mapping):
        raise ScenarioError("scenario.faults must be a mapping")
    for name in faults:
        if name not in FAULT_KEYS:
            raise ScenarioError(f"unknown fault {name!r}; known: {list(FAULT_KEYS)}")
        _check_prob(faults[name], "probability", f"faults.{name}")
    if "delayed_shipment" in faults:
        _check_int(faults["delayed_shipment"], "delay_minutes", "faults.delayed_shipment")
    if "price_variance" in faults:
        _check_int(faults["price_variance"], "max_variance_bps", "faults.price_variance")
    rp = data.get("retry_policy", {})
    if not isinstance(rp, Mapping):
        raise ScenarioError("scenario.retry_policy must be a mapping")
    retry = {
        "max_attempts": _check_int(rp, "max_attempts", "retry_policy", 1),
        "base_backoff_minutes": _check_int(rp, "base_backoff_minutes", "retry_policy", 0),
        "multiplier": _check_int(rp, "multiplier", "retry_policy", 1),
    }
    return Scenario(
        scenario_id=sid,
        description=str(data.get("description", "")),
        horizon_minutes=_check_int(data, "horizon_minutes", "scenario", 1),
        seed=_check_int(data, "seed", "scenario", 0),
        workload=dict(wl),
        faults={k: dict(v) for k, v in faults.items()},
        retry_policy=retry,
        schema_version=int(data.get("schema_version", SCENARIO_SCHEMA_VERSION)),
    )


def list_scenarios() -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in scenarios_dir().glob("*.yaml")))


def load_scenario(name_or_path: str | Path) -> Scenario:
    p = Path(name_or_path)
    if not p.suffix:
        p = scenarios_dir() / f"{name_or_path}.yaml"
    if not p.is_file():
        raise ScenarioError(
            f"scenario not found: {name_or_path!r}. Known scenarios: {list(list_scenarios())}"
        )
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return scenario_from_dict(data)


def save_scenario(scenario: Scenario, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        yaml.safe_dump(scenario.to_dict(), fh, sort_keys=False)
    return p


def export_scenario(scenario: Scenario) -> str:
    """Compact, URL-safe, self-checking string. zlib adds an Adler-32 checksum, so a
    tampered string fails to decode instead of producing a silently different scenario."""
    raw = json.dumps(scenario.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    packed = zlib.compress(raw, 9)
    return CODEC_PREFIX + base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def import_scenario(text: str) -> Scenario:
    text = text.strip()
    if not text.startswith(CODEC_PREFIX):
        raise ScenarioCodecError(f"scenario string must start with {CODEC_PREFIX!r}")
    body = text[len(CODEC_PREFIX):]
    body += "=" * (-len(body) % 4)
    try:
        packed = base64.urlsafe_b64decode(body.encode("ascii"))
        raw = zlib.decompress(packed)
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, zlib.error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ScenarioCodecError(f"scenario string is corrupt or was tampered with: {exc}") from exc
    return scenario_from_dict(data)
