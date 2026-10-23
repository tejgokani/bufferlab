"""New Experiment: validated configuration form with live summary."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static

from bufferlab.algorithms import ALGORITHMS
from bufferlab.core.traffic import TRAFFIC_MODELS
from bufferlab.experiments.models import ExperimentConfig
from bufferlab.experiments.scenarios import SCENARIOS
from bufferlab.tui.screens.base import LabScreen
from bufferlab.tui.widgets.forms import ParamEditor, fmt_num

FIELDS: list[tuple[str, str, type]] = [
    ("name", "Experiment name", str),
    ("link_mbps", "Link bandwidth (Mbps)", float),
    ("packet_size_bytes", "Packet size (bytes)", int),
    ("queue_capacity", "Queue capacity (pkts)", int),
    ("offered_load_pct", "Offered load (% of link)", float),
    ("n_sources", "Traffic sources", int),
    ("duration_s", "Duration (s)", float),
    ("warmup_s", "Warm-up (s)", float),
    ("seed", "Random seed", int),
    ("prop_delay_ms", "Propagation delay (ms)", float),
    ("burst_on_ms", "Burst ON mean (ms)", float),
    ("burst_off_ms", "Burst OFF mean (ms)", float),
]
CUSTOM = "(custom)"


class NewExperimentScreen(LabScreen):
    NAME = "new"
    TITLE_TEXT = "New Experiment"
    BINDINGS = [
        Binding("ctrl+r", "run", "Run"),
        Binding("ctrl+s", "save", "Save config"),
    ]
    HELP = (
        "New Experiment\n\nEvery field is validated live; errors block the run, warnings do not. "
        "Nothing is changed silently: blank algorithm parameters use the documented defaults, "
        "which are shown in the summary.\n\n"
        "Offered load is a percentage of the link capacity and is converted to a packet rate "
        "(pkts/s = load% x capacity / (packet bits)). Delivered throughput is measured, not assumed.\n\n"
        "Warm-up time is excluded from every metric. Same configuration + same seed => identical results.\n\n"
        "Burst ON/OFF only apply to the 'bursty' traffic model.\n\n"
        "Ctrl+R run · Ctrl+S save this configuration under its name · Tab / Shift+Tab move between fields"
    )

    def body(self) -> ComposeResult:
        with Horizontal():
            with VerticalScroll(id="form", classes="panel"):
                yield Static("Configuration", classes="title")
                yield self._row(
                    "Load scenario",
                    Select(
                        [(CUSTOM, CUSTOM)] + [(s.title, k) for k, s in SCENARIOS.items()],
                        value=CUSTOM,
                        allow_blank=False,
                        id="sel-scenario",
                    ),
                )
                yield self._row(
                    "Load saved config", Select([], prompt="(none saved)", id="sel-saved")
                )
                for key, label, _t in FIELDS[:1]:
                    yield self._row(label, Input(id=f"f-{key}"))
                yield self._row(
                    "Algorithm",
                    Select(
                        [(a.label, k) for k, a in ALGORITHMS.items()],
                        value="drop-tail",
                        allow_blank=False,
                        id="sel-alg",
                    ),
                )
                yield self._row(
                    "Traffic model",
                    Select(
                        [(m, m) for m in TRAFFIC_MODELS],
                        value="poisson",
                        allow_blank=False,
                        id="sel-traffic",
                    ),
                )
                for key, label, _t in FIELDS[1:]:
                    yield self._row(label, Input(id=f"f-{key}"))
                yield Static("Algorithm parameters (blank = default)", classes="title")
                yield ParamEditor(id="params")
                yield Static(id="param-help", classes="muted")
                with Horizontal(classes="form-row"):
                    yield Button("Run (ctrl+r)", id="btn-run", variant="success")
                    yield Button("Save config (ctrl+s)", id="btn-save")
                    yield Button("Reset", id="btn-reset")
            with VerticalScroll(id="summary-panel", classes="panel"):
                yield Static("Summary & validation", classes="title")
                yield Static(id="summary")

    @staticmethod
    def _row(label: str, widget: Any) -> Horizontal:
        return Horizontal(Label(label), widget, classes="form-row")

    # ------------------------------------------------------------------------------
    def on_mount(self) -> None:
        super().on_mount()
        self.set_config(ExperimentConfig(name="my-experiment"))

    def on_screen_resume(self) -> None:
        self._reload_saved()
        cfg = self.app.pending_config
        if cfg is not None:
            self.app.pending_config = None
            self.set_config(cfg)

    def _reload_saved(self) -> None:
        sel = self.query_one("#sel-saved", Select)
        names = list(self.app.repo.list_configs("experiment"))
        sel.set_options([(n, n) for n in names])

    def set_config(self, cfg: ExperimentConfig) -> None:
        self._loading = True
        try:
            for key, _label, _t in FIELDS:
                self.query_one(f"#f-{key}", Input).value = fmt_num(getattr(cfg, key))
            self.query_one("#sel-alg", Select).value = cfg.algorithm
            self.query_one("#sel-traffic", Select).value = cfg.traffic_model
            self.query_one("#params", ParamEditor).set_algorithm(
                cfg.algorithm, cfg.algorithm_params
            )
            self.query_one("#sel-scenario", Select).value = (
                cfg.scenario if cfg.scenario in SCENARIOS else CUSTOM
            )
        finally:
            self._loading = False
        self.call_after_refresh(self.refresh_summary)

    def build_config(self) -> tuple[ExperimentConfig | None, list[str]]:
        errors: list[str] = []
        vals: dict[str, Any] = {}
        for key, label, typ in FIELDS:
            text = self.query_one(f"#f-{key}", Input).value.strip()
            if typ is str:
                vals[key] = text or "experiment"
                continue
            try:
                vals[key] = int(text) if typ is int else float(text)
            except ValueError:
                errors.append(
                    f"{label}: {text!r} is not a valid {'whole number' if typ is int else 'number'}"
                )
        alg = self.query_one("#sel-alg", Select).value
        traffic = self.query_one("#sel-traffic", Select).value
        params, perr = self.query_one("#params", ParamEditor).read()
        errors += perr
        if errors:
            return None, errors
        sc = self.query_one("#sel-scenario", Select).value
        return ExperimentConfig(
            algorithm=alg,
            traffic_model=traffic,
            algorithm_params=params,
            scenario=None if sc in (CUSTOM, Select.BLANK) else sc,
            **vals,
        ), []

    def refresh_summary(self) -> None:
        cfg, errors = self.build_config()
        t = Text()
        if cfg is None:
            for e in errors:
                t.append(f"✗ {e}\n", style="red")
            t.append("\nFix the fields above to enable Run.", style="dim")
        else:
            report = cfg.validate()
            for i in report.errors:
                t.append(f"✗ {i.field}: {i.message}\n", style="red")
            for i in report.warnings:
                t.append(f"⚠ {i.field}: {i.message}\n", style="yellow")
            if report.ok and not report.warnings:
                t.append("✓ Configuration is valid\n", style="green")
            elif report.ok:
                t.append("✓ Valid (with warnings)\n", style="green")
            t.append("\n")
            t.append("\n".join(cfg.summary_lines()))
            if report.ok:
                try:
                    r = cfg.resolved_params()
                    t.append("\n\nResolved algorithm parameters:\n", style="bold")
                    t.append("\n".join(f"  {k} = {fmt_num(v)}" for k, v in r.items()) or "  (none)")
                except ValueError:
                    pass
                exp = 2 * cfg.arrival_rate_pps * cfg.duration_s
                t.append(f"\n\n~{exp:,.0f} events expected.", style="dim")
        self.query_one("#summary", Static).update(t)
        self.query_one("#param-help", Static).update(
            self.query_one("#params", ParamEditor).help_text()
        )

    # -- events -------------------------------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        if not getattr(self, "_loading", False):
            self.refresh_summary()

    def on_select_changed(self, event: Select.Changed) -> None:
        if getattr(self, "_loading", False) or event.value is Select.BLANK:
            return
        sid = event.select.id
        if sid == "sel-alg":
            self.query_one("#params", ParamEditor).set_algorithm(event.value)
            self.call_after_refresh(self.refresh_summary)
        elif sid == "sel-scenario" and event.value != CUSTOM:
            cfg, _ = self.build_config()
            alg = cfg.algorithm if cfg else "drop-tail"
            self.set_config(
                SCENARIOS[event.value].config.replace(algorithm=alg, name=f"{event.value}/{alg}")
            )
        elif sid == "sel-saved":
            data = self.app.repo.list_configs("experiment").get(event.value)
            if data:
                self.set_config(ExperimentConfig.from_dict(data))
        else:
            self.refresh_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            self.action_run()
        elif event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-reset":
            self.set_config(ExperimentConfig(name="my-experiment"))

    def action_run(self) -> None:
        cfg, errors = self.build_config()
        if cfg is None:
            self.app.notify("; ".join(errors), severity="error", title="Cannot run", timeout=8)
            return
        self.app.start_run(cfg)

    def action_save(self) -> None:
        cfg, errors = self.build_config()
        if cfg is None:
            self.app.notify("; ".join(errors), severity="error", title="Cannot save")
            return
        self.app.repo.save_config(cfg.name, "experiment", cfg.to_dict())
        self._reload_saved()
        self.app.notify(f"Saved configuration '{cfg.name}'")
