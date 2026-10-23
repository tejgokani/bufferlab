"""Deterministic priority-queue event scheduler."""

from __future__ import annotations

import heapq
from typing import Any

from bufferlab.core.events import EventKind


class Scheduler:
    """Min-heap of ``(time, kind, seq, payload)``.

    ``seq`` is a monotonically increasing counter, so the payload is never
    compared and equal-time/equal-kind events pop in insertion order.
    """

    __slots__ = ("_heap", "_seq", "now")

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, int, Any]] = []
        self._seq = 0
        self.now = 0.0

    def schedule(self, time: float, kind: EventKind, payload: Any = None) -> None:
        if time < self.now:
            raise ValueError(f"cannot schedule event in the past ({time} < {self.now})")
        heapq.heappush(self._heap, (time, int(kind), self._seq, payload))
        self._seq += 1

    def pop(self) -> tuple[float, EventKind, Any] | None:
        """Remove and return the next event, advancing ``now``; ``None`` if empty."""
        if not self._heap:
            return None
        time, kind, _seq, payload = heapq.heappop(self._heap)
        self.now = time
        return time, EventKind(kind), payload

    def peek_time(self) -> float | None:
        return self._heap[0][0] if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)
