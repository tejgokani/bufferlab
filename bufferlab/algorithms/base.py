"""Queue-management interface.

A :class:`QueueManager` owns the buffer (packets *waiting* for the link; the
packet currently being transmitted is not part of it) and decides which packets
are admitted (``enqueue``) and, for sojourn-time based schemes such as CoDel,
which are discarded at the head (``dequeue``).

Implementations must be pure functions of their inputs and the injected RNG:
no wall-clock time, no global state.  That keeps them independently testable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import StrEnum

from bufferlab.core.packets import Packet


class DropReason(StrEnum):
    OVERFLOW = "overflow"  # buffer full (forced drop)
    EARLY = "early"  # probabilistic/early drop on arrival (RED)
    AQM = "aqm"  # head drop decided at dequeue time (CoDel)


@dataclass(slots=True)
class DequeueResult:
    packet: Packet | None
    dropped: list[tuple[Packet, DropReason]] = field(default_factory=list)


class QueueManager(ABC):
    name = "base"

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("queue capacity must be at least 1 packet")
        self.capacity = capacity
        self._q: deque[Packet] = deque()
        self._bytes = 0
        self.admitted = 0
        self.drops: Counter[DropReason] = Counter()

    def __len__(self) -> int:
        return len(self._q)

    @property
    def backlog_bytes(self) -> int:
        return self._bytes

    # -- public API (bookkeeping wrapper around the hooks) -----------------
    def enqueue(self, pkt: Packet, now: float) -> DropReason | None:
        """Offer an arriving packet.  Returns ``None`` if admitted, else the drop reason."""
        reason = self._enqueue(pkt, now)
        if reason is None:
            pkt.enqueue_time = now
            self._q.append(pkt)
            self._bytes += pkt.size_bytes
            self.admitted += 1
        else:
            self.drops[reason] += 1
        return reason

    def dequeue(self, now: float) -> DequeueResult:
        """Select the next packet to transmit, possibly discarding others first."""
        result = self._dequeue(now)
        for _pkt, reason in result.dropped:
            self.drops[reason] += 1
        return result

    # -- hooks -------------------------------------------------------------
    @abstractmethod
    def _enqueue(self, pkt: Packet, now: float) -> DropReason | None:
        """Admission decision.  Must not mutate the buffer."""

    def _pop(self) -> Packet | None:
        if not self._q:
            return None
        pkt = self._q.popleft()
        self._bytes -= pkt.size_bytes
        return pkt

    def _dequeue(self, now: float) -> DequeueResult:
        return DequeueResult(self._pop())

    def describe(self) -> dict[str, object]:
        """Resolved parameters, recorded in results for reproducibility."""
        return {"capacity": self.capacity}
