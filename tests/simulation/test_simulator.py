import threading

import pytest

from bufferlab.algorithms import build_queue_manager
from bufferlab.core.metrics import MetricsCollector, percentile
from bufferlab.core.simulator import SimConfig, Simulator
from bufferlab.experiments.models import ConfigError, ExperimentConfig
from bufferlab.experiments.runner import run_experiment


def cfg(**kw):
    base = dict(
        name="t",
        algorithm="drop-tail",
        link_mbps=10.0,
        packet_size_bytes=1500,
        queue_capacity=50,
        traffic_model="poisson",
        offered_load_pct=90.0,
        duration_s=20.0,
        warmup_s=2.0,
        seed=3,
    )
    base.update(kw)
    return ExperimentConfig(**base)


def run(**kw):
    return run_experiment(cfg(**kw))


def check_invariants(rec):
    m = rec.metrics
    cap = rec.config.queue_capacity
    assert m["delivered"] <= m["admitted"] <= m["generated"]
    assert m["generated"] == m["delivered"] + m["dropped"] + m["unresolved"]
    assert m["unresolved"] >= 0
    assert m["dropped"] == m["dropped_overflow"] + m["dropped_early"] + m["dropped_aqm"]
    assert 0 <= m["max_queue_len"] <= cap
    assert m["avg_queue_len"] >= 0 and m["avg_queue_len"] <= cap
    assert m["throughput_mbps"] >= 0
    assert m["throughput_mbps"] <= rec.config.link_mbps * 1.01
    assert 0 <= m["link_utilisation"] <= 1
    for k in (
        "avg_queue_delay_ms",
        "median_queue_delay_ms",
        "p95_queue_delay_ms",
        "max_queue_delay_ms",
    ):
        assert m[k] is None or m[k] >= 0
    if m["p95_queue_delay_ms"] is not None:
        assert (
            m["median_queue_delay_ms"] <= m["p95_queue_delay_ms"] <= m["max_queue_delay_ms"] + 1e-9
        )


@pytest.mark.parametrize("alg", ["drop-tail", "red", "codel"])
@pytest.mark.parametrize("load", [0, 30, 100, 150])
def test_invariants_all_algorithms(alg, load):
    rec = run(algorithm=alg, offered_load_pct=load)
    check_invariants(rec)
    assert rec.terminated == "completed"


def test_same_seed_identical_results():
    a, b = (
        run(algorithm="red", traffic_model="bursty", offered_load_pct=110),
        run(algorithm="red", traffic_model="bursty", offered_load_pct=110),
    )
    assert a.metrics == b.metrics and a.series == b.series


def test_different_seed_differs():
    assert run(seed=1).metrics != run(seed=2).metrics


def test_zero_offered_load():
    m = run(offered_load_pct=0).metrics
    assert m["generated"] == 0 and m["throughput_mbps"] == 0
    assert m["loss_rate"] is None and m["avg_queue_delay_ms"] is None
    assert m["link_utilisation"] == 0


def test_below_capacity_constant_has_no_queueing():
    rec = run(traffic_model="constant", offered_load_pct=50, algorithm="drop-tail")
    m = rec.metrics
    assert m["dropped"] == 0
    assert m["max_queue_delay_ms"] == pytest.approx(0.0, abs=1e-9)
    assert m["throughput_mbps"] == pytest.approx(5.0, rel=0.01)
    assert m["link_utilisation"] == pytest.approx(0.5, rel=0.01)
    assert m["avg_total_delay_ms"] == pytest.approx(1.2, rel=1e-6)  # service time only


def test_total_delay_includes_propagation():
    m = run(traffic_model="constant", offered_load_pct=50, prop_delay_ms=20).metrics
    assert m["avg_total_delay_ms"] == pytest.approx(21.2, rel=1e-6)
    assert m["avg_queue_delay_ms"] == pytest.approx(0.0, abs=1e-9)


def test_overload_saturates_link_and_loses_excess():
    m = run(traffic_model="constant", offered_load_pct=200, duration_s=30).metrics
    assert m["throughput_mbps"] == pytest.approx(10.0, rel=0.01)
    assert m["link_utilisation"] > 0.99
    assert m["loss_rate"] == pytest.approx(0.5, abs=0.03)
    assert m["throughput_mbps"] < m["offered_load_mbps"]


def test_mdl_queueing_delay_matches_theory():
    # M/D/1 with a (practically) infinite buffer: Wq = rho * S / (2 * (1 - rho))
    rho, s_ms = 0.5, 1.2
    m = run(
        offered_load_pct=50, queue_capacity=100_000, duration_s=300, warmup_s=10, seed=11
    ).metrics
    assert m["avg_queue_delay_ms"] == pytest.approx(rho * s_ms / (2 * (1 - rho)), rel=0.08)


def test_mm1k_loss_matches_theory_roughly():
    # M/D/1/K blocking is close to M/M/1/K for moderate load; sanity range only.
    m = run(offered_load_pct=100, queue_capacity=1, duration_s=200, warmup_s=5, seed=5).metrics
    assert 0.2 < m["loss_rate"] < 0.6


def test_capacity_one_queue():
    rec = run(queue_capacity=1, offered_load_pct=120, duration_s=50)
    check_invariants(rec)
    assert rec.metrics["max_queue_len"] == 1


def test_codel_and_red_actually_drop_early_under_overload():
    red = run(algorithm="red", offered_load_pct=140).metrics
    codel = run(algorithm="codel", offered_load_pct=140).metrics
    assert red["dropped_early"] > 0
    assert codel["dropped_aqm"] > 0
    dt = run(algorithm="drop-tail", offered_load_pct=140).metrics
    assert dt["dropped_early"] == 0 and dt["dropped_aqm"] == 0
    assert codel["avg_queue_delay_ms"] < dt["avg_queue_delay_ms"]


def test_warmup_not_shorter_or_equal_duration_rejected():
    with pytest.raises(ConfigError):
        run(duration_s=5, warmup_s=5)
    with pytest.raises(ConfigError):
        run(duration_s=5, warmup_s=9)
    with pytest.raises(ValueError):
        sim = SimConfig(10, 1500, 100, 1.0, 2.0, 10)
        Simulator(
            sim,
            build_queue_manager("drop-tail", 10, {}, service_time=0.001, mtu_bytes=1500, seed=1),
        )


def test_invalid_bandwidth_rejected():
    for bw in (0, -5):
        with pytest.raises(ConfigError):
            run(link_mbps=bw)


def test_very_small_duration_and_no_completed_packets():
    rec = run(duration_s=0.001, warmup_s=0.0, offered_load_pct=100)
    check_invariants(rec)
    # 1 ms is shorter than one 1.2ms service time: nothing can be delivered
    assert rec.metrics["delivered"] == 0
    assert rec.metrics["avg_queue_delay_ms"] is None
    assert rec.metrics["delivery_ratio"] in (None, 0.0)


def test_no_event_processed_beyond_duration():
    sim_cfg = cfg(duration_s=3.0, warmup_s=0.5).to_sim_config()
    qm = build_queue_manager("drop-tail", 50, {}, service_time=0.0012, mtu_bytes=1500, seed=3)
    times = []
    from bufferlab.core import simulator as simmod

    orig = simmod.MetricsCollector.advance

    def spy(self, now, qlen, busy):
        times.append(now)
        return orig(self, now, qlen, busy)

    simmod.MetricsCollector.advance = spy
    try:
        res = Simulator(sim_cfg, qm).run()
    finally:
        simmod.MetricsCollector.advance = orig
    assert max(times) <= 3.0 and res.end_time == 3.0


def test_simultaneous_events_departure_before_arrival():
    # constant 1 source whose period equals the service time: arrival and departure coincide.
    # 10 Mbps, 1250 B -> service 1 ms; 100% load -> period exactly 1 ms.
    rec = run(
        packet_size_bytes=1250,
        traffic_model="constant",
        offered_load_pct=100,
        queue_capacity=1,
        duration_s=5,
    )
    assert rec.metrics["dropped"] == 0  # freed slot is available to the coincident arrival
    check_invariants(rec)


def test_event_limit_terminates_and_reports():
    rec = run(max_events=2000, duration_s=60)
    assert rec.terminated == "event_limit"
    assert rec.events_processed == 2000
    check_invariants(rec)


def test_cancellation():
    ev = threading.Event()
    ev.set()
    rec = run_experiment(cfg(duration_s=100), cancel=ev)
    assert rec.terminated == "cancelled"


def test_progress_callbacks_are_real_and_monotonic():
    seen = []
    run_experiment(cfg(duration_s=40, offered_load_pct=120, link_mbps=100), on_progress=seen.append)
    assert seen[-1].fraction == 1.0
    times = [p.sim_time for p in seen]
    assert times == sorted(times)
    assert all(p.metrics.approximate for p in seen[:-1])
    assert not seen[-1].metrics.approximate


def test_series_shapes_and_reconcile():
    rec = run(offered_load_pct=120, duration_s=20, warmup_s=0)
    s = rec.series
    n = len(s["t"])
    assert n == 200
    for key in ("throughput_mbps", "queue_len", "queue_delay_ms", "drops", "arrivals"):
        assert len(s[key]) == n
    bin_w = s["bin_width_s"]
    total_bits = sum(x * 1e6 * bin_w for x in s["throughput_mbps"])
    assert total_bits / 1e6 / 20 == pytest.approx(rec.metrics["throughput_mbps"], rel=1e-6)
    assert sum(s["arrivals"]) == rec.metrics["arrivals_total"]
    assert sum(s["drops"]) == rec.metrics["dropped"]  # warmup=0 => cohort == all packets


def test_pass_through_when_warmup_discards_early_packets():
    rec = run(warmup_s=10, duration_s=20)
    assert rec.metrics["arrivals_total"] > rec.metrics["generated"]
    assert rec.metrics["measured_window_s"] == pytest.approx(10.0)


def test_bursty_has_higher_delay_than_poisson_at_equal_load():
    p = run(traffic_model="poisson", offered_load_pct=70, duration_s=60).metrics
    b = run(traffic_model="bursty", offered_load_pct=70, duration_s=60, n_sources=2).metrics
    assert b["p95_queue_delay_ms"] > p["p95_queue_delay_ms"]


# ---- metrics unit tests ----
def make_mc(**kw):
    args = dict(
        duration=10.0,
        warmup=2.0,
        packet_size_bytes=1000,
        capacity_bps=8e6,
        queue_capacity=10,
        nominal_offered_bps=4e6,
        prop_delay_s=0.0,
        service_time=0.001,
        bins=10,
    )
    args.update(kw)
    return MetricsCollector(**args)


def test_percentile_interpolation():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert percentile(xs, 0) == 1.0
    assert percentile(xs, 50) == pytest.approx(2.5)
    assert percentile(xs, 100) == 4.0
    assert percentile(xs, 95) == pytest.approx(3.85)
    assert percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        percentile([], 50)


def test_collector_time_weighted_occupancy_and_window():
    mc = make_mc()
    mc.advance(1.0, 5, True)  # entirely in warm-up: ignored by window stats
    mc.advance(4.0, 2, True)  # window part: 2s at len 2 busy
    mc.advance(10.0, 0, False)
    m = mc.compute()
    assert m.measured_window_s == pytest.approx(8.0)
    assert m.avg_queue_len == pytest.approx(2 * 2.0 / 8.0)
    assert m.max_queue_len == 2
    assert m.link_utilisation == pytest.approx(2.0 / 8.0)
    assert m.queue_utilisation == pytest.approx(0.5 / 10)


def test_collector_throughput_and_loss_accounting():
    mc = make_mc()
    from bufferlab.algorithms.base import DropReason

    for t in (1.0, 3.0, 4.0, 5.0, 6.0):
        mc.arrival(t)
    for t in (3.0, 4.0, 5.0):
        mc.admit(t)
    mc.drop(6.0, DropReason.OVERFLOW, 6.0)
    mc.drop(1.0, DropReason.OVERFLOW, 1.0)  # warm-up packet: not in cohort
    mc.depart(3.0, 0.001, 8000, 3.5)
    mc.depart(4.0, 0.003, 8000, 4.5)
    mc.advance(10.0, 0, False)
    m = mc.compute()
    assert m.generated == 4  # arrivals at 3,4,5,6 (cohort)
    assert m.delivered == 2 and m.dropped == 1 and m.unresolved == 1
    assert m.loss_rate == pytest.approx(0.25)
    assert m.delivery_ratio == pytest.approx(0.5)
    assert m.throughput_mbps == pytest.approx(16000 / 8.0 / 1e6)
    assert m.avg_queue_delay_ms == pytest.approx(2.0)
    assert m.median_queue_delay_ms == pytest.approx(2.0)
    assert m.arrivals_total == 5


def test_collector_empty_has_none_not_zero():
    m = make_mc().compute()
    assert m.loss_rate is None and m.p95_queue_delay_ms is None and m.throughput_mbps == 0
