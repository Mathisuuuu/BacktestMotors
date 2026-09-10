"""Test exige n° 1 : corruption du futur, applique au moteur complet.

Remplacer toutes les barres apres l'index `k` par du bruit ne doit RIEN changer
a un backtest arrete a `k`. Pas "presque rien", pas "a l'epsilon pres" : la
courbe d'equity complete, la liste des fills, les compteurs et le hash du
rapport doivent etre identiques.

C'est le test qui attrape ce que la relecture ne voit pas : un `shift(-1)`
egare, une moyenne calculee une fois sur tout le tableau au chargement, un tri
qui touche l'ordre du calendrier, une protection evaluee contre la mauvaise
barre.

Couverture : buy & hold, SMA crossover avec stop, et strategie plate. Le
momentum transversal 12-1 rejoindra ce fichier avec le `CrossSectionalRunner`.
"""

from __future__ import annotations

import json

import pytest

from fixtures import synthetic
from rsl.data.schema import BarStore, InstrumentSpec
from rsl.engine.execution import (
    ExecutionConfig,
    PerContractFee,
    TickSlippage,
    ZeroFee,
    ZeroSlippage,
)
from rsl.engine.risk import RiskFraction, RiskManager
from rsl.engine.runner import RunConfig, RunResult, SingleAssetRunner
from rsl.strategies.base import Strategy
from rsl.strategies.handwritten import BuyAndHold
from rsl.strategies.rules import FlatStrategy, RuleStrategy
from rsl.strategies.signals import Arith, ArithOp, CrossesAbove, CrossesBelow, prim

pytestmark = pytest.mark.adversarial

SYMBOL = "TEST.v.0"
CASH = 100_000.0

SERIES = {
    "constante": synthetic.constant(400, 100.0),
    "rampe": synthetic.ramp(400, 100.0, 0.5),
    "sinusoide": synthetic.sine(400, 100.0, 10.0, 64),
    "marche_aleatoire": synthetic.random_walk(400, seed=20240101),
}

CUTS = [60, 150, 300, 398]


def buy_and_hold() -> Strategy:
    return BuyAndHold(SYMBOL, 2)


def crossover_with_stop() -> Strategy:
    fast, slow = prim("sma@1", window=5), prim("sma@1", window=20)
    return RuleStrategy(
        symbol=SYMBOL,
        quantity=1,
        entry_long=CrossesAbove(fast, slow),
        exit_long=CrossesBelow(fast, slow),
        stop_loss=Arith(
            prim("sma@1", window=5),
            ArithOp.SUB,
            Arith(prim("atr@1", window=14), ArithOp.MUL, prim("returns@1", window=1)),
        ),
    )


def flat() -> Strategy:
    return FlatStrategy()


STRATEGIES = {
    "buy_and_hold": buy_and_hold,
    "sma_crossover_stop": crossover_with_stop,
    "plate": flat,
}


def fingerprint(result: RunResult) -> str:
    """Empreinte exhaustive d'un run : courbe, fills, compteurs, rapport."""
    payload = {
        "equity": [e.hex() for e in result.equity.equity],
        "cash": [c.hex() for c in result.equity.cash],
        "ts": list(result.equity.ts_ns),
        "exposure": list(result.equity.exposure),
        "fills": [
            {
                "order_id": f.order_id,
                "bar_index": f.bar_index,
                "side": f.side.value,
                "quantity": f.quantity,
                "price": f.price.hex(),
                "fee": f.fee.hex(),
                "slippage": f.slippage_cost.hex(),
                "clamped": f.was_clamped,
                "tag": f.tag,
                "ts_ns": f.ts_ns,
            }
            for f in result.fills
        ],
        "counters": result.counters.describe(),
        "trades": [
            (t.opened_bar, t.closed_bar, t.direction, t.gross_pnl.hex(), t.fees.hex())
            for t in result.portfolio.closed_trades
        ],
        "report": result.describe(),
    }
    return json.dumps(payload, sort_keys=True)


def run_until(
    store: BarStore, spec: InstrumentSpec, make_strategy, cut: int, **kwargs: object
) -> RunResult:
    execution = kwargs.pop(
        "execution", ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(1))
    )
    risk = kwargs.pop("risk", None)
    config = RunConfig(initial_cash=CASH, execution=execution, stop=cut + 1)  # type: ignore[arg-type]
    return SingleAssetRunner(store, spec, config, risk=risk).run(make_strategy())  # type: ignore[arg-type]


class TestFutureCorruption:
    @pytest.mark.parametrize("strategy_name", sorted(STRATEGIES))
    @pytest.mark.parametrize("series_name", sorted(SERIES))
    @pytest.mark.parametrize("cut", CUTS)
    def test_a_run_stopped_at_k_ignores_everything_after_k(
        self, spec: InstrumentSpec, strategy_name: str, series_name: str, cut: int
    ):
        clean = synthetic.make_store(SERIES[series_name], symbol=SYMBOL)
        dirty = synthetic.corrupt_future(clean, after_index=cut)
        make_strategy = STRATEGIES[strategy_name]

        reference = run_until(clean, spec, make_strategy, cut)
        observed = run_until(dirty, spec, make_strategy, cut)

        assert fingerprint(observed) == fingerprint(reference)

    @pytest.mark.parametrize("cut", [80, 250])
    def test_it_holds_with_atr_based_sizing(self, spec: InstrumentSpec, cut: int):
        """Le dimensionnement lit lui aussi le `Context` : meme garantie."""
        clean = synthetic.make_store(SERIES["marche_aleatoire"], symbol=SYMBOL)
        dirty = synthetic.corrupt_future(clean, after_index=cut)
        risk = RiskManager(sizing=RiskFraction(0.02, atr_window=14))

        reference = run_until(clean, spec, crossover_with_stop, cut, risk=risk)
        observed = run_until(dirty, spec, crossover_with_stop, cut, risk=risk)

        assert fingerprint(observed) == fingerprint(reference)

    @pytest.mark.parametrize("cut", [80, 250])
    def test_it_holds_without_costs(self, spec: InstrumentSpec, cut: int):
        clean = synthetic.make_store(SERIES["sinusoide"], symbol=SYMBOL)
        dirty = synthetic.corrupt_future(clean, after_index=cut)
        execution = ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())

        reference = run_until(clean, spec, crossover_with_stop, cut, execution=execution)
        observed = run_until(dirty, spec, crossover_with_stop, cut, execution=execution)

        assert fingerprint(observed) == fingerprint(reference)


class TestTheTestIsNotVacuous:
    """Garde-fous. Un test de corruption qui passe pour de mauvaises raisons est
    pire qu'aucun test : il donne une garantie qui n'existe pas."""

    def test_the_strategy_actually_trades_before_the_cut(self, spec: InstrumentSpec):
        clean = synthetic.make_store(SERIES["sinusoide"], symbol=SYMBOL)
        result = run_until(clean, spec, crossover_with_stop, 300)
        assert len(result.fills) > 5
        assert result.portfolio.stats.contracts_traded > 5

    def test_running_past_the_cut_does_differ(self, spec: InstrumentSpec):
        """Sur les barres corrompues, les resultats DOIVENT diverger."""
        clean = synthetic.make_store(SERIES["sinusoide"], symbol=SYMBOL)
        dirty = synthetic.corrupt_future(clean, after_index=200)
        reference = run_until(clean, spec, crossover_with_stop, 399)
        observed = run_until(dirty, spec, crossover_with_stop, 399)
        assert fingerprint(observed) != fingerprint(reference)

    def test_the_corruption_reaches_the_bars_just_after_the_cut(self):
        clean = synthetic.make_store(SERIES["sinusoide"], symbol=SYMBOL)
        dirty = synthetic.corrupt_future(clean, after_index=200)
        assert float(clean.close[201]) != float(dirty.close[201])
        assert float(clean.close[200]) == float(dirty.close[200])

    def test_a_run_stopped_at_k_sees_exactly_k_plus_one_bars(self, spec: InstrumentSpec):
        result = run_until(
            synthetic.make_store(SERIES["rampe"], symbol=SYMBOL), spec, buy_and_hold, 99
        )
        assert result.counters.n_bars == 100
        assert len(result.equity) == 100
