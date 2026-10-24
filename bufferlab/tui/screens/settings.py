"""Settings."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, Select, Static, Switch

from bufferlab import SCHEMA_VERSION, __version__
from bufferlab.tui.screens.base import LabScreen
from bufferlab.utils.paths import data_dir, db_path, log_path


class SettingsScreen(LabScreen):
    NAME = "settings"
    TITLE_TEXT = "Settings"
    HELP = (
        "Settings\n\nASCII charts: use '#' and '.' instead of block characters (for terminals or fonts "
        "without Unicode block support).\nTheme: dark or light.\nDefault event limit applies to "
        "newly created configurations."
    )

    def body(self) -> ComposeResult:
        with Vertical(classes="panel"):
            yield Static("Settings", classes="title")
            yield Horizontal(Label("ASCII-only charts"), Switch(id="ascii"), classes="form-row")
            yield Horizontal(
                Label("Theme"),
                Select([("Dark", "dark"), ("Light", "light")], allow_blank=False, id="theme"),
                classes="form-row",
            )
            yield Horizontal(
                Label("Default event limit"), Input(id="max_events"), classes="form-row"
            )
            yield Static(id="about")

    def on_mount(self) -> None:
        super().on_mount()
        s = self.app.settings
        self._init = True
        self.query_one("#ascii", Switch).value = bool(s["ascii"])
        self.query_one("#theme", Select).value = s["theme"]
        self.query_one("#max_events", Input).value = str(s["max_events"])
        self._init = False
        t = Text()
        t.append(f"BufferLab {__version__} (schema {SCHEMA_VERSION})\n", style="bold")
        t.append(
            f"Data folder: {data_dir()}\nDatabase:    {db_path()}\nLog file:    {log_path()}\n"
            f"Saved runs:  {self.app.repo.count_runs()}",
            style="dim",
        )
        self.query_one("#about", Static).update(t)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if not self._init:
            self.app.settings["ascii"] = event.value
            self.app.save_settings()
            self.app.refresh(layout=True)

    def on_select_changed(self, event: Select.Changed) -> None:
        if not self._init and isinstance(event.value, str):
            self.app.settings["theme"] = event.value
            self.app.apply_theme()
            self.app.save_settings()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._init:
            return
        try:
            v = int(event.value)
            if v >= 1000:
                self.app.settings["max_events"] = v
                self.app.save_settings()
        except ValueError:
            pass
