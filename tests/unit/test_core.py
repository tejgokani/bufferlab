import pytest

from bufferlab.core.events import EventKind
from bufferlab.core.links import Link, offered_load_bps, rate_for_load_pct
from bufferlab.core.packets import Packet
from bufferlab.core.random_source import derive_rng
from bufferlab.core.scheduler import Scheduler
from bufferlab.core.traffic import make_source


def test_packet_creation_and_bits():
    p = Packet(1, 0, 1500, 0.5)
    assert p.size_bits == 12000
    assert p.enqueue_time == -1.0
    with pytest.raises(ValueError):
        Packet(2, 0, 0, 0.0)
    with pytest.raises(ValueError):
        _ = p.queueing_delay


def test_queueing_delay_property():
    p = Packet(1, 0, 100, 1.0, enqueue_time=1.0, service_start=1.25)
    assert p.queueing_delay == pytest.approx(0.25)


def test_scheduler_orders_by_time_then_kind_then_insertion():
    s = Scheduler()
    s.schedule(2.0, EventKind.ARRIVAL, "a2")
    s.schedule(1.0, EventKind.ARRIVAL, "a1")
    s.schedule(1.0, EventKind.DEPARTURE, "d1")  # same time: departure first
    s.schedule(1.0, EventKind.ARRIVAL, "a1b")  # same time+kind: insertion order
    order = []
    while (ev := s.pop()) is not None:
        order.append(ev[2])
    assert order == ["d1", "a1", "a1b", "a2"]
    assert s.now == 2.0


def test_scheduler_rejects_past_events():
    s = Scheduler()
    s.schedule(5.0, EventKind.ARRIVAL)
    s.pop()
    with pytest.raises(ValueError):
        s.schedule(4.0, EventKind.ARRIVAL)


def test_service_time():
    link = Link(10e6)
    assert link.service_time(1500) == pytest.approx(0.0012)
    assert Link(1e6).service_time(125) == pytest.approx(0.001)


def test_link_validation():
    with pytest.raises(ValueError):
        Link(0)
    with pytest.raises(ValueError):
        Link(1e6, -1)


def test_offered_load_units():
    assert offered_load_bps(1000, 1500) == 12_000_000
    assert rate_for_load_pct(50, 10e6, 1500) == pytest.approx(416.6666667)
    assert offered_load_bps(rate_for_load_pct(75, 10e6, 1500), 1500) == pytest.approx(7.5e6)


def test_rng_streams_are_deterministic_and_independent():
    assert derive_rng(1, "a").random() == derive_rng(1, "a").random()
    assert derive_rng(1, "a").random() != derive_rng(1, "b").random()
    assert derive_rng(1, "a").random() != derive_rng(2, "a").random()


@pytest.mark.parametrize("model", ["constant", "poisson", "bursty"])
def test_traffic_long_run_rate(model):
    src = make_source(model, 200.0, derive_rng(7, model), 0.2, 0.8)
    t = src.first_arrival()
    n = 0
    while t < 500.0:
        n += 1
        t = src.next_arrival(t)
    assert n / 500.0 == pytest.approx(200.0, rel=0.08)


def test_constant_traffic_is_evenly_spaced():
    src = make_source("constant", 100.0, derive_rng(1, "x"))
    t0 = src.first_arrival()
    assert 0 <= t0 < 0.01
    assert src.next_arrival(t0) - t0 == pytest.approx(0.01)


def test_unknown_traffic_model():
    with pytest.raises(ValueError):
        make_source("nope", 1.0, derive_rng(1, "x"))
