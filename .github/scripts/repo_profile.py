"""allotmint-mcp's RepoProfile — the sole local override allowed by cicaid#409.

Everything else (review logic, verdict extraction, follow-up creation, diff
preparation, discussion fetching, symbol verification, LLM labels) is in the
installed cicaid-devtools package. This file only supplies the repo-specific
persona, stack description, and MCP protocol safety checks that the shared
review prompt injects via RepoProfile.
"""

from __future__ import annotations

from cicaid_devtools.lib.review_common import RepoProfile

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
