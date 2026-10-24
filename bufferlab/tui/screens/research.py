"""Research Mode: experiment matrices with replications and a generated report."""

from __future__ import annotations

from typing import Any

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from bufferlab.algorithms import ALGORITHMS
from bufferlab.analysis.reporting import batch_report, export_batch
from bufferlab.experiments.batch import BatchSpec, research_matrix
from bufferlab.experiments.scenarios import SCENARIOS
from bufferlab.tui.screens.base import LabScreen
from bufferlab.utils.paths import exports_dir

QUESTIONS: dict[str, dict[str, Any]] = {
    "load": {
        "label": "How does offered load affect queueing delay?",
        "objective": "Measure how offered load (50-150% of link capacity) changes queueing delay under each algorithm.",
        "loads": "50,75,100,125,150",
        "caps": "50",
        "reps": 5,
    },
    "capacity": {
        "label": "Does queue capacity affect packet-loss rate?",
        "objective": "Measure how buffer size (small/medium/large) changes packet-loss rate at fixed offered load.",
        "loads": "110",
        "caps": "10,50,250",
        "reps": 5,
    },
    "tradeoff": {
        "label": "How does AQM influence the delay-throughput trade-off?",
        "objective": "Compare delivered throughput against queueing delay for Drop-Tail, RED and CoDel across loads.",
        "loads": "75,100,125,150",
        "caps": "250",
        "reps": 5,
    },
    "best": {
        "label": "Under which traffic conditions does an algorithm perform best?",
        "objective": "Identify, per load/buffer condition, which algorithm had the lowest p95 queueing delay and loss.",
        "loads": "50,75,100,125,150",
        "caps": "10,50,250",
        "reps": 5,
    },
    "variance": {
        "label": "How sensitive are results to random traffic variation?",
        "objective": "Quantify run-to-run variability (std. dev. and 95% CI) across many seeds at one operating point.",
        "loads": "100",
        "caps": "50",
        "reps": 15,
    },
}


class ResearchScreen(LabScreen):
    NAME = "research"
    TITLE_TEXT = "Research Mode"
    BINDINGS = [Binding("ctrl+r", "run", "Run matrix"), Binding("ctrl+w", "write", "Write report")]
    HELP = (
        "Research Mode\n\nBuilds a full-factorial matrix: algorithms x offered load (% of link "
        "capacity, converted to packet rates) x queue capacity, with N independent replications "
        "(seeds base, base+1, ...). Replication k uses the same traffic for every algorithm.\n\n"
        "Choosing a research question pre-fills sensible factors (you can edit them). Ctrl+R runs "
        "the matrix on the Dashboard; the report appears here when it finishes. Ctrl+W writes it to "
        "the exports folder in the chosen format.\n\n"
        "The report's observations are automated interpretations of the measurements, not verified "
        "scientific conclusions. Confidence intervals show run-to-run variation, not significance."
    )

    def body(self) -> ComposeResult:
        with Horizontal():
            with VerticalScroll(classes="panel", id="rform"):
                yield Static("Experiment matrix", classes="title")
                yield Horizontal(
                    Label("Research question"),
                    Select(
                        [(q["label"], k) for k, q in QUESTIONS.items()],
                        value="load",
                        allow_blank=False,
                        id="q",
                    ),
                    classes="form-row",
                )
                yield Horizontal(
                    Label("Base scenario"),
                    Select(
                        [(s.title, k) for k, s in SCENARIOS.items()],
                        value="approaching-saturation",
                        allow_blank=False,
                        id="scn",
                    ),
                    classes="form-row",
                )
                for k, a in ALGORITHMS.items():
                    yield Checkbox(a.label, True, id=f"alg-{k}")
                yield Horizontal(
                    Label("Offered load (% cap.)"), Input(id="loads"), classes="form-row"
                )
                yield Horizontal(
                    Label("Queue capacities (pkts)"), Input(id="caps"), classes="form-row"
                )
                yield Horizontal(Label("Replications"), Input(id="reps"), classes="form-row")
                yield Horizontal(Label("Duration (s)"), Input("20", id="dur"), classes="form-row")
                yield Horizontal(Label("Warm-up (s)"), Input("4", id="warm"), classes="form-row")
                yield Horizontal(Label("Base seed"), Input("1", id="seed"), classes="form-row")
                yield Horizontal(
                    Label("Report format"),
                    Select(
                        [
                            ("Markdown", "md"),
                            ("Plain text", "txt"),
                            ("JSON", "json"),
                            ("CSV", "csv"),
                        ],
                        value="md",
                        allow_blank=False,
                        id="fmt",
                    ),
                    classes="form-row",
                )
                with Horizontal(classes="form-row"):
                    yield Button("Run (ctrl+r)", id="run", variant="success")
                    yield Button("Write report (ctrl+w)", id="write")
                yield Static(id="plan")
            with VerticalScroll(classes="panel", id="rreport"):
                yield Static(
                    Text("Run a matrix to generate a report here.", style="dim"), id="report"
                )

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_question("load")
        self.query_one("#rform").styles.width = "50%"

    def on_screen_resume(self) -> None:
        self.show_report()

    def _apply_question(self, key: str) -> None:
        q = QUESTIONS[key]
        self.query_one("#loads", Input).value = q["loads"]
        self.query_one("#caps", Input).value = q["caps"]
        self.query_one("#reps", Input).value = str(q["reps"])

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "q" and isinstance(event.value, str):
            self._apply_question(event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.refresh_plan()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self.refresh_plan()

    def build_spec(self) -> tuple[BatchSpec | None, str]:
        try:
            algs = [k for k in ALGORITHMS if self.query_one(f"#alg-{k}", Checkbox).value]
            if not algs:
                return None, "select at least one algorithm"
            loads = [
                float(x) for x in self.query_one("#loads", Input).value.split(",") if x.strip()
            ]
            caps = [int(x) for x in self.query_one("#caps", Input).value.split(",") if x.strip()]
            reps = int(self.query_one("#reps", Input).value)
            dur = float(self.query_one("#dur", Input).value)
            warm = float(self.query_one("#warm", Input).value)
            seed = int(self.query_one("#seed", Input).value)
        except ValueError as exc:
            return None, f"invalid number ({exc})"
        if not loads or not caps:
            return None, "give at least one load and one capacity"
        qkey = self.query_one("#q", Select).value
        scn = self.query_one("#scn", Select).value
        base = SCENARIOS[scn].config.replace(
            duration_s=dur, warmup_s=warm, seed=seed, name="research"
        )
        spec = research_matrix(
            base,
            algorithms=algs,
            load_pcts=loads,
            capacities=caps,
            replications=reps,
            name=f"research-{qkey}",
            objective=QUESTIONS[qkey]["objective"],
        )
        spec.base_seed = seed
        return spec, ""

    def refresh_plan(self) -> None:
        spec, err = self.build_spec()
        plan = self.query_one("#plan", Static)
        if spec is None:
            plan.update(Text(f"✗ {err}", style="red"))
            return
        pts, n = len(spec.points()), spec.total_runs()
        plan.update(
            Text(
                f"{pts} points × {spec.replications} replication(s) = {n} runs "
                f"(about {n * spec.base.duration_s * 0.01:.0f}s at typical speeds)",
                style="dim",
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_run() if event.button.id == "run" else self.action_write()

    def action_run(self) -> None:
        spec, err = self.build_spec()
        if spec is None:
            self.app.notify(err, severity="error", title="Invalid matrix")
            return
        self.app.start_batch(
            spec, goto="dashboard", after=lambda res: self.app.action_goto("research")
        )

    def show_report(self) -> None:
        lb = self.app.last_batch
        w = self.query_one("#report", Static)
        if not lb or not lb[1]:
            return
        spec, runs = lb
        w.update(Markdown(batch_report(spec, runs).to_markdown()))

    def action_write(self) -> None:
        lb = self.app.last_batch
        if not lb or not lb[1]:
            self.app.notify("Run a matrix first.", severity="warning")
            return
        spec, runs = lb
        fmt = self.query_one("#fmt", Select).value
        out = export_batch(spec, runs, fmt, exports_dir() / f"{spec.name}.{fmt}")
        self.app.notify(f"Wrote {out}", title="Report written", timeout=8)
