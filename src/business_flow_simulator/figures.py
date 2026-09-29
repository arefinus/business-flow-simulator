"""Hand-written SVG figures (no matplotlib, to keep CI light). ``tools/render_figures.py``
is the command-line wrapper."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from business_flow_simulator.outputs import write_text
from business_flow_simulator.state_machine import HAPPY_PATH

_FONT = "font-family='Helvetica, Arial, sans-serif'"
_ACTORS = ("supplier", "manufacturer", "warehouse", "retailer", "customer",
           "invoice_payment_service", "review_queue")
_ACTOR_FLOWS = (
    ("customer", "retailer", "purchase order"),
    ("retailer", "warehouse", "reservation"),
    ("warehouse", "manufacturer", "replenishment"),
    ("supplier", "manufacturer", "components"),
    ("manufacturer", "warehouse", "restock"),
    ("warehouse", "customer", "shipment"),
    ("invoice_payment_service", "customer", "invoice"),
    ("customer", "invoice_payment_service", "payment"),
    ("retailer", "review_queue", "exception"),
    ("review_queue", "invoice_payment_service", "resolution"),
)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def workflow_svg() -> str:
    width, height = 960, 420
    parts = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
             "<rect width='100%' height='100%' fill='#ffffff'/>",
             f"<text x='16' y='28' {_FONT} font-size='16' fill='#222'>business-flow-simulator: order state machine (top) and actor flows (bottom). Synthetic demo, fictional organisations.</text>"]
    # state machine row
    n = len(HAPPY_PATH)
    box_w, box_h, gap, y = 128, 44, 22, 60
    x0 = (width - (n * box_w + (n - 1) * gap)) // 2
    for i, state in enumerate(HAPPY_PATH):
        x = x0 + i * (box_w + gap)
        parts.append(f"<rect x='{x}' y='{y}' width='{box_w}' height='{box_h}' rx='8' fill='#e8f0fe' stroke='#3b5bdb' stroke-width='1.5'/>")
        parts.append(f"<text x='{x + box_w // 2}' y='{y + 27}' {_FONT} font-size='12' text-anchor='middle' fill='#1c2b4a'>{_esc(state.value)}</text>")
        if i < n - 1:
            parts.append(f"<line x1='{x + box_w}' y1='{y + box_h // 2}' x2='{x + box_w + gap}' y2='{y + box_h // 2}' stroke='#3b5bdb' stroke-width='1.5' marker-end='url(#arrow)'/>")
    cx = x0 + 1 * (box_w + gap) + box_w // 2
    parts.append(f"<rect x='{cx - 64}' y='{y + 70}' width='128' height='{box_h}' rx='8' fill='#fdecec' stroke='#c92a2a' stroke-width='1.5'/>")
    parts.append(f"<text x='{cx}' y='{y + 97}' {_FONT} font-size='12' text-anchor='middle' fill='#7a1a1a'>cancelled + compensation</text>")
    parts.append(f"<line x1='{cx}' y1='{y + box_h}' x2='{cx}' y2='{y + 70}' stroke='#c92a2a' stroke-width='1.5' marker-end='url(#arrow)'/>")
    px = x0 + 3 * (box_w + gap) + box_w // 2
    parts.append(f"<path d='M {px + 20} {y} q 30 -30 0 -30 q -30 0 -20 30' fill='none' stroke='#3b5bdb' stroke-width='1.2'/>")
    parts.append(f"<text x='{px + 40}' y='{y - 20}' {_FONT} font-size='10' fill='#1c2b4a'>retry / review loop</text>")
    # actors row
    ay, aw, ah = 250, 118, 40
    ax0 = (width - (len(_ACTORS) * aw + (len(_ACTORS) - 1) * 14)) // 2
    pos: dict[str, tuple[int, int]] = {}
    for i, actor in enumerate(_ACTORS):
        x = ax0 + i * (aw + 14)
        pos[actor] = (x + aw // 2, ay)
        parts.append(f"<rect x='{x}' y='{ay}' width='{aw}' height='{ah}' rx='6' fill='#f1f3f5' stroke='#495057'/>")
        parts.append(f"<text x='{x + aw // 2}' y='{ay + 24}' {_FONT} font-size='10' text-anchor='middle' fill='#212529'>{_esc(actor.replace('_', ' '))}</text>")
    for k, (src, dst, label) in enumerate(_ACTOR_FLOWS):
        sx, sy = pos[src]
        dx, dy = pos[dst]
        bulge = 40 + 18 * (k % 5)
        mid = (sx + dx) // 2
        direction = -1 if k % 2 == 0 else 1
        cy = sy + (direction * bulge) + (ah if direction > 0 else 0)
        y1 = sy if direction < 0 else sy + ah
        parts.append(f"<path d='M {sx} {y1} Q {mid} {cy} {dx} {y1}' fill='none' stroke='#868e96' stroke-width='1.1' marker-end='url(#arrow-grey)'/>")
        parts.append(f"<text x='{mid}' y='{cy + (4 if direction > 0 else -2)}' {_FONT} font-size='9' text-anchor='middle' fill='#495057'>{_esc(label)}</text>")
    parts.append("<defs><marker id='arrow' markerWidth='8' markerHeight='8' refX='6' refY='3' orient='auto'><path d='M0,0 L6,3 L0,6 z' fill='#3b5bdb'/></marker>"
                 "<marker id='arrow-grey' markerWidth='8' markerHeight='8' refX='6' refY='3' orient='auto'><path d='M0,0 L6,3 L0,6 z' fill='#868e96'/></marker></defs>")
    parts.append(f"<text x='16' y='{height - 12}' {_FONT} font-size='10' fill='#666'>Rendered by tools/render_figures.py. original_project; no real company or transaction is depicted.</text>")
    parts.append("</svg>\n")
    return "\n".join(parts)


def backlog_svg(series_by_policy: Mapping[str, Sequence[Sequence[int]]], scenario_id: str, seed: int) -> str:
    width, height, left, top, right, bottom = 900, 360, 70, 50, 30, 60
    plot_w, plot_h = width - left - right, height - top - bottom
    colours = {"manual": "#1971c2", "rules_automation": "#2f9e44", "capacity_limited_review": "#e8590c"}
    max_t = max((pt[0] for s in series_by_policy.values() for pt in s), default=1) or 1
    max_d = max((pt[1] for s in series_by_policy.values() for pt in s), default=1) or 1
    parts = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>",
             "<rect width='100%' height='100%' fill='#ffffff'/>",
             f"<text x='{left}' y='24' {_FONT} font-size='14' fill='#222'>Review backlog over simulated time, scenario {_esc(scenario_id)}, seed {seed}. Demo output on synthetic workload; not a benchmark.</text>",
             f"<line x1='{left}' y1='{top + plot_h}' x2='{left + plot_w}' y2='{top + plot_h}' stroke='#333'/>",
             f"<line x1='{left}' y1='{top}' x2='{left}' y2='{top + plot_h}' stroke='#333'/>"]
    for k in range(5):
        d = round(max_d * k / 4)
        yy = top + plot_h - plot_h * k / 4
        parts.append(f"<text x='{left - 8}' y='{yy + 4:.0f}' {_FONT} font-size='10' text-anchor='end' fill='#333'>{d}</text>")
        parts.append(f"<line x1='{left}' y1='{yy:.0f}' x2='{left + plot_w}' y2='{yy:.0f}' stroke='#eee'/>")
    for k in range(8):
        t = round(max_t * k / 7)
        xx = left + plot_w * k / 7
        parts.append(f"<text x='{xx:.0f}' y='{top + plot_h + 16}' {_FONT} font-size='10' text-anchor='middle' fill='#333'>day {t / 1440:.1f}</text>")
    for i, (policy, series) in enumerate(series_by_policy.items()):
        pts = " ".join(f"{left + plot_w * t / max_t:.1f},{top + plot_h - plot_h * d / max_d:.1f}" for t, d in series)
        colour = colours.get(policy, "#555")
        parts.append(f"<polyline points='{pts}' fill='none' stroke='{colour}' stroke-width='1.8'/>")
        ly = top + 14 + 16 * i
        parts.append(f"<line x1='{left + plot_w - 220}' y1='{ly}' x2='{left + plot_w - 196}' y2='{ly}' stroke='{colour}' stroke-width='3'/>")
        parts.append(f"<text x='{left + plot_w - 190}' y='{ly + 4}' {_FONT} font-size='11' fill='#333'>{_esc(policy)}</text>")
    parts.append(f"<text x='{left}' y='{height - 14}' {_FONT} font-size='10' fill='#666'>x: simulated time (days from fictional epoch); y: open review items. Rendered by tools/render_figures.py.</text>")
    parts.append("</svg>\n")
    return "\n".join(parts)


def render_all(figures_dir: str | Path, comparison: Mapping[str, Any] | None) -> list[Path]:
    out = Path(figures_dir)
    written = [write_text(out / "workflow.svg", workflow_svg())]
    if comparison is not None:
        series = {p: r["backlog_series"] for p, r in comparison["policies"].items()}
        written.append(write_text(out / "review_backlog.svg", backlog_svg(series, comparison["scenario_id"], int(comparison["seed"]))))
    return written
