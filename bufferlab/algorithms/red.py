"""Random Early Detection (Floyd & Jacobson, 1993), packet-mode, drop (no ECN).

Equations (``q`` = packets waiting, excluding the one in service):

* average:        avg <- (1 - w) * avg + w * q                (queue non-empty)
* idle decay:     avg <- (1 - w) ** m * avg,  m = (now - t_idle) / s
                  where ``s`` is the transmission time of one packet
* min <= avg < max:  count += 1;  pb = max_p * (avg - min) / (max - min)
                     pa = pb / (1 - count * pb)  (pa = 1 if count * pb >= 1)
                     drop arrival with probability pa, then count = 0
* avg >= max:     drop the arrival, count = 0
* avg < min:      admit, count = -1
* full buffer:    forced overflow drop regardless of ``avg``

With ``gentle=True`` the drop probability rises linearly from ``max_p`` to 1
between ``max`` and ``2 * max`` (the "gentle RED" variant) instead of jumping to 1.

Simplifications / deviations: the idle period is "waiting queue empty" rather
than "link idle"; no ECN marking; no adaptive max_p.  This is not validated
against any operating-system RED implementation.
"""

from __future__ import annotations

import random

from bufferlab.algorithms.base import DequeueResult, DropReason, QueueManager
from bufferlab.core.packets import Packet


class RED(QueueManager):
    name = "red"

    def __init__(
        self,
        capacity: int,
        rng: random.Random,
        service_time: float,
        min_th: float,
        max_th: float,
        max_p: float = 0.1,
        weight: float = 0.01,
        gentle: bool = False,
    ) -> None:
        super().__init__(capacity)
        if not 0 <= min_th < max_th:
            raise ValueError("RED requires 0 <= min_th < max_th")
        if not 0 < max_p <= 1:
            raise ValueError("RED max_p must be in (0, 1]")
        if not 0 < weight <= 1:
            raise ValueError("RED weight must be in (0, 1]")
        if service_time <= 0:
            raise ValueError("service_time must be positive")
        self.rng = rng
        self.s = service_time
        self.min_th = min_th
        self.max_th = max_th
        self.max_p = max_p
        self.w = weight
        self.gentle = gentle
        self.avg = 0.0
        self.count = -1
        self.idle_since: float | None = 0.0

    # -- helpers -------------------------------------------------------------
    def update_average(self, now: float) -> float:
        if self._q:
            self.avg = (1.0 - self.w) * self.avg + self.w * len(self._q)
        else:
            idle = now - (self.idle_since if self.idle_since is not None else now)
            m = max(idle, 0.0) / self.s
            self.avg *= (1.0 - self.w) ** m
        return self.avg

    def base_probability(self, avg: float) -> float | None:
        """pb for the current average, or ``None`` when below ``min_th``."""
        if avg < self.min_th:
            return None
        if avg < self.max_th:
            return self.max_p * (avg - self.min_th) / (self.max_th - self.min_th)
        if self.gentle and avg < 2 * self.max_th:
            return self.max_p + (1 - self.max_p) * (avg - self.max_th) / self.max_th
        return 1.0

    # -- QueueManager hooks --------------------------------------------------
    def _enqueue(self, pkt: Packet, now: float) -> DropReason | None:
        avg = self.update_average(now)
        pb = self.base_probability(avg)
        early = False
        if pb is None:
            self.count = -1
        elif pb >= 1.0:
            early = True
            self.count = 0
        else:
            self.count += 1
            denom = 1.0 - self.count * pb
            pa = 1.0 if denom <= 0 else pb / denom
            if self.rng.random() < pa:
                early = True
                self.count = 0
        if early:
            return DropReason.EARLY
        if len(self._q) >= self.capacity:
            self.count = 0
            return DropReason.OVERFLOW
        return None

    def _dequeue(self, now: float) -> DequeueResult:
        pkt = self._pop()
        if pkt is not None and not self._q:
            self.idle_since = now
        return DequeueResult(pkt)

    def describe(self) -> dict[str, object]:
        return {
            "capacity": self.capacity,
            "min_th": self.min_th,
            "max_th": self.max_th,
            "max_p": self.max_p,
            "weight": self.w,
            "gentle": self.gentle,
        }
