import http.server
import threading
import time

import pytest

from bufferlab.netprobe import probe as pr
from bufferlab.netprobe import whatif
from bufferlab.netprobe.profile import NetworkProfile

MAC = """PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=8.123 ms
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=9.5 ms

--- 1.1.1.1 ping statistics ---
2 packets transmitted, 2 packets received, 0.0% packet loss
"""
LINUX = "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.4 ms\n64 bytes from 1.1.1.1: icmp_seq=3 ttl=57 time=13.0 ms\n"
WIN = "Reply from 1.1.1.1: bytes=32 time=9ms TTL=57\nReply from 1.1.1.1: bytes=32 time<1ms TTL=57\nRequest timed out.\n"


def test_parse_ping_outputs():
    assert pr.parse_ping_times(MAC) == [8.123, 9.5]
    assert pr.parse_ping_times(LINUX) == [12.4, 13.0]
    assert pr.parse_ping_times(WIN) == [9.0, 1.0]
    assert pr.parse_ping_times("garbage") == []


def test_ping_stats_loss_and_percentiles():
    s = pr.PingStats(10, [10.0, 12.0, 11.0, 50.0, 10.0, 10.0, 10.0, 10.0])
    assert s.received == 8 and s.loss == pytest.approx(0.2)
    assert s.median_ms == 10.0 and s.min_ms == 10.0 and s.p95_ms == 50.0
    assert pr.PingStats(5, []).loss == 1.0 and pr.PingStats(5, []).median_ms is None


def test_ping_command_per_platform_and_validation():
    assert pr.ping_command("h", 5, platform="win32") == ["ping", "-n", "5", "-w", "2000", "h"]
    assert pr.ping_command("h", 5, 0.2, "darwin")[:3] == ["ping", "-c", "5"]
    assert "-W" in pr.ping_command("h", 5, 0.2, "linux")
    with pytest.raises(pr.ProbeError):
        pr.ping_command("-f", 5)


class _Throttled(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(50_000_000))
        self.end_headers()
        try:
            for _ in range(500):
                self.wfile.write(b"x" * 100_000)
                time.sleep(0.1)  # 1 MB/s = 8 Mbps per connection
        except OSError:
            pass

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Throttled)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def test_download_measures_known_rate(server):
    r = pr.measure_download(server, seconds=4.0, connections=3, ramp_s=1.0)
    assert r.mbps == pytest.approx(24.0, rel=0.25)  # 3 connections x 8 Mbps


def test_download_byte_cap_and_errors(server):
    r = pr.measure_download(server, seconds=4.0, connections=1, ramp_s=0.3, max_bytes=300_000)
    assert r.bytes_total < 1_000_000
    with pytest.raises(pr.ProbeError):
        pr.measure_download("ftp://x/y")
    with pytest.raises(pr.ProbeError, match="download failed"):
        pr.measure_download("http://127.0.0.1:9/", seconds=2.0, connections=1)


def test_download_cancel(server):
    ev = threading.Event()
    ev.set()
    with pytest.raises(pr.ProbeCancelled):
        pr.measure_download(server, seconds=5.0, cancel=ev)


def meas(idle=20.0, loaded=220.0, mbps=100.0):
    idle_p = pr.PingStats(10, [idle] * 10)
    loaded_p = pr.PingStats(10, [loaded] * 10 if loaded is not None else [])
    return pr.Measurement("2026-01-01T00:00:00+00:00", "t", "u", "linux", idle_p, loaded_p, mbps, 1)


def test_profile_derivation_is_explicit():
    p = NetworkProfile.from_measurement(meas())
    assert p.capacity_mbps == 100.0 and p.idle_rtt_ms == 20.0
    assert p.buffer_delay_ms == pytest.approx(200.0)
    assert p.buffer_pkts == round(0.2 * 100e6 / 12000)  # delay x capacity / packet size
    cfg = p.base_config()
    assert cfg.link_mbps == 100.0 and cfg.queue_capacity == p.buffer_pkts
    assert cfg.prop_delay_ms == pytest.approx(10.0)  # one-way = half the idle RTT
    assert cfg.validate().ok


def test_profile_edge_cases():
    little = NetworkProfile.from_measurement(meas(loaded=21.0))
    assert little.buffer_pkts == 8 and "little queueing" in little.buffer_note
    none = NetworkProfile.from_measurement(meas(loaded=None))
    assert none.loaded_rtt_ms is None and "no replies" in none.buffer_note
    assert NetworkProfile.from_dict(little.to_dict()) == little
    assert NetworkProfile.manual(50.0, 30.0, 40.0).buffer_pkts == round(0.04 * 50e6 / 12000)


def test_predict_matches_basic_queueing_behaviour():
    prof = NetworkProfile.manual(10.0, 20.0, 50.0)
    preds = whatif.predict(prof, [5.0, 10.0, 20.0], ["drop-tail"])
    below, at, over = preds
    assert below.loss_rate < 0.001 and below.throughput_mbps == pytest.approx(5.0, rel=0.05)
    assert over.throughput_mbps == pytest.approx(10.0, rel=0.02)  # cannot exceed measured capacity
    assert over.loss_rate == pytest.approx(0.5, abs=0.06)  # half of 2x offered load is lost
    assert whatif.knee(preds, "drop-tail") in (10.0, 20.0)
    assert whatif.knee(preds[:1], "drop-tail") is None


def test_predict_cancel_and_defaults():
    prof = NetworkProfile.manual(10.0)
    ev = threading.Event()
    ev.set()
    assert whatif.predict(prof, [5.0], ["red"], cancel=ev) == []
    assert whatif.default_loads(10.0)[0] == 2.5 and whatif.default_loads(10.0)[-1] == 20.0
    d, w = whatif.duration_for(1000.0)
    assert 3.0 <= d <= 20.0 and w == pytest.approx(d * 0.2, abs=0.01)
