"""Turn a :class:`Measurement` into simulator parameters, with every derivation stated."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from bufferlab.experiments.models import ExperimentConfig
from bufferlab.netprobe.probe import Measurement

PACKET_BYTES = 1500
MIN_BUFFER_PKTS = 8
MAX_BUFFER_PKTS = 5000
BLOAT_NEGLIGIBLE_MS = 3.0


@dataclass(frozen=True)
class NetworkProfile:
    """What the simulator will assume about this network (all values come from the measurement)."""

    taken_at: str
    ping_target: str
    capacity_mbps: float  # measured download throughput = bottleneck capacity assumption
    idle_rtt_ms: float  # median RTT with no load
    loaded_rtt_ms: float | None  # median RTT while the link was saturated
    idle_loss: float | None  # measured ICMP loss, idle
    loaded_loss: float | None  # measured ICMP loss while saturated
    buffer_delay_ms: float  # loaded - idle RTT (>= 0): the standing queue the link built up
    buffer_pkts: int  # derived buffer size in 1500 B packets
    buffer_note: str

    @classmethod
    def from_measurement(cls, m: Measurement) -> NetworkProfile:
        idle = m.idle.median_ms or 0.0
        loaded = m.loaded.median_ms
        delay = max(0.0, (loaded - idle)) if loaded is not None else 0.0
        raw = delay / 1000 * m.download_mbps * 1e6 / (PACKET_BYTES * 8)
        pkts = int(round(min(max(raw, MIN_BUFFER_PKTS), MAX_BUFFER_PKTS)))
        if loaded is None:
            note = "no replies under load; buffer size assumed (minimum)"
        elif delay < BLOAT_NEGLIGIBLE_MS:
            note = f"latency rose only {delay:.1f} ms under load: little queueing, buffer assumed small ({pkts} pkts)"
        else:
            note = f"latency rose {delay:.0f} ms under load => about {pkts} packets of buffering"
        return cls(
            m.taken_at,
            m.ping_target,
            m.download_mbps,
            idle,
            loaded,
            m.idle.loss,
            m.loaded.loss,
            delay,
            pkts,
            note,
        )

    @classmethod
    def manual(
        cls, capacity_mbps: float, rtt_ms: float = 20.0, buffer_ms: float = 20.0
    ) -> NetworkProfile:
        pkts = int(
            round(
                min(
                    max(
                        buffer_ms / 1000 * capacity_mbps * 1e6 / (PACKET_BYTES * 8), MIN_BUFFER_PKTS
                    ),
                    MAX_BUFFER_PKTS,
                )
            )
        )
        return cls(
            "manual",
            "manual",
            capacity_mbps,
            rtt_ms,
            rtt_ms + buffer_ms,
            None,
            None,
            buffer_ms,
            pkts,
            "entered by hand, not measured",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkProfile:
        return cls(**d)

    def base_config(self, **overrides: Any) -> ExperimentConfig:
        """Simulator configuration for this network; the load is set per what-if situation."""
        cfg = ExperimentConfig(
            name="my-network",
            scenario="my-network",
            algorithm="drop-tail",
            link_mbps=self.capacity_mbps,
            packet_size_bytes=PACKET_BYTES,
            queue_capacity=self.buffer_pkts,
            traffic_model="poisson",
            n_sources=4,
            prop_delay_ms=self.idle_rtt_ms / 2.0,
        )
        return cfg.replace(**overrides) if overrides else cfg
