import math

import pytest

from bufferlab.algorithms import RED, CoDel, DropReason, DropTail, validate_params
from bufferlab.core.packets import Packet
from bufferlab.core.random_source import derive_rng


def pkt(i, t=0.0, size=1000):
    return Packet(i, 0, size, t)


# ---- Drop-Tail ----
def test_droptail_admits_until_full_then_drops_arrival():
    q = DropTail(3)
    results = [q.enqueue(pkt(i), 0.0) for i in range(5)]
    assert results == [None, None, None, DropReason.OVERFLOW, DropReason.OVERFLOW]
    assert len(q) == 3 and q.admitted == 3 and q.drops[DropReason.OVERFLOW] == 2


def test_droptail_is_fifo_and_frees_space():
    q = DropTail(2)
    q.enqueue(pkt(1), 0.0)
    q.enqueue(pkt(2), 0.0)
    assert q.dequeue(1.0).packet.pid == 1
    assert q.enqueue(pkt(3), 1.0) is None
    assert [q.dequeue(2.0).packet.pid, q.dequeue(2.0).packet.pid] == [2, 3]
    assert q.dequeue(2.0).packet is None


def test_droptail_capacity_one_and_invalid():
    q = DropTail(1)
    assert q.enqueue(pkt(1), 0) is None
    assert q.enqueue(pkt(2), 0) is DropReason.OVERFLOW
    with pytest.raises(ValueError):
        DropTail(0)


def test_enqueue_stamps_time():
    q = DropTail(2)
    p = pkt(1, 3.0)
    q.enqueue(p, 3.0)
    assert p.enqueue_time == 3.0


# ---- RED ----
def make_red(**kw):
    args = dict(
        capacity=100,
        rng=derive_rng(1, "red"),
        service_time=0.001,
        min_th=5,
        max_th=15,
        max_p=0.1,
        weight=0.5,
    )
    args.update(kw)
    return RED(**args)


def test_red_no_early_drop_below_min_threshold():
    q = make_red()
    for i in range(4):
        assert q.enqueue(pkt(i), 0.0) is None
    assert q.avg < q.min_th


def test_red_average_ewma_equation():
    q = make_red(weight=0.25)
    for i in range(4):
        q.enqueue(pkt(i), 0.0)
    # avg after arrival k sees queue length k-1 (updated before the packet is added)
    expected = 0.0
    for qlen in (0, 1, 2, 3):
        # first arrival: queue empty -> idle decay of 0 stays 0
        expected = expected if qlen == 0 else 0.75 * expected + 0.25 * qlen
    assert q.avg == pytest.approx(expected)


def test_red_drops_everything_above_max_threshold():
    q = make_red(min_th=2, max_th=4, weight=1.0, capacity=100)
    for i in range(10):
        q.enqueue(pkt(i), 0.0)
    # with weight 1, avg == queue length; once queue >= 4, all arrivals dropped early
    assert len(q) == 4
    assert q.drops[DropReason.EARLY] == 6


def test_red_probability_between_thresholds():
    q = make_red(min_th=10, max_th=20, max_p=0.2)
    assert q.base_probability(5) is None
    assert q.base_probability(15) == pytest.approx(0.1)
    assert q.base_probability(20) == 1.0
    g = make_red(min_th=10, max_th=20, max_p=0.2, gentle=True)
    assert g.base_probability(20) == pytest.approx(0.2)
    assert g.base_probability(30) == pytest.approx(0.6)
    assert g.base_probability(40) == 1.0


def test_red_empirical_drop_fraction_near_pa():
    # hold avg fixed mid-way: pb = 0.1 * (15-10)/(20-10)... use huge capacity, no dequeue
    q = make_red(min_th=10, max_th=20, max_p=0.5, weight=1.0, capacity=10_000)
    for i in range(12):
        q.enqueue(pkt(i), 0.0)  # fill past min_th without drops (avg lags by one)
    # now repeatedly offer then remove, keeping queue length at ~15 => pb = 0.25
    q.rng = derive_rng(5, "x")
    drops = trials = 0
    while len(q) < 15:
        q.enqueue(pkt(100 + len(q)), 0.0)
    for i in range(20000):
        r = q.enqueue(pkt(1000 + i), 0.0)
        trials += 1
        if r is DropReason.EARLY:
            drops += 1
        else:
            q._pop()  # keep length stable
    # pb = 0.25. After a drop, count restarts: pa = 1/3, then 1/2, then 1 (count*pb -> 1), so the
    # gap between drops is 1, 2 or 3 packets with probability 1/3 each => mean gap 2 => 50% drops.
    assert drops / trials == pytest.approx(0.5, abs=0.03)


def test_red_forced_drop_when_full():
    q = make_red(min_th=50, max_th=90, capacity=3, weight=0.001)
    out = [q.enqueue(pkt(i), 0.0) for i in range(5)]
    assert out[3:] == [DropReason.OVERFLOW] * 2


def test_red_idle_decay():
    q = make_red(weight=0.1, service_time=0.001)
    q.avg = 10.0
    q.idle_since = 1.0
    q.update_average(1.0 + 0.010)  # 10 packet-times idle
    assert q.avg == pytest.approx(10.0 * 0.9**10)


def test_red_idle_set_on_dequeue_to_empty():
    q = make_red()
    q.enqueue(pkt(1), 0.0)
    q.dequeue(2.5)
    assert q.idle_since == 2.5


def test_red_parameter_validation():
    with pytest.raises(ValueError):
        make_red(min_th=10, max_th=5)
    with pytest.raises(ValueError):
        make_red(max_p=0)
    errs, _ = validate_params("red", 50, {"min_th": 30, "max_th": 10})
    assert errs
    _, warns = validate_params("red", 50, {"min_th": 10, "max_th": 80})
    assert warns


def test_red_reproducible_with_seed():
    def run(seed):
        q = make_red(rng=derive_rng(seed, "r"), min_th=2, max_th=50, weight=0.5, capacity=1000)
        return [q.enqueue(pkt(i), 0.0) for i in range(100)]

    assert run(3) == run(3)
    assert run(3) != run(4)


# ---- CoDel ----
def fill_old(q, n, enq_time=0.0):
    for i in range(n):
        p = pkt(i, enq_time)
        assert q.enqueue(p, enq_time) is None


def test_codel_no_drop_when_sojourn_below_target():
    q = CoDel(100, target_s=0.005, interval_s=0.1, mtu_bytes=1000)
    fill_old(q, 10, 0.0)
    for k in range(10):
        r = q.dequeue(0.001 * (k + 1))  # sojourn <= 10ms but first few < 5ms
        assert not r.dropped or k >= 5
    assert q.first_above_time is None or q.first_above_time > 0


def test_codel_arms_timer_then_drops_after_interval():
    q = CoDel(1000, target_s=0.005, interval_s=0.1, mtu_bytes=1000)
    fill_old(q, 50, 0.0)
    r = q.dequeue(0.020)  # sojourn 20ms >= target, backlog > MTU: arm timer only
    assert not r.dropped and q.first_above_time == pytest.approx(0.120) and not q.dropping
    r = q.dequeue(0.100)
    assert not r.dropped and not q.dropping
    r = q.dequeue(0.130)  # now >= first_above_time: enter dropping, drop head
    assert len(r.dropped) == 1 and r.dropped[0][1] is DropReason.AQM
    assert q.dropping and q.count == 1
    assert q.drop_next == pytest.approx(0.130 + 0.1 / math.sqrt(1))


def test_codel_control_law_spacing_and_count_growth():
    q = CoDel(1000, target_s=0.005, interval_s=0.1, mtu_bytes=1000)
    fill_old(q, 200, 0.0)
    q.dequeue(0.020)
    q.dequeue(0.130)
    assert q.count == 1
    first_next = q.drop_next
    r = q.dequeue(first_next - 0.001)  # before drop_next: no drop
    assert not r.dropped
    r = q.dequeue(first_next + 0.0001)
    assert len(r.dropped) == 1 and q.count == 2
    assert q.drop_next == pytest.approx(first_next + 0.1 / math.sqrt(2))


def test_codel_leaves_dropping_when_delay_recovers():
    q = CoDel(1000, target_s=0.005, interval_s=0.1, mtu_bytes=1000)
    fill_old(q, 100, 0.0)
    q.dequeue(0.020)
    q.dequeue(0.130)
    assert q.dropping
    # fresh packets with tiny sojourn
    fresh = pkt(999, 0.5)
    q.enqueue(fresh, 0.5)
    while len(q) > 1:
        q._pop()
    r = q.dequeue(0.5005)
    assert not q.dropping and r.packet is fresh


def test_codel_hysteresis_reenter_resumes_count():
    q = CoDel(1000, target_s=0.005, interval_s=0.1, mtu_bytes=1000)
    fill_old(q, 100, 0.0)
    q.dequeue(0.020)
    q.dequeue(0.130)
    for _ in range(3):  # a few more drops
        q.dequeue(q.drop_next + 1e-6)
    cnt = q.count
    assert cnt >= 3
    q.dropping = False
    q.lastcount = 1
    q.first_above_time = 0.0
    q.drop_next = 0.5
    q.dequeue(0.55)  # ok_to_drop with recent drop_next (<16 intervals): resume count
    assert q.dropping and q.count == cnt - 1


def test_codel_no_drop_when_backlog_at_most_one_mtu():
    q = CoDel(100, target_s=0.001, interval_s=0.01, mtu_bytes=1000)
    q.enqueue(pkt(1, 0.0, 1000), 0.0)
    q.enqueue(pkt(2, 0.0, 1000), 0.0)
    for t in (0.1, 0.2, 0.3):
        r = q.dequeue(t)
        assert not r.dropped
        q.enqueue(pkt(int(t * 10) + 10, t, 1000), t)


def test_codel_tail_drops_on_overflow():
    q = CoDel(2)
    assert q.enqueue(pkt(1), 0) is None
    assert q.enqueue(pkt(2), 0) is None
    assert q.enqueue(pkt(3), 0) is DropReason.OVERFLOW


def test_codel_param_validation():
    with pytest.raises(ValueError):
        CoDel(10, target_s=0)
    errs, _ = validate_params("codel", 50, {"target_ms": -1})
    assert errs
