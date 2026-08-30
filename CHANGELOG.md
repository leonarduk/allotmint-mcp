# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

[Unreleased]: https://github.com/leonarduk/allotmint-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/leonarduk/allotmint-mcp/compare/v0.1.0...v0.2.0
[0.0.1]: https://github.com/leonarduk/allotmint-mcp/releases/tag/v0.0.1

## [Unreleased]

Add release notes here under the relevant headings before creating a release. Call out breaking
changes and required migrations explicitly.

### Added

- `allotmint_research` accepts an optional `session_id` to hold a multi-turn conversation
  across separate calls (#548): the research-agent sidecar threads the prior turns into
  the agent run via `pydantic_ai`'s `message_history`, keyed by `session_id`, in-memory
  only and capped by the new `ALLOTMINT_RESEARCH_MAX_CONVERSATION_SESSIONS` /
  `ALLOTMINT_RESEARCH_MAX_CONVERSATION_MESSAGES` settings. Omitting `session_id`
  preserves the original single-shot behavior unchanged. **Migration**: no action
  required for existing callers; clients that want conversational context should
  generate a `session_id` per conversation and pass it on every `ask` call. Sessions do
  not survive a sidecar restart and are not shared across horizontally-scaled sidecar
  instances -- both are known, documented limitations, not bugs. This is a
  backward-compatible addition; bump the minor version at the next release.

### Changed

### Deprecated

### Removed

### Fixed

- `AllotMintResearchTool`'s `optionalInteger` (the #250 non-integral `lookback_days`
  rejection) now compares against `Math.rint` with a small tolerance instead of exact
  floating-point equality, so a mathematically-integral value with a JSON-parsing
  representation artifact (e.g. `30.000000000000004`) is accepted instead of wrongly
  rejected as non-integral, while genuinely fractional values (e.g. `30.5`) are still
  rejected.

### Security

## [0.2.0] - 2026-08-16

### Added

- `allotmint_data_quality` MCP tool exposing the read-write data-quality admin API
  (issues/series/preview/audit/fix/dedupe/undo), mirroring `allotmint_instrument` /
  `allotmint_portfolio`. Write actions (fix/dedupe/undo) require `confirm=true` and
  `allotmint.mcp.write.enabled`, matching the existing reconciliation-apply gate
  (#498, #504).
- Sequential worker-verifier orchestration for the research agent sidecar, so a
  research answer is checked by a second pass before being returned (#517).
- A dedicated `allotmint.api.post-read-timeout-seconds` timeout for POST requests
  (e.g. large reconciliation payloads), separate from the general read timeout,
  since those calls legitimately take longer (#475).

### Fixed

- `--start-deps` now detects an unreachable Docker daemon and refuses to serve a
  broken UI, instead of launching as if the stack were healthy (#496, #497).

### Changed

- Bumped `actions/checkout` (4 → 7), `actions/setup-python` (5 → 7), and
  `actions/setup-java` (5.6.0 → 5.7.0) in CI workflows.

## [0.0.1] - 2026-07-19

### Added

- Initial Spring Boot MCP server with stdio transport and an `echo` tool.
