"""Algorithm registry: parameter specs, validation, defaults and construction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bufferlab.algorithms.base import QueueManager
from bufferlab.algorithms.codel import CoDel
from bufferlab.algorithms.drop_tail import DropTail
from bufferlab.algorithms.red import RED
from bufferlab.core.random_source import derive_rng


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    kind: str  # "float" | "int" | "bool"
    default: Any  # None => derived from queue capacity (see ``auto_hint``)
    help: str
    unit: str = ""
    auto_hint: str = ""


@dataclass(frozen=True)
class AlgorithmSpec:
    key: str
    label: str
    summary: str
    params: tuple[ParamSpec, ...] = ()
    build: Callable[..., QueueManager] = field(default=lambda **_: None)  # type: ignore[assignment]


def _build_drop_tail(capacity: int, params: dict[str, Any], **_: Any) -> QueueManager:
    return DropTail(capacity)


def _build_red(
    capacity: int, params: dict[str, Any], service_time: float, seed: int, **_: Any
) -> QueueManager:
    r = resolve_params("red", capacity, params)
    return RED(
        capacity,
        derive_rng(seed, "red"),
        service_time,
        min_th=r["min_th"],
        max_th=r["max_th"],
        max_p=r["max_p"],
        weight=r["weight"],
        gentle=bool(r["gentle"]),
    )


def _build_codel(capacity: int, params: dict[str, Any], mtu_bytes: int, **_: Any) -> QueueManager:
    r = resolve_params("codel", capacity, params)
    return CoDel(
        capacity,
        target_s=r["target_ms"] / 1000.0,
        interval_s=r["interval_ms"] / 1000.0,
        mtu_bytes=mtu_bytes,
    )


ALGORITHMS: dict[str, AlgorithmSpec] = {
    "drop-tail": AlgorithmSpec(
        "drop-tail",
        "Drop-Tail",
        "Finite FIFO; arrivals are dropped when the buffer is full. The baseline.",
        (),
        _build_drop_tail,
    ),
    "red": AlgorithmSpec(
        "red",
        "RED",
        "Random Early Detection: probabilistic early drops driven by an EWMA of queue length.",
        (
            ParamSpec(
                "min_th",
                "Min threshold",
                "float",
                None,
                "Average queue (packets) below which nothing is dropped early.",
                "pkts",
                "auto = 25% of capacity",
            ),
            ParamSpec(
                "max_th",
                "Max threshold",
                "float",
                None,
                "Average queue (packets) at/above which every arrival is dropped early.",
                "pkts",
                "auto = 75% of capacity",
            ),
            ParamSpec(
                "max_p",
                "Max drop prob.",
                "float",
                0.1,
                "Early-drop probability reached as the average queue hits max_th.",
                "",
            ),
            ParamSpec(
                "weight",
                "EWMA weight",
                "float",
                0.01,
                "Weight w of the queue-length moving average. Smaller = slower, smoother.",
                "",
            ),
            ParamSpec(
                "gentle",
                "Gentle RED",
                "bool",
                False,
                "Ramp drop probability from max_p to 1 between max_th and 2*max_th.",
                "",
            ),
        ),
        _build_red,
    ),
    "codel": AlgorithmSpec(
        "codel",
        "CoDel",
        "Controlled Delay: drops at the head when sojourn time stays above target for an interval.",
        (
            ParamSpec(
                "target_ms", "Target", "float", 5.0, "Acceptable standing queueing delay.", "ms"
            ),
            ParamSpec(
                "interval_ms",
                "Interval",
                "float",
                100.0,
                "Window over which delay must stay above target before dropping starts "
                "(should be about the worst-case RTT).",
                "ms",
            ),
        ),
        _build_codel,
    ),
}


def algorithm_keys() -> list[str]:
    return list(ALGORITHMS)


def get_algorithm(key: str) -> AlgorithmSpec:
    try:
        return ALGORITHMS[key]
    except KeyError:
        raise ValueError(f"unknown algorithm {key!r}; available: {', '.join(ALGORITHMS)}") from None


def resolve_params(key: str, capacity: int, params: dict[str, Any] | None) -> dict[str, Any]:
    """Fill defaults (including capacity-derived RED thresholds). Unknown keys raise."""
    spec = get_algorithm(key)
    params = dict(params or {})
    known = {p.name for p in spec.params}
    unknown = set(params) - known
    if unknown:
        raise ValueError(f"unknown parameter(s) for {key}: {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for p in spec.params:
        value = params.get(p.name)
        if value is None:
            value = p.default
        out[p.name] = value
    if key == "red":
        if out["min_th"] is None:
            out["min_th"] = 0.25 * capacity
        if out["max_th"] is None:
            out["max_th"] = 0.75 * capacity
    return out


def validate_params(
    key: str, capacity: int, params: dict[str, Any] | None
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for algorithm parameters."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        r = resolve_params(key, capacity, params)
    except ValueError as exc:
        return [str(exc)], []
    try:
        if key == "red":
            if r["min_th"] < 0:
                errors.append("RED min_th must be >= 0")
            if r["min_th"] >= r["max_th"]:
                errors.append(
                    f"RED requires min_th < max_th (got {r['min_th']:g} >= {r['max_th']:g})"
                )
            if not 0 < r["max_p"] <= 1:
                errors.append("RED max_p must be in (0, 1]")
            if not 0 < r["weight"] <= 1:
                errors.append("RED weight must be in (0, 1]")
            if r["max_th"] > capacity:
                warnings.append(
                    f"RED max_th ({r['max_th']:g}) exceeds queue capacity ({capacity}); "
                    "the average can never reach it, so early drops will be rare and "
                    "overflow drops will dominate"
                )
            if r["weight"] > 0.2:
                warnings.append("RED weight > 0.2 makes the average track the instantaneous queue")
        elif key == "codel":
            if r["target_ms"] <= 0:
                errors.append("CoDel target must be > 0 ms")
            if r["interval_ms"] <= 0:
                errors.append("CoDel interval must be > 0 ms")
            if not errors and r["target_ms"] >= r["interval_ms"]:
                warnings.append("CoDel target is normally much smaller than interval")
    except (TypeError, ValueError) as exc:
        errors.append(f"invalid {key} parameter: {exc}")
    return errors, warnings


def build_queue_manager(
    key: str,
    capacity: int,
    params: dict[str, Any] | None,
    *,
    service_time: float,
    mtu_bytes: int,
    seed: int,
) -> QueueManager:
    spec = get_algorithm(key)
    return spec.build(
        capacity=capacity,
        params=params or {},
        service_time=service_time,
        mtu_bytes=mtu_bytes,
        seed=seed,
    )
