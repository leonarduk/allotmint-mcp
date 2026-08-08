"""allotmint-mcp's RepoProfile plus re-exports of the shared cicaid-devtools review helpers.

The retry/outage/auth-error handling, diff truncation, and prompt scaffolding
used to be forked here from the cicaid-devtools package (see
https://github.com/leonarduk/cicaid). That duplication is now resolved:
everything except this repo's own review persona (MCP_REPO_PROFILE) comes
from the installed package. See allotmint-mcp#409.
"""

from __future__ import annotations

from cicaid_devtools.lib.review_common import (
    API_KEY_INVALID_MARKER,
    API_KEY_MISSING_MARKER,
    EMPTY_DIFF_MARKER,
    EMPTY_REVIEW_MARKER,
    MAX_DIFF_CHARS,
    PROVIDER_OUTAGE_MARKER,
    ProviderAuthError,
    ProviderOutageError,
    RepoProfile,
    ReviewContext,
    build_discussion_section,
    build_prompt,
    count_changed_files,
    emit_empty_diff_notice,
    emit_invalid_key_notice,
    emit_missing_key_notice,
    emit_outage_notice,
    extract_filenames_from_diff,
    extract_important_filenames,
    fetch_review,
    filter_binary_files,
    finalize_review,
    format_truncation_log,
    get_required_env,
    load_review_context,
    prioritize_diff_blocks,
    redact_env_var_names,
    split_diff_blocks,
    truncate_diff,
)

MCP_REPO_PROFILE = RepoProfile(
    name="allotmint-mcp",
    persona=(
        "a Java/Spring Boot Model Context Protocol (MCP) server exposing "
        "allotmint data over stdio/HTTP transports."
    ),
    stack_paragraph="""The stack is Java 25 + Spring Boot + the MCP Java SDK (`io.modelcontextprotocol.sdk`), built with Maven.
Key constraints: preserve MCP protocol correctness (tool/resource schemas, stdio framing), keep the
stdio transport free of stray stdout writes (anything not valid MCP JSON-RPC breaks the client), and
avoid regressions in the Spring Boot startup path.""",
    diff_file_types=(
        "Java, XML, YAML, properties, Markdown, shell/PowerShell scripts (.sh/.ps1), Python (.py)"
    ),
    dimension_2_body="""Blocking only: incorrect behaviour, unhandled edge cases, resource leaks (unclosed
streams/connections), null-safety violations, swallowed exceptions, thread-safety
issues, or security/data-loss risks. For documentation PRs: factual errors or
dangerously misleading statements.""",
    dimension_3_title="MCP protocol and Spring Boot safety",
    dimension_3_body="""- Anything writing to stdout on the stdio transport that isn't valid MCP JSON-RPC
  (breaks the protocol framing for stdio clients)?
- Tool/resource schema definitions that don't match their handler's actual behaviour?
- Spring Boot bean wiring, configuration, or startup changes that could break the app
  context, or Maven dependency/scope changes with unintended transitive effects?
- Secrets, permissions, or CI assumptions mishandled?""",
)
