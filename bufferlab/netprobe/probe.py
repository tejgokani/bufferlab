"""Real-network probe: ICMP ping (loss, RTT) plus a multi-connection HTTPS download (capacity).

Only the standard library and the system ``ping`` are used; no administrator rights are needed.
Everything here sends real traffic, so callers must obtain the user's consent first (the CLI and TUI do).
"""

from __future__ import annotations

import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

DEFAULT_TARGET = "1.1.1.1"
DEFAULT_URL = "https://speed.cloudflare.com/__down?bytes=25000000"
MAX_DOWNLOAD_BYTES = 300_000_000  # hard cap per probe, so a fast link cannot burn unbounded data
USER_AGENT = "BufferLab-probe/0.1"

ProgressFn = Callable[[str], None]


class ProbeError(RuntimeError):
    pass


class ProbeCancelled(ProbeError):
    pass


# ---- ping -------------------------------------------------------------------------
_TIME = re.compile(r"time\s*[=<]\s*([\d.,]+)\s*ms", re.IGNORECASE)


def parse_ping_times(output: str) -> list[float]:
    """Per-reply RTTs in ms from macOS/Linux/Windows ping output (locale-independent apart from 'time')."""
    out = []
    for m in _TIME.finditer(output):
        out.append(float(m.group(1).replace(",", ".")))
    return out


def ping_command(
    host: str, count: int, interval_s: float = 0.2, platform: str | None = None
) -> list[str]:
    platform = platform or sys.platform
    if not host or host.startswith("-"):
        raise ProbeError(f"invalid ping target {host!r}")
    if platform == "win32":
        return ["ping", "-n", str(count), "-w", "2000", host]
    if platform == "darwin":
        return ["ping", "-c", str(count), "-i", str(interval_s), "-W", "2000", host]
    return ["ping", "-c", str(count), "-i", str(interval_s), "-W", "2", host]


@dataclass
class PingStats:
    sent: int
    rtts_ms: list[float] = field(default_factory=list)

    @property
    def received(self) -> int:
        return min(len(self.rtts_ms), self.sent)

    @property
    def loss(self) -> float | None:
        return None if self.sent == 0 else 1.0 - self.received / self.sent

    @property
    def median_ms(self) -> float | None:
        return statistics.median(self.rtts_ms) if self.rtts_ms else None

    @property
    def min_ms(self) -> float | None:
        return min(self.rtts_ms) if self.rtts_ms else None

    @property
    def p95_ms(self) -> float | None:
        if not self.rtts_ms:
            return None
        s = sorted(self.rtts_ms)
        return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]

    @property
    def jitter_ms(self) -> float | None:
        return statistics.pstdev(self.rtts_ms) if len(self.rtts_ms) > 1 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sent": self.sent,
            "received": self.received,
            "loss": self.loss,
            "min_ms": self.min_ms,
            "median_ms": self.median_ms,
            "p95_ms": self.p95_ms,
            "jitter_ms": self.jitter_ms,
        }


def run_ping(
    host: str, count: int = 10, interval_s: float = 0.2, cancel: threading.Event | None = None
) -> PingStats:
    cmd = ping_command(host, count, interval_s)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=count * max(interval_s, 1.0) + 15,
            check=False,
        )
    except FileNotFoundError:
        raise ProbeError("the system `ping` command was not found") from None
    except subprocess.TimeoutExpired:
        return PingStats(count, [])
    times = parse_ping_times(proc.stdout)
    if (
        not times
        and proc.returncode not in (0, 1, 2)
        and "unknown host" in (proc.stderr + proc.stdout).lower()
    ):
        raise ProbeError(f"ping target {host!r} could not be resolved")
    return PingStats(count, times)


# ---- download ----------------------------------------------------------------------
@dataclass
class DownloadResult:
    mbps: float
    bytes_total: int
    seconds: float
    connections: int


def measure_download(
    url: str = DEFAULT_URL,
    seconds: float = 8.0,
    connections: int = 4,
    ramp_s: float = 1.5,
    cancel: threading.Event | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> DownloadResult:
    """Throughput over the steady part (after ``ramp_s``) of ``connections`` parallel downloads."""
    if not url.startswith(("http://", "https://")):
        raise ProbeError("download URL must be http(s)")
    lock = threading.Lock()
    total = [0]
    errors: list[str] = []
    stop = threading.Event()
    t0 = time.monotonic()
    samples: list[tuple[float, int]] = []

    def worker() -> None:
        try:
            while not stop.is_set():
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - scheme checked above
                    while not stop.is_set():
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        with lock:
                            total[0] += len(chunk)
                            if total[0] >= max_bytes:
                                stop.set()
        except Exception as exc:
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")
            stop.set() if len(errors) >= connections else None

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(connections)]
    for t in threads:
        t.start()
    while time.monotonic() - t0 < seconds and not stop.is_set():
        if cancel is not None and cancel.is_set():
            stop.set()
            raise ProbeCancelled("cancelled")
        time.sleep(0.1)
        with lock:
            samples.append((time.monotonic() - t0, total[0]))
    stop.set()
    for t in threads:
        t.join(timeout=2)
    if total[0] == 0:
        raise ProbeError("download failed: " + (errors[0] if errors else "no data received"))
    steady = [s for s in samples if s[0] >= ramp_s]
    if len(steady) < 2:
        steady = samples
    (ta, ba), (tb, bb) = steady[0], steady[-1]
    if tb <= ta:
        raise ProbeError("download finished too quickly to measure")
    return DownloadResult((bb - ba) * 8 / (tb - ta) / 1e6, total[0], tb, connections)


# ---- full probe --------------------------------------------------------------------
@dataclass
class Measurement:
    taken_at: str
    ping_target: str
    download_url: str
    platform: str
    idle: PingStats
    loaded: PingStats
    download_mbps: float
    download_bytes: int

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["idle"] = self.idle.to_dict() | {"rtts_ms": self.idle.rtts_ms}
        d["loaded"] = self.loaded.to_dict() | {"rtts_ms": self.loaded.rtts_ms}
        return d


def run_probe(
    target: str = DEFAULT_TARGET,
    url: str = DEFAULT_URL,
    seconds: float = 8.0,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Measurement:
    say = progress or (lambda _m: None)
    say(f"idle latency: pinging {target} ...")
    idle = run_ping(target, 10)
    if not idle.rtts_ms:
        raise ProbeError(
            f"no ping replies from {target}; check the connection or choose another --target"
        )
    say(f"idle: median {idle.median_ms:.1f} ms, loss {100 * (idle.loss or 0):.0f}%")
    if cancel is not None and cancel.is_set():
        raise ProbeCancelled("cancelled")
    say(f"downloading from {url.split('/')[2]} for ~{seconds:g}s while pinging ...")
    ramp = 1.5
    loaded_count = max(5, int((seconds - ramp - 0.5) / 0.2))
    holder: dict[str, PingStats] = {}

    def loaded_ping() -> None:
        time.sleep(ramp)
        try:
            holder["p"] = run_ping(target, loaded_count)
        except ProbeError:
            holder["p"] = PingStats(loaded_count, [])

    th = threading.Thread(target=loaded_ping, daemon=True)
    th.start()
    dl = measure_download(url, seconds, 4, ramp, cancel)
    th.join(timeout=seconds + 20)
    loaded = holder.get("p", PingStats(loaded_count, []))
    say(
        f"download: {dl.mbps:.1f} Mbps; loaded latency median {loaded.median_ms:.1f} ms"
        if loaded.median_ms is not None
        else f"download: {dl.mbps:.1f} Mbps"
    )
    return Measurement(
        taken_at=datetime.now(UTC).isoformat(timespec="seconds"),
        ping_target=target,
        download_url=url,
        platform=sys.platform,
        idle=idle,
        loaded=loaded,
        download_mbps=dl.mbps,
        download_bytes=dl.bytes_total,
    )
