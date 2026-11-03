"""Numeric provenance: does every figure in the answer appear in a source?

`grounded` used to mean only "retrieval or a tool call happened". That says
nothing about the answer's numbers: a model can call `allotmint_portfolio`,
receive a total of 10983.67, and then write "£7,403,919" around it (#692).
This module is the deterministic check between answer generation and the
guardrail review. It never calls an LLM and knows nothing about the provider,
so it behaves identically under ollama, deepseek, or any OpenAI-compatible
model.

The rules, all deliberately simple so a reviewer can predict the verdict:

**What counts as a figure in the answer.** A numeric literal with an optional
leading currency symbol (``£ $ €``), thousands separators (``10,983.67``), a
decimal part, a magnitude suffix (``k``, ``m``/``mn``/``million``,
``bn``/``billion``, ``tn``/``trillion``, ``thousand``) and/or a trailing
``%``/``percent``. Leading signs are ignored: "fell 2.5%" and a source value
of ``-2.5`` are the same magnitude.

**What is ignored** (not a magnitude claim, so never checked):

* citation markers -- ``[1]``, ``[1, 2]``, ``[tool:allotmint_portfolio]``;
* dates and times -- ISO dates/timestamps (``2026-08-01``), numeric dates
  (``14/05/2026``), month-name dates (``14 May 2026``, ``May 14, 2026``),
  clock times (``09:30``);
* years -- a bare integer from 1900 to 2100 (no currency, %, decimals,
  separators or suffix);
* list ordinals -- ``1.`` / ``2)`` at the start of a line, and ordinal words
  like ``2nd`` (a digit glued to letters is never a figure, which also skips
  tickers and identifiers such as ``Q1`` or ``FY2025``);
* index names -- the number in ``FTSE 100``, ``S&P 500`` and similar;
* small bare counts -- a bare integer below 10 ("top 3", "2 sectors");
* time spans -- a bare integer followed by a time unit ("past 12 months",
  "30 days").

**When a figure matches a source.** Source text is every retrieved document,
every recorded tool response (the full text the model saw, not the 400-char
citation excerpt), and the tool returns from earlier turns of the same
conversation. The user's question is deliberately *not* a source: a user asking
"is it £7m?" must not make an answer that says £7m look verified. Neither is
anything the model itself wrote in an earlier turn. Every numeric literal in that text is parsed
the same way (thousands separators, decimals, scientific notation, magnitude
suffixes). An answer figure matches when some source value rounds to it at the
precision the answer displays: ``|source - answer| <= half a unit of the
answer's last digit``. So ``51.93`` matches a source ``51.9312``, ``£10,983.67``
and ``£10.98k`` both match ``10983.67``, and ``27%`` matches ``27.0``. A
percentage additionally matches the equivalent fraction (``51.93%`` matches a
source ``0.5193``). An answer that is *more* precise than any source
(``27.04%`` against ``27.0``) does not match -- that precision was invented.

**Sums and differences of two source values pass.** A figure that is not a
literal in any source still matches when it equals ``a + b`` or ``|a - b|``
for two source values, within the same rounding tolerance -- so "up 9.0
points" from a weight of 18.0 to 27.0, or two sector weights added together,
stay grounded. These are bounded, additive derivations, so they cannot turn
small source numbers into a fabricated large one (the #692 £7,403,919 against
a £10,983.67 portfolio still fails).

**Ratios and relative changes do not pass yet.** "Technology grew 22.7%" from
a weight of 5.5 to 6.75 is a ratio. Ratios over a few hundred source numbers
are dense enough that almost any percentage would find a matching pair, which
would wave fabrications through, so they are reported as unverified. Tracing
the arithmetic the answer actually states is the follow-up.

**Known limit.** A real number attached to the wrong label (a Global Equity
weight quoted as the technology weight) passes, because the literal does exist
in a source. This check catches invented magnitudes, not misattribution.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .models import RetrievedDocument, ToolCallRecord

# How many unverified figures an answer may carry and still be `grounded`:
# grounded is false when `len(unverified) > UNVERIFIED_FIGURES_TOLERATED`.
# Zero tolerated: any invented magnitude about someone's own money is enough to
# stop the answer being presented as checked.
UNVERIFIED_FIGURES_TOLERATED = 0

_MULTIPLIERS: dict[str, Decimal] = {
    "k": Decimal(10) ** 3,
    "thousand": Decimal(10) ** 3,
    "m": Decimal(10) ** 6,
    "mn": Decimal(10) ** 6,
    "million": Decimal(10) ** 6,
    "bn": Decimal(10) ** 9,
    "billion": Decimal(10) ** 9,
    "tn": Decimal(10) ** 12,
    "trillion": Decimal(10) ** 12,
}
_SUFFIX = r"(?:thousand|million|billion|trillion|mn|bn|tn|k|m)"
_GROUPED = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"
_PLAIN = r"\d+(?:\.\d+)?"

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)

# Spans blanked out of the answer before figures are extracted.
_IGNORED_SPANS = [
    # Citation markers: [1], [1, 2], [1-3], [tool:allotmint_portfolio]
    re.compile(r"\[(?:\d+(?:\s*[,–-]\s*\d+)*|tool:[a-z_]+)\]", re.IGNORECASE),
    # ISO dates and timestamps
    re.compile(
        r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
        r"(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    ),
    # Numeric dates: 14/05/2026, 14.05.26
    re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"),
    # Month-name dates: 14 May 2026, 14th of May, May 14, 2026
    re.compile(
        rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b\.?(?:,?\s+\d{{4}})?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+\d{{4}})?", re.IGNORECASE
    ),
    # Clock times
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),
    # Numbered-list ordinals at the start of a line: "1. ", "2) "
    re.compile(r"(?m)^\s*\d+[.)]\s+"),
    # Index names whose number is part of the name
    re.compile(
        r"(?:\bFTSE|\bS&P|\bSTOXX|\bRussell|\bNikkei|\bASX|\bDAX|\bCAC|\bNasdaq)\s+\d+\b",
        re.IGNORECASE,
    ),
]

_ANSWER_FIGURE = re.compile(
    rf"(?<![\w.,])(?P<cur>[£$€])?\s?(?P<num>{_GROUPED}|{_PLAIN})"
    rf"(?:\s?(?P<suf>{_SUFFIX})(?![a-z]))?"
    r"(?P<pct>\s?(?:%|per\s?cent\b))?"
    r"(?![\w])",
    re.IGNORECASE,
)
_TIME_UNIT_AFTER = re.compile(
    r"\s*-?\s*(?:day|week|month|year|quarter|hour|minute)s?\b", re.IGNORECASE
)

_SOURCE_NUMBER = re.compile(
    rf"(?P<num>{_GROUPED}|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    rf"(?:\s?(?P<suf>{_SUFFIX})(?![a-z]))?",
    re.IGNORECASE,
)
_SOURCE_PLAIN = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


@dataclass(frozen=True)
class Figure:
    """One magnitude claimed by the answer."""

    text: str
    value: Decimal
    unit: Decimal
    percent: bool


def extract_figures(answer: str) -> list[Figure]:
    """Returns the magnitude claims in `answer`, skipping the ignored kinds."""
    text = answer
    for pattern in _IGNORED_SPANS:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)

    figures: list[Figure] = []
    for match in _ANSWER_FIGURE.finditer(text):
        figure = _to_figure(match, text)
        if figure is not None:
            figures.append(figure)
    return figures


def _to_figure(match: re.Match[str], text: str) -> Figure | None:
    raw = match.group("num")
    suffix = (match.group("suf") or "").lower()
    percent = bool(match.group("pct"))
    decorated = bool(match.group("cur")) or percent or bool(suffix) or "," in raw or "." in raw

    digits = Decimal(raw.replace(",", ""))
    if not decorated:
        if 1900 <= digits <= 2100:
            return None  # a year
        if digits < 10:
            return None  # a small count or prose number
        if _TIME_UNIT_AFTER.match(text, match.end()):
            return None  # a time span, e.g. "past 12 months"

    decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
    multiplier = _MULTIPLIERS.get(suffix, Decimal(1))
    return Figure(
        text=match.group(0).strip(),
        value=digits * multiplier,
        unit=Decimal(10) ** -decimals * multiplier,
        percent=percent,
    )


def source_values(texts: Iterable[str]) -> list[Decimal]:
    """Every numeric value present in `texts`, sorted, for range lookups.

    Each literal contributes its plain value and, when it carries a magnitude
    suffix, its scaled value too. A comma-grouped literal is also read as its
    separate parts, because ``[1,234]`` in JSON is two numbers, not one.
    """
    values: set[Decimal] = set()
    for text in texts:
        for match in _SOURCE_NUMBER.finditer(text):
            value = _decimal(match.group("num").replace(",", ""))
            if value is None:
                continue
            values.add(value)
            suffix = (match.group("suf") or "").lower()
            if suffix:
                values.add(value * _MULTIPLIERS[suffix])
        for match in _SOURCE_PLAIN.finditer(text):
            value = _decimal(match.group(0))
            if value is not None:
                values.add(value)
    return sorted(values)


def _decimal(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _any_within(values: list[Decimal], low: Decimal, high: Decimal) -> bool:
    index = bisect.bisect_left(values, low)
    return index < len(values) and values[index] <= high


def _is_sum_or_difference(value: Decimal, tolerance: Decimal, values: list[Decimal]) -> bool:
    """True when `value` is ``a + b`` or ``|a - b|`` for two source values.

    For each source value ``a`` this looks up a partner ``b`` near ``value - a``
    (a sum) or ``a - value`` (a difference), so it costs O(n log n), not O(n^2).
    """
    for a in values:
        if a == 0:
            continue
        for target in (value - a, a - value):
            if target > 0 and _any_within(values, target - tolerance, target + tolerance):
                return True
    return False


def _matches(figure: Figure, values: list[Decimal]) -> bool:
    candidates = [(figure.value, figure.unit)]
    if figure.percent:
        candidates.append((figure.value / 100, figure.unit / 100))
    for value, unit in candidates:
        tolerance = unit / 2
        if _any_within(values, value - tolerance, value + tolerance):
            return True
    # Sums/differences are taken on the figure as written only, not on its
    # fraction form, to keep the derived search as narrow as possible.
    return _is_sum_or_difference(figure.value, figure.unit / 2, values)


def unverified_figures(answer: str, source_texts: Iterable[str]) -> list[str]:
    """Names each figure in `answer` that no source value (or sum/difference of
    two) rounds to.

    Returned in answer order, de-duplicated, as the answer wrote them.
    """
    figures = extract_figures(answer)
    if not figures:
        return []
    values = source_values(source_texts)
    unmatched: list[str] = []
    for figure in figures:
        if not _matches(figure, values) and figure.text not in unmatched:
            unmatched.append(figure.text)
    return unmatched


def collect_source_texts(
    documents: list[RetrievedDocument],
    tool_calls: list[ToolCallRecord],
    extra: Iterable[str] = (),
) -> list[str]:
    """Gathers the text the answer's figures may legitimately come from."""
    texts = [document.content for document in documents]
    texts.extend(call.result_text or call.result_excerpt for call in tool_calls)
    texts.extend(extra)
    return texts


def unverified_warning(figures: list[str]) -> str:
    """The warning string naming each untraceable figure."""
    named = ", ".join(f'"{figure}"' for figure in figures)
    return (
        "The answer quotes figures that appear in no retrieved document or tool "
        f"response: {named}"
    )
