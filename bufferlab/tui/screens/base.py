"""Shared screen scaffolding: header, navigation strip, footer."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from bufferlab.tui.keymap import NAV

HELP_FALLBACK = "No contextual help for this screen. Press F1 for the full help."


class LabScreen(Screen):
    NAME = ""
    TITLE_TEXT = ""
    HELP = HELP_FALLBACK

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(self.nav_text(), id="nav")
        yield from self.body()
        yield Footer()

    def body(self) -> ComposeResult:  # pragma: no cover - overridden
        yield Static("")

    def nav_text(self) -> Text:
        t = Text()
        for n in NAV:
            label = f"{n.key.upper().replace('CTRL+', '^')} {n.label}"
            if n.screen == self.NAME:
                t.append(f" {label} ", style="bold reverse cyan")
            else:
                t.append(f" {label} ", style="dim")
        return t

    def on_mount(self) -> None:
        self.sub_title = self.TITLE_TEXT

    @property
    def lab(self):  # the BufferLabApp
        return self.app

    def on_run_state(self) -> None:
        """Called when the app's run state changes; override as needed."""
