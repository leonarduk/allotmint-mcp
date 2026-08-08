"""allotmint-mcp's DeepSeek review entrypoint, called by deepseek-pr-review.yml.

The DeepSeek integration (retry/outage/auth-error handling, prompt building,
verdict format) now lives entirely in the cicaid-devtools package; this file
only supplies this repo's RepoProfile. See allotmint-mcp#409.
"""

from __future__ import annotations

import logging

from cicaid_devtools.lib.deepseek_review import main as _cicaid_main

from review_common import MCP_REPO_PROFILE


def main() -> int:
    """Run the advisory DeepSeek review flow with allotmint-mcp's RepoProfile."""
    return _cicaid_main(MCP_REPO_PROFILE)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
