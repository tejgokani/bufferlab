"""Help and About."""

from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from bufferlab import SCHEMA_VERSION, __version__
from bufferlab.tui.keymap import GLOBAL_OTHER, NAV
from bufferlab.tui.screens.base import LabScreen

SECTIONS = [
    ("Dashboard (F2)", "Live metrics, charts and activity for the current or latest simulation."),
    (
        "New Experiment (F3)",
        "Validated form for every simulation parameter; Ctrl+R runs, Ctrl+S saves.",
    ),
    (
        "Scenario Library (F7)",
        "Built-in experiment configurations; run with one or all algorithms.",
    ),
    (
        "My Network (F8)",
        "Measure the network you are on, then simulate its packet loss and throughput at other loads.",
    ),
    (
        "Compare Runs (F4)",
        "Side-by-side metrics, sorting, bars and measured-evidence observations.",
    ),
    ("Experiment History (F5)", "Search, duplicate, rerun and delete saved runs."),
    ("Results Explorer (F9)", "Every metric and time series of one run."),
    ("Export Center (F6)", "CSV, JSON, Markdown and plain-text exports."),
    ("Settings (Ctrl+T)", "ASCII charts, theme, defaults."),
]

ABOUT = (
    "BufferLab analyses packet loss and throughput. It measures the network you are on (ping and a "
    "download test), then runs a discrete-event simulation of that network to predict loss and "
    "throughput at other loads with Drop-Tail, RED or CoDel queues. It is NOT a substitute for a "
    "validated production-network simulator such as ns-3. It does not model TCP congestion control, "
    "retransmissions or multiple hops, and its RED/CoDel implementations are not validated against "
    "any operating-system implementation. Every number shown comes from a simulation run you "
    "executed; scenarios are configurations, not stored results."
)


class HelpScreen(LabScreen):
    NAME = "help"
    TITLE_TEXT = "Help & About"
    HELP = "Press F2 to return to the Dashboard. Every screen has its own help under '?'."

    def body(self) -> ComposeResult:
        with VerticalScroll(classes="panel"):
            yield Static(self.content())

    def content(self) -> Group:
        keys = Table(title="Global keys", show_header=True, expand=False)
        keys.add_column("Key", style="cyan")
        keys.add_column("Action")
        for n in NAV:
            keys.add_row(n.key.upper(), n.label)
        for k, v in GLOBAL_OTHER:
            keys.add_row(k, v)
        sec = Table(title="Sections", show_header=False)
        sec.add_column(style="cyan", no_wrap=True)
        sec.add_column()
        for a, b in SECTIONS:
            sec.add_row(a, b)
        return Group(
            Text(f"BufferLab {__version__}  (result schema {SCHEMA_VERSION})\n", style="bold"),
            Text(ABOUT + "\n"),
            keys,
            Text(""),
            sec,
            Text(
                "\nIn tables: Space marks, Enter opens. In forms: Tab / Shift+Tab move focus.",
                style="dim",
            ),
        )
