"""Drop-Tail: finite FIFO that discards arrivals when full."""

from __future__ import annotations

from bufferlab.algorithms.base import DropReason, QueueManager
from bufferlab.core.packets import Packet


class DropTail(QueueManager):
    name = "drop-tail"

    def _enqueue(self, pkt: Packet, now: float) -> DropReason | None:
        if len(self._q) >= self.capacity:
            return DropReason.OVERFLOW
        return None
