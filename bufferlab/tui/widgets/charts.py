"""Terminal charts and metric cards (Rich renderables, no ANSI by hand)."""

from __future__ import annotations

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

BLOCKS = " ▁▂▃▄▅▆▇█"


def resample(values: list[float | None], cols: int, agg: str = "mean") -> list[float | None]:
    n = len(values)
    out: list[float | None] = []
    for c in range(cols):
        lo = int(c * n / cols)
        hi = max(lo + 1, int((c + 1) * n / cols))
        chunk = [v for v in values[lo:hi] if v is not None]
        if not chunk:
            out.append(None)
        else:
            out.append(sum(chunk) if agg == "sum" else sum(chunk) / len(chunk))
    return out


def render_bars(
    values: list[float | None], cols: int, rows: int, ymax: float, ascii_mode: bool = False
) -> list[list[str]]:
    """Return ``rows`` lists of ``cols`` characters, top row first."""
    grid: list[list[str]] = []
    for r in range(rows):
        b = rows - 1 - r
        line = []
        for v in values:
            if v is None:
                line.append(" ")
                continue
            eighths = max(0.0, min(8.0, v / ymax * rows * 8 - b * 8)) if ymax > 0 else 0.0
            if ascii_mode:
                line.append("#" if eighths >= 4 else ("." if eighths >= 1 else " "))
            else:
                line.append(BLOCKS[int(round(eighths))])
        grid.append(line)
    return grid


class LineChart(Widget):
    """Bar/line chart of a time series with y-axis labels and a warm-up shade."""

    DEFAULT_CSS = """
    LineChart { width: 1fr; height: 1fr; min-height: 6; padding: 0 1; border: round $primary-darken-1; }
    """

    def __init__(
        self, title: str, unit: str = "", color: str = "cyan", agg: str = "mean", **kw
    ) -> None:
        super().__init__(**kw)
        self.title = title
        self.unit = unit
        self.color = color
        self.agg = agg
        self._values: list[float | None] = []
        self._ymax: float | None = None
        self._x_end = 0.0
        self._warmup = 0.0
        self.border_title = title

    def set_data(
        self,
        values: list[float | None],
        ymax: float | None = None,
        x_end_s: float = 0.0,
        warmup_s: float = 0.0,
    ) -> None:
        self._values = list(values)
        self._ymax = ymax
        self._x_end = x_end_s
        self._warmup = warmup_s
        self.refresh()

    def clear(self) -> None:
        self.set_data([])

    def render(self) -> Text:
        w, h = self.size.width, self.size.height
        ascii_mode = bool(getattr(self.app, "ascii_mode", False))
        if h < 3 or w < 14:
            return Text("(too small)", style="dim")
        data = [v for v in self._values if v is not None]
        if not data:
            return Text("no data yet" if not self._values else "no samples", style="dim")
        gutter = 8
        cols = max(1, w - gutter)
        rows = max(1, h - 2)
        vals = resample(self._values, cols, self.agg)
        present = [v for v in vals if v is not None]
        top = max(present) if present else 0.0
        ymax = self._ymax if self._ymax and self._ymax >= top else top * 1.05
        if ymax <= 0:
            ymax = 1.0
        grid = render_bars(vals, cols, rows, ymax, ascii_mode)
        nb = len(self._values)
        warm_cols = 0
        if self._x_end > 0 and self._warmup > 0:
            warm_cols = min(cols, int(cols * self._warmup / self._x_end))
        text = Text()
        for r, line in enumerate(grid):
            label = f"{ymax:.3g}" if r == 0 else ("0" if r == rows - 1 else "")
            text.append(f"{label:>{gutter - 1}} ", style="dim")
            for c, ch in enumerate(line):
                text.append(ch, style=f"dim {self.color}" if c < warm_cols else self.color)
            text.append("\n")
        last = next((v for v in reversed(self._values) if v is not None), None)
        foot = f"{'':>{gutter}}0s"
        right = (
            f"{self._x_end:.0f}s  last={last:.3g}{self.unit}"
            if last is not None
            else f"{self._x_end:.0f}s"
        )
        pad = max(1, cols - 2 - len(right))
        text.append(foot + " " * pad + right, style="dim")
        if warm_cols and nb:
            text.append("  (dim = warm-up)", style="dim")
        return text


STATUS_STYLE = {
    "ok": ("green", "healthy"),
    "warn": ("yellow", "warning"),
    "bad": ("red", "congested"),
}


class MetricCard(Static):
    DEFAULT_CSS = """
    MetricCard { width: 1fr; height: 5; border: round $primary-darken-1; padding: 0 1; min-width: 14; }
    """

    def __init__(self, title: str, **kw) -> None:
        super().__init__("", **kw)
        self.border_title = title
        self.set_value("—")

    def set_value(
        self, value: str, status: str | None = None, note: str = "", status_text: str | None = None
    ) -> None:
        t = Text()
        style = STATUS_STYLE.get(status or "", ("", ""))[0]
        t.append(value, style=f"bold {style}".strip())
        t.append("\n")
        if status:
            label = status_text or STATUS_STYLE[status][1]
            t.append(
                f"{'●' if not getattr(self.app, 'ascii_mode', False) else '*'} {label}", style=style
            )
        else:
            t.append(note or "no data", style="dim")
        if status and note:
            t.append(f"\n{note}", style="dim")
        self.update(t)
