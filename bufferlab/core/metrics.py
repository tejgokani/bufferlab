"""Metric accounting.  See ``docs/metrics.md`` for the precise definitions.

Two windows are used, both starting at the warm-up boundary ``w0``:

* **Packet cohort** (generated / admitted / delivered / dropped / delays):
  a packet belongs to the measured cohort iff its *arrival time* is >= ``w0``.
  Every cohort packet ends the run in exactly one state: delivered, dropped, or
  *unresolved* (still queued or in service at the end).
  ``generated = delivered + dropped + unresolved``.
* **Time window** (throughput, utilisation, queue occupancy): integrals over
  ``[w0, end]`` of what the link and buffer actually did.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import asdict, dataclass, fields
from typing import Any

from bufferlab.algorithms.base import DropReason

LIVE_SAMPLE_TAIL = 20_000


def percentile(sorted_values: list[float] | array, q: float) -> float:
    """Linear-interpolation percentile (``q`` in [0, 100]) of a *sorted* sequence."""
    n = len(sorted_values)
    if n == 0:
        raise ValueError("percentile of empty data")
    if n == 1:
        return float(sorted_values[0])
    pos = (n - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    frac = pos - lo
    return float(sorted_values[lo]) * (1 - frac) + float(sorted_values[hi]) * frac


@dataclass
class Metrics:
    # configuration echo
    offered_load_mbps: float = 0.0  # nominal: rate x size x 8
    offered_load_pct: float = 0.0  # nominal, % of link capacity
    measured_window_s: float = 0.0
    # packet counts (cohort)
    generated: int = 0
    admitted: int = 0
    delivered: int = 0
    dropped: int = 0
    dropped_overflow: int = 0
    dropped_early: int = 0
    dropped_aqm: int = 0
    unresolved: int = 0
    # ratios (None when the denominator is zero)
    delivery_ratio: float | None = None
    loss_rate: float | None = None
    # rates (time window)
    measured_offered_mbps: float = 0.0
    throughput_mbps: float = 0.0
    link_utilisation: float = 0.0
    # queueing delay of delivered cohort packets, milliseconds
    avg_queue_delay_ms: float | None = None
    median_queue_delay_ms: float | None = None
    p95_queue_delay_ms: float | None = None
    max_queue_delay_ms: float | None = None
    avg_total_delay_ms: float | None = None  # queueing + service + propagation (one way)
    # queue occupancy (time window), packets waiting
    max_queue_len: int = 0
    avg_queue_len: float = 0.0
    queue_utilisation: float = 0.0
    overflow_events: int = 0
    # bookkeeping
    arrivals_total: int = 0  # including warm-up
    events_processed: int = 0
    approximate: bool = False  # True for live (in-progress) snapshots

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Metrics:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


class MetricsCollector:
    def __init__(
        self,
        *,
        duration: float,
        warmup: float,
        packet_size_bytes: int,
        capacity_bps: float,
        queue_capacity: int,
        nominal_offered_bps: float,
        prop_delay_s: float,
        service_time: float,
        bins: int = 200,
    ) -> None:
        self.duration = duration
        self.w0 = warmup
        self.packet_bits = packet_size_bytes * 8
        self.capacity_bps = capacity_bps
        self.queue_capacity = queue_capacity
        self.nominal_offered_bps = nominal_offered_bps
        self.prop_delay_s = prop_delay_s
        self.service_time = service_time
        self.nbins = max(1, bins)
        self.bw = duration / self.nbins
        self.last_t = 0.0
        self.events = 0
        # time-window integrals
        self.area_q = 0.0
        self.busy_time = 0.0
        self.max_q = 0
        self.departed_bits_w = 0
        # cohort counters
        self.arrivals_total = 0
        self.generated = 0
        self.admitted_n = 0
        self.delivered = 0
        self.drops = {r: 0 for r in DropReason}
        self.delays = array("d")
        self.delay_sum = 0.0
        # bins (whole timeline, including warm-up)
        n = self.nbins
        self.b_bits = [0] * n
        self.b_delay_sum = [0.0] * n
        self.b_delay_n = [0] * n
        self.b_drops = [0] * n
        self.b_arrivals = [0] * n
        self.b_qarea = [0.0] * n
        self.b_busy = [0.0] * n

    # -- helpers -------------------------------------------------------------
    def _bin(self, t: float) -> int:
        return min(max(int(t / self.bw), 0), self.nbins - 1)

    def _cohort(self, pkt_arrival: float) -> bool:
        return pkt_arrival >= self.w0

    # -- event hooks -----------------------------------------------------------
    def advance(self, now: float, qlen: int, busy: bool) -> None:
        """Integrate state that held constant over ``[last_t, now]``."""
        t0 = self.last_t
        if now <= t0:
            return
        lo = max(t0, self.w0)
        if now > lo:
            self.area_q += qlen * (now - lo)
            if busy:
                self.busy_time += now - lo
            if qlen > self.max_q:
                self.max_q = qlen
        t = t0
        while t < now:
            b = self._bin(t)
            edge = (b + 1) * self.bw if b < self.nbins - 1 else math.inf
            if edge <= t:
                b = min(b + 1, self.nbins - 1)
                edge = (b + 1) * self.bw if b < self.nbins - 1 else math.inf
            seg_end = min(now, edge)
            dt = seg_end - t
            self.b_qarea[b] += qlen * dt
            if busy:
                self.b_busy[b] += dt
            t = seg_end
        self.last_t = now

    def arrival(self, arrival_time: float) -> None:
        self.arrivals_total += 1
        self.b_arrivals[self._bin(arrival_time)] += 1
        if self._cohort(arrival_time):
            self.generated += 1

    def admit(self, arrival_time: float) -> None:
        if self._cohort(arrival_time):
            self.admitted_n += 1

    def drop(self, arrival_time: float, reason: DropReason, now: float) -> None:
        self.b_drops[self._bin(now)] += 1
        if self._cohort(arrival_time):
            self.drops[reason] += 1

    def depart(self, arrival_time: float, queue_delay: float, size_bits: int, now: float) -> None:
        b = self._bin(now)
        self.b_bits[b] += size_bits
        self.b_delay_sum[b] += queue_delay
        self.b_delay_n[b] += 1
        if now >= self.w0:
            self.departed_bits_w += size_bits
        if self._cohort(arrival_time):
            self.delivered += 1
            self.delays.append(queue_delay)
            self.delay_sum += queue_delay

    # -- results -----------------------------------------------------------------
    def compute(self, approximate: bool = False) -> Metrics:
        end = self.last_t
        window = end - self.w0
        dropped = sum(self.drops.values())
        m = Metrics(
            offered_load_mbps=self.nominal_offered_bps / 1e6,
            offered_load_pct=100.0 * self.nominal_offered_bps / self.capacity_bps,
            measured_window_s=max(window, 0.0),
            generated=self.generated,
            admitted=self.admitted_n,
            delivered=self.delivered,
            dropped=dropped,
            dropped_overflow=self.drops[DropReason.OVERFLOW],
            dropped_early=self.drops[DropReason.EARLY],
            dropped_aqm=self.drops[DropReason.AQM],
            unresolved=self.generated - self.delivered - dropped,
            overflow_events=self.drops[DropReason.OVERFLOW],
            arrivals_total=self.arrivals_total,
            events_processed=self.events,
            approximate=approximate,
        )
        if self.generated > 0:
            m.delivery_ratio = self.delivered / self.generated
            m.loss_rate = dropped / self.generated
        if window > 0:
            m.measured_offered_mbps = self.generated * self.packet_bits / window / 1e6
            m.throughput_mbps = self.departed_bits_w / window / 1e6
            m.link_utilisation = min(self.busy_time / window, 1.0)
            m.avg_queue_len = self.area_q / window
            m.queue_utilisation = m.avg_queue_len / self.queue_capacity
            m.max_queue_len = self.max_q
        if self.delivered > 0:
            data = self.delays[-LIVE_SAMPLE_TAIL:] if approximate else self.delays
            s = sorted(data)
            m.avg_queue_delay_ms = (
                (sum(data) / len(data)) * 1e3
                if approximate
                else self.delay_sum / self.delivered * 1e3
            )
            m.median_queue_delay_ms = percentile(s, 50) * 1e3
            m.p95_queue_delay_ms = percentile(s, 95) * 1e3
            m.max_queue_delay_ms = s[-1] * 1e3
            m.avg_total_delay_ms = (
                m.avg_queue_delay_ms + (self.service_time + self.prop_delay_s) * 1e3
            )
        return m

    def series(self) -> dict[str, Any]:
        """Per-bin time series up to the current simulated time."""
        end = self.last_t
        nb = self._bin(end) + 1 if end > 0 else 0
        t: list[float] = []
        thr: list[float] = []
        qlen: list[float] = []
        qdel: list[float | None] = []
        util: list[float] = []
        for b in range(nb):
            start = b * self.bw
            dt = min(end, start + self.bw) - start
            if dt <= 0:
                continue
            t.append(round(start + dt / 2, 9))
            thr.append(self.b_bits[b] / dt / 1e6)
            qlen.append(self.b_qarea[b] / dt)
            util.append(min(self.b_busy[b] / dt, 1.0))
            n = self.b_delay_n[b]
            qdel.append(self.b_delay_sum[b] / n * 1e3 if n else None)
        k = len(t)
        return {
            "bin_width_s": self.bw,
            "warmup_s": self.w0,
            "t": t,
            "throughput_mbps": thr,
            "queue_len": qlen,
            "queue_delay_ms": qdel,
            "link_utilisation": util,
            "drops": self.b_drops[:k],
            "arrivals": self.b_arrivals[:k],
        }
