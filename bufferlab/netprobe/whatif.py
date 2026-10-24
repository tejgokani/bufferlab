"""What-if predictions: run the simulator with the measured network's parameters at chosen loads."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from bufferlab.experiments.models import RunRecord
from bufferlab.experiments.runner import run_experiment
from bufferlab.netprobe.profile import NetworkProfile

DEFAULT_LOAD_FRACTIONS = (0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0)
ALGORITHMS = ("drop-tail", "red", "codel")


@dataclass(frozen=True)
class Prediction:
    load_mbps: float
    load_pct: float
    algorithm: str
    throughput_mbps: float
    loss_rate: float | None
    avg_delay_ms: float | None
    p95_delay_ms: float | None
    run_id: str


def default_loads(capacity_mbps: float) -> list[float]:
    return [round(capacity_mbps * f, 3) for f in DEFAULT_LOAD_FRACTIONS]


def duration_for(load_mbps: float, packet_bytes: int = 1500) -> tuple[float, float]:
    """(duration, warm-up): shorter at high packet rates so each run stays near 400k events."""
    pps = max(load_mbps * 1e6 / (packet_bytes * 8), 1.0)
    dur = max(3.0, min(20.0, 200_000 / pps))
    return dur, round(dur * 0.2, 3)


def predict(
    profile: NetworkProfile,
    loads_mbps: list[float],
    algorithms: list[str],
    traffic_model: str = "poisson",
    seed: int = 42,
    on_run: Callable[[RunRecord], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[Prediction]:
    out: list[Prediction] = []
    total = len(loads_mbps) * len(algorithms)
    done = 0
    for load in loads_mbps:
        dur, warm = duration_for(load)
        for alg in algorithms:
            if cancel is not None and cancel.is_set():
                return out
            if on_progress:
                on_progress(done, total)
            cfg = profile.base_config(
                algorithm=alg,
                traffic_model=traffic_model,
                offered_load_pct=100.0 * load / profile.capacity_mbps,
                duration_s=dur,
                warmup_s=warm,
                seed=seed,
                name=f"my-network/{alg}@{load:g}Mbps",
            )
            rec = run_experiment(cfg, cancel=cancel)
            if rec.terminated == "cancelled":
                return out
            if on_run:
                on_run(rec)
            m = rec.metrics
            out.append(
                Prediction(
                    load,
                    cfg.offered_load_pct,
                    alg,
                    m["throughput_mbps"],
                    m["loss_rate"],
                    m["avg_queue_delay_ms"],
                    m["p95_queue_delay_ms"],
                    rec.run_id,
                )
            )
            done += 1
    if on_progress:
        on_progress(done, total)
    return out


def knee(preds: list[Prediction], algorithm: str, loss_threshold: float = 0.01) -> float | None:
    """Smallest simulated offered load (Mbps) at which loss exceeds the threshold, or None."""
    for p in sorted((p for p in preds if p.algorithm == algorithm), key=lambda p: p.load_mbps):
        if p.loss_rate is not None and p.loss_rate > loss_threshold:
            return p.load_mbps
    return None
