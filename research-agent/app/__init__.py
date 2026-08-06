"""AllotMint research agent sidecar.

Runs the agentic RAG loop behind the `allotmint_research` MCP tool: retrieve
relevant context from pgvector, chain the read-only v0 MCP tools, and return a
grounded, cited answer. See ../README.md.
"""
