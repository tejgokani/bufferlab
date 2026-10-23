"""Compare Runs: select several completed runs and compare measured metrics."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Static

from bufferlab.analysis.comparison import COLUMNS
from bufferlab.experiments.models import RunRecord
from bufferlab.tui.screens.base import LabScreen
from bufferlab.tui.screens.history import run_row
from bufferlab.tui.widgets.tables import comparison_view

SORTABLE = [c.key for c in COLUMNS if c.key != "offered_load_mbps"]


class CompareScreen(LabScreen):
    NAME = "compare"
    TITLE_TEXT = "Compare Runs"
    BINDINGS = [
        Binding("space", "mark", "Mark"),
        Binding("s", "sort", "Sort metric"),
        Binding("x", "clear", "Clear marks"),
    ]
    HELP = (
        "Compare Runs\n\nMark two or more runs with Space; the comparison below updates immediately.\n\n"
        "s  cycle the metric used for sorting and for the bar chart\nx  clear all marks\n\n"
        "Observations are generated from the measured numbers only. If the runs differ in anything "
        "other than the algorithm (load, buffer, seed…) the screen says so, because differences can "
        "then not be attributed to the algorithm."
    )

    def body(self) -> ComposeResult:
        yield DataTable(id="tbl", cursor_type="row", zebra_stripes=True, classes="panel")
        with VerticalScroll(classes="panel", id="cmp-panel"):
            yield Static(id="view")

    def on_mount(self) -> None:
        super().on_mount()
        self.sort_idx = SORTABLE.index("p95_queue_delay_ms")
        self.runs: list[RunRecord] = []
        t = self.query_one("#tbl", DataTable)
        t.styles.height = "40%"
        t.add_columns(
            " ",
            "Run ID",
            "When (UTC)",
            "Name",
            "Algorithm",
            "Seed",
            "Throughput",
            "Loss",
            "p95 delay",
            "Batch",
        )

    def on_screen_resume(self) -> None:
        t = self.query_one("#tbl", DataTable)
        self.runs = self.app.repo.list_runs(limit=300)
        t.clear()
        for r in self.runs:
            t.add_row(*run_row(r, r.run_id in self.app.selected_runs), key=r.run_id)
        t.focus()
        self.render_view()

    def render_view(self) -> None:
        by_id = {r.run_id: r for r in self.runs}
        chosen = [by_id[i] for i in self.app.selected_runs if i in by_id]
        self.query_one("#view", Static).update(
            comparison_view(chosen, SORTABLE[self.sort_idx], self.app.ascii_mode)
        )

    def action_mark(self) -> None:
        t = self.query_one("#tbl", DataTable)
        if not self.runs:
            return
        r = self.runs[t.cursor_row]
        sel = self.app.selected_runs
        sel.remove(r.run_id) if r.run_id in sel else sel.append(r.run_id)
        t.update_cell_at(Coordinate(t.cursor_row, 0), "✓" if r.run_id in sel else " ")
        self.render_view()

    def action_sort(self) -> None:
        self.sort_idx = (self.sort_idx + 1) % len(SORTABLE)
        self.render_view()

    def action_clear(self) -> None:
        self.app.selected_runs.clear()
        self.on_screen_resume()
