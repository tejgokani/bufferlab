"""Built-in scenarios.

A scenario is an experiment *configuration*, not a set of expected results.
Running one with a given algorithm always executes the simulator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bufferlab.experiments.models import ExperimentConfig


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    config: ExperimentConfig


def _s(key: str, title: str, description: str, **kw: Any) -> Scenario:
    return Scenario(key, title, description, ExperimentConfig(name=key, scenario=key, **kw))


SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        _s(
            "light-traffic",
            "Light Traffic",
            "Offered load 30% of a 10 Mbps link; the buffer should rarely matter.",
            offered_load_pct=30.0,
        ),
        _s(
            "approaching-saturation",
            "Approaching Saturation",
            "Offered load 90%: random bursts regularly build short queues.",
            offered_load_pct=90.0,
        ),
        _s(
            "heavy-congestion",
            "Heavy Congestion",
            "Offered load 130% of capacity: sustained overload, buffer stays near full.",
            offered_load_pct=130.0,
        ),
        _s(
            "bursty-traffic",
            "Bursty Traffic",
            "Four on/off sources (200 ms ON / 800 ms OFF means), average load 80%.",
            traffic_model="bursty",
            n_sources=4,
            offered_load_pct=80.0,
            duration_s=60.0,
        ),
        _s(
            "small-buffer",
            "Small Buffer",
            "Load 95% with only 8 packets of buffering.",
            offered_load_pct=95.0,
            queue_capacity=8,
        ),
        _s(
            "large-buffer",
            "Large Buffer",
            "Load 110% with a 500-packet buffer: tests standing-queue delay (bufferbloat).",
            offered_load_pct=110.0,
            queue_capacity=500,
        ),
        _s(
            "low-bandwidth",
            "Low-Bandwidth Link",
            "1 Mbps link at 100% offered load, 60 s run.",
            link_mbps=1.0,
            offered_load_pct=100.0,
            duration_s=60.0,
            warmup_s=10.0,
        ),
        _s(
            "high-bandwidth",
            "High-Bandwidth Link",
            "1 Gbps link at 95% load, 200-packet buffer, short 5 s run (~400k packets).",
            link_mbps=1000.0,
            offered_load_pct=95.0,
            queue_capacity=200,
            duration_s=5.0,
            warmup_s=1.0,
        ),
    )
}


def scenario_keys() -> list[str]:
    return list(SCENARIOS)


def get_scenario(key: str) -> Scenario:
    norm = key.strip().lower().replace("_", "-").replace(" ", "-")
    try:
        return SCENARIOS[norm]
    except KeyError:
        raise ValueError(f"unknown scenario {key!r}; available: {', '.join(SCENARIOS)}") from None


def scenario_config(key: str, algorithm: str = "drop-tail", **overrides: Any) -> ExperimentConfig:
    sc = get_scenario(key)
    name = overrides.pop("name", f"{sc.key}/{algorithm}")
    return sc.config.replace(algorithm=algorithm, name=name, **overrides)
