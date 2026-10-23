"""Reusable form widgets."""

from __future__ import annotations

from itertools import count
from typing import Any

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, Static, Switch

from bufferlab.algorithms import ParamSpec, get_algorithm

_gen = count()


def fmt_num(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


class ParamInput(Input):
    def __init__(self, spec: ParamSpec, value: Any, **kw: Any) -> None:
        placeholder = spec.auto_hint or fmt_num(spec.default)
        super().__init__(
            value="" if value is None else fmt_num(value), placeholder=placeholder, **kw
        )
        self.spec = spec
        self.tooltip = spec.help


class ParamSwitch(Switch):
    def __init__(self, spec: ParamSpec, value: Any, **kw: Any) -> None:
        super().__init__(value=bool(value), **kw)
        self.spec = spec
        self.tooltip = spec.help


class ParamEditor(Vertical):
    """Dynamic inputs for the chosen algorithm's parameters (blank = documented default)."""

    DEFAULT_CSS = "ParamEditor { height: auto; }"

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.algorithm = "drop-tail"

    def set_algorithm(self, key: str, values: dict[str, Any] | None = None) -> None:
        self.algorithm = key
        self.remove_children()
        spec = get_algorithm(key)
        gen = next(_gen)
        widgets: list[Any] = []
        if not spec.params:
            widgets.append(
                Static(Text("No tunable parameters (queue capacity sets the limit).", style="dim"))
            )
        for i, p in enumerate(spec.params):
            v = (values or {}).get(p.name)
            unit = f" ({p.unit})" if p.unit else ""
            w = (
                ParamSwitch(p, v if v is not None else p.default, id=f"pe{gen}-{i}")
                if p.kind == "bool"
                else ParamInput(p, v, id=f"pe{gen}-{i}")
            )
            widgets.append(Horizontal(Label(f"{p.label}{unit}"), w, classes="form-row"))
        self.mount(*widgets)

    def read(self) -> tuple[dict[str, Any], list[str]]:
        """Return (explicit values, parse errors).  Blank inputs are omitted (use defaults)."""
        out: dict[str, Any] = {}
        errors: list[str] = []
        for w in self.query(ParamInput):
            text = w.value.strip()
            if not text:
                continue
            try:
                out[w.spec.name] = int(text) if w.spec.kind == "int" else float(text)
            except ValueError:
                errors.append(f"{w.spec.label}: {text!r} is not a number")
        for w in self.query(ParamSwitch):
            out[w.spec.name] = bool(w.value)
        return out, errors

    def help_text(self) -> Text:
        t = Text()
        for p in get_algorithm(self.algorithm).params:
            t.append(f"{p.label}: ", style="bold")
            t.append(f"{p.help}\n", style="dim")
        return t
