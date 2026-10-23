"""Scenario library."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Select, Static

from bufferlab.algorithms import ALGORITHMS
from bufferlab.experiments.batch import BatchSpec
from bufferlab.experiments.scenarios import SCENARIOS
from bufferlab.tui.screens.base import LabScreen


class ScenarioScreen(LabScreen):
    NAME = "scenarios"
    TITLE_TEXT = "Scenario Library"
    BINDINGS = [
        Binding("enter", "load", "Edit in form"),
        Binding("r", "run", "Run"),
        Binding("c", "run_all", "Run all 3 + compare"),
    ]
    HELP = (
        "Scenario Library\n\nScenarios are experiment configurations, not stored results. Every run "
        "executes the simulator with the algorithm chosen below.\n\n"
        "Enter  load the scenario into the New Experiment form\n"
        "r      run the highlighted scenario with the chosen algorithm\n"
        "c      run it with Drop-Tail, RED and CoDel (same seed, same traffic) and open Compare"
    )

    def body(self) -> ComposeResult:
        with Horizontal():
            with Vertical(classes="panel"):
                yield Static("Scenarios", classes="title")
                yield DataTable(id="tbl", cursor_type="row", zebra_stripes=True)
                yield Select(
                    [(a.label, k) for k, a in ALGORITHMS.items()],
                    value="drop-tail",
                    allow_blank=False,
                    id="alg",
                )
            with Vertical(classes="panel"):
                yield Static("Details", classes="title")
                yield Static(id="detail")

    def on_mount(self) -> None:
        super().on_mount()
        t = self.query_one("#tbl", DataTable)
        t.add_columns("Scenario", "Link", "Load", "Buffer", "Traffic", "Run")
        for k, s in SCENARIOS.items():
            c = s.config
            t.add_row(
                s.title,
                f"{c.link_mbps:g} Mbps",
                f"{c.offered_load_pct:g}%",
                f"{c.queue_capacity}",
                f"{c.traffic_model}×{c.n_sources}",
                f"{c.duration_s:g}s",
                key=k,
            )
        t.focus()
        self.show_detail()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.show_detail()

    def selected_key(self) -> str:
        t = self.query_one("#tbl", DataTable)
        return list(SCENARIOS)[t.cursor_row]

    def show_detail(self) -> None:
        s = SCENARIOS[self.selected_key()]
        txt = Text()
        txt.append(f"{s.title}\n", style="bold cyan")
        txt.append(f"{s.description}\n\n")
        txt.append("\n".join(s.config.summary_lines()))
        txt.append("\n\nThese are inputs, not predicted results.", style="dim")
        self.query_one("#detail", Static).update(txt)

    def _cfg(self):
        alg = self.query_one("#alg", Select).value
        key = self.selected_key()
        return SCENARIOS[key].config.replace(algorithm=alg, name=f"{key}/{alg}")

    def action_load(self) -> None:
        self.app.pending_config = self._cfg()
        self.app.action_goto("new")

    def action_run(self) -> None:
        self.app.start_run(self._cfg())

    def action_run_all(self) -> None:
        key = self.selected_key()
        base = SCENARIOS[key].config
        spec = BatchSpec(key, base, {"algorithm": list(ALGORITHMS)}, 1)
        self.app.start_batch(
            spec,
            goto="dashboard",
            after=lambda res: self.app.open_compare([r.run_id for r in res.runs]),
        )
