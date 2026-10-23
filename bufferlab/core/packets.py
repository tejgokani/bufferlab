"""Packet record."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Packet:
    """A packet in flight.  Times are simulated seconds; ``-1.0`` means unset."""

    pid: int
    source: int
    size_bytes: int
    arrival_time: float
    enqueue_time: float = -1.0
    service_start: float = -1.0
    departure_time: float = -1.0

    def __post_init__(self) -> None:
        if self.size_bytes <= 0:
            raise ValueError("packet size must be positive")

    @property
    def size_bits(self) -> int:
        return self.size_bytes * 8

    @property
    def queueing_delay(self) -> float:
        """Time spent waiting in the buffer (enqueue -> start of transmission)."""
        if self.enqueue_time < 0 or self.service_start < 0:
            raise ValueError("packet has not been served yet")
        return self.service_start - self.enqueue_time
