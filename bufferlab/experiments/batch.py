"""Batch experiments: parameter sweeps x replications, and the research matrix.

``factors`` name what varies between points.  Valid factor keys are any
:class:`ExperimentConfig` field (e.g. ``offered_load_pct``, ``queue_capacity``,
``link_mbps``), ``algorithm``, or ``param.<name>`` for an algorithm parameter.
Parameters an algorithm does not define are ignored for that algorithm and the
resulting duplicate points are merged.

Replication ``k`` of a point uses ``seed = base_seed + k``; the same replication
index therefore sees the same traffic realisation across algorithms (common
random numbers), which makes paired comparisons less noisy.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bufferlab.algorithms import get_algorithm
from bufferlab.analysis.statistics import SummaryStats, summarize
from bufferlab.experiments.models import ConfigError, ExperimentConfig, RunRecord
from bufferlab.experiments.runner import run_experiment

SUMMARY_METRICS = (
    "throughput_mbps",
    "loss_rate",
    "avg_queue_delay_ms",
    "p95_queue_delay_ms",
    "link_utilisation",
    "avg_queue_len",
    "max_queue_len",
    "delivery_ratio",
)

#: Nominal buffer sizes (packets) for the research matrix's small/medium/large.
CAPACITY_PRESETS = {"small": 10, "medium": 50, "large": 250}


@dataclass
class BatchSpec:
    name: str
    base: ExperimentConfig
    factors: dict[str, list[Any]] = field(default_factory=dict)
    replications: int = 1
    base_seed: int | None = None
    objective: str = ""

    def seed0(self) -> int:
        return self.base.seed if self.base_seed is None else self.base_seed

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base": self.base.to_dict(),
            "factors": self.factors,
            "replications": self.replications,
            "base_seed": self.seed0(),
            "objective": self.objective,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BatchSpec:
        return cls(
            d["name"],
            ExperimentConfig.from_dict(d["base"]),
            d.get("factors", {}),
            d.get("replications", 1),
            d.get("base_seed"),
            d.get("objective", ""),
        )

    def validate(self) -> list[str]:
        errs: list[str] = []
        if self.replications < 1:
            errs.append("replications must be >= 1")
        for key, values in self.factors.items():
            if not values:
                errs.append(f"factor {key!r} has no values")
        return errs

    def points(self) -> list[tuple[dict[str, Any], ExperimentConfig]]:
        """Distinct (factors, config-with-seed-base) points in sweep order."""
        keys = list(self.factors)
        seen: dict[tuple, tuple[dict[str, Any], ExperimentConfig]] = {}
        for combo in itertools.product(*(self.factors[k] for k in keys)) if keys else [()]:
            assigned = dict(zip(keys, combo, strict=True))
            cfg = self.base
            params = dict(cfg.algorithm_params)
            field_changes = {k: v for k, v in assigned.items() if not k.startswith("param.")}
            cfg = cfg.replace(**field_changes)
            relevant = dict(field_changes)
            declared = {p.name for p in get_algorithm(cfg.algorithm).params}
            for k, v in assigned.items():
                if k.startswith("param."):
                    pname = k[6:]
                    if pname in declared:
                        params[pname] = v
                        relevant[k] = v
            params = {k: v for k, v in params.items() if k in declared}
            cfg = cfg.replace(algorithm_params=params, seed=self.seed0())
            ident = tuple(sorted((k, repr(v)) for k, v in relevant.items()))
            if ident not in seen:
                label = ",".join(f"{k}={v}" for k, v in relevant.items())
                seen[ident] = (
                    relevant,
                    cfg.replace(name=f"{self.name}[{label}]" if label else self.name),
                )
        return list(seen.values())

    def total_runs(self) -> int:
        return len(self.points()) * self.replications


@dataclass
class PointResult:
    factors: dict[str, Any]
    runs: list[RunRecord]

    def summary(self) -> dict[str, SummaryStats]:
        return {m: summarize([r.metrics.get(m) for r in self.runs]) for m in SUMMARY_METRICS}


@dataclass
class BatchResult:
    batch_id: str
    spec: BatchSpec
    points: list[PointResult]
    cancelled: bool = False

    @property
    def runs(self) -> list[RunRecord]:
        return [r for p in self.points for r in p.runs]


BatchProgress = Callable[[int, int, str], None]  # (done, total, current label)


def run_batch(
    spec: BatchSpec,
    on_progress: BatchProgress | None = None,
    cancel: threading.Event | None = None,
    on_run: Callable[[RunRecord], None] | None = None,
) -> BatchResult:
    errs = spec.validate()
    if errs:
        raise ValueError("; ".join(errs))
    pts = spec.points()
    for _factors, cfg in pts:  # fail fast before running anything
        report = cfg.validate()
        if not report.ok:
            raise ConfigError(report)
    batch_id = "b" + uuid.uuid4().hex[:8]
    total = len(pts) * spec.replications
    done = 0
    results: list[PointResult] = []
    cancelled = False
    for factors, cfg in pts:
        runs: list[RunRecord] = []
        for k in range(spec.replications):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            if on_progress:
                on_progress(done, total, cfg.name)
            rec = run_experiment(
                cfg.replace(seed=spec.seed0() + k), cancel=cancel, batch_id=batch_id, replicate=k
            )
            if rec.terminated == "cancelled":
                cancelled = True
                break
            runs.append(rec)
            done += 1
            if on_run:
                on_run(rec)
        if runs:
            results.append(PointResult(factors, runs))
        if cancelled:
            break
    if on_progress:
        on_progress(done, total, "done" if not cancelled else "cancelled")
    return BatchResult(batch_id, spec, results, cancelled)


def research_matrix(
    base: ExperimentConfig,
    *,
    algorithms: list[str] | None = None,
    load_pcts: list[float] | None = None,
    capacities: list[int] | None = None,
    replications: int = 5,
    name: str = "research-matrix",
    objective: str = "",
) -> BatchSpec:
    """Algorithms x offered-load x queue-capacity matrix (percentages -> concrete pps)."""
    return BatchSpec(
        name=name,
        base=base,
        factors={
            "algorithm": algorithms or ["drop-tail", "red", "codel"],
            "offered_load_pct": load_pcts or [50.0, 75.0, 100.0, 125.0, 150.0],
            "queue_capacity": capacities or list(CAPACITY_PRESETS.values()),
        },
        replications=replications,
        objective=objective,
    )
