"""Use cases: validation modules for different kinds of financial models.

The core of the toolkit (0.1 and 0.2) validates the backtest of a systematic trading strategy. A use case adds
a self-contained family of checks for another kind of model that the financial industry validates: alpha
signals, machine-learning models, risk models (VaR / ES), point forecasts, portfolio allocations and the live
track record of a strategy against its backtest.

Each use case lives in ONE module of this package and declares everything it needs in a ``UseCase`` spec:
its input tables (file name, schema, aliases, date and numeric columns), the inputs each check requires,
the catalogue entry of each check (what, why, fix, allows, does not allow, references) and a ``run`` callable.
``register`` merges those declarations into the package-wide tables (``inputs.FILES``, ``inputs.SCHEMA``,
``inputs.REQUIREMENTS``, ``catalog.CHECKS``...), so the CLI, the scaffold, the MCP server and the docs see the
new tables and checks without editing the core files.

Every check keeps the contract of the core: CONFIRMED_ERROR only with evidence, NEEDS_REVIEW when something
must be checked by a person, NOT_EXECUTABLE with the reason when inputs are missing or insufficient, PASS only
when the property was actually verified, INFO for context. Each finding links to its evidence (rows, dates).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import catalog, inputs
from ..findings import AuditResult


@dataclass
class UseCase:
    name: str  # short id: signals, ml, risk, forecast, portfolio, live
    title: str
    description: str  # who uses it and what it validates (one paragraph)
    audience: str  # e.g. "quant researchers", "risk managers"
    detect_files: list[str]  # package tables whose presence activates the use case (any of them)
    files: dict[str, str] = field(default_factory=dict)  # table name -> file name
    file_aliases: dict[str, list[str]] = field(default_factory=dict)
    schema: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    aliases: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    date_columns: dict[str, list[str]] = field(default_factory=dict)
    numeric_columns: dict[str, list[str]] = field(default_factory=dict)
    requirements: dict[str, dict[str, list[str]]] = field(default_factory=dict)  # check -> required/optional
    catalog: dict[str, dict[str, Any]] = field(default_factory=dict)  # check -> catalogue entry
    references: dict[str, str] = field(default_factory=dict)  # ref key -> citation (merged into catalog.REF)
    conventions: dict[str, Any] = field(default_factory=dict)  # rules.yaml conventions defaults (documented)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)  # extra review profiles
    run: Callable[[Any, AuditResult], None] | None = None  # (Package, AuditResult) -> None

    @property
    def checks(self) -> list[str]:
        return list(self.catalog)


REGISTRY: dict[str, UseCase] = {}


def register(uc: UseCase) -> UseCase:
    """Register a use case and merge its declarations into the package-wide tables."""
    if uc.name in REGISTRY:
        return REGISTRY[uc.name]
    for table, fname in uc.files.items():
        if table in inputs.FILES and inputs.FILES[table] != fname:
            raise ValueError(f"use case {uc.name}: table {table!r} already declared with another file name")
        inputs.FILES[table] = fname
    for table, al in uc.file_aliases.items():
        inputs.FILE_ALIASES.setdefault(table, []).extend(a for a in al if a not in inputs.FILE_ALIASES.get(table, []))
    for table, sch in uc.schema.items():
        inputs.SCHEMA.setdefault(table, sch)
    for table, al in uc.aliases.items():
        inputs.ALIASES.setdefault(table, {}).update(al)
    for table, cols in uc.date_columns.items():
        inputs.DATE_COLUMNS.setdefault(table, cols)
    for table, cols in uc.numeric_columns.items():
        inputs.NUMERIC_COLUMNS.setdefault(table, cols)
    for check, req in uc.requirements.items():
        inputs.REQUIREMENTS.setdefault(check, req)
    catalog.REF.update(uc.references)
    for check, entry in uc.catalog.items():
        entry = dict(entry)
        entry.setdefault("block", uc.name)
        entry.setdefault("use_case", uc.name)
        catalog.CHECKS.setdefault(check, entry)
    for key, val in uc.conventions.items():
        inputs.DEFAULTS.setdefault(key, val)
    from ..profiles import PROFILES

    for pname, prof in uc.profiles.items():
        PROFILES.setdefault(pname, prof)
    REGISTRY[uc.name] = uc
    return uc


def active_usecases(pkg: Any) -> list[UseCase]:
    """Use cases whose detection tables are present in the package."""
    return [uc for uc in REGISTRY.values() if any(pkg.has(t) for t in uc.detect_files)]


def run_usecases(pkg: Any, res: AuditResult, only: list[str] | None = None) -> list[str]:
    """Run every registered use case (``only`` restricts by name). Returns the names that ran.

    A use case whose inputs are absent still runs: its checks report NOT_EXECUTABLE with the missing input,
    exactly like the core checks, so the report lists what could have been verified with more data.
    """
    ran = []
    for name, uc in REGISTRY.items():
        if only and name not in only:
            continue
        if uc.run is None:
            continue
        uc.run(pkg, res)
        ran.append(name)
    return ran


def load_all() -> None:
    """Import every bundled use case module (each registers itself on import)."""
    import importlib

    for mod in ("signals", "ml", "risk", "forecast", "portfolio", "live"):
        try:
            importlib.import_module(f"{__name__}.{mod}")
        except ModuleNotFoundError as e:  # a module not shipped yet
            if e.name != f"{__name__}.{mod}":
                raise


def describe() -> list[dict[str, Any]]:
    return [{"name": uc.name, "title": uc.title, "audience": uc.audience, "description": uc.description,
             "inputs": sorted(uc.files), "checks": uc.checks} for uc in REGISTRY.values()]
