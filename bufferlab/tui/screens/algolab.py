"""Algorithm Lab: explore parameters, run quick trials, save parameter sets."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Label, Select, Static

from bufferlab.algorithms import ALGORITHMS
from bufferlab.experiments.models import RunRecord
from bufferlab.experiments.scenarios import SCENARIOS
from bufferlab.tui import format as fmt
from bufferlab.tui.screens.base import LabScreen
from bufferlab.tui.widgets.forms import ParamEditor, fmt_num

EXPLAIN = {
    "drop-tail": "Drop-Tail: a plain FIFO. When the buffer is full the arriving packet is discarded. "
    "Simple, but a large buffer can hold a long standing queue (high delay) and loss only "
    "starts once the buffer is already full.",
    "red": "RED: keeps an exponentially weighted average of queue length. Below min_th nothing is "
    "dropped; between min_th and max_th arrivals are dropped with a probability rising to max_p; "
    "above max_th everything is dropped. A smaller EWMA weight reacts more slowly to bursts.",
    "codel": "CoDel: ignores queue length and watches each packet's time in the queue (sojourn). If it "
    "stays above target for a whole interval, it starts dropping at the head, speeding up "
    "(interval/sqrt(count)) until delay falls back under target.",
}


class AlgorithmLabScreen(LabScreen):
    NAME = "lab"
    TITLE_TEXT = "Algorithm Lab"
    BINDINGS = [
        Binding("ctrl+r", "run", "Run trial"),
        Binding("ctrl+s", "save", "Save param set"),
        Binding("m", "compare", "Compare trials"),
    ]
    HELP = (
        "Algorithm Lab\n\nPick an algorithm and a base scenario, edit parameters and run a trial "
        "(Ctrl+R). Blank parameters use documented defaults. Each trial is saved like any other "
        "run and appears in the table so parameter settings can be compared (m).\n\n"
        "Ctrl+S saves the current parameter set; reload it from the 'Saved sets' list."
    )

    def __init__(self) -> None:
        super().__init__()
        self.trials: list[RunRecord] = []

    def body(self) -> ComposeResult:
        with Horizontal():
            with VerticalScroll(classes="panel"):
                yield Static("Parameters", classes="title")
                yield Horizontal(
                    Label("Algorithm"),
                    Select(
                        [(a.label, k) for k, a in ALGORITHMS.items()],
                        value="red",
                        allow_blank=False,
                        id="alg",
                    ),
                    classes="form-row",
                )
                yield Horizontal(
                    Label("Base scenario"),
                    Select(
                        [(s.title, k) for k, s in SCENARIOS.items()],
                        value="heavy-congestion",
                        allow_blank=False,
                        id="scn",
                    ),
                    classes="form-row",
                )
                yield Horizontal(
                    Label("Saved sets"),
                    Select([], prompt="(none saved)", id="saved"),
                    classes="form-row",
                )
                yield ParamEditor(id="params")
                with Horizontal(classes="form-row"):
                    yield Button("Run trial (ctrl+r)", id="run", variant="success")
                    yield Button("Save set (ctrl+s)", id="save")
                    yield Button("Compare (m)", id="cmp")
                yield Static(id="explain", classes="muted")
            with Vertical(classes="panel"):
                yield Static("Trials this session", classes="title")
                yield DataTable(id="trials", cursor_type="row", zebra_stripes=True)
                yield Static(id="status")

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#params", ParamEditor).set_algorithm("red")
        t = self.query_one("#trials", DataTable)
        t.add_columns("#", "Alg", "Params", "Thr", "Loss", "Avg dly", "p95 dly")
        self.refresh_explain()

    def on_screen_resume(self) -> None:
        sel = self.query_one("#saved", Select)
        sel.set_options([(n, n) for n in self.app.repo.list_configs("params")])

    def refresh_explain(self) -> None:
        alg = self.query_one("#alg", Select).value
        t = Text(EXPLAIN[alg] + "\n\n")
        t.append(self.query_one("#params", ParamEditor).help_text())
        self.query_one("#explain", Static).update(t)

    def on_select_changed(self, event: Select.Changed) -> None:
        if not isinstance(event.value, str):
            return
        if event.select.id == "alg":
            self.query_one("#params", ParamEditor).set_algorithm(event.value)
            self.call_after_refresh(self.refresh_explain)
        elif event.select.id == "saved":
            d = self.app.repo.list_configs("params").get(event.value)
            if d:
                self.query_one("#alg", Select).value = d["algorithm"]
                self.query_one("#params", ParamEditor).set_algorithm(d["algorithm"], d["params"])
                self.call_after_refresh(self.refresh_explain)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        {"run": self.action_run, "save": self.action_save, "cmp": self.action_compare}[
            event.button.id
        ]()

    def _config(self):
        alg = self.query_one("#alg", Select).value
        scn = self.query_one("#scn", Select).value
        params, errors = self.query_one("#params", ParamEditor).read()
        if errors:
            self.app.notify("; ".join(errors), severity="error", title="Invalid parameters")
            return None
        n = len(self.trials) + 1
        return SCENARIOS[scn].config.replace(
            algorithm=alg, algorithm_params=params, name=f"lab/{scn}/{alg}#{n}"
        )

    def action_run(self) -> None:
        cfg = self._config()
        if cfg is None:
            return
        self.query_one("#status", Static).update(Text(f"running {cfg.name} …", style="cyan"))
        self.app.start_run(cfg, goto=False, after=self._done)

    def _done(self, rec: RunRecord) -> None:
        self.trials.append(rec)
        m = rec.metrics
        p = ", ".join(f"{k}={fmt_num(v)}" for k, v in rec.resolved_params.items()) or "-"
        self.query_one("#trials", DataTable).add_row(
            str(len(self.trials)),
            rec.config.algorithm,
            p,
            fmt.mbps(m["throughput_mbps"]),
            fmt.pct(m["loss_rate"]),
            fmt.ms(m["avg_queue_delay_ms"]),
            fmt.ms(m["p95_queue_delay_ms"]),
        )
        self.query_one("#status", Static).update(Text(f"finished {rec.run_id}", style="green"))

    def action_save(self) -> None:
        alg = self.query_one("#alg", Select).value
        params, errors = self.query_one("#params", ParamEditor).read()
        if errors:
            self.app.notify("; ".join(errors), severity="error")
            return
        name = f"{alg}: " + (" ".join(f"{k}={fmt_num(v)}" for k, v in params.items()) or "defaults")
        self.app.repo.save_config(name, "params", {"algorithm": alg, "params": params})
        self.on_screen_resume()
        self.app.notify(f"Saved parameter set '{name}'")

    def action_compare(self) -> None:
        if len(self.trials) < 2:
            self.app.notify("Run at least two trials first.", severity="warning")
            return
        self.app.open_compare([r.run_id for r in self.trials])
