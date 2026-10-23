"""Experiment configuration, validation and run records."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import UTC, datetime
from typing import Any

from bufferlab import SCHEMA_VERSION, __version__
from bufferlab.algorithms import algorithm_keys, resolve_params, validate_params
from bufferlab.core.links import rate_for_load_pct
from bufferlab.core.simulator import SimConfig
from bufferlab.core.traffic import TRAFFIC_MODELS
from bufferlab.utils.validation import ValidationReport


class ConfigError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__("; ".join(str(i) for i in report.errors))


@dataclass(frozen=True)
class ExperimentConfig:
    name: str = "experiment"
    algorithm: str = "drop-tail"
    algorithm_params: dict[str, Any] = field(default_factory=dict)
    link_mbps: float = 10.0
    packet_size_bytes: int = 1500
    queue_capacity: int = 50
    traffic_model: str = "poisson"
    offered_load_pct: float = 90.0  # % of link capacity (nominal)
    n_sources: int = 1
    duration_s: float = 30.0
    warmup_s: float = 5.0
    seed: int = 42
    prop_delay_ms: float = 0.0
    burst_on_ms: float = 200.0
    burst_off_ms: float = 800.0
    max_events: int = 5_000_000
    scenario: str | None = None

    # -- derived -------------------------------------------------------------
    @property
    def arrival_rate_pps(self) -> float:
        return rate_for_load_pct(
            self.offered_load_pct, self.link_mbps * 1e6, self.packet_size_bytes
        )

    @property
    def service_time_ms(self) -> float:
        return self.packet_size_bytes * 8 / (self.link_mbps * 1e6) * 1e3

    def resolved_params(self) -> dict[str, Any]:
        return resolve_params(self.algorithm, self.queue_capacity, self.algorithm_params)

    def to_sim_config(self) -> SimConfig:
        return SimConfig(
            link_mbps=self.link_mbps,
            packet_size_bytes=self.packet_size_bytes,
            arrival_rate_pps=self.arrival_rate_pps,
            duration_s=self.duration_s,
            warmup_s=self.warmup_s,
            queue_capacity=self.queue_capacity,
            n_sources=self.n_sources,
            traffic_model=self.traffic_model,
            seed=self.seed,
            prop_delay_s=self.prop_delay_ms / 1000.0,
            burst_on_s=self.burst_on_ms / 1000.0,
            burst_off_s=self.burst_off_ms / 1000.0,
            max_events=self.max_events,
        )

    def replace(self, **changes: Any) -> ExperimentConfig:
        return replace(self, **changes)

    # -- serialisation ---------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentConfig:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def fingerprint(self) -> str:
        """Hash of everything that affects simulation output (excludes the display name)."""
        d = self.to_dict()
        d.pop("name", None)
        d.pop("scenario", None)
        return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]

    # -- validation ------------------------------------------------------------
    def validate(self) -> ValidationReport:
        r = ValidationReport()
        if self.algorithm not in algorithm_keys():
            r.error("algorithm", f"unknown algorithm {self.algorithm!r}")
        if self.traffic_model not in TRAFFIC_MODELS:
            r.error("traffic_model", f"must be one of {', '.join(TRAFFIC_MODELS)}")
        if not self.link_mbps > 0:
            r.error("link_mbps", "bandwidth must be greater than zero")
        if self.packet_size_bytes < 1:
            r.error("packet_size_bytes", "packet size must be at least 1 byte")
        elif self.packet_size_bytes > 65535:
            r.error("packet_size_bytes", "packet size cannot exceed 65535 bytes")
        if self.queue_capacity < 1:
            r.error("queue_capacity", "queue capacity must be at least 1 packet")
        if self.offered_load_pct < 0:
            r.error("offered_load_pct", "offered load cannot be negative")
        if self.n_sources < 1:
            r.error("n_sources", "need at least one traffic source")
        if not self.duration_s > 0:
            r.error("duration_s", "duration must be greater than zero")
        if self.warmup_s < 0:
            r.error("warmup_s", "warm-up cannot be negative")
        elif self.duration_s > 0 and self.warmup_s >= self.duration_s:
            r.error(
                "warmup_s",
                f"warm-up ({self.warmup_s:g}s) must be shorter than the duration "
                f"({self.duration_s:g}s); nothing would be measured",
            )
        if self.seed < 0:
            r.error("seed", "seed must be a non-negative integer")
        if self.prop_delay_ms < 0:
            r.error("prop_delay_ms", "propagation delay cannot be negative")
        if self.traffic_model == "bursty" and (self.burst_on_ms <= 0 or self.burst_off_ms <= 0):
            r.error("burst", "burst ON and OFF mean durations must be positive")
        if self.max_events < 1000:
            r.error("max_events", "event limit must be at least 1000")
        if self.algorithm in algorithm_keys() and self.queue_capacity >= 1:
            errs, warns = validate_params(
                self.algorithm, self.queue_capacity, self.algorithm_params
            )
            for e in errs:
                r.error("algorithm_params", e)
            for w in warns:
                r.warn("algorithm_params", w)
        if r.ok:
            self._add_warnings(r)
        return r

    def _add_warnings(self, r: ValidationReport) -> None:
        pps = self.arrival_rate_pps
        window = self.duration_s - self.warmup_s
        expected = pps * window
        if self.offered_load_pct == 0:
            r.warn("offered_load_pct", "zero offered load: no packets will be generated")
        elif expected < 1000:
            r.warn(
                "duration_s",
                f"only ~{expected:.0f} packets expected in the measurement window; "
                "percentile and loss estimates will be noisy",
            )
        if self.duration_s > 0 and self.warmup_s < 0.1 * self.duration_s:
            r.warn(
                "warmup_s", "warm-up is under 10% of the run; start-up transients may bias results"
            )
        if self.queue_capacity == 1:
            r.warn("queue_capacity", "a 1-packet buffer drops almost every burst")
        if 2 * pps * self.duration_s > self.max_events:
            r.warn(
                "max_events",
                f"estimated {2 * pps * self.duration_s:,.0f} events exceeds the limit "
                f"({self.max_events:,}); the run will stop early",
            )
        if self.n_sources > 1 and self.traffic_model == "constant":
            r.warn(
                "n_sources",
                "multiple constant-rate sources have random phases but identical periods",
            )
        if self.offered_load_pct > 100:
            r.warn(
                "offered_load_pct",
                "offered load exceeds link capacity: sustained loss/queue growth is expected",
            )

    def summary_lines(self) -> list[str]:
        lines = [
            f"Algorithm      {self.algorithm}  {self._params_text()}",
            f"Link           {self.link_mbps:g} Mbps, {self.packet_size_bytes} B packets "
            f"(service {self.service_time_ms:.3f} ms)",
            f"Buffer         {self.queue_capacity} packets",
            f"Traffic        {self.traffic_model}, {self.n_sources} source(s), "
            f"{self.offered_load_pct:g}% of capacity = {self.arrival_rate_pps:,.1f} pkt/s "
            f"({self.arrival_rate_pps * self.packet_size_bytes * 8 / 1e6:.3f} Mbps)",
            f"Duration       {self.duration_s:g}s run, {self.warmup_s:g}s warm-up, seed {self.seed}",
        ]
        if self.prop_delay_ms:
            lines.append(f"Propagation    {self.prop_delay_ms:g} ms one-way")
        return lines

    def _params_text(self) -> str:
        try:
            p = self.resolved_params()
        except ValueError:
            return ""
        return " ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}" for k, v in p.items())


def new_run_id() -> str:
    return "r" + uuid.uuid4().hex[:9]


@dataclass
class RunRecord:
    run_id: str
    created_at: str
    config: ExperimentConfig
    resolved_params: dict[str, Any]
    metrics: dict[str, Any]
    series: dict[str, Any]
    terminated: str = "completed"
    events_processed: int = 0
    wall_time_s: float = 0.0
    software_version: str = __version__
    schema_version: int = SCHEMA_VERSION
    batch_id: str | None = None
    replicate: int = 0

    @property
    def label(self) -> str:
        return f"{self.run_id} {self.config.algorithm} ({self.config.name})"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
