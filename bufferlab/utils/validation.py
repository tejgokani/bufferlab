"""Validation result types and text-input parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()}: {self.field}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    def error(self, name: str, message: str) -> None:
        self.issues.append(Issue("error", name, message))

    def warn(self, name: str, message: str) -> None:
        self.issues.append(Issue("warning", name, message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_float(text: str, name: str) -> float:
    try:
        value = float(text.strip())
    except ValueError:
        raise ValueError(f"{name}: {text!r} is not a number") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name}: must be finite")
    return value


def parse_int(text: str, name: str) -> int:
    try:
        return int(text.strip())
    except ValueError:
        raise ValueError(f"{name}: {text!r} is not a whole number") from None
