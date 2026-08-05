"""
Stub versions of the four v0 allotmint-mcp tools, shared by both agent
framework spikes (langgraph_agent.py, pydantic_agent.py).

Mirrors the real input schemas from the Java tool implementations:
  - AllotMintPortfolioTool.java  (allotmint_portfolio)
  - AllotMintInstrumentTool.java (allotmint_instrument)
  - AllotMintMarketTool.java     (allotmint_market)
  - AllotMintHealthTool.java     (allotmint_health)

Not wired to the real AllotMint backend -- see issue #12 for scope. The
`exposure` and `news` stub data is adapted from the sibling pgvector spike's
fixtures (scripts/spikes/pgvector_research/fixtures/report_snapshot.json and
news_items.json) so both spikes tell a consistent story about the same
sample question: "how has my tech exposure changed this year, and why?"
"""

# Sector weights for the one stubbed owner, with a year-ago comparison so the
# "changed this year" half of the sample question is answerable. Shape
# matches scripts/spikes/pgvector_research/fixtures/report_snapshot.json.
_SECTOR_EXPOSURE = {
    "demo": {
        "as_of": "2026-08-01",
        "sectors": [
            {"sector": "Technology", "weight_pct": 27.0, "weight_pct_year_ago": 18.0},
            {"sector": "Financials", "weight_pct": 15.5, "weight_pct_year_ago": 17.0},
            {"sector": "Healthcare", "weight_pct": 12.0, "weight_pct_year_ago": 13.5},
            {"sector": "Consumer Discretionary", "weight_pct": 10.5, "weight_pct_year_ago": 11.0},
            {"sector": "Industrials", "weight_pct": 9.0, "weight_pct_year_ago": 10.0},
            {"sector": "Other", "weight_pct": 26.0, "weight_pct_year_ago": 29.5},
        ],
    }
}

# Recent headlines for tech names, driving the "why" half of the question.
# Shape matches scripts/spikes/pgvector_research/fixtures/news_items.json.
_NEWS_BY_TICKER = {
    "NVDA": [
        {
            "ticker": "NVDA",
            "headline": "NVIDIA raises data center revenue guidance on AI chip demand",
            "summary": "NVIDIA lifted its quarterly revenue guidance, citing sustained demand "
            "for its data center GPUs from cloud providers building out AI infrastructure.",
            "published": "2026-05-14",
        }
    ],
    "MSFT": [
        {
            "ticker": "MSFT",
            "headline": "Microsoft Azure growth accelerates on AI services adoption",
            "summary": "Microsoft reported Azure revenue growth of 31%, ahead of estimates, "
            "attributed to enterprise adoption of Copilot and AI-related cloud services.",
            "published": "2026-04-28",
        }
    ],
    "ASML": [
        {
            "ticker": "ASML",
            "headline": "ASML order backlog grows as chipmakers invest in next-gen lithography",
            "summary": "ASML reported a larger-than-expected order backlog as semiconductor "
            "manufacturers continue investing in EUV lithography equipment.",
            "published": "2026-06-02",
        }
    ],
    "SMCI": [
        {
            "ticker": "SMCI",
            "headline": "Super Micro Computer expands AI server production capacity",
            "summary": "Super Micro Computer announced expanded manufacturing capacity for "
            "AI-optimized server racks, amid strong demand from hyperscale customers.",
            "published": "2026-03-19",
        }
    ],
}

_TECH_TICKERS = list(_NEWS_BY_TICKER)


def allotmint_portfolio(
    action: str, owner: str, account_type: str | None = None, currency: str | None = None
) -> dict:
    """Stub of the allotmint_portfolio tool. Actions: summary, exposure, holdings."""
    if action == "exposure":
        data = _SECTOR_EXPOSURE.get(owner, _SECTOR_EXPOSURE["demo"])
        return {"action": "exposure", "owner": owner, **data}
    if action == "summary":
        return {
            "action": "summary",
            "owner": owner,
            "as_of": "2026-08-01",
            "total_value_gbp": 250000.00,
            "day_change_gbp": 1200.50,
        }
    if action == "holdings":
        return {
            "action": "holdings",
            "owner": owner,
            "as_of": "2026-08-01",
            "holdings": [
                {"ticker": "NVDA.US", "sector": "Technology", "market_value_gbp": 32000.00},
                {"ticker": "MSFT.US", "sector": "Technology", "market_value_gbp": 28500.00},
                {"ticker": "ASML.AS", "sector": "Technology", "market_value_gbp": 15200.00},
            ],
        }
    return {"error": f"unsupported action '{action}'; expected summary, exposure, or holdings"}


def allotmint_instrument(
    action: str,
    query: str | None = None,
    ticker: str | None = None,
    exchange: str | None = None,
) -> dict:
    """Stub of the allotmint_instrument tool. Actions: search, detail, prices, news."""
    if action == "news":
        base_ticker = (ticker or "").split(".")[0].upper()
        if base_ticker in _NEWS_BY_TICKER:
            return {"action": "news", "ticker": ticker, "items": _NEWS_BY_TICKER[base_ticker]}
        return {"action": "news", "ticker": ticker, "items": []}
    if action == "search":
        term = (query or "").lower()
        matches = [t for t in _TECH_TICKERS if term in t.lower()]
        return {"action": "search", "query": query, "matches": matches}
    if action == "prices":
        return {"action": "prices", "ticker": ticker, "price": 123.45, "currency": "USD"}
    if action == "detail":
        base_ticker = (ticker or "").split(".")[0].upper()
        return {
            "action": "detail",
            "ticker": ticker,
            "news": _NEWS_BY_TICKER.get(base_ticker, []),
        }
    return {"error": f"unsupported action '{action}'; expected search, detail, prices, or news"}


def allotmint_market(action: str) -> dict:
    """Stub of the allotmint_market tool. Actions: overview, movers, indices."""
    if action == "overview":
        return {"action": "overview", "sentiment": "risk-on", "note": "AI capex cycle continues"}
    if action == "movers":
        return {"action": "movers", "gainers": _TECH_TICKERS, "losers": []}
    if action == "indices":
        return {"action": "indices", "S&P 500": {"change_pct": 0.4}, "NASDAQ": {"change_pct": 0.9}}
    return {"error": f"unsupported action '{action}'; expected overview, movers, or indices"}


def allotmint_health() -> dict:
    """Stub of the allotmint_health tool. No arguments."""
    return {"reachable": True, "version": "stub", "baseUrl": "http://localhost:8000"}
