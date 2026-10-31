"""``lockin-validate init <dir>``: scaffold an input package template.

Writes header-only CSV files (one example row each, marked so it is easy to delete), a commented rules.yaml,
declared_results.json and llm_checklist.json examples, and a short README explaining which file enables which
check. It refuses to write into a non-empty folder.
"""

from __future__ import annotations

import json
from pathlib import Path

from .inputs import DATE_COLUMNS, FILES, NUMERIC_COLUMNS, REQUIREMENTS, SCHEMA

CSV_TEMPLATES: dict[str, str] = {
    "prices.csv": "date,ticker,open,high,low,close,volume,adjusted,available_from\n"
                  "2024-01-02,AAA,10.00,10.20,9.90,10.10,150000,true,2024-01-02T17:00:00\n",
    "signals.csv": "decision_time,ticker,signal,data_date,data_source\n"
                   "2024-01-03T09:30:00,AAA,0.75,2024-01-02,prices\n",
    "trades.csv": "trade_id,timestamp,ticker,side,quantity,price,commission\n"
                  "1,2024-01-03T16:00:00,AAA,buy,100,10.15,1.02\n",
    "positions.csv": "date,ticker,quantity\n2024-01-31,AAA,100\n",
    "costs.csv": "item,value,unit\ncommission,10,bps\nslippage,5,bps\n",
    "fundamentals.csv": "ticker,period_end,filing_date,available_from,roe\n"
                        "AAA,2023-12-31,2024-02-20,2024-02-21T09:30:00,0.15\n",
    "universe.csv": "ticker,start_date,end_date\nAAA,2015-01-02,\n",
    "security_master.csv": "ticker,entity_id,start_date,end_date\nAAA,ENTITY-0001,2015-01-02,\n",
    "corporate_actions.csv": "ticker,date,ratio,type\nAAA,2024-06-10,2,split\n",
    "reference_prices.csv": "date,ticker,close\n2024-01-02,AAA,10.10\n",
    "returns.csv": "date,return\n2024-01-02,0.0012\n",
    "trials.csv": "date,config_001,config_002\n2024-01-02,0.0012,-0.0004\n",
    "benchmark_returns.csv": "date,return\n2024-01-02,0.0009\n",
    "universe_returns.csv": "date,return\n2024-01-02,0.0011\n",
    "unadjusted_prices.csv": "date,ticker,close\n2024-01-02,AAA,10.10\n",
    "dividends.csv": "ticker,ex_date,amount\nAAA,2024-03-15,0.12\n",
    "run_log.csv": "timestamp,run_id,window_start,window_end,config_hash,purpose\n"
                   "2024-01-05T10:00:00,run-001,2015-01-01,2020-12-31,cfg-a1b2,train\n",
    "regimes.csv": "date,inverted_curve\n2024-01-31,0\n",
}

PROTOCOL_YAML = """\
# protocol.yaml: research windows. The test window is single-use unless single_use: false.
train: {start: '2015-01-01', end: '2020-12-31'}
validation: {start: '2021-01-01', end: '2022-12-31'}
test: {start: '2023-01-01', end: '2023-12-31', single_use: true}
reserved:                          # further windows kept untouched for later tests
  - {name: fresh_2024, start: '2024-01-01', end: '2024-06-28', single_use: true}
"""

RULES_YAML = """\
# rules.yaml: the strategy as written down by its owner. Every key is optional; what is declared is checked.
strategy: free text describing the strategy
universe: [AAA, BBB, CCC]          # or "all"
period: {start: 2024-01-02, end: 2024-06-28}
signal: {column: signal, order: desc}        # rank on this column of signals.csv; desc = higher is better
selection: {top_n: 3}
rebalance: {frequency: monthly, timing: first_day}   # monthly | weekly | daily ; first_day | last_day
sizing: equal_weight
costs: {commission_rate: 0.001, slippage_rate: 0.0005}   # FRACTIONS of notional (0.001 = 10 bps), separately
research: {n_trials: 1}            # number of configurations tried (alternative to declared_results.n_trials)
benchmark: {name: MY_INDEX, weighting: equal_weighted}   # construction of benchmark_returns.csv (or cap_weighted)
required_inputs: [roe]             # inputs the model needs for each scored name (signals or fundamentals columns)
min_input_share: 0.8               # minimum share of required_inputs a scored name must have
conditional_rules:                 # rules that switch on by regime (columns of regimes.csv)
  - {name: inverted_curve_rule, column: inverted_curve}
conventions:
  initial_cash: 100000             # NAV starts here: return base = initial cash
  valuation: close
  leverage: false
  short_selling: false
  calendar: nyse                   # nyse | byma | none
  # holidays_file: holidays.csv    # optional with byma: your own (date, reason, note) file in this folder
  review_date: '2026-10-27'        # limit for "future dates" (default: today)
  end_date: '2024-06-28'           # end of the reconstructed NAV (default: last price)
  periods_per_year: 252
  sharpe: arithmetic               # arithmetic | geometric
  std_ddof: 1
  risk_free_annual: 0.0
  annual_return: geometric         # geometric | arithmetic | calendar
  stale_run: 10                    # identical consecutive closes that flag a frozen price
  jump_threshold: 0.40             # one-period move that flags a price jump
  tolerances: {total_return: 0.005, sharpe: 0.05}   # optional, override the defaults
"""

DECLARED = {
    "total_return": 0.0523, "annual_return": 0.1071, "sharpe": 1.12, "max_drawdown": -0.064, "n_trades": 42,
    "final_nav": 105230.0, "n_trials": 1,
    "convention": {"periods_per_year": 252, "sharpe": "arithmetic", "std_ddof": 1, "risk_free_annual": 0.0,
                   "annual_return": "geometric", "returns": "simple"},
    "curve": [{"date": "2024-01-31", "nav": 101200.0}],
}

LLM_CHECKLIST = {
    "uses_llm": False, "model_name": "-", "model_training_cutoff": "2024-10", "backtest_start": "2019-01-01",
    "backtest_end": "2023-12-31", "uses_company_names": None, "uses_tickers": None, "uses_explicit_dates": None,
    "uses_news_or_filings_text": None, "anonymized_entities": None, "retrieval_pit_filtered": None,
    "pit_model": None, "post_cutoff_evaluation": None, "memorization_probe_done": None,
}


def _example_value(table: str, col: str) -> str:
    if col in DATE_COLUMNS.get(table, []) or col.endswith(("_date", "_time", "timestamp")) or col in ("date", "timestamp"):
        return "2024-01-02"
    if col in NUMERIC_COLUMNS.get(table, []) or col in ("weight", "value", "prediction", "actual", "forecast", "pnl",
                                                         "return", "signal", "quantity", "price", "probability"):
        return "0.0"
    if col == "split":
        return "train"
    if col == "side":
        return "buy"
    return "EXAMPLE"


def usecase_templates() -> dict[str, str]:
    """One header + one example row for every table declared by a registered use-case module."""
    from . import usecases

    usecases.load_all()
    out: dict[str, str] = {}
    for uc in usecases.REGISTRY.values():
        for table, fname in uc.files.items():
            if fname in CSV_TEMPLATES or not fname.endswith(".csv"):
                continue
            sch = SCHEMA.get(table, {})
            cols = list(sch.get("required", [])) + list(sch.get("optional", []))
            if not cols:
                continue
            out[fname] = ",".join(cols) + "\n" + ",".join(_example_value(table, c) for c in cols) + "\n"
    return out


def scaffold(target: str | Path, force: bool = False) -> list[Path]:
    d = Path(target)
    if d.exists() and any(d.iterdir()) and not force:
        raise FileExistsError(f"{d} is not empty (use --force to write anyway)")
    d.mkdir(parents=True, exist_ok=True)
    written = []
    templates = dict(CSV_TEMPLATES)
    templates.update(usecase_templates())
    for name, content in templates.items():
        p = d / name
        p.write_text(content, encoding="utf-8")
        written.append(p)
    (d / "rules.yaml").write_text(RULES_YAML, encoding="utf-8")
    (d / "protocol.yaml").write_text(PROTOCOL_YAML, encoding="utf-8")
    (d / "declared_results.json").write_text(json.dumps(DECLARED, indent=2), encoding="utf-8")
    (d / "llm_checklist.json").write_text(json.dumps(LLM_CHECKLIST, indent=2), encoding="utf-8")
    (d / "version.txt").write_text("my-strategy 0.1.0 (git commit abc1234)\n", encoding="utf-8")
    lines = ["# Input package template", "",
             "Every file here contains ONE example row: replace it with your data or delete the file. No file is "
             "mandatory; checks that lack inputs are reported as NOT_EXECUTABLE with the missing input.", "",
             "Full specification: docs/INPUT_SPEC.md in the lockin-validate repository; the tables of the use-case "
             "modules (signals, ml, risk, forecast, portfolio, live) are described in docs/usecases/.", "",
             "| Check | Required inputs | Optional inputs |", "|---|---|---|"]
    for k, v in REQUIREMENTS.items():
        lines.append(f"| {k} | {', '.join(v['required']) or '-'} | {', '.join(v['optional']) or '-'} |")
    lines += ["", "Run: `lockin-validate run <this folder> --out <another folder>`", ""]
    (d / "README_INPUTS.md").write_text("\n".join(lines), encoding="utf-8")
    written += [d / "rules.yaml", d / "protocol.yaml", d / "declared_results.json", d / "llm_checklist.json", d / "version.txt",
                d / "README_INPUTS.md"]
    return written
