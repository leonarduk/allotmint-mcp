"""Data models for the eval runner.

These are deliberately decoupled from the HTTP API models (`models.py`) so
eval expectations can be stricter than the response contract and can change
without affecting the Java/HTTP boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalCase:
    """One test case in an eval set.

    `id` is a short slug used in reports. `question` and `owner` are the
    request fields. `expect` captures the pass/fail predicates.
    """

    id: str
    question: str
    owner: str | None = None
    lookback_days: int = 365
    expect: Expectation = field(default_factory=lambda: Expectation())


@dataclass
class Expectation:
    """Programmatic pass/fail predicates for one eval case.

    Every field is optional; absent fields are not checked. All checks are
    simple: booleans, list membership, substring containment. Nothing here
    requires subjective judgment.

    ``needs_review`` means the guardrail *should* flag this answer (used
    for adversarial cases). ``tools_called`` checks that every named tool
    appeared at least once in the recorded calls.
    """

    grounded: bool | None = None
    needs_review: bool | None = None
    tools_called: list[str] = field(default_factory=list)
    tools_not_called: list[str] = field(default_factory=list)
    citations_min: int | None = None
    answer_contains: list[str] = field(default_factory=list)
    answer_not_contains: list[str] = field(default_factory=list)
    warnings_contain: list[str] = field(default_factory=list)
    review_reasons_contain: list[str] = field(default_factory=list)


@dataclass
class EvalCaseResult:
    """The verdict for one eval case after running it.

    ``passed`` means every expectation was met. ``detail`` records which checks
    failed and why — always concrete, never hand-wavy.
    """

    case_id: str
    passed: bool = False
    skipped: bool = False
    skip_reason: str = ""
    detail: list[str] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None
    runtime_ms: float = 0.0


@dataclass
class EvalRunReport:
    """Aggregate report after running a full eval set."""

    set_name: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[EvalCaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        effective = self.total - self.skipped
        return self.passed / effective if effective > 0 else 0.0
