"""Shared, dependency-free evidence contracts for CUDA Repository Steward."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class State(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Evidence:
    kind: str
    state: State
    source: str
    observed_sha: str = ""
    expected_sha: str = ""
    url: str = ""
    details: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def current(self) -> bool:
        return bool(self.observed_sha and self.expected_sha and self.observed_sha == self.expected_sha)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        value["current"] = self.current
        return value


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    summary: str
    evidence: tuple[str, ...] = ()
    blocking: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["severity"] = self.severity.value
        value["evidence"] = list(self.evidence)
        return value


@dataclass
class Report:
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    repository: str = ""
    findings: list[Finding] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "repository": self.repository,
            "findings": [item.to_dict() for item in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "modules": self.modules,
        }


def parse_state(value: str | None) -> State:
    try:
        return State(value or "unknown")
    except ValueError:
        return State.UNKNOWN
