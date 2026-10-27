# Security and privacy

## Offline by design

- `lockin-validate run`, `cases`, `init`, `explain` and the MCP server only read local files, compute and write reports
  from templates. There are no network calls, no data downloads, no remote AI and no telemetry. The NYSE calendar is
  computed from rules in the code; the BYMA holiday list ships with the package.
- `tests/test_offline.py` replaces `socket.socket`, `socket.create_connection` and `socket.getaddrinfo` with functions
  that fail, verifies the network is blocked and runs complete cases end to end. It does not prove anything about
  operating-system level isolation: if you need demonstrable isolation, run the tool on a machine or container without a
  network interface.
- Network is only needed once, to install the package and its dependencies (`uv sync` / `pip install`). With a lock file
  and a filled cache, `uv sync --offline` works without network.

## Privacy of inputs

- Originals are opened read-only and never modified; the output folder may not be inside the input folder.
- The console prints only counts and check ids, never data rows or tickers.
- Reports contain evidence (row numbers, dates, tickers, point values), never whole rows. Up to 20 evidence rows per
  finding are kept in report.json and 8 in the Markdown and HTML reports. Treat reports with the same confidentiality as
  the inputs.
- The manifest stores the sha256 of every input so a report can be tied to the exact data it reviewed.

## Reporting a vulnerability

Please report security issues privately to the maintainers (Joaquín Domínguez and Mateo Domínguez) through the contact
listed in the repository hosting page, not in a public issue. Include the version (`lockin-validate --version`), a
minimal input package that reproduces the problem (synthetic data only) and the observed behaviour.
