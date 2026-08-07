"""CLI helper to check out the branch for an open GitHub pull request."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

import requests
from lib.github_repo import get_repo_info

logger = logging.getLogger(__name__)

def _auth_headers(token: str | None) -> dict:
    """Build GitHub API headers, including authentication when available."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def list_open_prs(owner: str, repo: str, token: str | None) -> list[dict]:
    """Fetch open pull requests from the GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    try:
        resp = requests.get(
            url,
            headers=_auth_headers(token),
            params={"state": "open", "per_page": 100},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.exception("Failed to list open pull requests: %s", exc)
        sys.exit(1)
    return resp.json()


def fetch_pr(owner: str, repo: str, pr_number: int, token: str | None) -> dict:
    """Fetch a single pull request from the GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    try:
        resp = requests.get(url, headers=_auth_headers(token), timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.exception("Failed to fetch PR #%d: %s", pr_number, exc)
        sys.exit(1)
    return resp.json()


def prompt_for_pr(prs: list[dict]) -> dict:
    """List open PRs and prompt the user to pick one."""
    if not prs:
        logger.error("No open pull requests found.")
        sys.exit(1)

    logger.info("Open pull requests:")
    for pr in prs:
        author = (pr.get("user") or {}).get("login", "unknown")
        logger.info("  #%d: %s [%s] (by %s)", pr["number"], pr["title"], pr["head"]["ref"], author)

    try:
        choice = input("\nEnter PR number to work on: ").strip()
    except (EOFError, KeyboardInterrupt):
        logger.error("Aborted.")
        sys.exit(1)
    try:
        pr_number = int(choice)
    except ValueError:
        logger.error("Invalid PR number: %r", choice)
        sys.exit(1)

    for pr in prs:
        if pr["number"] == pr_number:
            return pr
    logger.error("PR #%d not found among open pull requests.", pr_number)
    sys.exit(1)


def checkout_pr_branch(pr: dict) -> None:
    """Fetch and check out the branch a PR is built on, handling forks."""
    head = pr["head"]
    branch_name = head["ref"]
    head_repo = head.get("repo")
    base_repo_full_name = pr["base"]["repo"]["full_name"]
    is_fork = head_repo is None or head_repo.get("full_name") != base_repo_full_name

    if is_fork:
        if head_repo is None:
            logger.error(
                "Error: PR head repository is inaccessible (likely deleted fork); cannot check out."
            )
            sys.exit(1)
        fork_full_name = head_repo["full_name"]
        fork_clone_url = head_repo["clone_url"]
        remote_name = f"pr-{pr['number']}"
        local_branch = f"pr-{pr['number']}-{branch_name}"
        remote_ref = f"{remote_name}/{branch_name}"
        logger.info("PR head is in fork %s; fetching as remote '%s'...", fork_full_name, remote_name)
        subprocess.run(["git", "remote", "remove", remote_name], capture_output=True, check=False)
        try:
            subprocess.run(["git", "remote", "add", remote_name, fork_clone_url], check=True)
            subprocess.run(["git", "fetch", remote_name, branch_name], check=True)
        except subprocess.CalledProcessError as exc:
            logger.exception("Failed to fetch %s from fork %s: %s", branch_name, fork_full_name, exc)
            sys.exit(1)
        try:
            _checkout_local_branch(local_branch, remote_ref)
        finally:
            # The remote is temporary and must also be removed after a failed checkout.
            subprocess.run(["git", "remote", "remove", remote_name], capture_output=True, check=False)
        return

    logger.info("Fetching branch %s from origin...", branch_name)
    try:
        subprocess.run(["git", "fetch", "origin", branch_name], check=True)
    except subprocess.CalledProcessError as exc:
        logger.exception("Failed to fetch branch %s from origin: %s", branch_name, exc)
        sys.exit(1)
    _checkout_local_branch(branch_name, f"origin/{branch_name}")


def _checkout_local_branch(local_branch: str, remote_ref: str) -> None:
    """Check out ``local_branch`` tracking ``remote_ref``, updating it in place if it already exists."""
    try:
        subprocess.run(
            ["git", "checkout", "-b", local_branch, remote_ref],
            check=True,
            capture_output=True,
        )
        return
    except subprocess.CalledProcessError:
        pass

    try:
        subprocess.run(["git", "checkout", local_branch], check=True)
        subprocess.run(["git", "merge", "--ff-only", remote_ref], check=True)
    except subprocess.CalledProcessError as exc:
        logger.exception("Failed to update local branch %s to %s: %s", local_branch, remote_ref, exc)
        sys.exit(1)


def main() -> None:
    """Fetch a selected pull request and check out its head branch."""
    parser = argparse.ArgumentParser(description="Check out the branch for an open GitHub pull request")
    parser.add_argument(
        "pr_number",
        type=int,
        nargs="?",
        default=None,
        help="GitHub PR number (omit to list open PRs and choose interactively)",
    )
    parser.add_argument(
        "--token",
        help="GitHub personal access token (also reads GITHUB_TOKEN env var)",
        default=None,
    )
    args = parser.parse_args()

    try:
        owner, repo = get_repo_info()
    except ValueError as exc:
        logger.error("Error: %s", exc)
        sys.exit(1)

    logger.info("Using repository: %s/%s", owner, repo)
    token = args.token or os.getenv("GITHUB_TOKEN")

    logger.info("Fetching from origin...")
    try:
        subprocess.run(["git", "fetch", "origin"], check=True)
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to fetch from origin: %s", exc)
        sys.exit(1)

    if args.pr_number is not None:
        pr = fetch_pr(owner, repo, args.pr_number, token)
        if pr.get("state") != "open":
            logger.warning("PR #%d is %s, not open.", args.pr_number, pr.get("state"))
    else:
        prs = list_open_prs(owner, repo, token)
        pr = prompt_for_pr(prs)

    logger.info("\nWorking on PR #%d: %s", pr["number"], pr["title"])
    checkout_pr_branch(pr)
    logger.info("\n[OK] Checked out branch for PR #%d", pr["number"])


if __name__ == "__main__":
    main()
