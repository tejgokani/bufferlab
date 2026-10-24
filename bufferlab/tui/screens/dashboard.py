"""Dashboard: live metric cards, charts and activity from the running simulation."""

from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import ProgressBar, RichLog, Static

from bufferlab.tui import format as fmt
from bufferlab.tui.screens.base import LabScreen
from bufferlab.tui.widgets.charts import LineChart, MetricCard

STATUS_STYLE = {
    "idle": ("IDLE", "dim"),
    "running": ("RUNNING", "bold cyan"),
    "done": ("COMPLETE", "bold green"),
    "cancelled": ("CANCELLED", "bold yellow"),
    "error": ("FAILED", "bold red"),
}
LEVEL_STYLE = {"info": "cyan", "ok": "green", "warn": "yellow", "error": "red"}


class DashboardScreen(LabScreen):
    NAME = "dashboard"
    TITLE_TEXT = "Dashboard"
    HELP = (
        "Dashboard\n\nShows the most recent simulation. While a run is in progress the cards and "
        "charts update from the simulator's actual state (live percentiles are estimates from the "
        "most recent 20,000 delivered packets; final values are exact).\n\n"
        "Dim bars in the charts are the warm-up period, which is excluded from all metrics.\n\n"
        "Esc  cancel the running simulation\nF3   configure a new experiment\n"
        "F7   pick a built-in scenario\nq    quit"
    )

    def body(self) -> ComposeResult:
        yield Static(id="status-line")
        with Horizontal(id="cards"):
            yield MetricCard("Throughput", id="c-thr")
            yield MetricCard("Packet loss", id="c-loss")
            yield MetricCard("Avg queue delay", id="c-avg")
            yield MetricCard("p95 queue delay", id="c-p95")
            yield MetricCard("Link utilisation", id="c-util")
        with Vertical(id="charts"):
            with Horizontal(id="chart-top"):
                yield LineChart("Throughput (Mbps)", " Mbps", "green", id="ch-thr")
                yield LineChart("Packet loss (% of arrivals per bin)", "%", "red", id="ch-drop")
            with Horizontal(id="chart-bottom"):
                yield LineChart("Queue occupancy (pkts)", " pkts", "cyan", id="ch-q")
                yield LineChart("Queueing delay (ms)", " ms", "yellow", id="ch-d")
        with Horizontal(id="activity"):
            with Vertical(classes="panel", id="progress-panel"):
                yield Static("Progress", classes="title")
                yield ProgressBar(total=100, show_eta=False, id="pbar")
                yield Static(id="counts")
                yield Static(id="empty-state")
            yield RichLog(
                id="events",
                classes="panel",
                markup=False,
                highlight=False,
                max_lines=300,
                wrap=True,
            )

    def on_mount(self) -> None:
        super().on_mount()
        self._logged = 0
        self.render_state()
        self.set_interval(0.5, self._tick)

    def on_screen_resume(self) -> None:
        self._logged = 0
        self.query_one("#events", RichLog).clear()
        self.render_state()

    def on_run_state(self) -> None:
        self.render_state()

    def _tick(self) -> None:
        if self.app.state.status == "running" and self.is_current:
            self.render_state(status_only=True)

    # ------------------------------------------------------------------------------
    def render_state(self, status_only: bool = False) -> None:
        st = self.app.state
        label, style = STATUS_STYLE[st.status]
        cfg = st.config
        line = Text()
        line.append(f" {label} ", style=f"reverse {style}")
        if cfg:
            line.append(f"  scenario: {cfg.scenario or cfg.name}", style="")
            line.append(f"  algorithm: {cfg.algorithm}", style="cyan")
            if st.kind == "batch":
                line.append(f"  batch run {st.batch_done}/{st.batch_total}", style="")
        else:
            line.append("  no simulation yet", style="dim")
        if st.status == "running":
            line.append(f"  elapsed {fmt.duration(time.monotonic() - st.started)}", style="dim")
        self.query_one("#status-line", Static).update(line)
        if status_only:
            return
        self._render_events()
        self._render_progress()
        source = st.progress.metrics if st.progress else (st.record.metrics if st.record else None)
        series = st.progress.series if st.progress else (st.record.series if st.record else None)
        self._render_cards(source, cfg)
        self._render_charts(series, cfg)

    def _render_events(self) -> None:
        log = self.query_one("#events", RichLog)
        for level, msg in self.app.state.events[self._logged :]:
            log.write(Text(msg, style=LEVEL_STYLE.get(level, "")))
        self._logged = len(self.app.state.events)

    def _render_progress(self) -> None:
        st = self.app.state
        bar = self.query_one("#pbar", ProgressBar)
        counts = self.query_one("#counts", Static)
        empty = self.query_one("#empty-state", Static)
        p = st.progress
        if st.status == "idle":
            bar.update(total=100, progress=0)
            counts.update(Text(""))
            empty.update(
                Text(
                    "No simulation has been run yet.\n"
                    "F8 My Network (measure your network, predict its loss and throughput) · F3 New Experiment · F7 Scenarios",
                    style="dim",
                )
            )
            return
        empty.update(Text(""))
        if st.kind == "batch":
            bar.update(total=max(st.batch_total, 1), progress=st.batch_done)
            counts.update(
                Text(f"batch: {st.batch_done}/{st.batch_total} runs complete  ·  {st.label}")
            )
            return
        if p is not None:
            bar.update(total=100, progress=100 * p.fraction)
            q = Text()
            q.append(f"sim time {p.sim_time:.2f}s / {p.duration:g}s   ")
            q.append(f"events {p.events:,}\n")
            q.append(
                f"arrivals {p.arrivals:,}   departures {p.departures:,}   drops {p.drops:,}   "
                f"queue now {p.queue_len}"
            )
            counts.update(q)
        elif st.record is not None:
            r = st.record
            bar.update(total=100, progress=100)
            m = r.metrics
            counts.update(
                Text(
                    f"sim time {r.config.duration_s:g}s ({r.terminated})   events {r.events_processed:,}\n"
                    f"arrivals {m['arrivals_total']:,}   delivered {m['delivered']:,}   dropped {m['dropped']:,}   "
                    f"unresolved {m['unresolved']:,}"
                )
            )
        else:
            counts.update(Text("starting…", style="dim"))

    def _render_cards(self, m: dict | object | None, cfg) -> None:
        thr, loss, avg, p95, util = (
            self.query_one(f"#c-{k}", MetricCard) for k in ("thr", "loss", "avg", "p95", "util")
        )
        if m is None:
            for c in (thr, loss, avg, p95, util):
                c.set_value("—")
            return
        d = m if isinstance(m, dict) else m.to_dict()
        approx = " (live est.)" if d.get("approximate") else ""
        offered = d["offered_load_mbps"]
        link = cfg.link_mbps if cfg else offered
        target = min(offered, link)  # the most the link could possibly have delivered
        ratio = d["throughput_mbps"] / target if target else 1.0
        thr.set_value(
            fmt.mbps(d["throughput_mbps"]),
            "ok" if ratio >= 0.97 else "warn" if ratio >= 0.85 else "bad",
            f"offered {fmt.mbps(offered)}",
            ("link-limited" if offered > link else "carrying offered load")
            if ratio >= 0.97
            else "below achievable",
        )
        lr = d["loss_rate"]
        if lr is None:
            loss.set_value("—")
        else:
            loss.set_value(
                fmt.pct(lr),
                "ok" if lr <= 0.001 else "warn" if lr <= 0.05 else "bad",
                f"{d['dropped']:,} of {d['generated']:,} pkts",
                "no loss" if lr <= 0.001 else "some loss" if lr <= 0.05 else "heavy loss",
            )
        cap = cfg.queue_capacity if cfg else 1
        svc = cfg.service_time_ms if cfg else 1.0
        full = cap * svc

        def delay_card(card: MetricCard, v: float | None) -> None:
            if v is None:
                card.set_value("—")
                return
            r = v / full if full else 0
            card.set_value(
                fmt.ms(v),
                "ok" if r < 0.25 else "warn" if r < 0.6 else "bad",
                f"buffer-full ≈ {fmt.ms(full)}{approx}",
                "low delay" if r < 0.25 else "building" if r < 0.6 else "standing queue",
            )

        delay_card(avg, d["avg_queue_delay_ms"])
        delay_card(p95, d["p95_queue_delay_ms"])
        u = d["link_utilisation"]
        util.set_value(
            f"{u * 100:.1f}%",
            "ok" if u < 0.85 else "warn" if u < 0.99 else "bad",
            f"queue avg {d['avg_queue_len']:.1f}/{cap}",
            "headroom" if u < 0.85 else "near saturation" if u < 0.99 else "saturated",
        )

    def _render_charts(self, s: dict | None, cfg) -> None:
        ids = ("ch-q", "ch-thr", "ch-d", "ch-drop")
        if not s or not s.get("t"):
            for i in ids:
                self.query_one(f"#{i}", LineChart).clear()
            return
        x_end = s["t"][-1] + s["bin_width_s"] / 2
        w = s["warmup_s"]
        cap = cfg.queue_capacity if cfg else None
        link = cfg.link_mbps if cfg else None
        for cid, key, ymax in (
            ("ch-q", "queue_len", cap),
            ("ch-thr", "throughput_mbps", link),
            ("ch-d", "queue_delay_ms", None),
            ("ch-drop", "loss_pct", None),
        ):
            self.query_one(f"#{cid}", LineChart).set_data(s[key], ymax, x_end, w)
