"""Single source of truth for global navigation keys (no duplicates allowed; see tests)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Nav:
    key: str
    screen: str
    label: str
    show_in_footer: bool = True


NAV: tuple[Nav, ...] = (
    Nav("f1", "help", "Help"),
    Nav("f2", "dashboard", "Dashboard"),
    Nav("f3", "new", "New"),
    Nav("f4", "compare", "Compare"),
    Nav("f5", "history", "History"),
    Nav("f6", "export", "Export"),
    Nav("f7", "scenarios", "Scenarios", False),
    Nav("f8", "lab", "Algo Lab", False),
    Nav("f9", "results", "Results", False),
    Nav("f10", "research", "Research", False),
    Nav("ctrl+t", "settings", "Settings", False),
)

#: Other global keys.
GLOBAL_OTHER = (
    ("?", "Contextual help"),
    ("q", "Quit (Dashboard) / back to Dashboard"),
    ("Esc", "Cancel a running simulation / go back"),
    ("Ctrl+Q", "Quit immediately"),
    ("Ctrl+P", "Command palette"),
)
