"""Numeric provenance (#692): figures in the answer must appear in a source.

These pin the extraction, tolerance and ignore rules documented in
`app/provenance.py`. The point of the check is to catch invented magnitudes
without tripping on formatting, so both directions are covered: fabricated
figures are named, and faithful figures in any reasonable format are not.
"""

from __future__ import annotations

import json

import pytest

from app.models import RetrievedDocument, ToolCallRecord
from app.provenance import (
    collect_source_texts,
    extract_figures,
    unverified_figures,
    unverified_warning,
)

# The shape of the allotmint_portfolio response behind the #692 report: the
# whole portfolio is £10,983.67. Global Equity / Fixed Income weights here are
# deliberately not the 51.93 / 9.24 the model wrote.
PORTFOLIO = json.dumps(
    {
        "action": "exposure",
        "owner": "alice",
        "total_value_gbp": 10983.67,
        "sectors": [
            {"sector": "Global Equity", "weight_pct": 48.1031, "value_gbp": 5283.47},
            {"sector": "Fixed Income", "weight_pct": 12.4, "value_gbp": 1361.98},
            {"sector": "Technology", "weight_pct": 6.75, "weight_pct_year_ago": 5.5},
        ],
    }
)

REPORTED_ANSWER = (
    "Your technology exposure is currently valued at £7,403,919 (GBP), with a sector "
    "weight of 51.93% in Global Equity and 9.24% in Fixed Income [tool:allotmint_portfolio]. "
    "Microsoft Azure has contributed 15.22% to your portfolio's value, and NVIDIA is "
    "contributing 2.34% [tool:allotmint_portfolio]."
)


def _portfolio_call(text: str = PORTFOLIO) -> ToolCallRecord:
    return ToolCallRecord(
        tool="allotmint_portfolio",
        arguments={"action": "exposure", "owner": "alice"},
        result_excerpt=text[:400],
        result_text=text,
    )


def test_the_reported_fabrication_names_every_invented_figure():
    sources = collect_source_texts([], [_portfolio_call()])

    assert unverified_figures(REPORTED_ANSWER, sources) == [
        "£7,403,919",
        "51.93%",
        "9.24%",
        "15.22%",
        "2.34%",
    ]


def test_real_figures_quoted_against_the_wrong_label_still_pass():
    # Documented limit: a literal that exists in a source passes even when the
    # model attaches it to the wrong thing. Only the invented ones are named.
    sources = [PORTFOLIO.replace("48.1031", "51.93").replace("12.4", "9.24")]

    assert unverified_figures(REPORTED_ANSWER, sources) == ["£7,403,919", "15.22%", "2.34%"]


def test_a_faithful_answer_has_no_unverified_figures():
    answer = (
        "Your portfolio is worth £10,983.67 [tool:allotmint_portfolio]. Technology is "
        "6.75% of it, up from 5.5% a year ago; Global Equity is the largest sector at "
        "48.10% (£5,283.47) [tool:allotmint_portfolio]."
    )

    assert unverified_figures(answer, [PORTFOLIO]) == []


def test_a_qualitative_answer_has_no_figures_to_check():
    answer = "Your largest sector is Global Equity [tool:allotmint_portfolio]."

    assert extract_figures(answer) == []
    assert unverified_figures(answer, [PORTFOLIO]) == []


@pytest.mark.parametrize(
    "figure",
    [
        "£10,983.67",
        "10983.67",
        "10,983.67",
        "£10,984",
        "£10.98k",
        "£11k",
        "£0.011m",
        "GBP 10,983.67",
    ],
)
def test_formatting_and_rounding_of_a_source_value_is_not_a_mismatch(figure):
    assert unverified_figures(f"The total is {figure} [1].", ['{"total": 10983.67}']) == []


@pytest.mark.parametrize(
    ("answer", "source"),
    [
        ("Global Equity is 51.93% [1].", '{"weight_pct": 51.9312}'),
        ("Global Equity is 52% [1].", '{"weight_pct": 51.9312}'),
        ("Technology is 27.0% [1].", '{"weight_pct": 27}'),
        ("Technology is 27% [1].", '{"weight_pct": 27.0}'),
        ("Technology is 51.93% [1].", '{"weight": 0.5193}'),
        ("Revenue reached $3.2bn [1].", "Revenue reached 3,200,000,000 dollars."),
        ("Revenue reached $3,200,000,000 [1].", "Revenue reached $3.2bn."),
        ("Revenue reached $3.2 billion [1].", "Revenue reached $3.2bn."),
        ("The fund fell 2.5% [1].", '{"change_pct": -2.5}'),
        ("The price is 0.000012 [1].", '{"price": 1.2e-05}'),
        ("Holdings: 1,234 units [1].", '{"units": [1,234]}'),
    ],
)
def test_equivalent_representations_match(answer, source):
    assert unverified_figures(answer, [source]) == []


@pytest.mark.parametrize(
    ("answer", "source", "flagged"),
    [
        # More precision than any source has is invented precision.
        ("Technology is 27.04% [1].", '{"weight_pct": 27.0}', "27.04%"),
        # Rounding tolerance is half a unit of the answer's last digit, no more.
        ("Global Equity is 51.94% [1].", '{"weight_pct": 51.9312}', "51.94%"),
        ("The total is £10.97k [1].", '{"total": 10983.67}', "£10.97k"),
        # Derived arithmetic is not traced (documented follow-up).
        ("Technology and Fixed Income together are 19.15% [1].", PORTFOLIO, "19.15%"),
    ],
)
def test_near_misses_and_derived_figures_are_flagged(answer, source, flagged):
    assert unverified_figures(answer, [source]) == [flagged]


@pytest.mark.parametrize(
    "answer",
    [
        "Technology rose [1] [2] [tool:allotmint_portfolio] [1, 2] [12].",
        "As of 2026-08-01 [1], and per the 2026-08-01T09:30:00Z snapshot.",
        "Published on 14/05/2026, 14 May 2026, May 14, 2026 and the 3rd of June.",
        "In 2025 the market rallied, and in 1999 it peaked.",
        "1. Technology\n2. Financials\n10. Utilities",
        "Over the past 12 months and the last 365 days, across 4 sectors.",
        "The FTSE 100 and the S&P 500 both rose; Q1 and FY2025 were strong.",
        "The update landed at 09:30 for your 2nd account.",
    ],
)
def test_dates_markers_ordinals_and_labels_are_not_figures(answer):
    assert extract_figures(answer) == []


def test_a_bare_integer_of_ten_or_more_is_a_figure():
    assert [f.text for f in extract_figures("You hold 14 positions [1].")] == ["14"]
    assert unverified_figures("You hold 14 positions [1].", ['{"count": 3}']) == ["14"]


def test_a_repeated_figure_is_named_once():
    answer = "It is £7,403,919 [1]. Again, £7,403,919 [1]."

    assert unverified_figures(answer, [PORTFOLIO]) == ["£7,403,919"]


def test_figures_past_the_citation_excerpt_are_still_traced():
    # result_excerpt is capped at 400 chars for the citation; the model saw the
    # full response, so provenance must check the full response too.
    padding = "x" * 500
    text = json.dumps({"padding": padding, "total_value_gbp": 10983.67})
    call = _portfolio_call(text)
    assert "10983.67" not in call.result_excerpt

    sources = collect_source_texts([], [call])

    assert unverified_figures("The total is £10,983.67 [1].", sources) == []


def test_document_text_and_extra_texts_are_sources():
    document = RetrievedDocument(
        source="key_findings.md", content="Technology rose to 27%.", distance=0.5
    )

    sources = collect_source_texts([document], [], extra=["What if I add £5,000?"])

    assert unverified_figures("Technology is 27% [1]; adding £5,000 [1].", sources) == []


def test_the_warning_names_each_figure():
    warning = unverified_warning(["£7,403,919", "15.22%"])

    assert '"£7,403,919"' in warning
    assert '"15.22%"' in warning
    assert "no retrieved document or tool response" in warning
