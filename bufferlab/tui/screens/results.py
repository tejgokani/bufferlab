"""Results Explorer: full metrics, configuration and time series of one run."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Select, Static

from bufferlab.storage import NotFoundError
from bufferlab.tui.screens.base import LabScreen
from bufferlab.tui.widgets.charts import LineChart
from bufferlab.tui.widgets.tables import metrics_table


class ResultsScreen(LabScreen):
    NAME = "results"
    TITLE_TEXT = "Results Explorer"
    HELP = (
        "Results Explorer\n\nChoose any saved run to see every metric, its configuration (including "
        "resolved algorithm parameters, seed and software version) and its time series.\n\n"
        "Time-series bins cover the whole run including warm-up (shown dim); summary metrics exclude "
        "warm-up. Queue delay is queueing delay only — not RTT."
    )

    def body(self) -> ComposeResult:
        yield Select([], prompt="Choose a run…", id="pick")
        with Horizontal():
            with VerticalScroll(classes="panel", id="left"):
                yield Static(
                    "No run selected. Run a simulation (F3) or open one from History (F5).",
                    id="info",
                )
            with Vertical(id="right"):
                yield LineChart("Queue occupancy (pkts)", " pkts", "cyan", id="r-q")
                yield LineChart("Throughput (Mbps)", " Mbps", "green", id="r-thr")
                yield LineChart("Queueing delay (ms)", " ms", "yellow", id="r-d")
                yield LineChart("Drops per bin", "", "red", agg="sum", id="r-drop")

    def on_mount(self) -> None:
        super().on_mount()
        self._loading = False
        self.query_one("#left").styles.width = "45%"

    def on_screen_resume(self) -> None:
        sel = self.query_one("#pick", Select)
        runs = self.app.repo.list_runs(limit=200)
        self._loading = True
        sel.set_options(
            [(f"{r.run_id}  {r.config.algorithm:<9} {r.config.name}", r.run_id) for r in runs]
        )
        want = self.app.focus_run_id
        if want and any(r.run_id == want for r in runs):
            sel.value = want
        self._loading = False
        if want:
            self.load(want)

    def on_select_changed(self, event: Select.Changed) -> None:
        if not self._loading and event.value is not Select.BLANK:
            self.app.focus_run_id = event.value
            self.load(event.value)

    def load(self, run_id: str) -> None:
        try:
            rec = self.app.repo.get_run(run_id)
        except NotFoundError:
            return
        head = Text(
            f"{rec.run_id}  ·  {rec.created_at}  ·  v{rec.software_version} (schema {rec.schema_version})\n",
            style="dim",
        )
        cfg = Text("\n".join(rec.config.summary_lines()) + "\n\n")
        self.query_one("#info", Static).update(Group(head, cfg, metrics_table(rec)))
        s = rec.series
        if s.get("t"):
            x_end = s["t"][-1] + s["bin_width_s"] / 2
            cap, link = rec.config.queue_capacity, rec.config.link_mbps
            for cid, key, ymax in (
                ("r-q", "queue_len", cap),
                ("r-thr", "throughput_mbps", link),
                ("r-d", "queue_delay_ms", None),
                ("r-drop", "drops", None),
            ):
                self.query_one(f"#{cid}", LineChart).set_data(s[key], ymax, x_end, s["warmup_s"])
