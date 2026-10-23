"""Rich renderables shared by several screens."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from bufferlab.analysis.comparison import (
    COLUMN_BY_KEY,
    COLUMNS,
    comparison_rows,
    fmt_value,
    observations,
    sort_rows,
)
from bufferlab.experiments.models import RunRecord
from bufferlab.tui import format as fmt


def metrics_table(rec: RunRecord) -> Table:
    m = rec.metrics
    t = Table(show_header=False, box=None, pad_edge=False, expand=True)
    t.add_column(style="cyan", no_wrap=True)
    t.add_column(justify="right")
    rows = [
        (
            "Offered load",
            f"{fmt.mbps(m['offered_load_mbps'])} ({m['offered_load_pct']:.0f}% of link)",
        ),
        ("Measured offered", fmt.mbps(m["measured_offered_mbps"])),
        ("Delivered throughput", fmt.mbps(m["throughput_mbps"])),
        ("Delivery ratio", fmt.pct(m["delivery_ratio"])),
        ("Packet-loss rate", fmt.pct(m["loss_rate"])),
        ("Generated", fmt.count(m["generated"])),
        ("Delivered", fmt.count(m["delivered"])),
        (
            "Dropped (ovf/early/aqm)",
            f"{fmt.count(m['dropped'])} ({m['dropped_overflow']}/{m['dropped_early']}/{m['dropped_aqm']})",
        ),
        ("Unresolved at end", fmt.count(m["unresolved"])),
        ("Queue delay avg", fmt.ms(m["avg_queue_delay_ms"])),
        ("Queue delay median", fmt.ms(m["median_queue_delay_ms"])),
        ("Queue delay p95", fmt.ms(m["p95_queue_delay_ms"])),
        ("Queue delay max", fmt.ms(m["max_queue_delay_ms"])),
        ("Total delay avg (one-way)", fmt.ms(m["avg_total_delay_ms"])),
        ("Queue length avg / max", f"{m['avg_queue_len']:.2f} / {m['max_queue_len']}"),
        ("Queue utilisation", fmt.pct(m["queue_utilisation"], 1)),
        ("Link utilisation", fmt.pct(m["link_utilisation"], 1)),
        ("Overflow events", fmt.count(m["overflow_events"])),
        ("Measured window", fmt.duration(m["measured_window_s"])),
        ("Status", f"{rec.terminated}, {rec.events_processed:,} events"),
    ]
    for k, v in rows:
        t.add_row(k, v)
    return t


def bars(rows: list[dict], key: str, width: int = 30, ascii_mode: bool = False) -> Text:
    col = COLUMN_BY_KEY[key]
    vals = [r[key] for r in rows if r[key] is not None]
    top = max(vals) if vals else 0
    out = Text()
    out.append(
        f"{col.label} ({col.unit}) — {'lower' if col.better == 'lower' else 'higher' if col.better else ''} "
        f"{'is better' if col.better else ''}\n".replace("  \n", "\n"),
        style="bold",
    )
    ch = "#" if ascii_mode else "█"
    for r in rows:
        v = r[key]
        n = int(round(width * v / top)) if v is not None and top > 0 else 0
        out.append(f" {r['tag']} {r['algorithm']:<10} ")
        out.append(ch * n, style="cyan")
        out.append(f" {fmt_value(col, v)}\n")
    return out


def comparison_view(
    runs: list[RunRecord], sort_key: str, ascii_mode: bool = False
) -> RenderableType:
    if len(runs) < 2:
        return Text("Mark two or more runs (Space) to compare them.", style="dim")
    rows = comparison_rows(runs)
    col = COLUMN_BY_KEY[sort_key]
    rows = sort_rows(rows, sort_key, descending=col.better == "higher")
    t = Table(title=f"Sorted by {col.label}", expand=True)
    t.add_column("Tag")
    t.add_column("Run", style="cyan", no_wrap=True)
    t.add_column("Algorithm")
    for c in COLUMNS:
        t.add_column(f"{c.label}\n({c.unit})", justify="right")
    for r in rows:
        t.add_row(
            r["tag"],
            r["run_id"],
            r["algorithm"],
            *[
                Text(fmt_value(c, r[c.key]), style="bold cyan" if c.key == sort_key else "")
                for c in COLUMNS
            ],
        )
    obs = Text("\nObservations (automated, from measured values only):\n", style="bold")
    for o in observations(runs):
        obs.append(f" • {o}\n")
    return Group(t, Text(""), bars(rows, sort_key, ascii_mode=ascii_mode), obs)
