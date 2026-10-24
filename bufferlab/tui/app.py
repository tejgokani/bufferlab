"""BufferLab Textual application: navigation, settings and background simulation runs."""

from __future__ import annotations

import contextlib
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from textual.app import App, SystemCommand
from textual.binding import Binding
from textual.screen import ModalScreen

from bufferlab import __version__
from bufferlab.core.simulator import Progress
from bufferlab.experiments.batch import BatchResult, BatchSpec, run_batch
from bufferlab.experiments.models import ExperimentConfig, RunRecord
from bufferlab.experiments.runner import run_experiment
from bufferlab.storage import Repository
from bufferlab.tui.keymap import NAV
from bufferlab.tui.screens.modals import TextModal
from bufferlab.utils.logging import get_logger
from bufferlab.utils.paths import settings_path

log = get_logger("tui")

DEFAULT_SETTINGS: dict[str, Any] = {"ascii": False, "theme": "dark", "max_events": 5_000_000}


@dataclass
class RunState:
    status: str = "idle"  # idle | running | done | cancelled | error
    label: str = ""
    config: ExperimentConfig | None = None
    progress: Progress | None = None
    record: RunRecord | None = None
    batch_done: int = 0
    batch_total: int = 0
    events: list[tuple[str, str]] = field(default_factory=list)  # (level, message)
    started: float = 0.0
    finished: float = 0.0
    kind: str = "run"  # run | batch


class BufferLabApp(App):
    TITLE = f"BufferLab {__version__}"
    CSS_PATH = "styles/bufferlab.tcss"
    ENABLE_COMMAND_PALETTE = True
    BINDINGS = [
        *[Binding(n.key, f"goto('{n.screen}')", n.label, show=n.show_in_footer) for n in NAV],
        Binding("escape", "back", "Cancel/Back", show=False),
        Binding("q", "quit_or_back", "Quit/Back"),
        Binding("question_mark", "context_help", "Help?", key_display="?"),
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def __init__(self, repo: Repository | None = None) -> None:
        super().__init__()
        self.repo = repo or Repository()
        self.settings = self._load_settings()
        self.state = RunState()
        self.cancel_event = threading.Event()
        self.selected_runs: list[str] = []  # marked run ids (compare / export)
        self.focus_run_id: str | None = None
        self.last_batch: tuple[BatchSpec, list[RunRecord]] | None = None
        self.pending_config: ExperimentConfig | None = None  # handed to New Experiment
        self._after_run: list[Any] = []

    # -- settings ------------------------------------------------------------------
    def _load_settings(self) -> dict[str, Any]:
        s = dict(DEFAULT_SETTINGS)
        enc = (getattr(sys.stdout, "encoding", None) or "").lower()
        if enc and "utf" not in enc:
            s["ascii"] = True
        with contextlib.suppress(OSError, ValueError):
            s.update(json.loads(settings_path().read_text(encoding="utf-8")))
        return s

    def save_settings(self) -> None:
        try:
            settings_path().write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError as exc:
            self.notify(f"Could not save settings: {exc}", severity="warning")

    @property
    def ascii_mode(self) -> bool:
        return bool(self.settings.get("ascii"))

    def apply_theme(self) -> None:
        self.theme = "textual-light" if self.settings.get("theme") == "light" else "textual-dark"

    # -- screens -------------------------------------------------------------------
    def _screen_classes(self) -> dict[str, Any]:
        from bufferlab.tui.screens.compare import CompareScreen
        from bufferlab.tui.screens.dashboard import DashboardScreen
        from bufferlab.tui.screens.export import ExportScreen
        from bufferlab.tui.screens.help import HelpScreen
        from bufferlab.tui.screens.history import HistoryScreen
        from bufferlab.tui.screens.network import NetworkScreen
        from bufferlab.tui.screens.new_experiment import NewExperimentScreen
        from bufferlab.tui.screens.results import ResultsScreen
        from bufferlab.tui.screens.scenarios import ScenarioScreen
        from bufferlab.tui.screens.settings import SettingsScreen

        return {
            "dashboard": DashboardScreen,
            "new": NewExperimentScreen,
            "scenarios": ScenarioScreen,
            "compare": CompareScreen,
            "history": HistoryScreen,
            "results": ResultsScreen,
            "export": ExportScreen,
            "settings": SettingsScreen,
            "help": HelpScreen,
            "network": NetworkScreen,
        }

    def on_mount(self) -> None:
        for name, cls in self._screen_classes().items():
            self.install_screen(cls(), name)
        self.apply_theme()
        self.push_screen("dashboard")

    def on_unmount(self) -> None:
        self.cancel_event.set()

    def get_system_commands(self, screen):
        yield from super().get_system_commands(screen)
        for n in NAV:
            yield SystemCommand(
                f"Go to {n.label}",
                f"{n.screen} ({n.key.upper()})",
                lambda s=n.screen: self.action_goto(s),
            )

    def current_name(self) -> str:
        return getattr(self.screen, "NAME", "")

    def action_goto(self, name: str) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self.current_name() == name:
            return
        self.switch_screen(name)

    def action_back(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self.current_name() == "dashboard":
            if self.state.status == "running":
                self.cancel_run()
            return
        self.action_goto("dashboard")

    def action_quit_or_back(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self.current_name() == "dashboard":
            self.cancel_event.set()
            self.exit()
        else:
            self.action_goto("dashboard")

    def action_context_help(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        name = self.current_name() or "BufferLab"
        self.push_screen(
            TextModal(f"Help: {name}", getattr(self.screen, "HELP", "No help available."))
        )

    # -- run state -----------------------------------------------------------------
    def log_event(self, level: str, message: str) -> None:
        self.state.events.append((level, f"{datetime.now():%H:%M:%S} {message}"))
        del self.state.events[:-300]

    def broadcast(self) -> None:
        for scr in list(self.screen_stack):
            fn = getattr(scr, "on_run_state", None)
            if fn:
                fn()

    def start_run(self, config: ExperimentConfig, goto: bool = True, after: Any = None) -> bool:
        if self.state.status == "running":
            self.notify(
                "A simulation is already running. Press Esc on the Dashboard to cancel it.",
                severity="warning",
            )
            return False
        report = config.validate()
        if not report.ok:
            self.notify(
                "; ".join(f"{i.field}: {i.message}" for i in report.errors),
                severity="error",
                title="Invalid configuration",
                timeout=8,
            )
            return False
        self.cancel_event = threading.Event()
        self.state = RunState("running", config.name, config, started=time.monotonic())
        self._after_run = [after] if after else []
        self.log_event("info", f"Started '{config.name}' ({config.algorithm}, seed {config.seed})")
        for w in report.warnings:
            self.log_event("warn", f"{w.field}: {w.message}")
        if goto:
            self.action_goto("dashboard")
        self.broadcast()
        self.run_worker(
            lambda: self._run_one(config),
            thread=True,
            group="sim",
            exclusive=True,
            name="simulation",
        )
        return True

    def _run_one(self, config: ExperimentConfig) -> None:
        try:
            rec = run_experiment(
                config, on_progress=self._progress_from_thread, cancel=self.cancel_event
            )
            if rec.terminated != "cancelled":
                self.repo.save_run(rec)
            self._call(self._finish_run, rec)
        except Exception as exc:  # surface any engine/storage failure to the UI
            log.exception("run failed")
            self._call(self._fail, exc)

    def _call(self, fn: Any, *args: Any) -> None:
        with contextlib.suppress(RuntimeError):  # app is shutting down
            self.call_from_thread(fn, *args)

    def _progress_from_thread(self, p: Progress) -> None:
        self._call(self._on_progress, p)

    def _on_progress(self, p: Progress) -> None:
        self.state.progress = p
        self.broadcast()

    def _finish_run(self, rec: RunRecord) -> None:
        st = self.state
        st.finished = time.monotonic()
        st.record = rec
        st.progress = None if rec.terminated == "cancelled" else st.progress
        if rec.terminated == "cancelled":
            st.status = "cancelled"
            self.log_event("warn", "Cancelled; partial results were not saved")
        else:
            st.status = "done"
            self.focus_run_id = rec.run_id
            m = rec.metrics
            self.log_event(
                "ok",
                f"Finished {rec.run_id}: {m['throughput_mbps']:.2f} Mbps, "
                f"{rec.events_processed:,} events in {rec.wall_time_s:.2f}s",
            )
            if rec.terminated == "event_limit":
                self.log_event(
                    "warn", "Stopped at the event limit; metrics cover only the simulated portion"
                )
            self.notify(f"Saved as {rec.run_id}", title="Simulation complete")
        self.broadcast()
        for cb in self._after_run:
            cb(rec)
        self._after_run = []

    def _fail(self, exc: Exception) -> None:
        self.state.status = "error"
        self.log_event("error", f"{type(exc).__name__}: {exc}")
        self.notify(str(exc), severity="error", title="Simulation failed", timeout=10)
        self.broadcast()

    def start_batch(
        self, spec: BatchSpec, goto: str | None = "dashboard", after: Any = None
    ) -> bool:
        if self.state.status == "running":
            self.notify("A simulation is already running.", severity="warning")
            return False
        errs = spec.validate()
        for _f, cfg in spec.points():
            rep = cfg.validate()
            errs += [f"{i.field}: {i.message}" for i in rep.errors]
        if errs:
            self.notify("; ".join(errs[:3]), severity="error", title="Invalid batch", timeout=8)
            return False
        self.cancel_event = threading.Event()
        total = spec.total_runs()
        self.state = RunState(
            "running",
            spec.name,
            spec.base,
            started=time.monotonic(),
            batch_total=total,
            kind="batch",
        )
        self._after_run = [after] if after else []
        self.log_event(
            "info",
            f"Batch '{spec.name}': {len(spec.points())} points x "
            f"{spec.replications} replication(s) = {total} runs",
        )
        if goto:
            self.action_goto(goto)
        self.broadcast()
        self.run_worker(
            lambda: self._run_batch(spec), thread=True, group="sim", exclusive=True, name="batch"
        )
        return True

    def _run_batch(self, spec: BatchSpec) -> None:
        try:

            def on_prog(done: int, total: int, label: str) -> None:
                self._call(self._on_batch_progress, done, total, label)

            result = run_batch(spec, on_prog, self.cancel_event, on_run=self.repo.save_run)
            self._call(self._finish_batch, spec, result)
        except Exception as exc:
            log.exception("batch failed")
            self._call(self._fail, exc)

    def _on_batch_progress(self, done: int, total: int, label: str) -> None:
        self.state.batch_done = done
        self.state.label = label
        self.broadcast()

    def _finish_batch(self, spec: BatchSpec, result: BatchResult) -> None:
        st = self.state
        st.finished = time.monotonic()
        st.status = "cancelled" if result.cancelled else "done"
        runs = result.runs
        self.last_batch = (spec, runs)
        if runs:
            self.focus_run_id = runs[-1].run_id
        self.log_event(
            "warn" if result.cancelled else "ok",
            f"Batch {result.batch_id} {'cancelled' if result.cancelled else 'finished'}: "
            f"{len(runs)} run(s) saved",
        )
        self.notify(f"{len(runs)} runs saved (batch {result.batch_id})", title="Batch complete")
        self.broadcast()
        for cb in self._after_run:
            cb(result)
        self._after_run = []

    def open_compare(self, run_ids: list[str]) -> None:
        self.selected_runs = list(run_ids)
        self.action_goto("compare")

    def cancel_run(self) -> None:
        if self.state.status == "running":
            self.cancel_event.set()
            self.log_event("warn", "Cancellation requested")
            self.broadcast()


def run_tui() -> None:
    BufferLabApp().run()
