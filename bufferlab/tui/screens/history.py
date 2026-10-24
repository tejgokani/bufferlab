"""Experiment history: search, mark, open, duplicate, rerun, delete."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input, Static

from bufferlab.experiments.models import RunRecord
from bufferlab.tui import format as fmt
from bufferlab.tui.screens.base import LabScreen
from bufferlab.tui.screens.modals import ConfirmModal


def run_row(r: RunRecord, marked: bool) -> tuple:
    m = r.metrics
    return (
        "✓" if marked else " ",
        r.run_id,
        r.created_at.replace("T", " ")[:16],
        r.config.name,
        r.config.algorithm,
        str(r.config.seed),
        fmt.mbps(m["throughput_mbps"]),
        fmt.pct(m["loss_rate"]),
        fmt.mbps(m["offered_load_mbps"]),
        r.batch_id or "",
    )


class HistoryScreen(LabScreen):
    NAME = "history"
    TITLE_TEXT = "Experiment History"
    BINDINGS = [
        Binding("slash", "search", "Search", key_display="/"),
        Binding("space", "mark", "Mark"),
        Binding("enter", "open", "Open"),
        Binding("c", "compare", "Compare marked"),
        Binding("u", "duplicate", "Duplicate"),
        Binding("r", "rerun", "Rerun"),
        Binding("d", "delete", "Delete"),
        Binding("e", "export", "Export marked"),
    ]
    HELP = (
        "Experiment History\n\nEvery completed run is stored in the local SQLite database.\n\n"
        "/      search by id, name, scenario or algorithm (Esc leaves the box)\n"
        "Space  mark/unmark a run for Compare (F4) and Export (F6)\n"
        "Enter  open in Results Explorer\n"
        "u      duplicate: load the configuration into New Experiment\n"
        "r      rerun with the same seed (identical result expected)\n"
        "d      delete (asks for confirmation)\n"
        "c / e  compare / export the marked runs"
    )

    def body(self) -> ComposeResult:
        with Vertical(classes="panel"):
            yield Input(placeholder="/ search runs…", id="search")
            yield DataTable(id="tbl", cursor_type="row", zebra_stripes=True)
            yield Static(id="status", classes="muted")

    def on_mount(self) -> None:
        super().on_mount()
        t = self.query_one("#tbl", DataTable)
        t.add_columns(
            " ",
            "Run ID",
            "When (UTC)",
            "Name",
            "Algorithm",
            "Seed",
            "Throughput",
            "Loss",
            "Offered",
            "Batch",
        )
        self.runs: list[RunRecord] = []
        self.reload()

    def on_screen_resume(self) -> None:
        self.reload()
        self.query_one("#tbl", DataTable).focus()

    def reload(self) -> None:
        t = self.query_one("#tbl", DataTable)
        keep = t.cursor_row
        q = self.query_one("#search", Input).value.strip() or None
        self.runs = self.app.repo.list_runs(search=q, limit=500)
        t.clear()
        for r in self.runs:
            t.add_row(*run_row(r, r.run_id in self.app.selected_runs), key=r.run_id)
        if self.runs:
            t.move_cursor(row=min(keep, len(self.runs) - 1))
        n = len(self.app.selected_runs)
        self.query_one("#status", Static).update(
            Text(
                f"{len(self.runs)} run(s) shown · {n} marked"
                if self.runs
                else "No saved experiments yet. Run one from the Dashboard (F2/F3) and it will appear here.",
                style="dim",
            )
        )

    def current(self) -> RunRecord | None:
        t = self.query_one("#tbl", DataTable)
        if not self.runs or t.cursor_row >= len(self.runs):
            return None
        return self.runs[t.cursor_row]

    def on_input_changed(self, event: Input.Changed) -> None:
        self.reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#tbl", DataTable).focus()

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_mark(self) -> None:
        r = self.current()
        if not r:
            return
        sel = self.app.selected_runs
        sel.remove(r.run_id) if r.run_id in sel else sel.append(r.run_id)
        t = self.query_one("#tbl", DataTable)
        t.update_cell_at(Coordinate(t.cursor_row, 0), "✓" if r.run_id in sel else " ")
        self.query_one("#status", Static).update(
            Text(f"{len(self.runs)} run(s) shown · {len(sel)} marked", style="dim")
        )

    def action_open(self) -> None:
        r = self.current()
        if r:
            self.app.focus_run_id = r.run_id
            self.app.action_goto("results")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open()

    def action_compare(self) -> None:
        if len(self.app.selected_runs) < 2:
            self.app.notify("Mark at least two runs with Space.", severity="warning")
            return
        self.app.action_goto("compare")

    def action_export(self) -> None:
        if not self.app.selected_runs and self.current():
            self.app.selected_runs = [self.current().run_id]
        self.app.action_goto("export")

    def action_duplicate(self) -> None:
        r = self.current()
        if r:
            self.app.pending_config = r.config.replace(name=f"{r.config.name} (copy)")
            self.app.action_goto("new")

    def action_rerun(self) -> None:
        r = self.current()
        if r:
            self.app.start_run(r.config)

    def action_delete(self) -> None:
        r = self.current()
        if not r:
            return

        def done(yes: bool | None) -> None:
            if yes:
                self.app.repo.delete_run(r.run_id)
                if r.run_id in self.app.selected_runs:
                    self.app.selected_runs.remove(r.run_id)
                self.reload()
                self.app.notify(f"Deleted {r.run_id}")

        self.app.push_screen(
            ConfirmModal(
                f"Delete run {r.run_id} ({r.config.algorithm}, {r.config.name})?\nThis cannot be undone."
            ),
            done,
        )
