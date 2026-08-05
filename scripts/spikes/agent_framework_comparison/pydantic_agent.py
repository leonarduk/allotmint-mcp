"""
Throwaway spike script for allotmint-mcp issue #12: Pydantic AI side.

Runs the same sample compound question as langgraph_agent.py through a
Pydantic AI agent wired to the same stubbed tools (stub_tools.py) and the
same local Ollama model, for a fair side-by-side comparison. Not wired into
the MCP server -- see the issue for scope.

MODEL defaults to a locally-imported "DeepSeek-Qwen3-8B" tag; see
langgraph_agent.py's docstring for how to get an equivalent model.

Usage:
    pip install -r requirements.txt
    python pydantic_agent.py
"""

import sys

# Model output can include non-cp1252 characters (e.g. reasoning-model markup);
# force UTF-8 stdout so this doesn't crash on Windows' default console codepage.
sys.stdout.reconfigure(encoding="utf-8")

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

import stub_tools

MODEL = "DeepSeek-Qwen3-8B:latest"
SAMPLE_QUESTION = "How has my tech exposure changed this year, and why? My owner slug is 'demo'."
SYSTEM_PROMPT = (
    "You are a portfolio research assistant with access to AllotMint tools. To answer a "
    "question about how a sector's exposure has changed, you MUST call these tools in order "
    "and MUST NOT answer until both have been called: "
    "(1) allotmint_portfolio with action='exposure' to see current vs year-ago sector weights; "
    "(2) allotmint_instrument with action='news' and ticker='NVDA' to get headlines explaining "
    "the move. Never invent a tool result or a ticker/company that was not returned by a tool. "
    "Ground every claim in the actual JSON returned by the tools you called."
)

model = OpenAIChatModel(MODEL, provider=OllamaProvider(base_url="http://localhost:11434/v1"))
agent = Agent(model, instructions=SYSTEM_PROMPT)


@agent.tool_plain
def allotmint_portfolio(
    action: str, owner: str, account_type: str | None = None, currency: str | None = None
) -> dict:
    """Reads one owner's AllotMint portfolio. Actions: summary, exposure, holdings."""
    return stub_tools.allotmint_portfolio(action, owner, account_type, currency)


@agent.tool_plain
def allotmint_instrument(
    action: str, query: str | None = None, ticker: str | None = None, exchange: str | None = None
) -> dict:
    """Looks up an AllotMint instrument. Actions: search, detail, prices, news."""
    return stub_tools.allotmint_instrument(action, query, ticker, exchange)


@agent.tool_plain
def allotmint_market(action: str) -> dict:
    """Returns AllotMint market overview, movers, or index levels. Actions: overview, movers, indices."""
    return stub_tools.allotmint_market(action)


@agent.tool_plain
def allotmint_health() -> dict:
    """Checks connectivity to the AllotMint backend."""
    return stub_tools.allotmint_health()


def main():
    print(f"Question: {SAMPLE_QUESTION}\n")
    print("--- trace ---")

    result = agent.run_sync(SAMPLE_QUESTION)

    for message in result.new_messages():
        for part in message.parts:
            kind = type(part).__name__
            if kind == "ToolCallPart":
                print(f"[tool call] {part.tool_name}({part.args})")
            elif kind == "ToolReturnPart":
                print(f"[tool result] {part.tool_name} -> {part.content}")
            elif kind == "TextPart":
                print(f"[text] {part.content}")

    print("\n--- final answer ---")
    print(result.output)


if __name__ == "__main__":
    main()
