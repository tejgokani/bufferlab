"""Single-bottleneck discrete-event simulator.

Sources -> arrivals -> QueueManager -> bottleneck link -> destination.

Only two event kinds exist: ARRIVAL (a source emits a packet) and DEPARTURE
(the packet in service finishes transmission).  Time is advanced by popping the
scheduler, never by sleeping, so runs execute much faster than real time.
Events with time > ``duration`` are never processed.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bufferlab.algorithms.base import QueueManager
from bufferlab.core.events import EventKind
from bufferlab.core.links import Link
from bufferlab.core.metrics import Metrics, MetricsCollector
from bufferlab.core.packets import Packet
from bufferlab.core.random_source import derive_rng
from bufferlab.core.scheduler import Scheduler
from bufferlab.core.traffic import make_source


@dataclass(frozen=True)
class SimConfig:
    link_mbps: float
    packet_size_bytes: int
    arrival_rate_pps: float  # total, across all sources
    duration_s: float
    warmup_s: float
    queue_capacity: int
    n_sources: int = 1
    traffic_model: str = "poisson"
    seed: int = 1
    prop_delay_s: float = 0.0
    burst_on_s: float = 0.2
    burst_off_s: float = 0.8
    max_events: int = 5_000_000
    series_bins: int = 200

    @property
    def capacity_bps(self) -> float:
        return self.link_mbps * 1e6

    @property
    def offered_bps(self) -> float:
        return self.arrival_rate_pps * self.packet_size_bytes * 8


@dataclass
class Progress:
    sim_time: float
    duration: float
    events: int
    arrivals: int
    departures: int
    drops: int
    queue_len: int
    metrics: Metrics
    series: dict[str, Any]

    @property
    def fraction(self) -> float:
        return min(self.sim_time / self.duration, 1.0) if self.duration > 0 else 1.0


@dataclass
class SimResult:
    metrics: Metrics
    series: dict[str, Any]
    terminated: str  # "completed" | "cancelled" | "event_limit"
    end_time: float
    events_processed: int
    wall_time_s: float
    queue_params: dict[str, Any] = field(default_factory=dict)


ProgressCallback = Callable[[Progress], None]


class Simulator:
    def __init__(
        self,
        cfg: SimConfig,
        qm: QueueManager,
        on_progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
        progress_interval_s: float = 0.1,
    ) -> None:
        if cfg.duration_s <= 0:
            raise ValueError("duration must be positive")
        if not 0 <= cfg.warmup_s < cfg.duration_s:
            raise ValueError("warm-up must satisfy 0 <= warmup < duration")
        self.cfg = cfg
        self.qm = qm
        self.link = Link(cfg.capacity_bps, cfg.prop_delay_s)
        self.on_progress = on_progress
        self.cancel = cancel
        self.progress_interval_s = progress_interval_s

    def run(self) -> SimResult:
        cfg = self.cfg
        qm = self.qm
        link = self.link
        sched = Scheduler()
        service_time = link.service_time(cfg.packet_size_bytes)
        mc = MetricsCollector(
            duration=cfg.duration_s,
            warmup=cfg.warmup_s,
            packet_size_bytes=cfg.packet_size_bytes,
            capacity_bps=cfg.capacity_bps,
            queue_capacity=cfg.queue_capacity,
            nominal_offered_bps=cfg.offered_bps,
            prop_delay_s=cfg.prop_delay_s,
            service_time=service_time,
            bins=cfg.series_bins,
        )

        sources = []
        if cfg.arrival_rate_pps > 0:
            per_source = cfg.arrival_rate_pps / cfg.n_sources
            for i in range(cfg.n_sources):
                src = make_source(
                    cfg.traffic_model,
                    per_source,
                    derive_rng(cfg.seed, f"source-{i}"),
                    cfg.burst_on_s,
                    cfg.burst_off_s,
                )
                sources.append(src)
                first = src.first_arrival()
                if first <= cfg.duration_s:
                    sched.schedule(first, EventKind.ARRIVAL, i)

        busy = False
        in_service: Packet | None = None
        next_pid = 0
        events = 0
        arrivals = departures = drops = 0
        terminated = "completed"
        wall0 = time.monotonic()
        last_report = wall0

        while True:
            ev = sched.pop()
            if ev is None:
                break
            t, kind, payload = ev
            if t > cfg.duration_s:
                break
            mc.advance(t, len(qm), busy)
            events += 1

            if kind is EventKind.ARRIVAL:
                src_id = payload
                pkt = Packet(next_pid, src_id, cfg.packet_size_bytes, t)
                next_pid += 1
                arrivals += 1
                mc.arrival(t)
                reason = qm.enqueue(pkt, t)
                if reason is None:
                    mc.admit(t)
                else:
                    drops += 1
                    mc.drop(t, reason, t)
                nxt = sources[src_id].next_arrival(t)
                if nxt <= cfg.duration_s:
                    sched.schedule(nxt, EventKind.ARRIVAL, src_id)
            else:  # DEPARTURE
                pkt = in_service
                assert pkt is not None
                pkt.departure_time = t
                departures += 1
                mc.depart(pkt.arrival_time, pkt.queueing_delay, pkt.size_bits, t)
                busy = False
                in_service = None

            if not busy:
                res = qm.dequeue(t)
                for dpkt, dreason in res.dropped:
                    drops += 1
                    mc.drop(dpkt.arrival_time, dreason, t)
                if res.packet is not None:
                    in_service = res.packet
                    in_service.service_start = t
                    busy = True
                    sched.schedule(t + service_time, EventKind.DEPARTURE)

            if events >= cfg.max_events:
                terminated = "event_limit"
                break
            if events & 1023 == 0:
                if self.cancel is not None and self.cancel.is_set():
                    terminated = "cancelled"
                    break
                now_wall = time.monotonic()
                if self.on_progress and now_wall - last_report >= self.progress_interval_s:
                    last_report = now_wall
                    mc.events = events
                    self.on_progress(
                        Progress(
                            t,
                            cfg.duration_s,
                            events,
                            arrivals,
                            departures,
                            drops,
                            len(qm),
                            mc.compute(approximate=True),
                            mc.series(),
                        )
                    )

        end_time = cfg.duration_s if terminated == "completed" else sched.now
        mc.advance(end_time, len(qm), busy)
        mc.events = events
        metrics = mc.compute()
        result = SimResult(
            metrics=metrics,
            series=mc.series(),
            terminated=terminated,
            end_time=end_time,
            events_processed=events,
            wall_time_s=time.monotonic() - wall0,
            queue_params=qm.describe(),
        )
        if self.on_progress:
            self.on_progress(
                Progress(
                    end_time,
                    cfg.duration_s,
                    events,
                    arrivals,
                    departures,
                    drops,
                    len(qm),
                    metrics,
                    result.series,
                )
            )
        return result
