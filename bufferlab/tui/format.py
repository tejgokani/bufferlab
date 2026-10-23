"""Human-readable number formatting for the UI."""

from __future__ import annotations

from typing import Any


def mbps(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v / 1000:.2f} Gbps"
    if v >= 1:
        return f"{v:.2f} Mbps"
    return f"{v * 1000:.1f} kbps"


def ms(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v / 1000:.2f} s"
    return f"{v:.2f} ms"


def pct(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 120:
        return f"{seconds:.1f} s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def count(v: Any) -> str:
    return "—" if v is None else f"{int(v):,}"
