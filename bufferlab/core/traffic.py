"""Traffic generators.

Each source produces a sequence of packet emission times.  The configured total
arrival rate is split equally across sources.

Models
------
constant : fixed inter-arrival ``1/rate`` with a random initial phase per source.
poisson  : exponential inter-arrivals with mean ``1/rate``.
bursty   : Markov-modulated on/off.  ON and OFF period lengths are exponential
           with means ``on_mean_s`` / ``off_mean_s``.  During ON, packets arrive
           as a Poisson process at the peak rate
           ``rate * (on + off) / on`` so the long-run average equals ``rate``.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

TRAFFIC_MODELS = ("constant", "poisson", "bursty")


class TrafficSource(ABC):
    @abstractmethod
    def first_arrival(self) -> float: ...

    @abstractmethod
    def next_arrival(self, prev: float) -> float: ...


class ConstantRate(TrafficSource):
    def __init__(self, rate_pps: float, rng: random.Random) -> None:
        self.period = 1.0 / rate_pps
        self._phase = rng.random() * self.period

    def first_arrival(self) -> float:
        return self._phase

    def next_arrival(self, prev: float) -> float:
        return prev + self.period


class PoissonRate(TrafficSource):
    def __init__(self, rate_pps: float, rng: random.Random) -> None:
        self.rate = rate_pps
        self.rng = rng

    def first_arrival(self) -> float:
        return self.rng.expovariate(self.rate)

    def next_arrival(self, prev: float) -> float:
        return prev + self.rng.expovariate(self.rate)


class OnOffBursty(TrafficSource):
    def __init__(
        self, avg_rate_pps: float, on_mean_s: float, off_mean_s: float, rng: random.Random
    ) -> None:
        self.rng = rng
        self.on_mean = on_mean_s
        self.off_mean = off_mean_s
        self.peak = avg_rate_pps * (on_mean_s + off_mean_s) / on_mean_s
        self.on = rng.random() < on_mean_s / (on_mean_s + off_mean_s)
        mean = on_mean_s if self.on else off_mean_s
        self.period_end = rng.expovariate(1.0 / mean)

    def _next_after(self, t: float) -> float:
        while True:
            if self.on:
                cand = t + self.rng.expovariate(self.peak)
                if cand <= self.period_end:
                    return cand
                t = self.period_end
                self.on = False
                self.period_end = t + self.rng.expovariate(1.0 / self.off_mean)
            else:
                t = self.period_end
                self.on = True
                self.period_end = t + self.rng.expovariate(1.0 / self.on_mean)

    def first_arrival(self) -> float:
        return self._next_after(0.0)

    def next_arrival(self, prev: float) -> float:
        return self._next_after(prev)


def make_source(
    model: str,
    rate_pps: float,
    rng: random.Random,
    burst_on_s: float = 0.2,
    burst_off_s: float = 0.8,
) -> TrafficSource:
    if rate_pps <= 0:
        raise ValueError("per-source rate must be positive")
    if model == "constant":
        return ConstantRate(rate_pps, rng)
    if model == "poisson":
        return PoissonRate(rate_pps, rng)
    if model == "bursty":
        return OnOffBursty(rate_pps, burst_on_s, burst_off_s, rng)
    raise ValueError(f"unknown traffic model {model!r}; choose from {TRAFFIC_MODELS}")
