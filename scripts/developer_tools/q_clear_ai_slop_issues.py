"""Detect and close AI-generated issues that are duplicates, already resolved, or
approval artifacts mis-filed as issues.

Continues the a_/b_/.../q_ script chain in scripts/developer_tools/. Scans all
open issues with the ``ai-suggested`` label and flags candidates that are safe to
close because they duplicate another open issue, match an already-closed issue,
or are APPROVE review messages incorrectly filed as standalone issues.

Detection strategies
--------------------
- **LLM-powered** (default, ``--model-source local``): sends the full issue list
  to a local (Ollama) or cloud (DeepSeek) model and asks it to identify slop.
  The model sees both titles and bodies so it can catch near-duplicates, subtle
  APPROVE language, and issues no longer relevant.  Falls back gracefully when
  the model is unreachable.
- **Rule-based** (always on, disable with ``--skip-rules`` or ``--no-llm``): uses
  token-set similarity, regex patterns, and `gh` issue-list queries --- fast,
  deterministic, needs no API key.  Findings from both tiers are merged.

Safety
------
- Defaults to dry-run. Pass ``--yes`` to actually close anything.
- Only ever touches issues with the ``ai-suggested`` label.
- Posts a standardised closing comment explaining the reason before closing,
  so there is an audit trail.
- Idempotent: re-running the same detection produces the same results.
- Candidate issues are deduplicated across detection categories so an issue
  flagged by multiple detectors is only closed once.

Requires the ``gh`` CLI to be authenticated with a token that can close issues
on the target repo.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Add lib/ (for llm_common) to sys.path so this works when invoked directly.
sys.path.insert(0, str(Path(__file__).parent / "lib"))
from llm_common import (  # noqa: E402
    CLOUD,
    LOCAL,
    describe_model_source,
    fetch_review,
    validate_model_source,
)

REPO_OWNER = "leonarduk"
REPO_NAME = "allotmint-mcp"
TARGET_LABEL = "ai-suggested"
DUPLICATE_JACCARD_THRESHOLD = 0.65
GH_TIMEOUT_SECONDS = 60

# Title prefixes that don't change the core ask --- stripping them before
# comparison prevents "Add tests for X" and "Consider adding tests for X"
# from looking like different issues.
_NOISE_PREFIXES = (
    "add ",
    "consider adding ",
    "consider ",
    "implement ",
    "explore ",
    "review ",
    "document ",
    "evaluate ",
    "investigate ",
    "ensure ",
    "verify ",
    "create ",
    "update ",
    "fix ",
    "refactor ",
    "remove ",
    "replace ",
    "migrate ",
    "introduce ",
    "support ",
    "enable ",
    "allow ",
    "provide ",
    "include ",
    "set up ",
    "setup ",
)

# Approval-signalling phrases. When a title *starts* with one of these (after
# stripping markdown formatting) the issue is an APPROVE artifact.
_APPROVAL_TITLE_PREFIXES = (
    "approve",
    "approved",
    "lgtm",
    "looks good",
    "looks good to me",
    ":+1:",
    ":+1:",
    "ship it",
    "shipit",
)

# Approval phrases that, when they appear at the very start of an issue body
# (first 80 characters, stripped), indicate the body is an approval message.
_APPROVAL_BODY_PATTERNS = (
    r"\*\*`?APPROVE`?\*\*",
    r"\bAPPROVE\b",
    r"\bLGTM\b",
    r"\bApproved\b",
    r"\bLooks good\b",
    r"\bShip it\b",
    r"\bShipit\b",
    r"\b:+1:\b",
)


@dataclass
class GhIssue:
    """A single GitHub issue with the fields needed for slop detection."""

    number: int
    title: str
    body: str
    state: str
    url: str


@dataclass
class CloseCandidate:
    """An issue detected as slop, with the reason and evidence it was found."""

    issue: GhIssue
    reason: str
    evidence: str  # e.g. "Duplicate of #279" or "APPROVE artifact"


def _run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a ``gh`` CLI command scoped to REPO_OWNER/REPO_NAME.  Never raises."""
    cmd = ["gh", *args, "--repo", f"{REPO_OWNER}/{REPO_NAME}"]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout="", stderr=f"gh {' '.join(args)} timed out"
        )


def fetch_issues(state: str, label: str | None = None, limit: int = 500) -> list[GhIssue]:
    """Fetch issues via ``gh issue list`` with the given state and optional label.

    Returns an empty list on any failure (printed to stderr) so callers can
    degrade gracefully rather than crashing.
    """
    args: list[str] = [
        "issue",
        "list",
        "--state",
        state,
        "--json",
        "number,title,body,state,url",
        "--limit",
        str(limit),
    ]
    if label:
        args += ["--label", label]

    result = _run_gh(args)
    if result.returncode != 0:
        print(f"ERROR: gh issue list (state={state}) failed: {result.stderr.strip()}", file=sys.stderr)
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"ERROR: gh issue list returned non-JSON output: {exc}", file=sys.stderr)
        return []

    return [
        GhIssue(
            number=item["number"],
            title=item.get("title", ""),
            body=item.get("body") or "",
            state=item.get("state", state).lower(),
            url=item.get("url", ""),
        )
        for item in data
    ]


# ------------------------------------------------------------------ title helpers


def _strip_markdown(text: str) -> str:
    """Remove bold/italic/code markers and backtick-quoted spans."""
    text = re.sub(r"\*\*`?([^`*]+)`?\*\*", r"\1", text)  # **`FOO`** or **FOO**
    text = re.sub(r"`([^`]+)`", r"\1", text)  # `code`
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)  # italic / bold
    return text


def _strip_noise_prefix(title: str) -> str:
    """Remove a leading noise prefix if one is present, returning the remainder."""
    lower = title.lower()
    for prefix in _NOISE_PREFIXES:
        if lower.startswith(prefix):
            return title[len(prefix) :]
    return title


def _normalise_title(title: str) -> str:
    """Normalise a title into a bag-of-tokens string for similarity comparison.

    Steps:
    1. Strip markdown formatting.
    2. Strip noise prefixes.
    3. Lowercase.
    4. Replace non-alphanumeric characters with spaces.
    5. Collapse whitespace.
    """
    text = _strip_markdown(title)
    text = _strip_noise_prefix(text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _tokenize(text: str) -> set[str]:
    """Return the set of unique tokens in *text*."""
    return set(text.split())


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets.  0.0 -- 1.0."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------- detection logic


def _find_duplicates(
    open_issues: list[GhIssue],
    threshold: float = DUPLICATE_JACCARD_THRESHOLD,
) -> list[CloseCandidate]:
    """Find open ai-suggested issues that duplicate another open issue.

    The earliest (lowest-numbered) issue in each cluster is considered the
    canonical one; every later member of the cluster is flagged.
    """
    if len(open_issues) < 2:
        return []

    norm_titles: dict[int, str] = {}
    token_sets: dict[int, set[str]] = {}
    for issue in open_issues:
        norm = _normalise_title(issue.title)
        norm_titles[issue.number] = norm
        token_sets[issue.number] = _tokenize(norm)

    # Cluster by similarity.  A Union-Find would be more elegant, but O(n^2) is
    # fine for the expected issue count (a few hundred).
    parent: dict[int, int] = {issue.number: issue.number for issue in open_issues}
    numbers = sorted(parent)  # ascending -> lowest number wins

    for i_idx, i_num in enumerate(numbers):
        for j_num in numbers[i_idx + 1 :]:
            sim = _jaccard(token_sets[i_num], token_sets[j_num])
            if sim >= threshold:
                # Union: point the higher number to the lower.
                root_i = parent[i_num]
                root_j = parent[j_num]
                winner = min(root_i, root_j)
                parent[root_i] = winner
                parent[root_j] = winner

    # Build flag list: every issue whose parent is not itself.
    duplicates_by_canonical: dict[int, list[GhIssue]] = defaultdict(list)
    for issue in open_issues:
        root = parent[issue.number]
        if root != issue.number:
            duplicates_by_canonical[root].append(issue)

    candidates: list[CloseCandidate] = []
    for canon_num, dups in sorted(duplicates_by_canonical.items()):
        for dup in sorted(dups, key=lambda i: i.number):
            candidates.append(
                CloseCandidate(
                    issue=dup,
                    reason="duplicate",
                    evidence=f"Duplicate of #{canon_num} (title similarity >= {threshold:.0%})",
                )
            )
    return candidates


def _find_already_closed(
    open_issues: list[GhIssue],
    closed_issues: list[GhIssue],
    threshold: float = DUPLICATE_JACCARD_THRESHOLD,
) -> list[CloseCandidate]:
    """Find open ai-suggested issues whose equivalent was already closed."""
    if not closed_issues:
        return []

    closed_norm: dict[int, str] = {}
    closed_tokens: dict[int, set[str]] = {}
    for issue in closed_issues:
        norm = _normalise_title(issue.title)
        closed_norm[issue.number] = norm
        closed_tokens[issue.number] = _tokenize(norm)

    candidates: list[CloseCandidate] = []
    closed_nums = sorted(closed_tokens)

    for open_issue in open_issues:
        open_norm = _normalise_title(open_issue.title)
        open_toks = _tokenize(open_norm)

        best_match: tuple[int, float] = (0, 0.0)
        for cnum in closed_nums:
            sim = _jaccard(open_toks, closed_tokens[cnum])
            if sim > best_match[1]:
                best_match = (cnum, sim)

        # Also check exact title match after normalisation (stricter, but
        # catches the obvious case).
        exact_match = None
        for cnum in closed_nums:
            if open_norm == closed_norm[cnum]:
                exact_match = cnum
                break

        if exact_match is not None:
            candidates.append(
                CloseCandidate(
                    issue=open_issue,
                    reason="already-closed",
                    evidence=f"Closed as #{exact_match} already covers this (exact title match after normalisation)",
                )
            )
        elif best_match[0] and best_match[1] >= threshold:
            candidates.append(
                CloseCandidate(
                    issue=open_issue,
                    reason="already-closed",
                    evidence=f"Closed as #{best_match[0]} already covers this (title similarity {best_match[1]:.0%})",
                )
            )

    return candidates


def _title_looks_like_approve(title: str) -> bool:
    """Return True when *title* starts with an approval phrase."""
    stripped = _strip_markdown(title).strip().lower()
    # Also strip leading dash / bullet markers the model may prepend.
    stripped = re.sub(r"^[-]+\s*", "", stripped)
    for prefix in _APPROVAL_TITLE_PREFIXES:
        if stripped.startswith(prefix):
            return True
        # Also match "**APPROVE** --- ..." which after stripping becomes "approve ..."
        if stripped.startswith(prefix + " ") or stripped.startswith(prefix + "---"):
            return True
    return False


def _body_opens_with_approval(body: str) -> bool:
    """Return True when the body's first meaningful line is an approval message."""
    if not body.strip():
        return False
    first_line = body.strip().split("\n")[0][:80].strip()
    # Also strip markdown formatting from the first line before checking.
    first_line = _strip_markdown(first_line).strip()
    for pattern in _APPROVAL_BODY_PATTERNS:
        if re.search(pattern, first_line, re.IGNORECASE):
            return True
    return False


def _find_approve_artifacts(open_issues: list[GhIssue]) -> list[CloseCandidate]:
    """Find open ai-suggested issues that look like APPROVE artifacts."""
    candidates: list[CloseCandidate] = []
    for issue in open_issues:
        if _title_looks_like_approve(issue.title):
            candidates.append(
                CloseCandidate(
                    issue=issue,
                    reason="approve-artifact",
                    evidence="Title starts with an approval phrase --- likely a review approval mis-filed as an issue",
                )
            )
        elif _body_opens_with_approval(issue.body):
            candidates.append(
                CloseCandidate(
                    issue=issue,
                    reason="approve-artifact",
                    evidence="Body opens with an approval message --- likely a review approval mis-filed as an issue",
                )
            )
    return candidates


_SUPERSEDED_RE = re.compile(
    r"superseded\s+by\s+#(\d+)", re.IGNORECASE
)


def _find_superseded(open_issues: list[GhIssue]) -> list[CloseCandidate]:
    """Find open issues that explicitly reference a newer superseding issue."""
    open_nums = {issue.number for issue in open_issues}
    candidates: list[CloseCandidate] = []
    for issue in open_issues:
        for match in _SUPERSEDED_RE.finditer(issue.body):
            ref_num = int(match.group(1))
            if ref_num in open_nums and ref_num > issue.number:
                candidates.append(
                    CloseCandidate(
                        issue=issue,
                        reason="superseded",
                        evidence=f"Superseded by #{ref_num} (referenced in issue body)",
                    )
                )
                break  # one superseding reference is enough
    return candidates


# ------------------------------------------------------------------ actions


def _close_issue(
    issue: GhIssue,
    candidate: CloseCandidate,
    dry_run: bool,
) -> bool:
    """Close *issue* with a comment explaining why.  Returns True on success."""
    prefix = "[DRY RUN] " if dry_run else ""

    comment = _closing_comment(candidate)
    print(
        f"{prefix}Closing #{issue.number} ({issue.title[:70]}...): {candidate.reason} --- {candidate.evidence}"
    )

    if dry_run:
        return True

    # Post the comment first so it exists even if close fails.
    comment_result = _run_gh(
        ["issue", "comment", str(issue.number), "--body", comment]
    )
    if comment_result.returncode != 0:
        print(
            f"ERROR: Failed to comment on #{issue.number}: {comment_result.stderr.strip()}",
            file=sys.stderr,
        )
        # Continue anyway --- the close is the important part.

    close_result = _run_gh(
        [
            "issue",
            "close",
            str(issue.number),
            "--reason",
            "not planned",
            "--comment",
            comment,
        ]
    )
    if close_result.returncode != 0:
        print(
            f"ERROR: Failed to close #{issue.number}: {close_result.stderr.strip()}",
            file=sys.stderr,
        )
        return False
    return True


def _closing_comment(candidate: CloseCandidate) -> str:
    """Build the standardised closing comment for a candidate."""
    if candidate.reason == "duplicate":
        return (
            f"[bot] *Automated cleanup:* closing as {candidate.evidence}. "
            "This issue was detected by `q_clear_ai_slop_issues.py` --- "
            "if this was a mistake, please re-open or comment."
        )
    if candidate.reason == "already-closed":
        return (
            f"[bot] *Automated cleanup:* closing because {candidate.evidence}. "
            "This issue was detected by `q_clear_ai_slop_issues.py` --- "
            "if the work still needs doing, please re-open or comment."
        )
    if candidate.reason == "approve-artifact":
        return (
            f"[bot] *Automated cleanup:* {candidate.evidence}. "
            "This issue was detected by `q_clear_ai_slop_issues.py` --- "
            "if this is actually an actionable issue, please re-open or comment."
        )
    if candidate.reason == "superseded":
        return (
            f"[bot] *Automated cleanup:* closing because {candidate.evidence}. "
            "This issue was detected by `q_clear_ai_slop_issues.py` --- "
            "if this is still relevant, please re-open or comment."
        )
    return (
        f"[bot] *Automated cleanup:* closing ({candidate.reason}). {candidate.evidence}. "
        "Detected by `q_clear_ai_slop_issues.py`. "
        "If this was a mistake, please re-open or comment."
    )


# ------------------------------------------------------------------- LLM detection

_LLM_PROMPT_TEMPLATE = """You are cleaning up issues in the {owner}/{repo} repository on GitHub.
Below is a list of {open_count} OPEN ai-suggested issues. Each issue has a number,
title, and body. Some of these issues are duplicates, already resolved, approval
artifacts, or superseded --- they should be CLOSED to keep the issue tracker clean.

{focus_prompt}

Respond with a JSON array of objects. Each object represents one issue that
should be closed and has these keys:
- "number" (int): the issue number
- "reason" (string): one of "duplicate", "already-closed", "approve-artifact", "superseded"
- "evidence" (string): a short explanation (max 120 chars) referencing relevant
  issue numbers or concrete observations from the issue body.

Only include issues you are confident are slop. When in doubt, omit them.
If no issues match, return an empty array [].
Respond with ONLY the JSON array and nothing else.

--- OPEN issues ---
{open_issues}

--- CLOSED issues for reference ---
{closed_issues}
"""

# The focused detection prompt is substituted into the template above when the
# user opted into a specific detection category via --llm-focus.
_DEFAULT_FOCUS = """Identify issues in ALL of these categories:
1. **Duplicates**: two or more open issues that ask for the same thing.
2. **Already-closed**: an open issue whose work was already done under a closed issue.
3. **APPROVE artifacts**: issues whose title or body is an approval message
   (e.g. starts with "APPROVE", "LGTM", "Approved") rather than a real issue.
4. **Superseded**: an older issue that a newer, more specific issue covers."""

_FOCUS_MAP: dict[str, str] = {
    "duplicate": "Focus ONLY on identifying duplicate issues (two or more open issues that ask for the same thing).",
    "already-closed": "Focus ONLY on identifying open issues whose work was already done under a closed issue.",
    "approve-artifact": "Focus ONLY on identifying APPROVE artifacts (issues whose title or body is an approval message like APPROVE, LGTM, Approved).",
    "superseded": "Focus ONLY on identifying superseded issues (an older issue that a newer, more specific issue covers).",
}


def _format_issue_for_llm(issue: GhIssue, max_body_chars: int = 600) -> str:
    """Format a single issue for the LLM prompt, truncating long bodies."""
    body = issue.body
    if len(body) > max_body_chars:
        body = body[:max_body_chars] + "..."
    return f"#{issue.number}: {issue.title}\n{body}"


def _build_llm_prompt(
    open_issues: list[GhIssue],
    closed_issues: list[GhIssue],
    focus: str | None = None,
) -> str:
    """Build the LLM prompt with all open and closed issues."""
    focus_text = _FOCUS_MAP.get(focus or "", _DEFAULT_FOCUS)

    open_text = "\n\n".join(_format_issue_for_llm(i) for i in open_issues)
    closed_text = "\n\n".join(_format_issue_for_llm(i) for i in closed_issues)
    if not closed_text.strip():
        closed_text = "(no closed ai-suggested issues)"

    return _LLM_PROMPT_TEMPLATE.format(
        owner=REPO_OWNER,
        repo=REPO_NAME,
        open_count=len(open_issues),
        focus_prompt=focus_text,
        open_issues=open_text,
        closed_issues=closed_text,
    )


def _parse_llm_response(response: str, open_issues: list[GhIssue]) -> list[CloseCandidate]:
    """Parse the LLM's JSON response into CloseCandidate objects.

    Tolerates leading/trailing text that isn't JSON (code fences, explanatory
    text) by extracting the first JSON array found.
    """
    # Find the JSON array in the response.
    match = re.search(r"\[.*\]", response, re.DOTALL)
    if not match:
        print("WARNING: LLM response contained no JSON array.", file=sys.stderr)
        return []

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        print(f"WARNING: Failed to parse LLM response as JSON: {exc}", file=sys.stderr)
        return []

    if not isinstance(data, list):
        print("WARNING: LLM response was not a JSON array.", file=sys.stderr)
        return []

    # Build a lookup for issue metadata.
    issue_by_num: dict[int, GhIssue] = {i.number: i for i in open_issues}
    valid_reasons = {"duplicate", "already-closed", "approve-artifact", "superseded"}

    candidates: list[CloseCandidate] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        reason = item.get("reason", "").strip().lower()
        evidence = item.get("evidence", "").strip()[:200]

        if not isinstance(number, int) or number not in issue_by_num:
            continue
        if reason not in valid_reasons:
            reason = "unknown"
        if not evidence:
            evidence = f"Flagged by LLM as {reason}"

        candidates.append(
            CloseCandidate(issue=issue_by_num[number], reason=reason, evidence=evidence)
        )

    return candidates


def _find_with_llm(
    model_source: str,
    open_issues: list[GhIssue],
    closed_issues: list[GhIssue],
    focus: str | None = None,
) -> list[CloseCandidate]:
    """Use the chosen LLM to identify issues that should be closed.

    Returns an empty list on any failure (connection error, empty response,
    unparseable output, etc.) so the overall run always continues with the
    rule-based results.
    """
    if not validate_model_source(model_source):
        return []

    prompt = _build_llm_prompt(open_issues, closed_issues, focus)
    print(
        f"INFO: Sending {len(open_issues)} open + {len(closed_issues)} closed issues "
        f"to {describe_model_source(model_source)}...",
        file=sys.stderr,
    )

    response = fetch_review(model_source, prompt)
    if not response.strip():
        print("WARNING: LLM returned an empty response.", file=sys.stderr)
        return []

    candidates = _parse_llm_response(response, open_issues)
    print(
        f"INFO: LLM identified {len(candidates)} candidate issue(s).",
        file=sys.stderr,
    )
    return candidates


# ----------------------------------------------------------------------- main


def _deduplicate_candidates(candidates: list[CloseCandidate]) -> list[CloseCandidate]:
    """Keep only the first candidate for each issue number."""
    seen: set[int] = set()
    result: list[CloseCandidate] = []
    for c in candidates:
        if c.issue.number not in seen:
            seen.add(c.issue.number)
            result.append(c)
    return result


def _resolve_repo(explicit: str | None) -> tuple[str, str]:
    """Resolve the (owner, repo) from --repo, git remote, or built-in default."""
    if explicit:
        owner, _, name = explicit.partition("/")
        if not owner or not name:
            print(
                f"ERROR: --repo must be in 'owner/name' form, got '{explicit}'",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return owner, name

    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode == 0:
        match = re.search(
            r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", result.stdout.strip()
        )
        if match:
            return match.group(1), match.group(2)
    return REPO_OWNER, REPO_NAME


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect and close AI-generated duplicate/obsolete/approval issues"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually close issues. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Repository to operate on as 'owner/name'. Defaults to the 'origin' git remote.",
    )
    parser.add_argument(
        "--model-source",
        choices=[LOCAL, CLOUD],
        default=LOCAL,
        help="Which LLM to use for detection: 'local' (Ollama, default) or 'cloud' (DeepSeek). "
        "Use --skip-rules to rely solely on the LLM, or --no-llm to disable LLM entirely.",
    )
    parser.add_argument(
        "--llm-focus",
        choices=list(_FOCUS_MAP),
        default=None,
        help="When using --model-source, narrow the LLM's focus to one detection category "
        "(reduces prompt size and cost). By default the LLM checks all four categories.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM-powered detection and use only rule-based detection.",
    )
    parser.add_argument(
        "--skip-rules",
        action="store_true",
        help="Skip all rule-based detection and rely solely on the LLM.",
    )
    parser.add_argument(
        "--skip-already-closed",
        action="store_true",
        help="Skip rule-based detection of issues whose equivalent was already closed.",
    )
    parser.add_argument(
        "--skip-approve-artifacts",
        action="store_true",
        help="Skip rule-based detection of APPROVE artifacts.",
    )
    parser.add_argument(
        "--skip-superseded",
        action="store_true",
        help="Skip rule-based detection of superseded issues.",
    )
    parser.add_argument(
        "--jaccard-threshold",
        type=float,
        default=DUPLICATE_JACCARD_THRESHOLD,
        help=f"Jaccard similarity threshold for rule-based duplicate detection (default: {DUPLICATE_JACCARD_THRESHOLD:.2f})",
    )
    args = parser.parse_args()
    dry_run = not args.yes



    global REPO_OWNER, REPO_NAME
    REPO_OWNER, REPO_NAME = _resolve_repo(args.repo)

    print(
        f"INFO: Scanning {REPO_OWNER}/{REPO_NAME} for ai-suggested slop issues...",
        file=sys.stderr,
    )
    if not args.no_llm:
        print(f"INFO: Model source: {args.model_source}", file=sys.stderr)
    if args.llm_focus and not args.no_llm:
        print(f"INFO: LLM focus: {args.llm_focus}", file=sys.stderr)

    # ------------------------------------------------------------------ fetch
    open_issues = fetch_issues("open", label=TARGET_LABEL)
    print(
        f"INFO: {len(open_issues)} open issue(s) with label '{TARGET_LABEL}'",
        file=sys.stderr,
    )
    if not open_issues:
        print("INFO: No open ai-suggested issues found --- nothing to clean up.", file=sys.stderr)
        return 0

    # Fetch closed issues once (needed by both rule-based and LLM paths).
    closed_issues: list[GhIssue] = []
    if not args.skip_already_closed or args.model_source:
        closed_issues = fetch_issues("closed", label=TARGET_LABEL)
        print(
            f"INFO: {len(closed_issues)} closed issue(s) with label '{TARGET_LABEL}'",
            file=sys.stderr,
        )

    if dry_run:
        print("INFO: Running in dry-run mode. Pass --yes to actually close issues.", file=sys.stderr)

    # ------------------------------------------------------------------ detect
    all_candidates: list[CloseCandidate] = []

    # --- Rule-based detection (unless --skip-rules) ---
    if not args.skip_rules:
        # 1. Duplicates
        print("INFO: [rules] Detecting duplicates among open issues...", file=sys.stderr)
        dupes = _find_duplicates(open_issues, threshold=args.jaccard_threshold)
        print(f"INFO:   -> {len(dupes)} duplicate(s) found", file=sys.stderr)
        all_candidates.extend(dupes)

        # 2. Already-closed
        if not args.skip_already_closed:
            print("INFO: [rules] Detecting already-closed equivalents...", file=sys.stderr)
            ac = _find_already_closed(open_issues, closed_issues, threshold=args.jaccard_threshold)
            print(f"INFO:   -> {len(ac)} already-closed equivalent(s) found", file=sys.stderr)
            all_candidates.extend(ac)

        # 3. APPROVE artifacts
        if not args.skip_approve_artifacts:
            print("INFO: [rules] Detecting APPROVE artifacts...", file=sys.stderr)
            aa = _find_approve_artifacts(open_issues)
            print(f"INFO:   -> {len(aa)} approve artifact(s) found", file=sys.stderr)
            all_candidates.extend(aa)

        # 4. Superseded
        if not args.skip_superseded:
            print("INFO: [rules] Detecting superseded issues...", file=sys.stderr)
            ss = _find_superseded(open_issues)
            print(f"INFO:   -> {len(ss)} superseded issue(s) found", file=sys.stderr)
            all_candidates.extend(ss)

    # --- LLM-powered detection (default; skip with --no-llm) ---
    if not args.no_llm:
        print("INFO: [llm] Running LLM-powered detection...", file=sys.stderr)
        llm_candidates = _find_with_llm(
            args.model_source,
            open_issues,
            closed_issues,
            focus=args.llm_focus,
        )
        print(f"INFO: [llm] -> {len(llm_candidates)} LLM-identified candidate(s)", file=sys.stderr)
        all_candidates.extend(llm_candidates)

    # Deduplicate candidates (one close per issue).
    all_candidates = _deduplicate_candidates(all_candidates)

    if not all_candidates:
        print("INFO: No slop issues detected --- issue list looks clean.", file=sys.stderr)
        return 0

    # ------------------------------------------------------------------ report
    print(f"\n{'=' * 70}")
    print(f"Found {len(all_candidates)} candidate issue(s) to close:\n")
    for c in all_candidates:
        print(f"  #{c.issue.number:>4}  [{c.reason:>16}]  {c.issue.title[:80]}")
        print(f"         Evidence: {c.evidence}")
        print(f"         URL:      {c.issue.url}")
        print()
    print(f"{'=' * 70}")

    if dry_run:
        print(
            "\nDRY RUN: no issues were closed. Pass --yes to close the above issues.",
            file=sys.stderr,
        )
        return 0

    # ------------------------------------------------------------------ confirm
    try:
        answer = input(f"\nClose {len(all_candidates)} issue(s)? [y/N] ").strip().lower()
    except EOFError:
        answer = "n"
    if answer not in ("y", "yes"):
        print("Aborted; no issues were closed.", file=sys.stderr)
        return 0

    # ------------------------------------------------------------------ close
    had_failures = False
    for c in all_candidates:
        if not _close_issue(c.issue, c, dry_run=False):
            had_failures = True

    if had_failures:
        print(
            "\nWARNING: Some issues failed to close. Check the errors above.",
            file=sys.stderr,
        )
        return 1

    print(f"\n[OK] Closed {len(all_candidates)} issue(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
