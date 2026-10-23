"""Exports and reproducible reports (CSV / JSON / Markdown / plain text)."""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bufferlab import SCHEMA_VERSION, __version__
from bufferlab.analysis.comparison import COLUMNS, comparison_rows, fmt_value, observations
from bufferlab.analysis.statistics import SummaryStats, summarize
from bufferlab.experiments.batch import BatchSpec
from bufferlab.experiments.models import RunRecord

FORMATS = ("csv", "json", "md", "txt")
AUTO_LABEL = (
    "Automated interpretation generated from the measured numbers below; it is not an "
    "independently verified scientific conclusion."
)


# -- flat export ---------------------------------------------------------------
def run_to_flat(r: RunRecord) -> dict[str, Any]:
    c = r.config.to_dict()
    flat: dict[str, Any] = {
        "run_id": r.run_id,
        "created_at": r.created_at,
        "batch_id": r.batch_id or "",
        "replicate": r.replicate,
        "software_version": r.software_version,
        "schema_version": r.schema_version,
        "terminated": r.terminated,
        "algorithm_params_resolved": json.dumps(r.resolved_params, sort_keys=True),
    }
    flat.update(
        {
            f"cfg_{k}": (json.dumps(v, sort_keys=True) if isinstance(v, dict) else v)
            for k, v in c.items()
        }
    )
    flat.update({f"m_{k}": v for k, v in r.metrics.items()})
    return flat


def run_to_json(r: RunRecord, include_series: bool = True) -> dict[str, Any]:
    d: dict[str, Any] = {
        "run_id": r.run_id,
        "created_at": r.created_at,
        "software_version": r.software_version,
        "schema_version": r.schema_version,
        "batch_id": r.batch_id,
        "replicate": r.replicate,
        "terminated": r.terminated,
        "events_processed": r.events_processed,
        "config": r.config.to_dict(),
        "resolved_algorithm_params": r.resolved_params,
        "metrics": r.metrics,
    }
    if include_series:
        d["series"] = r.series
    return d


# -- tiny document model -------------------------------------------------------
@dataclass
class Doc:
    title: str
    blocks: list[tuple] = field(default_factory=list)

    def h(self, text: str) -> None:
        self.blocks.append(("h", text))

    def p(self, text: str) -> None:
        self.blocks.append(("p", text))

    def bullets(self, items: list[str]) -> None:
        self.blocks.append(("ul", items))

    def table(self, headers: list[str], rows: list[list[str]]) -> None:
        self.blocks.append(("table", headers, rows))

    def code(self, text: str) -> None:
        self.blocks.append(("code", text))

    def to_markdown(self) -> str:
        out = [f"# {self.title}", ""]
        for b in self.blocks:
            if b[0] == "h":
                out += [f"## {b[1]}", ""]
            elif b[0] == "p":
                out += [b[1], ""]
            elif b[0] == "ul":
                out += [f"- {i}" for i in b[1]] + [""]
            elif b[0] == "code":
                out += ["```", b[1], "```", ""]
            else:
                _, headers, rows = b
                out.append("| " + " | ".join(headers) + " |")
                out.append("|" + "|".join("---" for _ in headers) + "|")
                out += ["| " + " | ".join(r) + " |" for r in rows]
                out.append("")
        return "\n".join(out)

    def to_text(self) -> str:
        out = [self.title.upper(), "=" * len(self.title), ""]
        for b in self.blocks:
            if b[0] == "h":
                out += [b[1].upper(), "-" * len(b[1])]
            elif b[0] == "p":
                out += [b[1], ""]
            elif b[0] == "ul":
                out += [f"  * {i}" for i in b[1]] + [""]
            elif b[0] == "code":
                out += [b[1], ""]
            else:
                _, headers, rows = b
                widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows, strict=True)]
                out.append("  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)))
                out.append("  ".join("-" * w for w in widths))
                out += [
                    "  ".join(str(x).ljust(w) for x, w in zip(r, widths, strict=True)) for r in rows
                ]
                out.append("")
        return "\n".join(out)

    def render(self, fmt: str) -> str:
        return self.to_markdown() if fmt == "md" else self.to_text()


METRIC_DEFINITIONS = [
    "Offered load = arrival rate x packet size x 8 (nominal, Mbps); % of link capacity.",
    "Throughput = bits whose transmission finished in the measurement window / window length.",
    "Loss rate = dropped / generated, over packets arriving after warm-up (unresolved packets "
    "still queued at the end are neither delivered nor dropped).",
    "Queueing delay = time from enqueue to start of transmission (not RTT), delivered packets only.",
    "Link utilisation = fraction of the window the link was transmitting.",
    "Queue length = packets waiting (excluding the one being transmitted), time-averaged.",
]
LIMITATIONS = [
    "Single bottleneck, open-loop sources: no TCP congestion control, retransmissions or "
    "multiple hops, so results do not predict TCP throughput.",
    "RED and CoDel are simplified, unvalidated implementations of their published descriptions "
    "(see docs/algorithms.md); drop-only, no ECN.",
    "Simulation results depend on the traffic model and parameters chosen; they are not "
    "measurements of any real network.",
    "Confidence intervals describe variation across seeds only; they are not significance tests.",
]


def _config_lines(r: RunRecord) -> list[str]:
    return r.config.summary_lines()


# -- reports -------------------------------------------------------------------
def runs_report(runs: list[RunRecord], title: str = "BufferLab run comparison") -> Doc:
    doc = Doc(title)
    doc.p(
        f"Generated by BufferLab {__version__} (schema {SCHEMA_VERSION}). All numbers come from "
        "the discrete-event simulator; nothing is estimated analytically."
    )
    doc.h("Runs")
    doc.table(
        ["Tag", "Run ID", "Seed", "Config"],
        [
            [row["tag"], r.run_id, str(r.config.seed), r.config.name]
            for row, r in zip(comparison_rows(runs), runs, strict=True)
        ],
    )
    doc.h("Configurations")
    for i, r in enumerate(runs):
        doc.p(f"Run {chr(65 + i)} ({r.run_id}):")
        doc.code("\n".join(_config_lines(r)))
    doc.h("Metrics")
    doc.bullets(METRIC_DEFINITIONS)
    doc.h("Results")
    headers = ["Tag", "Algorithm"] + [f"{c.label} ({c.unit})" for c in COLUMNS]
    rows = [
        [row["tag"], row["algorithm"]] + [fmt_value(c, row[c.key]) for c in COLUMNS]
        for row in comparison_rows(runs)
    ]
    doc.table(headers, rows)
    doc.h("Comparative observations")
    doc.p(AUTO_LABEL)
    doc.bullets(observations(runs))
    doc.h("Limitations")
    doc.bullets(LIMITATIONS)
    return doc


def group_by_point(runs: list[RunRecord]) -> list[list[RunRecord]]:
    """Group replications that share a configuration (ignoring seed/name)."""
    groups: dict[str, list[RunRecord]] = defaultdict(list)
    for r in runs:
        d = r.config.to_dict()
        for k in ("seed", "name", "scenario"):
            d.pop(k, None)
        groups[json.dumps(d, sort_keys=True)].append(r)
    return [sorted(g, key=lambda r: r.replicate) for g in groups.values()]


def _pm(s: SummaryStats, digits: int = 2, scale: float = 1.0) -> str:
    if s.mean is None:
        return "n/a"
    if s.n < 2 or s.half_width is None:
        return f"{s.mean * scale:.{digits}f} (n=1)"
    return f"{s.mean * scale:.{digits}f} ± {s.half_width * scale:.{digits}f}"


def batch_report(spec: BatchSpec, runs: list[RunRecord]) -> Doc:
    doc = Doc(f"BufferLab experiment report: {spec.name}")
    doc.h("Objective")
    doc.p(spec.objective or "Compare queue-management algorithms across the configured factors.")
    doc.h("Configuration")
    doc.code("\n".join(spec.base.summary_lines()))
    doc.p("Factors varied: " + (", ".join(f"{k} = {v}" for k, v in spec.factors.items()) or "none"))
    doc.h("Algorithms tested")
    algs = sorted({r.config.algorithm for r in runs})
    doc.bullets(
        [
            f"{a}: {json.dumps(next(r.resolved_params for r in runs if r.config.algorithm == a))}"
            for a in algs
        ]
    )
    doc.h("Methodology")
    doc.bullets(
        [
            f"{spec.replications} independent replication(s) per point; replication k uses seed "
            f"{spec.seed0()} + k, so each algorithm sees the same traffic realisation per replication "
            "(common random numbers).",
            f"Each run lasts {spec.base.duration_s:g}s; the first {spec.base.warmup_s:g}s is warm-up and "
            "excluded from all statistics.",
            "Offered-load percentages are converted to packet rates from link bandwidth and packet size; "
            "delivered throughput is measured separately and is not assumed equal to offered load.",
            "Mean ± half-width of a 95% Student-t interval across replications is shown "
            "(n=1 shows the single value).",
            f"BufferLab {__version__}, schema {SCHEMA_VERSION}; rerun with the same spec to reproduce.",
        ]
    )
    doc.h("Metrics")
    doc.bullets(METRIC_DEFINITIONS)
    doc.h("Results")
    groups = group_by_point(runs)
    varying = [k for k in spec.factors if k not in ("algorithm",)]
    headers = (
        ["Algorithm"]
        + [k.replace("param.", "") for k in varying]
        + [
            "n",
            "Throughput (Mbps)",
            "Loss (%)",
            "Avg q-delay (ms)",
            "p95 q-delay (ms)",
            "Link util (%)",
        ]
    )
    rows = []
    summaries: dict[int, dict[str, SummaryStats]] = {}
    for gi, g in enumerate(groups):
        c = g[0].config
        s = {
            m: summarize([r.metrics.get(m) for r in g])
            for m in (
                "throughput_mbps",
                "loss_rate",
                "avg_queue_delay_ms",
                "p95_queue_delay_ms",
                "link_utilisation",
            )
        }
        summaries[gi] = s
        fvals = []
        for k in varying:
            if k.startswith("param."):
                fvals.append(str(c.algorithm_params.get(k[6:], "-")))
            else:
                fvals.append(str(getattr(c, k)))
        rows.append(
            [c.algorithm]
            + fvals
            + [
                str(len(g)),
                _pm(s["throughput_mbps"]),
                _pm(s["loss_rate"], 2, 100),
                _pm(s["avg_queue_delay_ms"]),
                _pm(s["p95_queue_delay_ms"]),
                _pm(s["link_utilisation"], 1, 100),
            ]
        )
    doc.table(headers, rows)
    doc.h("Comparative observations")
    doc.p(AUTO_LABEL)
    doc.bullets(batch_observations(groups, summaries, varying))
    doc.h("Limitations")
    doc.bullets(LIMITATIONS)
    doc.h("Questions for further investigation")
    doc.bullets(
        [
            "Do the observed ordering and trade-offs persist with more replications or longer runs?",
            "How sensitive are the results to RED thresholds/weight and CoDel target/interval?",
            "How would closed-loop (TCP-like) sources change delay and loss under the same buffers?",
            "Do the results change with different traffic models (constant vs Poisson vs bursty)?",
        ]
    )
    return doc


def batch_observations(
    groups: list[list[RunRecord]], summaries: dict[int, dict[str, SummaryStats]], varying: list[str]
) -> list[str]:
    """Per condition (all non-algorithm factors fixed): who had the lowest mean p95 delay."""
    by_cond: dict[tuple, list[int]] = defaultdict(list)
    for gi, g in enumerate(groups):
        c = g[0].config
        cond = tuple(
            (k, c.algorithm_params.get(k[6:]) if k.startswith("param.") else getattr(c, k))
            for k in varying
        )
        by_cond[cond].append(gi)
    out: list[str] = []
    for cond, idxs in by_cond.items():
        if len(idxs) < 2:
            continue
        label = ", ".join(f"{k.replace('param.', '')}={v}" for k, v in cond) or "all conditions"
        ranked = sorted(
            (i for i in idxs if summaries[i]["p95_queue_delay_ms"].mean is not None),
            key=lambda i: summaries[i]["p95_queue_delay_ms"].mean,
        )
        if len(ranked) < 2:
            continue
        lo, hi = ranked[0], ranked[-1]
        s_lo, s_hi = summaries[lo]["p95_queue_delay_ms"], summaries[hi]["p95_queue_delay_ms"]
        a_lo, a_hi = groups[lo][0].config.algorithm, groups[hi][0].config.algorithm
        if s_hi.mean - s_lo.mean <= 0.02 * max(s_hi.mean, 1e-9):
            out.append(
                f"[{label}] mean p95 queueing delay was within 2% across algorithms "
                f"({s_lo.mean:.2f}-{s_hi.mean:.2f} ms); no meaningful difference observed."
            )
            continue
        overlap = (
            s_lo.ci_high is not None and s_hi.ci_low is not None and s_lo.ci_high >= s_hi.ci_low
        )
        note = (
            (
                "the 95% intervals overlap, so the difference is not distinguishable from "
                "run-to-run variation at this sample size"
                if overlap
                else "the 95% intervals do not overlap (not a formal significance test)"
            )
            if s_lo.n >= 2 and s_hi.n >= 2
            else "only one replication, so variability is unknown"
        )
        loss_lo = summaries[lo]["loss_rate"].mean
        loss_hi = summaries[hi]["loss_rate"].mean
        out.append(
            f"[{label}] {a_lo} had the lowest mean p95 queueing delay "
            f"({s_lo.mean:.2f} ms) vs {a_hi} ({s_hi.mean:.2f} ms); {note}. "
            f"Mean loss: {a_lo} {100 * (loss_lo or 0):.2f}% vs {a_hi} {100 * (loss_hi or 0):.2f}%."
        )
    return out or ["Not enough comparable points for automated observations."]


# -- file export -----------------------------------------------------------------
def export_runs(
    runs: list[RunRecord], fmt: str, path: Path | str, include_series: bool = True
) -> Path:
    if fmt not in FORMATS:
        raise ValueError(f"unsupported format {fmt!r}; choose from {', '.join(FORMATS)}")
    if not runs:
        raise ValueError("nothing to export")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        flats = [run_to_flat(r) for r in runs]
        cols: list[str] = []
        for f in flats:
            cols += [k for k in f if k not in cols]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(flats)
        path.write_text(buf.getvalue(), encoding="utf-8")
    elif fmt == "json":
        payload = {
            "bufferlab_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "runs": [run_to_json(r, include_series) for r in runs],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        path.write_text(runs_report(runs).render(fmt), encoding="utf-8")
    return path


def export_batch(spec: BatchSpec, runs: list[RunRecord], fmt: str, path: Path | str) -> Path:
    if fmt in ("md", "txt"):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(batch_report(spec, runs).render(fmt), encoding="utf-8")
        return path
    if fmt == "json":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "bufferlab_version": __version__,
                    "schema_version": SCHEMA_VERSION,
                    "spec": spec.to_dict(),
                    "runs": [run_to_json(r, False) for r in runs],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path
    return export_runs(runs, fmt, path, include_series=False)
