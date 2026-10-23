import json
import stat
import sys

import pytest

from bufferlab.experiments.models import ExperimentConfig
from bufferlab.experiments.runner import run_experiment
from bufferlab.measure import iperf

TCP = {
    "start": {"version": "iperf 3.x"},
    "end": {
        "sum_sent": {"retransmits": 3, "seconds": 2.0},
        "sum_received": {"bits_per_second": 94_000_000.0, "seconds": 2.0},
    },
}
UDP = {
    "end": {"sum": {"bits_per_second": 5e6, "seconds": 2.0, "jitter_ms": 0.2, "lost_percent": 1.5}}
}


def test_parse_tcp_udp_and_error():
    r = iperf.parse_iperf_json(TCP, "h", 5201, "tcp", False)
    assert r.throughput_mbps == 94.0 and r.retransmits == 3 and r.source.startswith("measured")
    u = iperf.parse_iperf_json(UDP, "h", 5201, "udp", False)
    assert u.jitter_ms == 0.2 and u.lost_percent == 1.5
    with pytest.raises(iperf.MeasureError):
        iperf.parse_iperf_json({"error": "unable to connect"}, "h", 1, "tcp", False)
    with pytest.raises(iperf.MeasureError):
        iperf.parse_iperf_json({"end": {}}, "h", 1, "tcp", False)


def test_refuses_without_confirmation_or_bad_input():
    with pytest.raises(iperf.MeasureError, match="confirmation"):
        iperf.run_client("example.org")
    with pytest.raises(iperf.MeasureError):
        iperf.run_client("-oProxy", confirmed=True, exe="x")
    with pytest.raises(iperf.MeasureError):
        iperf.run_client("h", duration_s=0, confirmed=True, exe="x")


def test_missing_binary_gives_hint(monkeypatch):
    monkeypatch.setattr(iperf, "find_iperf3", lambda: None)
    with pytest.raises(iperf.MeasureError, match="not found"):
        iperf.run_client("h", confirmed=True)


@pytest.mark.skipif(sys.platform == "win32", reason="uses a shell-script stand-in for iperf3")
def test_run_client_with_stand_in_executable(tmp_path):
    fake = tmp_path / "iperf3"
    fake.write_text("#!/bin/sh\necho '" + json.dumps(TCP) + "'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    r = iperf.run_client("10.0.0.1", confirmed=True, exe=str(fake))
    assert r.throughput_mbps == 94.0 and r.host == "10.0.0.1"


def test_plots(tmp_path):
    pytest.importorskip("matplotlib")
    from bufferlab.analysis.plots import plot_comparison, plot_runs

    runs = [
        run_experiment(
            ExperimentConfig(algorithm=a, duration_s=6.0, warmup_s=1.0, offered_load_pct=120)
        )
        for a in ("drop-tail", "codel")
    ]
    for fn, name in ((plot_runs, "a.png"), (plot_comparison, "b.png")):
        out = fn(runs, tmp_path / name)
        assert out.read_bytes()[:4] == b"\x89PNG"
