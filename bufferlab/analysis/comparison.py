"""Run comparison tables and evidence-based observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bufferlab.experiments.models import RunRecord


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    unit: str
    better: str | None  # "lower" | "higher" | None
    digits: int = 2
    scale: float = 1.0


COLUMNS: tuple[Column, ...] = (
    Column("offered_load_mbps", "Offered", "Mbps", None, 2),
    Column("throughput_mbps", "Throughput", "Mbps", "higher", 2),
    Column("loss_rate", "Loss", "%", "lower", 2, 100.0),
    Column("avg_queue_delay_ms", "Avg q-delay", "ms", "lower", 2),
    Column("link_utilisation", "Link util", "%", None, 1, 100.0),
)
COLUMN_BY_KEY = {c.key: c for c in COLUMNS}


def fmt_value(col: Column, value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value * col.scale:.{col.digits}f}"


def run_name(run: RunRecord, index: int | None = None) -> str:
    tag = f"{chr(ord('A') + index)}" if index is not None and index < 26 else ""
    return f"Run {tag} ({run.config.algorithm})" if tag else run.config.algorithm


def comparison_rows(runs: list[RunRecord]) -> list[dict[str, Any]]:
    rows = []
    for i, r in enumerate(runs):
        row: dict[str, Any] = {
            "tag": chr(ord("A") + i) if i < 26 else str(i),
            "run_id": r.run_id,
            "algorithm": r.config.algorithm,
            "name": r.config.name,
        }
        for c in COLUMNS:
            row[c.key] = r.metrics.get(c.key)
        rows.append(row)
    return rows


def sort_rows(
    rows: list[dict[str, Any]], key: str, descending: bool = False
) -> list[dict[str, Any]]:
    present = [r for r in rows if r.get(key) is not None]
    missing = [r for r in rows if r.get(key) is None]
    return sorted(present, key=lambda r: r[key], reverse=descending) + missing


def differing_config_fields(runs: list[RunRecord]) -> list[str]:
    """Config fields (other than name/scenario) that are not identical across runs."""
    if len(runs) < 2:
        return []
    dicts = [r.config.to_dict() for r in runs]
    out = []
    for k in dicts[0]:
        if k in ("name", "scenario"):
            continue
        if any(d.get(k) != dicts[0].get(k) for d in dicts[1:]):
            out.append(k)
    return out


def observations(runs: list[RunRecord], rel_tol: float = 0.02) -> list[str]:
    """Measured differences only; no claims beyond the tested configurations."""
    if len(runs) < 2:
        return ["Select at least two runs to compare."]
    out: list[str] = []
    diff = differing_config_fields(runs)
    non_alg = [d for d in diff if d not in ("algorithm", "algorithm_params")]
    if non_alg:
        out.append(
            "Caution: these runs also differ in "
            + ", ".join(non_alg)
            + ", so metric differences cannot be attributed to the algorithm alone."
        )
    seeds = {r.config.seed for r in runs}
    if len(runs) >= 2:
        out.append(
            "Each figure comes from a single run per entry"
            + (" (same seed)." if len(seeds) == 1 else " (different seeds).")
            + " Use repeated runs (batch mode) to judge sensitivity to random variation."
        )
    names = {i: run_name(r, i) for i, r in enumerate(runs)}
    for key, phrase in (
        ("loss_rate", "packet-loss rate"),
        ("throughput_mbps", "delivered throughput"),
        ("avg_queue_delay_ms", "average queueing delay"),
    ):
        col = COLUMN_BY_KEY[key]
        vals = [
            (i, r.metrics.get(key)) for i, r in enumerate(runs) if r.metrics.get(key) is not None
        ]
        if len(vals) < 2:
            continue
        best = (
            min(vals, key=lambda x: x[1])
            if col.better == "lower"
            else max(vals, key=lambda x: x[1])
        )
        worst = (
            max(vals, key=lambda x: x[1])
            if col.better == "lower"
            else min(vals, key=lambda x: x[1])
        )
        scale = max(abs(best[1]), abs(worst[1]), 1e-12)
        if abs(best[1] - worst[1]) / scale <= rel_tol:
            out.append(f"{phrase.capitalize()} was within {rel_tol:.0%} across all selected runs.")
            continue
        direction = "lower" if col.better == "lower" else "higher"
        out.append(
            f"{names[best[0]]} had {direction} {phrase} than {names[worst[0]]} under the tested "
            f"configuration ({fmt_value(col, best[1])} vs {fmt_value(col, worst[1])} {col.unit})."
        )
    return out
