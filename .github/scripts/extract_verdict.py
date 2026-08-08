"""Extract and validate the AI review verdict from review output."""

from __future__ import annotations
import logging


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
import re
import sys
from pathlib import Path

from review_common import (
    API_KEY_INVALID_MARKER,
    API_KEY_MISSING_MARKER,
    EMPTY_DIFF_MARKER,
    EMPTY_REVIEW_MARKER,
    PROVIDER_OUTAGE_MARKER,
)

# Primary format: bold verdict, optionally with backticks inside the bold markers, e.g.
# `**APPROVE**` or `` **`APPROVE`** ``. Matched anywhere in the text (first occurrence wins),
# since this is the format the prompt instructs models to use.
_BOLD_VERDICT_RE = re.compile(r"\*\*`?(APPROVE|REQUEST CHANGES)`?\*\*")

# Fallback format: some models (observed with DeepSeek) drop the bold markers and emit the
# verdict as a plain or bulleted line instead, e.g. `- APPROVE` or `APPROVE — no concerns`.
# Anchored to the whole line (modulo an optional leading bullet marker and a trailing
# " - explanation") so a stray mention of APPROVE/REQUEST CHANGES inside prose or an echoed
# acceptance-criteria checklist item doesn't false-positive. Since the prompt asks for the
# verdict as the last line, the LAST matching line is preferred over the first.
_LINE_VERDICT_RE = re.compile(
    r"^[ \t]*(?:[-*•]\s+)?(APPROVE|REQUEST CHANGES)\b(?:\s*[-—:].*)?$",
    re.MULTILINE,
)


def extract_verdict(review_text: str) -> str | None:
    """Extract the verdict from review text.

    Looks for verdict lines in the format:
    - `**APPROVE**` or `` **`APPROVE`** ``
    - `**REQUEST CHANGES**` or `` **`REQUEST CHANGES`** ``

    Falls back to a plain or bulleted line consisting solely of the verdict
    (e.g. `- APPROVE`) when no bold verdict is present, to tolerate models
    that drop the markdown bold markers.

    Returns 'APPROVE' or 'REQUEST CHANGES' if found, None otherwise.
    """
    match = _BOLD_VERDICT_RE.search(review_text)
    if match:
        return match.group(1)

    line_matches = list(_LINE_VERDICT_RE.finditer(review_text))
    if line_matches:
        return line_matches[-1].group(1)

    return None


def main(review_file: str, provider_name: str) -> int:
    """Read review file, extract verdict, and exit with appropriate status.

    Args:
        review_file: Path to the file containing the review text.
        provider_name: Name of the provider (DeepSeek or GPT) for output messages.

    Returns:
        0 if verdict is APPROVE, 1 if REQUEST CHANGES or no verdict found,
        2 if the review was skipped due to an empty diff, a provider outage,
        an empty provider response, or a missing/invalid API key (see the
        `review_common.*_MARKER` constants) — all soft-fails distinct from a
        genuine review failure, so the calling workflow doesn't block the
        merge gate over an infra incident or a docs-only PR.
    """
    try:
        review_text = Path(review_file).read_text()
    except FileNotFoundError:
        logger.error(f"ERROR: Review file not found: {review_file}")
        return 1

    if not review_text.strip():
        logger.error(f"ERROR: {provider_name} review output was empty")
        return 1

    if EMPTY_DIFF_MARKER in review_text:
        print(f"⚠ {provider_name} review skipped: empty diff (see log for details)")
        return 2

    if PROVIDER_OUTAGE_MARKER in review_text:
        print(f"⚠ {provider_name} review skipped: provider outage (see log for details)")
        return 2

    if EMPTY_REVIEW_MARKER in review_text:
        print(f"⚠ {provider_name} review skipped: empty provider response (see log for details)")
        return 2

    if API_KEY_MISSING_MARKER in review_text:
        print(f"⚠ {provider_name} review skipped: API key not configured (see log for details)")
        return 2

    if API_KEY_INVALID_MARKER in review_text:
        print(f"⚠ {provider_name} review skipped: API key rejected (see log for details)")
        return 2

    verdict = extract_verdict(review_text)

    if verdict == "APPROVE":
        print(f"✓ {provider_name} review: APPROVED")
        return 0

    if verdict == "REQUEST CHANGES":
        print(f"✗ {provider_name} review: CHANGES REQUESTED")
        return 1

    logger.error(
        f"{provider_name} review did not include a valid verdict. "
        "Expected '**APPROVE**' or '**REQUEST CHANGES**' (with or without backticks) in the review."
    )
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        logger.error(
            f"Usage: {sys.argv[0]} <review_file> <provider_name>"
        )
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
