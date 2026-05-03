from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["critical", "high", "medium", "low"]
LineKind = Literal["context", "added", "removed"]
AgentCategory = Literal["security", "performance", "quality"]

SEVERITIES: tuple[Severity, ...] = ("critical", "high", "medium", "low")
SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


@dataclass(slots=True)
class ChangedFile:
    filename: str
    patch: str | None
    additions: int = 0
    deletions: int = 0
    status: str = "modified"


@dataclass(slots=True)
class DiffLine:
    kind: LineKind
    content: str
    new_line: int | None = None
    old_line: int | None = None

    @property
    def display_line(self) -> int | None:
        return self.old_line if self.kind == "removed" else self.new_line


@dataclass(slots=True)
class DiffChunk:
    file_path: str
    language: str
    start_line: int
    end_line: int
    patch: str
    lines: list[DiffLine] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    token_estimate: int = 0

    def changed_line_numbers(self) -> list[int]:
        added_lines = [line.new_line for line in self.lines if line.kind == "added" and line.new_line]
        if added_lines:
            return added_lines
        return [line.new_line for line in self.lines if line.new_line]

    def contains_line(self, line_number: int) -> bool:
        return any(line.new_line == line_number for line in self.lines if line.new_line)

    def nearest_line(self, line_number: int | None = None) -> int:
        valid_lines = self.changed_line_numbers()
        if not valid_lines:
            return max(self.start_line, 1)
        if line_number is None:
            return valid_lines[0]
        return min(valid_lines, key=lambda candidate: abs(candidate - line_number))


@dataclass(slots=True)
class Finding:
    file: str
    line: int
    severity: Severity
    category: AgentCategory
    issue: str
    suggestion: str
    confidence: float | None = None
    source_agent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}


@dataclass(slots=True)
class ReviewStats:
    files_reviewed: int = 0
    chunks_reviewed: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    tokens_estimated: int = 0
    model: str = "google/gemma-3-1b-it"
    cost_per_1k_tokens: float = 0.0001
    elapsed_seconds: float = 0.0

    @property
    def estimated_cost(self) -> float:
        return (self.tokens_estimated / 1000) * self.cost_per_1k_tokens

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["estimated_cost"] = self.estimated_cost
        return data


@dataclass(slots=True)
class ReviewResult:
    summary: str
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    findings: list[Finding] = field(default_factory=list)
    stats: ReviewStats = field(default_factory=ReviewStats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "findings": [finding.to_dict() for finding in self.findings],
            "stats": self.stats.to_dict(),
        }


def normalize_severity(value: Any, default: Severity = "low") -> Severity:
    normalized = str(value or default).strip().lower()
    return normalized if normalized in SEVERITY_RANK else default


def count_findings(findings: list[Finding]) -> dict[str, int]:
    return {severity: sum(1 for finding in findings if finding.severity == severity) for severity in SEVERITIES}
