"""CLI tool to extract GitHub issue prompts for Aider with local LLM assistance."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from lib.github_repo import get_repo_info, get_repo_root
from lib.ollama_common import (
    fetch_ollama_review,
    get_ollama_endpoint,
    get_ollama_model,
    validate_ollama_connection,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract GitHub issue prompt for Aider with local LLM assistance",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-i",
        "--issue",
        type=int,
        dest="issue_id",
        help="GitHub issue ID (fetches from GitHub)",
    )
    group.add_argument(
        "-f",
        "--file",
        type=str,
        dest="issue_file",
        help="Local markdown file containing issue",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose/debug output",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip confirmation and proceed directly to Aider",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="GitHub personal access token (optional, uses GITHUB_TOKEN env var if not provided)",
    )

    return parser.parse_args(argv)


def fetch_issue_from_github(
    owner: str,
    repo: str,
    issue_id: int,
    token: str | None = None,
    verbose: bool = False,
) -> tuple[str, str]:
    """Fetch issue title and body from GitHub API.

    Returns: (title, body) tuple.
    """
    logger.debug("Fetching issue #%d from %s/%s...", issue_id, owner, repo)

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_id}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to fetch issue #%d: %s", issue_id, exc)
        logger.error(
            "Tip: If GitHub API is unreachable, use -f <file> to load a local markdown file instead."
        )
        sys.exit(1)

    issue = resp.json()
    title = issue.get("title", "")
    body = issue.get("body", "")

    if not title:
        logger.error("Issue #%d has no title", issue_id)
        sys.exit(1)

    logger.debug("Fetched issue: %s", title)

    return title, body


def load_issue_from_file(file_path: str, verbose: bool = False) -> tuple[str, str]:
    """Load issue title and body from a local markdown file.

    File format: first line is title, rest is body.
    Returns: (title, body) tuple.
    """
    logger.debug("Loading issue from file: %s", file_path)

    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("File not found: %s", file_path)
        sys.exit(1)
    except OSError as exc:
        logger.error("Failed to read file %s: %s", file_path, exc)
        sys.exit(1)

    lines = content.strip().split("\n", 1)
    title = lines[0].strip()
    body = lines[1].strip() if len(lines) > 1 else ""

    logger.debug("Loaded issue: %s", title)

    return title, body


def parse_issue_body(body: str, verbose: bool = False) -> dict[str, str]:
    """Parse issue body into structured sections.

    Extracts: What, Why, How, Constraints, LLM tier, Success looks like, Failure looks like.
    """
    sections = {}

    # Not every issue follows the "## Heading" template exactly -- issues
    # filed before the template was standardized (or edited by hand) use a
    # whole-line "**Heading**" bold style instead. Normalize those to ATX
    # headers first so the single pattern below catches both.
    normalized_body = re.sub(r"(?m)^\*\*([^\n*]+)\*\*\s*$", r"## \1", body)

    # Split by markdown headers (## Section)
    pattern = r"##\s*([^\n]+)\n(.*?)(?=##\s*|\Z)"
    matches = re.finditer(pattern, normalized_body, re.DOTALL | re.IGNORECASE)

    for match in matches:
        section_title = match.group(1).strip().lower()
        section_content = match.group(2).strip()

        # Normalize section names
        if section_title in ("what", "description"):
            sections["what"] = section_content
        elif section_title == "why":
            sections["why"] = section_content
        elif section_title == "how":
            sections["how"] = section_content
        elif section_title in ("files affected", "files_affected", "files to change"):
            sections["files_affected"] = section_content
        elif section_title == "constraints":
            sections["constraints"] = section_content
        elif section_title in ("llm tier", "llm_tier"):
            sections["llm_tier"] = section_content
        elif section_title in ("success looks like", "success_looks_like"):
            sections["success"] = section_content
        elif section_title in ("failure looks like", "failure_looks_like"):
            sections["failure"] = section_content

    logger.debug("Parsed sections: %s", list(sections.keys()))

    return sections


def is_safe_relative_path(path: str) -> bool:
    """Reject absolute paths and paths that escape the repo root via '..' segments.

    Issue bodies and Ollama's suggestions are both untrusted input; without
    this check a path like '../../.aws/credentials' could be handed straight
    to aider if such a file happens to exist relative to the cwd.

    Path.is_absolute() alone isn't enough here: PureWindowsPath treats a
    leading '/' with no drive letter (e.g. '/etc/passwd') as relative, so a
    script running on Windows would miss it. Reject a leading separator of
    either style explicitly before falling back to is_absolute() for
    drive-letter and POSIX-root paths.
    """
    if path.startswith(("/", "\\")):
        return False
    candidate = Path(path)
    if candidate.is_absolute():
        return False
    return ".." not in candidate.parts


def extract_file_paths_from_issue(
    issue_body: str,
    verbose: bool = False,
) -> list[str]:
    """Extract file paths mentioned in the issue body.

    Looks for paths that exist in the repo (basic heuristic). Supported
    formats (see the `pattern` regex below for the exact extension list):

    - Bare paths, e.g. ``backend/app.py`` or ``src/foo.ts``.
    - Markdown link paths, e.g. ``[backend/app.py](https://...)``.
    - Backtick-wrapped bullets, e.g. ``- `backend/app.py``` -- the "Files
      Affected" convention produced by every issue template in this repo.

    Paths must be relative (no leading ``/`` or ``\\``, no ``..`` segments --
    see :func:`is_safe_relative_path`) and must exist on disk relative to the
    current working directory to be returned; anything else is silently
    skipped rather than raising, since the input is free-form issue text.
    """
    paths = []

    # Match common path patterns
    pattern = r"(?:^|[\s\[\(\`])([a-zA-Z0-9._/\-]+\.(?:tsx|ts|py|jsx|js|css|md|yaml|yml|json))"
    matches = re.finditer(pattern, issue_body, re.MULTILINE)

    for match in matches:
        path = match.group(1)
        if not is_safe_relative_path(path):
            continue
        if Path(path).exists():
            paths.append(path)
            logger.debug("Found file reference: %s", path)

    return list(set(paths))  # deduplicate


def suggest_files_with_ollama(
    issue_title: str,
    issue_body: str,
    extracted_paths: list[str],
    endpoint: str,
    model: str,
    verbose: bool = False,
) -> list[str]:
    """Use Ollama to suggest which files to add to Aider based on the issue.

    Returns: list of suggested file paths.
    """
    logger.debug("Calling Ollama (%s) to suggest files...", model)

    extracted_summary = ", ".join(extracted_paths) if extracted_paths else "none"
    prompt = f"""You are a code analysis assistant. Based on the GitHub issue below, identify
which files should be reviewed or modified to implement the requested change.

Issue Title: {issue_title}

Issue Description:
{issue_body}

Extracted file references from issue: {extracted_summary}

Return ONLY a JSON array of file paths to include, like:
["src/components/Foo.tsx", "backend/app.py"]

Do not include test files or lock files. Be concise."""

    try:
        response = fetch_ollama_review(endpoint, model, prompt)
    except SystemExit:
        # Ollama failed; return what we extracted
        logger.debug("Ollama query failed; using extracted paths only")
        return extracted_paths

    # Parse JSON response
    try:
        # Find JSON array in response
        start = response.find("[")
        end = response.rfind("]")
        if start != -1 and end != -1:
            json_str = response[start : end + 1]
            suggested = json.loads(json_str)
            if isinstance(suggested, list):
                # Filter to existing, safe (non-traversal) files
                existing = [
                    p for p in suggested if isinstance(p, str) and is_safe_relative_path(p) and Path(p).exists()
                ]
                logger.debug("Ollama suggested %d files: %s", len(existing), existing)
                return existing
    except (json.JSONDecodeError, ValueError):
        pass

    logger.debug("Could not parse Ollama response as JSON; using extracted paths")
    return extracted_paths


def resolve_files_to_edit(
    title: str,
    body: str,
    endpoint: str,
    model: str,
    verbose: bool = False,
    files_affected: str = "",
) -> list[str]:
    """Return the files to hand to aider.

    Prefers file paths listed in the issue's "Files Affected" section, then
    falls back to any file paths mentioned elsewhere in the issue body, and
    only asks Ollama to suggest files when none are found in either place.
    """
    if files_affected:
        section_paths = extract_file_paths_from_issue(files_affected, verbose)
        if section_paths:
            logger.debug("Using Files Affected paths: %s", section_paths)
            return section_paths

    extracted_paths = extract_file_paths_from_issue(body, verbose)
    if extracted_paths:
        logger.debug("Using extracted paths: %s", extracted_paths)
        return extracted_paths

    logger.debug("No files extracted from issue; asking Ollama to suggest...")
    return suggest_files_with_ollama(title, body, extracted_paths, endpoint, model, verbose)


def _normalize_symbol_prefix(path: str) -> str:
    """Convert a repo-relative file path to the underscore-joined id prefix
    graphify uses for symbols defined in that file, e.g. "backend/app.py" ->
    "backend_app"."""
    stem = Path(path).with_suffix("")
    return re.sub(r"[^a-z0-9]+", "_", str(stem).lower()).strip("_")


def load_graphify_analysis(
    analysis_path: str = "graphify-out/.graphify_analysis.json",
    verbose: bool = False,
) -> dict | None:
    """Load graphify's precomputed knowledge-graph analysis, if present.

    Returns None (never raises) when the file is missing or unreadable --
    graphify-out/ is only refreshed manually via workflow_dispatch on
    .github/workflows/graphify.yml, so it's a helpful-if-present snapshot,
    not something every checkout is guaranteed to have.
    """
    path = Path(analysis_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Could not read graphify analysis: %s", exc)
        return None


def graphify_hint_for_files(files: list[str], analysis: dict | None) -> str:
    """Build a short prompt hint from graphify's analysis for the given files."""
    if not analysis:
        return ""

    gods = {g["id"]: g for g in analysis.get("gods", []) if isinstance(g, dict) and "id" in g}
    communities = analysis.get("communities", {})

    lines = []
    for file in files:
        prefix = _normalize_symbol_prefix(file)
        if not prefix:
            continue

        for god_id, god in gods.items():
            if god_id == prefix or god_id.startswith(f"{prefix}_"):
                lines.append(
                    f"- {file}: high fan-in hotspot ('{god.get('label', god_id)}', "
                    f"degree {god.get('degree', '?')}) -- changes here have broad blast radius."
                )

        for community_id, members in communities.items():
            if not isinstance(members, list):
                continue
            if any(m == prefix or m.startswith(f"{prefix}_") for m in members):
                lines.append(
                    f"- {file}: in knowledge-graph community {community_id} with "
                    f"{len(members) - 1} other symbols -- check for related usages."
                )
                break

    if not lines:
        return ""

    return "\n".join(
        [
            "\nGraphify knowledge-graph hints (precomputed, may be stale -- verify against the actual source):",
            *lines,
        ]
    )


def formulate_aider_prompt(
    issue_title: str,
    parsed_sections: dict[str, str],
    verbose: bool = False,
    graphify_hint: str = "",
) -> str:
    """Formulate the prompt to pass to Aider based on parsed issue sections."""
    prompt_lines = [issue_title]

    logger.debug("Formulating Aider prompt...")

    # Add structured sections
    for section in ["what", "how", "constraints", "success"]:
        if section in parsed_sections:
            content = parsed_sections[section].strip()
            if content:
                section_title = section.replace("_", " ").title()
                prompt_lines.append(f"\n{section_title}:\n{content}")

    if graphify_hint:
        prompt_lines.append(graphify_hint)

    prompt = "\n".join(prompt_lines)

    logger.debug("Prompt length: %d characters", len(prompt))

    return prompt


def confirm_with_user(
    files: list[str],
    prompt: str,
    no_confirm: bool = False,
    verbose: bool = False,
) -> bool:
    """Show files and prompt to user for confirmation."""
    print("\n" + "=" * 70)
    print("AIDER EXTRACTION SUMMARY")
    print("=" * 70)

    print(f"\nFiles to add to Aider ({len(files)}):")
    for f in files:
        print(f"  - {f}")

    print("\nPrompt for Aider:")
    print("-" * 70)
    print(prompt)
    print("-" * 70)

    if no_confirm:
        logger.debug("--no-confirm flag set; skipping confirmation")
        return True

    print("\nProceed with Aider? (Y/n): ", end="", flush=True)
    try:
        response = input().strip().lower()
        return response in ("", "y", "yes")
    except EOFError:
        logger.debug("EOF received; skipping confirmation")
        return False


def _run_aider(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run one aider invocation with inherited stdio."""
    try:
        return subprocess.run(cmd, check=False)
    except FileNotFoundError:
        logger.error("aider not found. Install it with: pip install aider-chat")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Aider session interrupted by user")
        sys.exit(0)


def run_aider(files: list[str], prompt: str, verbose: bool = False) -> None:
    """Apply the initial prompt, then hand off to an interactive aider session."""
    if not files:
        logger.error("No files to add to Aider; aborting.")
        sys.exit(1)

    message_file = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    try:
        message_file.write(prompt)
        message_file.close()
        logger.debug("Applying initial prompt to %d files...", len(files))
        initial = _run_aider(["aider", "--edit-format", "whole", "--message-file", message_file.name, *files])
    finally:
        Path(message_file.name).unlink(missing_ok=True)

    if initial.returncode != 0:
        logger.error(
            "aider exited with status %d while applying the initial prompt",
            initial.returncode,
        )
        sys.exit(initial.returncode)

    logger.debug("Handing off to an interactive aider session...")
    interactive = _run_aider(["aider", "--edit-format", "whole", *files])
    if interactive.returncode != 0:
        logger.error("aider exited with status %d", interactive.returncode)
        sys.exit(interactive.returncode)


def main(argv: list[str] | None = None) -> None:
    """Main entry point."""
    args = parse_args(argv)

    # Resolve a local issue file against the caller's original cwd before
    # the chdir below moves us to the repo root.
    if args.issue_file:
        args.issue_file = str(Path(args.issue_file).resolve())

    # Fail early if Ollama isn't running
    endpoint = get_ollama_endpoint()
    model = get_ollama_model()

    logger.debug("Ollama endpoint: %s", endpoint)
    logger.debug("Ollama model: %s", model)

    if not validate_ollama_connection(endpoint):
        logger.error("Ollama serve must be running")
        logger.error("Could not connect to %s", endpoint)
        sys.exit(1)

    # chdir to repo root
    try:
        os.chdir(get_repo_root())
    except ValueError as exc:
        logger.error("Error: %s", exc)
        sys.exit(1)

    # Get repo info (for GitHub fetching)
    if args.issue_id:
        try:
            owner, repo = get_repo_info()
        except ValueError as exc:
            logger.error("Error: %s", exc)
            sys.exit(1)

    # Fetch or load issue
    if args.issue_id:
        token = args.token or os.getenv("GITHUB_TOKEN")
        title, body = fetch_issue_from_github(owner, repo, args.issue_id, token, args.verbose)
    else:
        title, body = load_issue_from_file(args.issue_file, args.verbose)

    # Parse issue structure
    parsed = parse_issue_body(body, args.verbose)

    files = resolve_files_to_edit(title, body, endpoint, model, args.verbose, parsed.get("files_affected", ""))
    if not files:
        logger.warning(
            "No files found or suggested. Proceeding with empty file list."
        )

    # Formulate prompt
    graphify_hint = graphify_hint_for_files(files, load_graphify_analysis(verbose=args.verbose))
    prompt = formulate_aider_prompt(title, parsed, args.verbose, graphify_hint)

    # Confirm with user
    if not confirm_with_user(files, prompt, args.no_confirm, args.verbose):
        logger.info("Aborted by user")
        sys.exit(0)

    # Run Aider
    run_aider(files, prompt, args.verbose)

    logger.info("Aider session complete")


if __name__ == "__main__":
    main()
