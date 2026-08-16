# Product framing

AllotMint MCP is an integration layer for people who already use AllotMint and want to
inspect their portfolio from an MCP-capable assistant. It is not a standalone portfolio
manager or a general investment-advice product: AllotMint remains the system of record,
while this server gives an assistant narrowly defined access to its data and operations.

## Target user and problem

The primary user is a self-directed investor or technically confident household portfolio
manager who has holdings in AllotMint and uses an MCP client such as Claude Desktop. A
secondary user is a developer evaluating how to expose an existing financial application
to AI clients without moving its business rules into prompts.

Portfolio questions often require switching between dashboards, holdings tables, market
data, and broker exports. A generic assistant cannot safely access that private, structured
context, and copying it into a chat is repetitive and error-prone. AllotMint MCP exposes
explicit tools for portfolio, instrument, market, reconciliation, file, and data-quality
workflows. The optional research agent can combine those deterministic results with
retrieved documents and report the sources used. The intended value is faster exploration
and administration of an existing portfolio, not automated trading or personalised
financial advice.

## Product and technical trade-offs

| Decision | What we chose and why | Cost of the choice |
| --- | --- | --- |
| Build a thin MCP adapter rather than a new portfolio backend | Keep portfolio calculations, validation, and broker normalisation in AllotMint, so MCP and web clients share one source of truth. | Users must deploy or connect to AllotMint; this project has little value on its own. |
| Deterministic tools first; agentic research opt-in | Core tasks remain predictable and require only the backend. The LLM path is disabled by default and grounded in retrieved documents and recorded tool calls. | Rich, cross-source questions require a Python sidecar, a model, and pgvector, increasing operational complexity and latency. |
| Read-only defaults with explicit write enablement | Reduce the blast radius of an incorrect model action; write workflows are separately enabled and protected by backend validation, backups, and audit records. | Setup has more feature flags and an administrator must deliberately enable automation. |
| Local-first, open components | The Java server, PostgreSQL/pgvector, local embeddings, and Ollama can run without per-request vendor fees or sending portfolio context to a hosted model. | Local models need capable hardware and may be slower or less reliable than hosted models; self-hosting shifts maintenance to the operator. |
| Support stdio and HTTP transports | Stdio makes desktop setup simple; HTTP supports shared services and lets the research agent call the same MCP tools. | Two deployment modes expand the configuration and testing surface. |
| Build the domain adapter; buy model capability when useful | The AllotMint-specific tool contracts and safety boundaries are the differentiator. LLM providers and optional observability are replaceable integrations rather than capabilities to build from scratch. | Hosted providers introduce variable spend, internet egress, privacy review, and vendor availability risk. |

## Rough running-cost profile

These are cost drivers rather than a quote: actual spend depends on hardware, hosting
region, traffic, corpus size, model choice, and whether the AllotMint backend already
exists.

- **Core MCP server:** no usage-based fee from this project. It is one small JVM process
  plus the existing AllotMint backend. Local use mainly consumes modest CPU and memory;
  a hosted deployment adds the chosen compute, networking, logging, and backend costs.
- **Local research setup:** no per-token API charge. It adds the Python research service,
  PostgreSQL with pgvector, disk for the corpus, local embedding work, and Ollama. The main
  economic cost is the machine (and electricity); useful latency may require substantially
  more RAM or GPU capacity than the core server.
- **Hosted research setup:** model cost is variable per request and grows with prompt,
  retrieved context, output length, and agent tool-call count. Provider pricing should be
  checked when deploying. A managed database and optional hosted Langfuse add their own
  storage, ingestion, retention, and subscription costs.
- **Operational costs:** backups, patching, monitoring, TLS, authentication, secret
  handling, and incident response can outweigh infrastructure spend for a production or
  multi-user deployment. The default short-lived backend token flow is suitable for
  personal use but adds friction and is not a turnkey enterprise identity solution.

The lowest-cost path is therefore the deterministic server against an already-running
AllotMint backend. Enable local research when richer synthesis justifies extra hardware and
operations; choose hosted model or observability services when their capability and reduced
maintenance justify variable spend and the privacy trade-off.
