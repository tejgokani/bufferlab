"""Optional Matplotlib exports (``pip install "bufferlab[plots]"``)."""

from __future__ import annotations

from pathlib import Path

from bufferlab.analysis.comparison import COLUMNS, fmt_value
from bufferlab.experiments.models import RunRecord


def _plt():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise RuntimeError('matplotlib is not installed: pip install "bufferlab[plots]"') from None
    return plt


def plot_runs(runs: list[RunRecord], path: Path | str) -> Path:
    """Time series overlay (one line per run) in a 2x2 grid."""
    if not runs:
        raise ValueError("nothing to plot")
    plt = _plt()
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    panels = [
        ("queue_len", "Queue occupancy (pkts)"),
        ("throughput_mbps", "Throughput (Mbps)"),
        ("queue_delay_ms", "Queueing delay (ms)"),
        ("drops", "Drops per bin"),
    ]
    for ax, (key, title) in zip(axes.flat, panels, strict=True):
        for r in runs:
            s = r.series
            ys = [float("nan") if v is None else v for v in s[key]]
            ax.plot(s["t"], ys, label=f"{r.config.algorithm} ({r.run_id})", linewidth=1.2)
        warm = runs[0].series.get("warmup_s", 0)
        if warm:
            ax.axvspan(0, warm, color="grey", alpha=0.15)
        ax.set_title(title)
        ax.set_xlabel("simulated time (s)")
        ax.grid(alpha=0.3)
    axes[0][0].legend(fontsize=8)
    fig.suptitle("BufferLab time series (shaded = warm-up, excluded from metrics)")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_comparison(runs: list[RunRecord], path: Path | str) -> Path:
    """Bar charts of the comparison metrics, one panel per metric."""
    if not runs:
        raise ValueError("nothing to plot")
    plt = _plt()
    cols = [c for c in COLUMNS if c.key != "offered_load_mbps"]
    fig, axes = plt.subplots(2, 3, figsize=(12, 7), constrained_layout=True)
    labels = [f"{chr(65 + i)}:{r.config.algorithm}" for i, r in enumerate(runs)]
    for ax, c in zip(axes.flat, cols, strict=False):
        vals = [(r.metrics.get(c.key) or 0.0) * c.scale for r in runs]
        ax.bar(labels, vals)
        ax.set_title(f"{c.label} ({c.unit})")
        for i, r in enumerate(runs):
            ax.annotate(
                fmt_value(c, r.metrics.get(c.key)),
                (i, vals[i]),
                ha="center",
                va="bottom",
                fontsize=8,
            )
        ax.tick_params(axis="x", labelrotation=30)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
