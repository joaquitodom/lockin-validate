# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and the project uses
semantic versioning.

## [0.1.0] - 2026-10-27

First public version (not yet published).

### Added
- Input package reader with manifest (sha256 of every input), own schema and type validation, column aliases,
  required/optional inputs per check, transformation log (applied vs proposed, nothing fixed silently).
- Data checks: duplicates, dates (NYSE / BYMA / none calendars), essential fields, coverage against the calendar, stale
  prices, price jumps and bad ticks, declared corporate actions, accuracy against a reference, point-in-time
  fundamentals, survivorship, ticker identity, trade before signal, signal data after decision.
- Reconstruction of positions, cash and NAV from trades (return base = initial cash) and reconciliation against
  declared positions and results.
- Strategy checks: look-ahead with availability timestamps and a rank-correlation hint, omitted costs (commission and
  slippage separately, zero cost with turnover), metric errors under alternative conventions, rules vs implementation.
- Statistics: Sharpe standard error, Lo (2002) adjustment, PSR, MinTRL, deflated Sharpe, multiple-testing haircut, PBO
  via CSCV, declared number of trials, LLM look-ahead risk checklist.
- Reports in Markdown, JSON and static HTML with disclaimer, evidence, procedure, limitations and prioritised actions.
- CLI (`run`, `init`, `cases`, `explain`, `checks`), Python API (`audit`, `run`), optional MCP server.
- Benchmark battery of 36 synthetic cases (core, adversarial, statistical, data) with generators and expected outcomes.
- Independent oracle, hand-computed case, metamorphic tests and an offline test.

### Ported
- Core review blocks and synthetic cases from the internal review core; data and statistical checks from the earlier
  prototype. See docs/CASE_CHANGES.md.
