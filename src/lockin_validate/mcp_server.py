"""Minimal MCP server (stdio) exposing the review to Claude and other agents.

Tools: ``run_validation`` (review a local input folder), ``explain_check``, ``list_checks`` and ``list_use_cases``.
Requires the optional extra: ``pip install "lockin-validate[mcp]"``. Start with ``lockin-validate-mcp``.
The tools read local files only and send nothing anywhere.
"""

from __future__ import annotations

from . import tools


def _server_class():
    """High-level server class for the installed MCP SDK (2.x ``MCPServer`` or 1.x ``FastMCP``)."""
    try:
        from mcp.server.mcpserver import MCPServer  # type: ignore[import-not-found]
        return MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]
        return FastMCP


def build_server():
    server = _server_class()("lockin-validate")

    @server.tool()
    def run_validation(input_dir: str, out_dir: str | None = None, profile: str | None = None,
                       include_report: bool = False) -> dict:
        """Review a local input package folder (prices.csv, signals.csv, trades.csv, positions.csv, costs.csv,
        fundamentals.csv, universe.csv, rules.yaml, declared_results.json, trials.csv, ...). Returns counts per
        status and every non-PASS finding. With out_dir, writes REPORT.md, report.json and report.html there (it must
        not be inside input_dir). Profiles: equities_daily (default), nyse_equities_daily, byma_equities_daily,
        equities_monthly, crypto_daily."""
        return tools.run_tool(input_dir, out_dir, profile, include_report)

    @server.tool()
    def explain_check(check_id: str) -> dict:
        """Explain a check by id (e.g. 'deflated_sharpe', 'lookahead', 'omitted_costs'): what it measures, why it
        matters, how to fix it, what it allows to conclude, required inputs and references."""
        return tools.explain_tool(check_id)

    @server.tool()
    def list_checks() -> dict:
        """List every check id with its block and title."""
        return tools.list_checks_tool()

    @server.tool()
    def list_use_cases() -> list:
        """List the use-case modules (alpha signals, ML models, VaR / ES risk models, point forecasts, portfolio
        allocations, live track record vs backtest): what each validates, who it is for, its input files and
        checks."""
        return tools.list_use_cases_tool()

    return server


def main() -> None:
    try:
        server = build_server()
    except ImportError:
        raise SystemExit('the MCP server needs the optional extra: pip install "lockin-validate[mcp]"') from None
    server.run()


if __name__ == "__main__":
    main()
