"""Render the committed SVG figures into docs/figures/.

Usage: python tools/render_figures.py [--comparison examples/output/comparison_baseline.json]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from business_flow_simulator.figures import render_all  # noqa: E402
from business_flow_simulator.outputs import read_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", default=str(ROOT / "examples" / "output" / "comparison_baseline.json"))
    parser.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    args = parser.parse_args()
    comparison = read_json(args.comparison) if Path(args.comparison).is_file() else None
    for p in render_all(args.out, comparison):
        print(f"wrote {p}")
    if comparison is None:
        print("note: comparison file not found; backlog figure skipped (run the demo first)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
