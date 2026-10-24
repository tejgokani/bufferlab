"""Exports and reproducible reports (CSV / JSON / Markdown / plain text)."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bufferlab import SCHEMA_VERSION, __version__
from bufferlab.analysis.comparison import COLUMNS, comparison_rows, fmt_value, observations
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
