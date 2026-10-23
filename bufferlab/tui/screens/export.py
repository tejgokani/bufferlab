"""Export Center."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Select, Static

from bufferlab.analysis.reporting import FORMATS, export_batch, export_runs
from bufferlab.tui.screens.base import LabScreen
from bufferlab.utils.paths import exports_dir

FORMAT_LABELS = {
    "csv": "CSV (one row per run)",
    "json": "JSON (full, with time series)",
    "md": "Markdown report",
    "txt": "Plain-text report",
}


class ExportScreen(LabScreen):
    NAME = "export"
    TITLE_TEXT = "Export Center"
    BINDINGS = [Binding("ctrl+e", "export", "Export")]
    HELP = (
        "Export Center\n\nChoose what to export and the format, then press Ctrl+E.\n\n"
        "Sources: the runs marked in History/Compare, the run currently open in Results, every saved "
        "run, or a stored batch (which produces the methodology/results/limitations report).\n\n"
        "Exports include the configuration, seed, resolved algorithm parameters, software version and "
        "schema version needed to reproduce the run."
    )

    def body(self) -> ComposeResult:
        with Vertical(classes="panel"):
            yield Static("Export", classes="title")
            yield Horizontal(
                Label("What"),
                Select([("All saved runs", "all")], id="what", allow_blank=False),
                classes="form-row",
            )
            yield Horizontal(
                Label("Format"),
                Select(
                    [(FORMAT_LABELS[f], f) for f in FORMATS],
                    value="csv",
                    allow_blank=False,
                    id="fmt",
                ),
                classes="form-row",
            )
            yield Horizontal(Label("Output file"), Input(id="path"), classes="form-row")
            yield Button("Export (ctrl+e)", id="go", variant="success")
            yield Static(id="msg")
            yield Static(Text(f"Default folder: {exports_dir()}", style="dim"))

    def on_screen_resume(self) -> None:
        what = self.query_one("#what", Select)
        opts = []
        n = len(self.app.selected_runs)
        if n:
            opts.append((f"Marked runs ({n})", "marked"))
        if self.app.focus_run_id:
            opts.append((f"Open run ({self.app.focus_run_id})", "focus"))
        opts.append(("All saved runs", "all"))
        for b in self.app.repo.list_batches():
            opts.append(
                (
                    f"Batch {b['batch_id']} · {b['name']} ({b['n_runs']} runs)",
                    f"batch:{b['batch_id']}",
                )
            )
        what.set_options(opts)
        what.value = opts[0][1]
        self.update_path()

    def on_select_changed(self, event: Select.Changed) -> None:
        self.update_path()

    def update_path(self) -> None:
        what = self.query_one("#what", Select).value
        fmt = self.query_one("#fmt", Select).value
        if what is Select.BLANK or fmt is Select.BLANK:
            return
        stem = {
            "marked": "runs-marked",
            "focus": str(self.app.focus_run_id),
            "all": "runs-all",
        }.get(what, what.replace(":", "-") if what.startswith("batch:") else "export")
        self.query_one("#path", Input).value = str(exports_dir() / f"{stem}.{fmt}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_export()

    def action_export(self) -> None:
        what = self.query_one("#what", Select).value
        fmt = self.query_one("#fmt", Select).value
        path = Path(self.query_one("#path", Input).value.strip()).expanduser()
        msg = self.query_one("#msg", Static)
        try:
            repo = self.app.repo
            if isinstance(what, str) and what.startswith("batch:"):
                spec, runs = repo.get_batch(what[6:])
                out = export_batch(spec, runs, fmt, path)
            else:
                ids = (
                    self.app.selected_runs
                    if what == "marked"
                    else [self.app.focus_run_id]
                    if what == "focus"
                    else [r.run_id for r in repo.list_runs()]
                )
                runs = [repo.get_run(i) for i in ids]
                out = export_runs(runs, fmt, path)
            msg.update(Text(f"✓ wrote {out}", style="green"))
        except (OSError, ValueError, LookupError) as exc:
            msg.update(Text(f"✗ {exc}", style="red"))
