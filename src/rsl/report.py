"""Execution d'une specification, et rapport - JSON et texte.

Un rapport reunit quatre choses qui n'ont d'interet qu'ensemble :

  - la **provenance** (`manifest.py`) : quelles donnees, quel code, quel etat
    du depot ;
  - la **specification** : ce qui a ete demande, sous forme canonique ;
  - les **metriques** : ce qui en est sorti ;
  - l'**empreinte de resultat** : de quoi verifier qu'un second run donne bien
    la meme chose.

L'empreinte de resultat merite un mot. Elle porte sur la courbe d'equity, les
fills, les compteurs et la comptabilite - jamais sur l'horodatage du run ni sur
la machine. Deux runs identiques lances a dix minutes d'intervalle doivent
avoir la meme empreinte ; y meler la date rendrait l'exigence de
reproductibilite inverifiable, ce qui est pire que de ne pas l'exiger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rsl.config import BacktestSpec, build_panel_from, load_stores
from rsl.data.schema import BarStore, InstrumentSpec
from rsl.engine.cross_sectional import CrossSectionalRunner, CrossSectionalRunResult
from rsl.engine.runner import RunResult, SingleAssetRunner
from rsl.errors import ConfigurationError
from rsl.manifest import RunManifest, apply_seed, canonical_hash
from rsl.metrics.performance import PerformanceMetrics, compute_performance
from rsl.metrics.statistics import DeflatedSharpeResult, TrialLog, deflated_sharpe_ratio
from rsl.primitives.registry import RegistrySnapshot
from rsl.strategies.base import (
    CrossSectionalStrategy,
    Strategy,
    build_strategy,
    get_strategy,
)

SpecDict = dict[str, object]

AnyRunResult = RunResult | CrossSectionalRunResult
"""Les deux runners produisent des types distincts, volontairement : leurs
compteurs ne decrivent pas les memes evenements. Ce qui les traite en aval
accepte donc l'un ou l'autre."""


def result_fingerprint(result: AnyRunResult) -> str:
    """Empreinte deterministe d'un resultat de run.

    Contient tout ce qui doit etre stable entre deux executions identiques, et
    rien de ce qui ne peut pas l'etre. Les flottants sont haches sous leur
    forme hexadecimale exacte : une comparaison a 15 decimales laisserait
    passer une derive d'un bit, qui est precisement ce qu'on cherche a exclure.
    """
    equity = result.equity
    portfolio = result.portfolio

    payload = {
        "equity": [value.hex() for value in equity.equity],
        "cash": [value.hex() for value in equity.cash],
        "ts_ns": list(equity.ts_ns),
        "exposure": list(equity.exposure),
        "fills": [
            [
                fill.order_id,
                fill.symbol,
                fill.bar_index,
                fill.side.value,
                fill.quantity,
                fill.price.hex(),
                fill.fee.hex(),
                fill.slippage_cost.hex(),
                fill.was_clamped,
                fill.tag,
            ]
            for fill in result.fills
        ],
        "trades": [
            [t.symbol, t.opened_bar, t.closed_bar, t.direction, t.gross_pnl.hex(), t.fees.hex()]
            for t in portfolio.closed_trades
        ],
        "counters": result.counters.describe(),
        "portfolio": portfolio.describe(),
    }
    return canonical_hash(payload)


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """Produit complet d'un run."""

    spec: BacktestSpec
    manifest: RunManifest
    metrics: PerformanceMetrics
    run: SpecDict
    result_fingerprint: str
    deflated_sharpe: DeflatedSharpeResult | None
    symbols: tuple[str, ...]
    cross_sectional: bool

    def to_dict(self) -> SpecDict:
        return {
            "name": self.spec.name,
            "cross_sectional": self.cross_sectional,
            "symbols": list(self.symbols),
            "result_fingerprint": self.result_fingerprint,
            "manifest": self.manifest.describe(),
            "specification": self.spec.canonical(),
            "metrics": self.metrics.describe(),
            "deflated_sharpe": (
                None if self.deflated_sharpe is None else self.deflated_sharpe.describe()
            ),
            "run": self.run,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, ensure_ascii=False)

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def render(self) -> str:
        rule = "-" * 72
        mode = "transversal" if self.cross_sectional else "mono-instrument"
        lines = [
            rule,
            f"{self.spec.name}   [{mode}]   {', '.join(self.symbols)}",
            rule,
            self.manifest.render(),
            rule,
            f"Strategie    {self.spec.strategy.ref}   {self.spec.strategy.params}",
            f"Couts        frais {self.spec.execution.fees.kind}, "
            f"slippage {self.spec.execution.slippage.kind}, "
            f"lag {self.spec.execution.lag_bars} barre(s)",
            f"Risque       sizing {self.spec.risk.sizing.kind}",
            rule,
            self.metrics.render(),
            rule,
        ]
        if self.deflated_sharpe is not None:
            lines.extend([self.deflated_sharpe.render(), rule])
        lines.append(f"Empreinte    {self.result_fingerprint}")
        lines.append(rule)
        return "\n".join(lines)


def run_backtest(spec: BacktestSpec, *, trial_log: TrialLog | None = None) -> BacktestReport:
    """Execute une specification et produit son rapport.

    `trial_log` porte le compteur d'essais du Deflated Sharpe. Sans lui, le run
    est traite comme un essai unique - ce qui est vrai pour un run isole, et
    faux des qu'on explore. Le DSR emet alors son avertissement plutot que de
    laisser croire a une significativite.
    """
    apply_seed(spec.seed)

    entry = get_strategy(*_parse_ref(spec.strategy.ref))
    stores, instruments, sources = load_stores(spec)
    strategy = build_strategy(spec.strategy.as_dict())

    result: AnyRunResult = (
        _run_cross_sectional(spec, stores, instruments, strategy)
        if entry.cross_sectional
        else _run_single(spec, stores, instruments, strategy)
    )
    symbols = tuple(sorted(stores))

    metrics = compute_performance(result, risk_free_annual=spec.risk_free_annual)
    manifest = RunManifest.capture(
        config=spec.canonical(),
        seed=spec.seed,
        data_sources=sources,
        primitives=RegistrySnapshot.capture().entries,
    )

    log = trial_log if trial_log is not None else TrialLog()
    log.record(spec.canonical(), metrics.sharpe_per_period or 0.0, label=spec.name)
    deflated = (
        deflated_sharpe_ratio(
            sharpe_per_period=metrics.sharpe_per_period,
            n_observations=metrics.n_returns,
            skewness=metrics.returns_skewness,
            kurtosis=metrics.returns_kurtosis,
            n_trials=log.n_trials,
            variance_of_trial_sharpes=log.variance_of_sharpes,
        )
        if metrics.sharpe_per_period is not None
        else None
    )

    return BacktestReport(
        spec=spec,
        manifest=manifest,
        metrics=metrics,
        run=result.describe(),
        result_fingerprint=result_fingerprint(result),
        deflated_sharpe=deflated,
        symbols=symbols,
        cross_sectional=entry.cross_sectional,
    )


def _parse_ref(ref: str) -> tuple[str, int | None]:
    name, _, version = ref.partition("@")
    if version and not version.isdigit():
        raise ConfigurationError(f"version invalide dans '{ref}'")
    return name, int(version) if version else None


def _run_single(
    spec: BacktestSpec,
    stores: dict[str, BarStore],
    instruments: dict[str, InstrumentSpec],
    strategy: Strategy | CrossSectionalStrategy,
) -> RunResult:
    if len(stores) != 1:
        raise ConfigurationError(
            f"la strategie '{spec.strategy.ref}' est mono-instrument mais la "
            f"specification en declare {len(stores)}"
        )
    if not isinstance(strategy, Strategy):
        raise ConfigurationError(f"'{spec.strategy.ref}' n'est pas une strategie mono-instrument")
    symbol = next(iter(stores))
    runner = SingleAssetRunner(
        stores[symbol],
        instruments[symbol],
        spec.build_run_config(),
        risk=spec.build_risk(),
    )
    return runner.run(strategy)


def _run_cross_sectional(
    spec: BacktestSpec,
    stores: dict[str, BarStore],
    instruments: dict[str, InstrumentSpec],
    strategy: Strategy | CrossSectionalStrategy,
) -> CrossSectionalRunResult:
    if not isinstance(strategy, CrossSectionalStrategy):
        raise ConfigurationError(f"'{spec.strategy.ref}' n'est pas une strategie transversale")
    runner = CrossSectionalRunner(
        build_panel_from(spec, stores),
        instruments,
        spec.build_run_config(),
        risk=spec.build_risk(),
        schedule=spec.rebalance.build(),
    )
    return runner.run(strategy)
