"""Controlled Delay (CoDel), following the pseudo-code of RFC 8289 section 5.

State: ``first_above_time``, ``drop_next``, ``count``, ``lastcount``, ``dropping``.

* Each packet's *sojourn time* is ``now - enqueue_time`` measured at dequeue.
* The queue is "persistently bad" once sojourn has stayed >= ``target`` for a
  full ``interval`` (``first_above_time`` armed at ``now + interval`` and
  reached) while more than one MTU is still backlogged.
* Entering the dropping state drops the head packet and schedules the next drop
  at ``now + interval / sqrt(count)`` (the control law); while dropping, further
  head drops follow ``drop_next = drop_next + interval / sqrt(count)``.
* Leaving the dropping state happens when sojourn falls below ``target`` (or the
  queue drains).  Re-entering shortly afterwards resumes near the previous
  ``count`` (``count = count - lastcount``) per the RFC's hysteresis rule.

Simplifications: drops (no ECN), a hard buffer limit tail-drops arrivals
(counted as overflow, not as CoDel decisions), the MTU used for the
"backlog <= MTU" test is the configured packet size, and there is no
square-root lookup table (``math.sqrt`` is used).  Not validated against the
Linux ``sch_codel`` implementation.
"""

from __future__ import annotations

import math

from bufferlab.algorithms.base import DequeueResult, DropReason, QueueManager
from bufferlab.core.packets import Packet


class CoDel(QueueManager):
    name = "codel"

    def __init__(
        self,
        capacity: int,
        target_s: float = 0.005,
        interval_s: float = 0.100,
        mtu_bytes: int = 1500,
    ) -> None:
        super().__init__(capacity)
        if target_s <= 0 or interval_s <= 0:
            raise ValueError("CoDel target and interval must be positive")
        self.target = target_s
        self.interval = interval_s
        self.mtu = mtu_bytes
        self.first_above_time: float | None = None
        self.drop_next = 0.0
        self.count = 0
        self.lastcount = 0
        self.dropping = False

    def _enqueue(self, pkt: Packet, now: float) -> DropReason | None:
        if len(self._q) >= self.capacity:
            return DropReason.OVERFLOW
        return None

    def control_law(self, t: float) -> float:
        return t + self.interval / math.sqrt(self.count)

    def _do_dequeue(self, now: float) -> tuple[Packet | None, bool]:
        """RFC 8289 ``dodequeue``: pop the head and report whether it is droppable."""
        pkt = self._pop()
        if pkt is None:
            self.first_above_time = None
            return None, False
        sojourn = now - pkt.enqueue_time
        if sojourn < self.target or self._bytes <= self.mtu:
            self.first_above_time = None
            return pkt, False
        if self.first_above_time is None:
            self.first_above_time = now + self.interval
            return pkt, False
        return pkt, now >= self.first_above_time

    def _dequeue(self, now: float) -> DequeueResult:
        dropped: list[tuple[Packet, DropReason]] = []
        pkt, ok_to_drop = self._do_dequeue(now)
        if pkt is None:
            self.dropping = False
            return DequeueResult(None, dropped)
        if self.dropping:
            if not ok_to_drop:
                self.dropping = False
            else:
                while now >= self.drop_next and self.dropping:
                    dropped.append((pkt, DropReason.AQM))
                    self.count += 1
                    pkt, ok_to_drop = self._do_dequeue(now)
                    if pkt is None or not ok_to_drop:
                        self.dropping = False
                    else:
                        self.drop_next = self.control_law(self.drop_next)
        elif ok_to_drop:
            dropped.append((pkt, DropReason.AQM))
            pkt, ok_to_drop = self._do_dequeue(now)
            self.dropping = True
            delta = self.count - self.lastcount
            if delta > 1 and now - self.drop_next < 16 * self.interval:
                self.count = delta
            else:
                self.count = 1
            self.drop_next = self.control_law(now)
            self.lastcount = self.count
        return DequeueResult(pkt, dropped)

    def describe(self) -> dict[str, object]:
        return {
            "capacity": self.capacity,
            "target_ms": self.target * 1000,
            "interval_ms": self.interval * 1000,
            "mtu_bytes": self.mtu,
        }
