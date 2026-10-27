"""Input package: reading, manifest, schema and type validation, required inputs per check.

An input package is ONE folder with fixed file names (docs/INPUT_SPEC.md). No file is mandatory:
the audit runs what the inputs allow and every check that cannot run is reported as
NOT_EXECUTABLE with the missing input. Originals are opened read-only and never written; the
report must go to a different folder.

Tables (CSV, UTF-8, comma separator, ISO 8601 dates, dot decimal):

  prices.csv             date, ticker, close [open, high, low, volume, adjusted, available_from, source]
  signals.csv            decision_time, ticker, signal [data_date, data_source]
  trades.csv             timestamp, ticker, side, quantity, price [commission, trade_id]
  positions.csv          date, ticker, quantity
  costs.csv              item, value, unit                       (commission / slippage; pct, bps or fraction)
  fundamentals.csv       ticker, period_end [filing_date, available_from, any accounting field]
  universe.csv           ticker, start_date [end_date]            (point-in-time membership)
  security_master.csv    ticker, entity_id [start_date, end_date] (identity, ticker recycling)
  corporate_actions.csv  ticker, date, ratio [type]               (splits: new shares / old shares)
  reference_prices.csv   date, ticker, close                      (independent second source)
  returns.csv            date, return  (or date, nav)             (strategy periodic returns)
  trials.csv             date, <one column of returns per configuration tried>
  rules.yaml             structured rules and conventions
  declared_results.json  total_return, annual_return, sharpe, max_drawdown, n_trades, final_nav
                         [convention, curve, n_trials]
  llm_checklist.json     look-ahead risk checklist when an LLM is part of the strategy
  version.txt            code / strategy version (optional; alias code_version.txt)
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .calendars import Calendar, calendar_from
from .findings import CONFIRMED_ERROR, NEEDS_REVIEW, PASS, AuditResult, Finding
from .profiles import DEFAULTS, get_profile
from .transformations import TransformationLog

FILES: dict[str, str] = {
    "prices": "prices.csv",
    "signals": "signals.csv",
    "trades": "trades.csv",
    "positions": "positions.csv",
    "costs": "costs.csv",
    "fundamentals": "fundamentals.csv",
    "universe": "universe.csv",
    "security_master": "security_master.csv",
    "corporate_actions": "corporate_actions.csv",
    "reference_prices": "reference_prices.csv",
    "returns": "returns.csv",
    "trials": "trials.csv",
    "rules": "rules.yaml",
    "declared_results": "declared_results.json",
    "llm_checklist": "llm_checklist.json",
    "version": "version.txt",
}
FILE_ALIASES = {"version": ["code_version.txt"], "rules": ["rules.yml"]}
NON_TABLE = {"rules", "declared_results", "llm_checklist", "version"}

SCHEMA: dict[str, dict[str, list[str]]] = {
    "prices": {"required": ["date", "ticker", "close"],
               "optional": ["open", "high", "low", "volume", "adjusted", "available_from", "source"]},
    "signals": {"required": ["decision_time", "ticker", "signal"], "optional": ["data_date", "data_source"]},
    "trades": {"required": ["timestamp", "ticker", "side", "quantity", "price"],
               "optional": ["commission", "trade_id"]},
    "positions": {"required": ["date", "ticker", "quantity"], "optional": []},
    "costs": {"required": ["item", "value", "unit"], "optional": []},
    "fundamentals": {"required": ["ticker", "period_end"], "optional": ["filing_date", "available_from"]},
    "universe": {"required": ["ticker", "start_date"], "optional": ["end_date"]},
    "security_master": {"required": ["ticker", "entity_id"], "optional": ["start_date", "end_date"]},
    "corporate_actions": {"required": ["ticker", "date", "ratio"], "optional": ["type"]},
    "reference_prices": {"required": ["date", "ticker", "close"], "optional": []},
    "returns": {"required": ["date"], "optional": ["return", "nav"]},
    "trials": {"required": ["date"], "optional": []},
}

ALIASES: dict[str, dict[str, list[str]]] = {
    "prices": {"date": ["datetime", "timestamp", "day"], "ticker": ["symbol"],
               "close": ["adj_close", "adjclose", "adjusted_close", "price"], "volume": ["vol"],
               "adjusted": ["is_adjusted"], "available_from": ["available_at", "available_date"]},
    "signals": {"decision_time": ["timestamp", "decision_date", "date", "decision_timestamp"],
                "ticker": ["symbol"], "signal": ["score", "value"], "data_date": ["as_of", "data_as_of"],
                "data_source": ["source"]},
    "trades": {"timestamp": ["date", "datetime", "time", "execution_time"], "ticker": ["symbol"],
               "side": ["direction", "action"], "quantity": ["qty", "shares", "units"],
               "price": ["fill_price", "execution_price"], "commission": ["fee", "fees", "commissions"],
               "trade_id": ["id", "order_id"]},
    "positions": {"date": ["as_of"], "ticker": ["symbol"], "quantity": ["qty", "shares", "units"]},
    "costs": {"item": ["concept", "type", "name"], "value": ["amount"], "unit": ["units"]},
    "fundamentals": {"ticker": ["symbol"], "period_end": ["fiscal_period_end", "report_period"],
                     "filing_date": ["filed", "filing", "publication_date"],
                     "available_from": ["available_date", "available_at", "knowledge_date"]},
    "universe": {"ticker": ["symbol"], "start_date": ["start", "added", "from"], "end_date": ["end", "removed", "to"]},
    "security_master": {"ticker": ["symbol"], "entity_id": ["permid", "figi", "cik", "company_id"],
                        "start_date": ["start", "from"], "end_date": ["end", "to"]},
    "corporate_actions": {"ticker": ["symbol"], "date": ["ex_date", "effective_date"],
                          "ratio": ["split_ratio", "factor"], "type": ["action"]},
    "reference_prices": {"date": ["datetime"], "ticker": ["symbol"], "close": ["adj_close", "adjclose", "price"]},
    "returns": {"date": ["datetime", "timestamp"], "return": ["ret", "returns", "strategy_return", "r"],
                "nav": ["equity", "value", "portfolio_value"]},
    "trials": {"date": ["datetime", "timestamp"]},
}

DATE_COLUMNS = {"prices": ["date", "available_from"], "signals": ["decision_time", "data_date"],
                "trades": ["timestamp"], "positions": ["date"],
                "fundamentals": ["period_end", "filing_date", "available_from"],
                "universe": ["start_date", "end_date"], "security_master": ["start_date", "end_date"],
                "corporate_actions": ["date"], "reference_prices": ["date"], "returns": ["date"], "trials": ["date"]}
NUMERIC_COLUMNS = {"prices": ["close", "open", "high", "low", "volume"], "signals": ["signal"],
                   "trades": ["quantity", "price", "commission"], "positions": ["quantity"], "costs": ["value"],
                   "corporate_actions": ["ratio"], "reference_prices": ["close"], "returns": ["return", "nav"]}

SIDES = {"buy": "buy", "sell": "sell", "b": "buy", "s": "sell", "long": "buy", "short": "sell"}

# Inputs needed by each check. "table(column)" requires that column with at least one value;
# "a or b" accepts either. Documented in docs/INPUT_SPEC.md and shipped in the JSON report.
REQUIREMENTS: dict[str, dict[str, list[str]]] = {
    "schema_and_types": {"required": [], "optional": [k for k in SCHEMA]},
    "duplicates": {"required": ["prices"], "optional": ["trades", "signals", "positions"]},
    "dates": {"required": ["prices"], "optional": ["trades", "signals", "positions", "rules"]},
    "essential_fields": {"required": ["prices"], "optional": ["trades", "signals", "positions"]},
    "coverage": {"required": ["prices"], "optional": ["trades", "rules"]},
    "trade_before_signal": {"required": ["trades", "signals"], "optional": []},
    "signal_data_after_decision": {"required": ["signals", "signals(data_date)"], "optional": []},
    "stale_prices": {"required": ["prices"], "optional": ["trades"]},
    "price_jumps": {"required": ["prices"], "optional": ["corporate_actions"]},
    "corporate_actions": {"required": ["prices", "corporate_actions"], "optional": []},
    "reference_accuracy": {"required": ["prices", "reference_prices"], "optional": []},
    "pit_fundamentals": {"required": ["fundamentals"], "optional": ["signals"]},
    "survivorship": {"required": ["prices", "universe"], "optional": ["fundamentals", "trades"]},
    "ticker_identity": {"required": ["prices", "security_master"], "optional": ["fundamentals"]},
    "reconstruction": {"required": ["trades", "prices"], "optional": ["rules"]},
    "positions_reconciliation": {"required": ["trades", "prices", "positions"], "optional": []},
    "results_reconciliation": {"required": ["trades", "prices", "declared_results"], "optional": ["rules"]},
    "lookahead": {"required": ["signals", "signals(data_date)",
                               "prices(available_from) or fundamentals(available_from) or fundamentals(filing_date)"],
                  "optional": []},
    "omitted_costs": {"required": ["trades", "prices"], "optional": ["rules", "costs", "declared_results"]},
    "metrics": {"required": ["trades", "prices", "declared_results"], "optional": ["rules"]},
    "rules_vs_implementation": {"required": ["rules", "signals", "trades", "prices"], "optional": []},
    "sharpe_significance": {"required": ["trades and prices, or returns"], "optional": ["rules"]},
    "sharpe_autocorrelation": {"required": ["trades and prices, or returns"], "optional": ["rules"]},
    "trials_declared": {"required": ["declared_results(n_trials) or trials"], "optional": ["returns"]},
    "deflated_sharpe": {"required": ["trades and prices, or returns", "declared_results(n_trials) or trials"],
                        "optional": []},
    "multiple_testing": {"required": ["trades and prices, or returns", "declared_results(n_trials) or trials"],
                         "optional": []},
    "pbo": {"required": ["trials (at least 2 configurations)"], "optional": []},
    "llm_lookahead_risk": {"required": ["llm_checklist"], "optional": ["returns"]},
}

# Extension point: callables (Package) -> list[Finding] to plug Pandera / Great Expectations later.
EXTERNAL_VALIDATORS: list[Callable[[Package], list[Finding]]] = []


class InputError(ValueError):
    """Invalid folder or input (messages never contain client data)."""


@dataclass
class Table:
    name: str
    path: Path | None
    original: pd.DataFrame  # as read (strings), untouched
    work: pd.DataFrame  # normalised; column ``row`` = line number in the CSV file
    original_columns: list[str]
    renames: dict[str, str] = field(default_factory=dict)


@dataclass
class Package:
    folder: Path
    tables: dict[str, Table] = field(default_factory=dict)
    rules: dict[str, Any] | None = None
    declared: dict[str, Any] | None = None
    llm_checklist: dict[str, Any] | None = None
    version: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    log: TransformationLog = field(default_factory=TransformationLog)
    read_findings: list[Finding] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=lambda: get_profile(None))

    # ------------------------------------------------------------------ availability
    def has(self, name: str) -> bool:
        if name in NON_TABLE:
            return {"rules": self.rules, "declared_results": self.declared, "llm_checklist": self.llm_checklist,
                    "version": self.version}[name] is not None
        t = self.tables.get(name)
        if t is None:
            return False
        # a table without its required columns enables no check (it is reported as a schema finding)
        return all(c in t.work.columns for c in SCHEMA.get(name, {}).get("required", []))

    def df(self, name: str) -> pd.DataFrame | None:
        t = self.tables.get(name)
        return None if t is None or not self.has(name) else t.work

    def has_column(self, table: str, column: str) -> bool:
        if table == "declared_results":
            return bool(self.declared) and self.declared.get(column) is not None
        d = self.df(table)
        return d is not None and column in d.columns and bool(d[column].notna().any())

    def has_returns_source(self) -> bool:
        return (self.has("trades") and self.has("prices")) or self.has("returns")

    def missing(self, check: str) -> list[str]:
        """Required inputs of a check (REQUIREMENTS) that did not arrive."""
        out = []
        for req in REQUIREMENTS.get(check, {}).get("required", []):
            if req == "trades and prices, or returns":
                ok = self.has_returns_source()
            elif req.startswith("trials (at least 2"):
                d = self.df("trials")
                ok = d is not None and len([c for c in d.columns if c not in ("row", "date")]) >= 2
            else:
                ok = False
                for alt in [x.strip() for x in req.split(" or ")]:
                    if "(" in alt:
                        tab, col = alt.split("(")[0], alt[alt.index("(") + 1:alt.index(")")]
                        ok = ok or self.has_column(tab, col)
                    else:
                        ok = ok or self.has(alt)
                if not ok and all("(" not in a and a in self.tables for a in req.split(" or ")):
                    req = req + " (with its required columns)"
            if not ok:
                out.append(req)
        return out

    # ------------------------------------------------------------------ conventions
    def conv(self, key: str, default: Any = None) -> Any:
        """Convention from rules.yaml ``conventions``, else the profile, else built-in default, else ``default``."""
        v, _ = self.conv_with_source(key, default)
        return v

    def conv_with_source(self, key: str, default: Any = None) -> tuple[Any, str]:
        if self.rules and isinstance(self.rules.get("conventions"), dict):
            v = self.rules["conventions"].get(key)
            if v is not None:
                return v, "rules.yaml"
        pv = (self.profile.get("conventions") or {}).get(key)
        if pv is not None:
            return pv, f"profile {self.profile.get('name')}"
        if default is not None:
            return default, "default"
        if key in DEFAULTS:
            return DEFAULTS[key], "default"
        return None, "-"

    def calendar(self) -> Calendar:
        v, src = self.conv_with_source("calendar")
        return calendar_from(v, self.folder, self.conv("holidays_file"), declared_by=src)


# ---------------------------------------------------------------------------- reading

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_dates(s: pd.Series) -> pd.Series:
    ts = pd.to_datetime(s, errors="coerce", format="mixed")
    try:
        ts = ts.dt.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    return ts


def _normalise_columns(df: pd.DataFrame, name: str) -> tuple[pd.DataFrame, dict[str, str]]:
    renames: dict[str, str] = {}
    df = df.rename(columns={c: str(c).strip().lower() for c in df.columns}) if name != "trials" else \
        df.rename(columns={c: str(c).strip() for c in df.columns})
    for canon, alts in ALIASES.get(name, {}).items():
        if canon in df.columns:
            continue
        for a in alts:
            if a in df.columns:
                df = df.rename(columns={a: canon})
                renames[a] = canon
                break
    if name == "trials" and "date" not in df.columns:
        for c in list(df.columns):
            if c.lower() in ("date", "datetime", "timestamp"):
                df = df.rename(columns={c: "date"})
                renames[c] = "date"
                break
    return df, renames


def read_table(p: Path, name: str, log: TransformationLog) -> Table:
    with open(p, encoding="utf-8-sig", newline="") as f:  # read-only
        original = pd.read_csv(f, dtype=str, keep_default_na=False)
    original = original.astype(object)
    work, renames = _normalise_columns(original.copy(), name)
    cols = {"row": list(range(2, len(work) + 2))}  # CSV line number (line 1 is the header)
    for c in work.columns:
        cols[c] = pd.Series([None if x == "" else x for x in work[c]], index=work.index, dtype=object)
    work = pd.DataFrame(cols, index=work.index)
    if renames:
        log.applied(name, "rename_columns", "column aliases mapped to canonical names",
                    {"columns": list(original.columns)}, {"renames": renames})
    if "ticker" in work.columns:
        before = list(work["ticker"])
        work["ticker"] = [None if x is None else str(x).strip().upper() for x in work["ticker"]]
        changed = [int(r) for r, a, b in zip(work["row"], before, work["ticker"]) if a is not None and a != b]
        if changed:
            log.applied(name, "normalise_ticker", "ticker upper-cased and stripped",
                        {"rows_different": len(changed)}, {"rows_different": 0}, rows=changed)
    for c in DATE_COLUMNS.get(name, []):
        if c in work.columns:
            work[c] = parse_dates(work[c])
    for c in NUMERIC_COLUMNS.get(name, []):
        if c in work.columns:
            work[c] = pd.to_numeric(work[c], errors="coerce")
    if name == "trials":
        for c in work.columns:
            if c not in ("row", "date"):
                work[c] = pd.to_numeric(work[c], errors="coerce")
    if name == "trades" and "side" in work.columns:
        work["side"] = [None if x is None else SIDES.get(str(x).strip().lower()) for x in work["side"]]
    if name == "prices" and "adjusted" in work.columns:
        work["adjusted"] = [str(x).strip().lower() in ("1", "true", "yes", "y", "adjusted", "adj") for x in
                            work["adjusted"]]
    return Table(name, p, original, work, list(original.columns), renames)


def _find_file(folder: Path, name: str) -> Path | None:
    for fname in [FILES[name]] + FILE_ALIASES.get(name, []):
        p = folder / fname
        if p.exists():
            return p
    return None


def read_package(folder: str | Path, profile: str | None = None) -> Package:
    """Read whatever is in the folder. Missing files are not an error: they are listed in the manifest."""
    folder = Path(folder)
    if not folder.is_dir():
        raise InputError(f"input folder does not exist: {folder}")
    pkg = Package(folder=folder, profile=get_profile(profile))
    files: dict[str, Any] = {}
    used: set[str] = set()
    for name, fname in FILES.items():
        p = _find_file(folder, name)
        if p is None:
            files[name] = {"file": fname, "present": False}
            continue
        used.add(p.name)
        entry: dict[str, Any] = {"file": p.name, "present": True, "bytes": p.stat().st_size, "sha256": sha256_file(p)}
        try:
            if name in SCHEMA:
                t = read_table(p, name, pkg.log)
                pkg.tables[name] = t
                entry.update({"rows": int(len(t.original)), "columns": t.original_columns})
            elif name == "rules":
                pkg.rules = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                if not isinstance(pkg.rules, dict):
                    raise InputError("rules.yaml is not a mapping")
                entry["keys"] = sorted(pkg.rules)
            elif name in ("declared_results", "llm_checklist"):
                obj = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(obj, dict):
                    raise InputError(f"{p.name} is not a JSON object")
                if name == "declared_results":
                    pkg.declared = obj
                else:
                    pkg.llm_checklist = obj
                entry["keys"] = sorted(obj)
            elif name == "version":
                pkg.version = p.read_text(encoding="utf-8").strip()
                entry["version"] = pkg.version
        except InputError:
            raise
        except Exception as e:  # message without file content
            entry["read_error"] = type(e).__name__
            pkg.read_findings.append(Finding(
                "schema_and_types", "input", CONFIRMED_ERROR, f"Could not read {p.name}",
                f"Read error: {type(e).__name__}.", [], 0, "Reading the file with pandas / yaml / json.", "",
                "Fix the file format (see docs/INPUT_SPEC.md).", "high", [name]))
        files[name] = entry
    others = sorted(p.name for p in folder.iterdir() if p.is_file() and p.name not in used)
    pkg.manifest = {
        "folder": folder.name,
        "read_at": datetime.now().isoformat(timespec="seconds"),
        "files": files,
        "unrecognised": others,
        "declared_version": pkg.version,
    }
    return pkg


# ---------------------------------------------------------------------------- own schema validation

def _raw_column(t: Table, canon: str) -> pd.Series | None:
    orig = next((k for k, v in t.renames.items() if v == canon), canon)
    lower = {str(c).strip().lower(): c for c in t.original.columns}
    if orig in lower:
        return t.original[lower[orig]]
    if orig in t.original.columns:
        return t.original[orig]
    return None


def validate_schema(pkg: Package, res: AuditResult) -> None:
    """Structure and types without Pandera: required columns, unparseable dates and numbers, sides."""
    log = pkg.log
    for name, sch in SCHEMA.items():
        t = pkg.tables.get(name)
        if t is None:
            continue
        df = t.work
        fname = t.path.name if t.path else name
        miss = [c for c in sch["required"] if c not in df.columns]
        if name == "returns" and not ({"return", "nav"} & set(df.columns)):
            miss.append("return or nav")
        if miss:
            res.add("schema_and_types", "input", CONFIRMED_ERROR, f"{fname}: required columns missing",
                    f"Missing {miss}. Columns received: {t.original_columns}.",
                    [{"file": fname, "missing_columns": miss}],
                    "Header compared with the input schema (aliases included).",
                    action="Add or rename the columns as documented in docs/INPUT_SPEC.md.", priority="high",
                    inputs=[name])
        for c in DATE_COLUMNS.get(name, []):
            if c not in df.columns:
                continue
            raw = _raw_column(t, c)
            if raw is None:
                continue
            bad = df[df[c].isna().to_numpy() & (raw.astype(str).to_numpy() != "")]
            if len(bad):
                rows = [int(x) for x in bad["row"]]
                res.add("schema_and_types", "input", CONFIRMED_ERROR, f"{fname}: unparseable dates in `{c}`",
                        f"{len(rows)} rows with a date that could not be parsed.",
                        [{"row": r, "column": c} for r in rows],
                        "pd.to_datetime(errors='coerce') on the column; rows that became NaT are listed.",
                        action="Fix the format (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).", priority="high",
                        inputs=[name])
                if c in sch["required"]:
                    log.applied(name, "exclude_rows_without_valid_date",
                                f"rows with an invalid `{c}` cannot be used by the checks",
                                {"rows": int(len(df))}, {"rows_usable": int(len(df) - len(rows))}, rows=rows)
        num_cols = list(NUMERIC_COLUMNS.get(name, []))
        if name == "trials":
            num_cols = [c for c in df.columns if c not in ("row", "date")]
        for c in num_cols:
            if c not in df.columns:
                continue
            raw = _raw_column(t, c)
            if raw is None:
                continue
            bad = df[df[c].isna().to_numpy() & (raw.astype(str).to_numpy() != "")]
            if len(bad):
                rows = [int(x) for x in bad["row"]]
                res.add("schema_and_types", "input", CONFIRMED_ERROR, f"{fname}: non-numeric values in `{c}`",
                        f"{len(rows)} rows with a value that is not a number.",
                        [{"row": r, "column": c} for r in rows],
                        "pd.to_numeric(errors='coerce'); rows that became NaN are listed.",
                        action="Fix the values (dot decimal, no thousands separator).", priority="high",
                        inputs=[name])
        if name == "trades" and "side" in df.columns:
            raw = _raw_column(t, "side")
            bad = df[df["side"].isna().to_numpy() & (raw.astype(str).to_numpy() != "")] if raw is not None else df[:0]
            if len(bad):
                rows = [int(x) for x in bad["row"]]
                res.add("schema_and_types", "input", CONFIRMED_ERROR, "trades.csv: unknown `side` values",
                        f"{len(rows)} rows with a side that is not buy/sell.", [{"row": r} for r in rows],
                        "Mapping of `side` (buy, sell, b, s, long, short).", action="Use buy / sell.",
                        priority="high", inputs=[name])
        if name == "prices" and "adjusted" not in df.columns:
            res.add("schema_and_types", "input", NEEDS_REVIEW, "prices.csv: no adjustment flag",
                    "It is unknown whether prices are adjusted for splits and dividends. Valuation and return "
                    "comparisons depend on it.", [{"file": fname, "missing_column": "adjusted"}],
                    "Search for the `adjusted` column (or alias) in the header.",
                    action="Add an `adjusted` column (true/false) to prices.csv.", priority="medium",
                    inputs=["prices"])
    for f in pkg.read_findings:
        res.findings.append(f)
    for v in EXTERNAL_VALIDATORS:
        res.findings.extend(v(pkg))
    if not any(f.check == "schema_and_types" for f in res.findings):
        res.add("schema_and_types", "input", PASS, "Input structure and types",
                "Every table present has its required columns and its dates and numbers parse.", [],
                "Header compared with the input schema; dates and numbers coerced.", inputs=list(pkg.tables))


def review_date(pkg: Package, today: date | None = None) -> date:
    v = pkg.conv("review_date")
    if v is not None:
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        return pd.Timestamp(str(v)).date()
    return today or date.today()
