"""Bottleneck link model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Link:
    capacity_bps: float
    prop_delay_s: float = 0.0

    def __post_init__(self) -> None:
        if self.capacity_bps <= 0:
            raise ValueError("link capacity must be positive")
        if self.prop_delay_s < 0:
            raise ValueError("propagation delay cannot be negative")

    def service_time(self, size_bytes: int) -> float:
        """Seconds to serialise a packet: ``size_bits / capacity_bps``."""
        return size_bytes * 8 / self.capacity_bps


def offered_load_bps(arrival_rate_pps: float, size_bytes: int) -> float:
    """Offered load (bps) = arrival rate x packet size in bytes x 8."""
    return arrival_rate_pps * size_bytes * 8


def rate_for_load_pct(load_pct: float, capacity_bps: float, size_bytes: int) -> float:
    """Packet arrival rate (pps) that offers ``load_pct`` % of link capacity."""
    return load_pct / 100.0 * capacity_bps / (size_bytes * 8)
