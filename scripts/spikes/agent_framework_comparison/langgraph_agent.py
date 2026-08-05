"""
Throwaway spike script for allotmint-mcp issue #12: LangGraph side.

Runs the sample compound question through a LangGraph ReAct agent wired to
stubbed versions of the four v0 allotmint-mcp tools (stub_tools.py), backed
by a local Ollama model. Not wired into the MCP server -- see the issue for
scope.

MODEL defaults to a locally-imported "DeepSeek-Qwen3-8B" tag (DeepSeek's
R1-distilled Qwen3-8B, tool-calling capable). If you don't have that tag
imported, the closest publicly-pullable equivalent is `ollama pull qwen3:8b`
-- or set MODEL to "llama3.2" (`ollama pull llama3.2`), which this spike also
exercised; see README.md for how each behaved.

Usage:
    pip install -r requirements.txt
    python langgraph_agent.py
"""

import sys

# Model output can include non-cp1252 characters (e.g. reasoning-model markup);
# force UTF-8 stdout so this doesn't crash on Windows' default console codepage.
sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent

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


@tool
def allotmint_portfolio(
    action: str, owner: str, account_type: str | None = None, currency: str | None = None
) -> dict:
    """Reads one owner's AllotMint portfolio. Actions: summary, exposure, holdings."""
    return stub_tools.allotmint_portfolio(action, owner, account_type, currency)


@tool
def allotmint_instrument(
    action: str, query: str | None = None, ticker: str | None = None, exchange: str | None = None
) -> dict:
    """Looks up an AllotMint instrument. Actions: search, detail, prices, news."""
    return stub_tools.allotmint_instrument(action, query, ticker, exchange)


@tool
def allotmint_market(action: str) -> dict:
    """Returns AllotMint market overview, movers, or index levels. Actions: overview, movers, indices."""
    return stub_tools.allotmint_market(action)


@tool
def allotmint_health() -> dict:
    """Checks connectivity to the AllotMint backend."""
    return stub_tools.allotmint_health()


def main():
    model = ChatOllama(model=MODEL, temperature=0)
    agent = create_react_agent(
        model,
        [allotmint_portfolio, allotmint_instrument, allotmint_market, allotmint_health],
        prompt=SYSTEM_PROMPT,
    )

    print(f"Question: {SAMPLE_QUESTION}\n")
    print("--- trace ---")

    final_answer = None
    for step in agent.stream(
        {"messages": [{"role": "user", "content": SAMPLE_QUESTION}]}, stream_mode="values"
    ):
        message = step["messages"][-1]
        message.pretty_print()
        final_answer = message.content

    print("\n--- final answer ---")
    print(final_answer)


if __name__ == "__main__":
    main()
