"""Tests exiges n° 3, 4, 5, 6, 7 et 8, appliques au moteur complet.

Ce sont eux qui donnent sa valeur au socle. Un moteur qui les passe tous a une
verite terrain ; un moteur qui en echoue un n'a rien.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import ClassVar

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from fixtures import synthetic
from rsl.data.schema import Bar, BarStore, InstrumentSpec
from rsl.engine.execution import (
    BpsSlippage,
    ExecutionConfig,
    ExecutionEngine,
    FlatFee,
    PerContractFee,
    TickSlippage,
    ZeroFee,
    ZeroSlippage,
)
from rsl.engine.orders import Order, OrderType, Side
from rsl.engine.risk import FixedContracts, RiskManager
from rsl.engine.runner import RunConfig, SingleAssetRunner
from rsl.strategies.handwritten import BuyAndHold
from rsl.strategies.rules import FlatStrategy, RuleStrategy
from rsl.strategies.signals import CrossesAbove, CrossesBelow, prim

pytestmark = pytest.mark.adversarial

SYMBOL = "TEST.v.0"
CASH = 100_000.0

SERIES = {
    "constante": synthetic.constant(400, 100.0),
    "rampe": synthetic.ramp(400, 100.0, 0.5),
    "rampe_descendante": synthetic.ramp(400, 300.0, -0.5),
    "sinusoide": synthetic.sine(400, 100.0, 10.0, 64),
    "marche_aleatoire": synthetic.random_walk(400, seed=20240101),
}


def store_of(name: str) -> BarStore:
    return synthetic.make_store(SERIES[name], symbol=SYMBOL)


def config(**kwargs: object) -> RunConfig:
    execution = kwargs.pop(
        "execution", ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())
    )
    return RunConfig(initial_cash=CASH, execution=execution, **kwargs)  # type: ignore[arg-type]


def crossover(quantity: int = 1) -> RuleStrategy:
    fast, slow = prim("sma@1", window=5), prim("sma@1", window=20)
    return RuleStrategy(
        symbol=SYMBOL,
        quantity=quantity,
        entry_long=CrossesAbove(fast, slow),
        exit_long=CrossesBelow(fast, slow),
    )


# ---------------------------------------------------------------------------
# Test n° 3 : buy & hold analytique
# ---------------------------------------------------------------------------


class TestBuyAndHoldClosedForm:
    """Le P&L doit correspondre a une formule fermee calculee hors du moteur.

        equity = cash + q * multiplicateur * (mark_final - prix_entree) - frais

    avec `prix_entree = open(barre_1)` sous le lag par defaut.
    """

    @pytest.mark.parametrize("name", sorted(SERIES))
    @pytest.mark.parametrize("quantity", [1, 3])
    def test_without_costs(self, spec: InstrumentSpec, name: str, quantity: int):
        store = store_of(name)
        result = SingleAssetRunner(store, spec, config()).run(BuyAndHold(SYMBOL, quantity))

        entry_price = float(store.open[1])
        final_mark = float(store.close[store.n_bars - 1])
        expected = CASH + quantity * spec.multiplier * (final_mark - entry_price)

        assert len(result.fills) == 1
        assert result.fills[0].bar_index == 1
        assert result.fills[0].price == pytest.approx(entry_price, abs=1e-12)
        assert result.final_equity == pytest.approx(expected, abs=1e-9)

    @pytest.mark.parametrize("name", sorted(SERIES))
    def test_with_fees_and_slippage(self, spec: InstrumentSpec, name: str):
        store = store_of(name)
        execution = ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(1))
        result = SingleAssetRunner(store, spec, config(execution=execution)).run(
            BuyAndHold(SYMBOL, 2)
        )

        # Le slippage est ecrete au haut de la barre : sur une serie plate, un
        # tick complet sort deja de la barre. La formule doit modeliser
        # l'ecretage, sinon elle decrirait un prix qui n'a pas existe.
        entry_price = min(float(store.open[1]) + spec.tick_size, float(store.high[1]))
        final_mark = float(store.close[store.n_bars - 1])
        fees = 2 * spec.fee_per_contract_per_side
        expected = CASH + 2 * spec.multiplier * (final_mark - entry_price) - fees

        assert result.fills[0].price == pytest.approx(entry_price, abs=1e-12)
        assert result.final_equity == pytest.approx(expected, abs=1e-9)

    def test_the_clamped_case_is_actually_exercised(self, spec: InstrumentSpec):
        """Garde-fou : sans lui, le `min` ci-dessus pourrait ne jamais mordre."""
        store = store_of("constante")
        execution = ExecutionConfig(fees=ZeroFee(), slippage=TickSlippage(1))
        result = SingleAssetRunner(store, spec, config(execution=execution)).run(
            BuyAndHold(SYMBOL, 1)
        )
        assert result.fills[0].was_clamped
        assert result.fills[0].price == pytest.approx(float(store.high[1]))

    @pytest.mark.parametrize("lag", [1, 2, 5])
    def test_the_entry_price_follows_the_lag(self, spec: InstrumentSpec, lag: int):
        store = store_of("marche_aleatoire")
        execution = ExecutionConfig(
            fees=ZeroFee(), slippage=ZeroSlippage(), execution_lag=lag
        )
        result = SingleAssetRunner(store, spec, config(execution=execution)).run(
            BuyAndHold(SYMBOL, 1)
        )
        expected = CASH + spec.multiplier * (
            float(store.close[store.n_bars - 1]) - float(store.open[lag])
        )
        assert result.final_equity == pytest.approx(expected, abs=1e-9)

    def test_a_short_hold_is_the_mirror_image(self, spec: InstrumentSpec):
        store = store_of("rampe")
        long_result = SingleAssetRunner(store, spec, config()).run(BuyAndHold(SYMBOL, 1))
        short_result = SingleAssetRunner(store, spec, config()).run(
            BuyAndHold(SYMBOL, 1, side=Side.SELL)
        )
        assert (long_result.final_equity - CASH) == pytest.approx(
            -(short_result.final_equity - CASH), abs=1e-9
        )

    def test_a_constant_series_yields_exactly_nothing(self, spec: InstrumentSpec):
        result = SingleAssetRunner(store_of("constante"), spec, config()).run(
            BuyAndHold(SYMBOL, 1)
        )
        assert result.final_equity == CASH


# ---------------------------------------------------------------------------
# Test n° 4 : strategie plate
# ---------------------------------------------------------------------------


class TestFlatStrategy:
    @pytest.mark.parametrize("name", sorted(SERIES))
    def test_equity_is_exactly_constant(self, spec: InstrumentSpec, name: str):
        """Exactement, pas approximativement : aucune arithmetique n'a lieu."""
        result = SingleAssetRunner(store_of(name), spec, config()).run(FlatStrategy())
        assert set(result.equity.equity) == {CASH}
        assert set(result.equity.cash) == {CASH}
        assert result.fills == ()
        assert result.portfolio.stats.fees_paid == 0.0

    def test_costs_change_nothing_when_nothing_is_traded(self, spec: InstrumentSpec):
        execution = ExecutionConfig(fees=FlatFee(1000.0), slippage=BpsSlippage(500))
        result = SingleAssetRunner(
            store_of("marche_aleatoire"), spec, config(execution=execution)
        ).run(FlatStrategy())
        assert set(result.equity.equity) == {CASH}


# ---------------------------------------------------------------------------
# Test n° 5 : invariante comptable
# ---------------------------------------------------------------------------


class TestAccountingInvariant:
    """Verifiee a chaque barre par le moteur lui-meme : un run qui se termine
    est un run dont l'invariante a tenu sur toutes ses barres."""

    @pytest.mark.parametrize("name", sorted(SERIES))
    @pytest.mark.parametrize(
        "make_strategy", [lambda: FlatStrategy(), lambda: BuyAndHold(SYMBOL, 2), crossover]
    )
    def test_holds_for_every_strategy_and_series(self, spec, name, make_strategy):
        execution = ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(1))
        result = SingleAssetRunner(
            store_of(name), spec, config(execution=execution)
        ).run(make_strategy())
        assert result.counters.n_bars > 0
        final_marks = {SYMBOL: float(store_of(name).close[store_of(name).n_bars - 1])}
        assert result.portfolio.equity(final_marks) == pytest.approx(
            result.portfolio.equity_incremental, rel=1e-12
        )

    def test_it_holds_with_protections_firing(self, spec):
        closes = synthetic.ramp(200, 100.0, 1.0)
        closes[100:] = 50.0
        store = synthetic.make_store(closes, symbol=SYMBOL)
        strategy = RuleStrategy(
            symbol=SYMBOL,
            quantity=1,
            entry_long=CrossesAbove(prim("sma@1", window=5), prim("sma@1", window=20)),
            stop_loss=prim("rolling_low@1", window=10),
        )
        execution = ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(1))
        result = SingleAssetRunner(store, spec, config(execution=execution)).run(strategy)
        assert result.counters.n_bars > 0


# ---------------------------------------------------------------------------
# Test n° 6 : frais monotones
# ---------------------------------------------------------------------------


class TestFeeMonotonicity:
    FEES: ClassVar[list[float]] = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 50.0]

    def _run_with_fee(self, spec: InstrumentSpec, fee: float) -> float:
        execution = ExecutionConfig(fees=FlatFee(fee), slippage=ZeroSlippage())
        runner = SingleAssetRunner(
            store_of("sinusoide"),
            spec,
            config(execution=execution),
            risk=RiskManager(sizing=FixedContracts(1)),
        )
        return runner.run(crossover()).final_equity

    def test_higher_fees_degrade_performance_monotonically(self, spec: InstrumentSpec):
        equities = [self._run_with_fee(spec, fee) for fee in self.FEES]
        assert all(a > b for a, b in pairwise(equities)), equities

    def test_the_degradation_is_exactly_the_fee_difference(self, spec: InstrumentSpec):
        """Le nombre de contrats traites etant identique, l'ecart est calculable."""
        execution_a = ExecutionConfig(fees=FlatFee(0.0), slippage=ZeroSlippage())
        execution_b = ExecutionConfig(fees=FlatFee(3.0), slippage=ZeroSlippage())
        store = store_of("sinusoide")
        a = SingleAssetRunner(store, spec, config(execution=execution_a)).run(crossover())
        b = SingleAssetRunner(store, spec, config(execution=execution_b)).run(crossover())
        assert a.portfolio.stats.contracts_traded == b.portfolio.stats.contracts_traded
        expected_gap = 3.0 * a.portfolio.stats.contracts_traded
        assert (a.final_equity - b.final_equity) == pytest.approx(expected_gap, abs=1e-9)

    def test_slippage_is_monotone_too(self, spec: InstrumentSpec):
        equities = []
        for ticks in (0, 1, 2, 4, 8):
            execution = ExecutionConfig(fees=ZeroFee(), slippage=TickSlippage(ticks))
            equities.append(
                SingleAssetRunner(store_of("sinusoide"), spec, config(execution=execution))
                .run(crossover())
                .final_equity
            )
        assert all(a >= b for a, b in pairwise(equities)), equities

    def test_the_strategy_actually_trades(self, spec: InstrumentSpec):
        """Garde-fou : sans trades, la monotonie serait vraie et vide de sens."""
        result = SingleAssetRunner(store_of("sinusoide"), spec, config()).run(crossover())
        assert result.portfolio.stats.contracts_traded > 10


# ---------------------------------------------------------------------------
# Test n° 7 : fills bornes (property-based)
# ---------------------------------------------------------------------------


TS = datetime(2024, 3, 14, 13, 30, tzinfo=UTC)


@st.composite
def bars(draw: st.DrawFn) -> Bar:
    low = draw(st.floats(min_value=0.01, max_value=10_000.0, allow_nan=False))
    height = draw(st.floats(min_value=0.0, max_value=1_000.0, allow_nan=False))
    high = low + height
    open_ = draw(st.floats(min_value=low, max_value=high, allow_nan=False))
    close = draw(st.floats(min_value=low, max_value=high, allow_nan=False))
    return Bar(
        ts_event=TS,
        ts_close=TS + timedelta(minutes=1),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=draw(st.floats(min_value=0.0, max_value=1e6, allow_nan=False)),
    )


@st.composite
def orders(draw: st.DrawFn) -> Order:
    side = draw(st.sampled_from([Side.BUY, Side.SELL]))
    kind = draw(st.sampled_from([OrderType.MARKET, OrderType.LIMIT, OrderType.STOP]))
    quantity = draw(st.integers(min_value=1, max_value=100))
    level = draw(st.floats(min_value=0.01, max_value=20_000.0, allow_nan=False))
    if kind is OrderType.MARKET:
        return Order(symbol=SYMBOL, side=side, quantity=quantity)
    if kind is OrderType.LIMIT:
        return Order(
            symbol=SYMBOL, side=side, quantity=quantity, order_type=kind, limit_price=level
        )
    return Order(symbol=SYMBOL, side=side, quantity=quantity, order_type=kind, stop_price=level)


SLIPPAGES = [ZeroSlippage(), TickSlippage(1), TickSlippage(10_000), BpsSlippage(5_000)]


class TestFillsAreAlwaysInsideTheBar:
    """Test exige n° 7. Aucun fill ne peut avoir un prix qui n'a pas existe."""

    @given(bar=bars(), order=orders(), slip=st.sampled_from(SLIPPAGES))
    @settings(
        max_examples=500,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_property(self, spec: InstrumentSpec, bar: Bar, order: Order, slip: object):
        assume(bar.high >= bar.low)
        engine = ExecutionEngine(ExecutionConfig(fees=ZeroFee(), slippage=slip))  # type: ignore[arg-type]
        fill = engine.try_fill(order, bar=bar, bar_index=0, spec=spec, order_id=0)
        if fill is None:
            return
        assert bar.low <= fill.price <= bar.high
        assert fill.quantity == order.quantity
        assert fill.slippage_cost >= 0.0

    @given(
        closes=st.lists(
            st.floats(min_value=1.0, max_value=5_000.0, allow_nan=False),
            min_size=60,
            max_size=120,
        )
    )
    @settings(
        max_examples=40,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_every_fill_of_a_full_run_is_inside_its_bar(self, spec: InstrumentSpec, closes):
        import numpy as np

        store = synthetic.make_store(np.array(closes, dtype=np.float64), symbol=SYMBOL)
        execution = ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(4))
        result = SingleAssetRunner(store, spec, config(execution=execution)).run(crossover())
        for fill in result.fills:
            assert store.low[fill.bar_index] <= fill.price <= store.high[fill.bar_index]


# ---------------------------------------------------------------------------
# Test n° 8 : determinisme
# ---------------------------------------------------------------------------


class TestDeterminism:
    @pytest.mark.parametrize("name", sorted(SERIES))
    def test_two_identical_runs_are_bit_identical(self, spec: InstrumentSpec, name: str):
        store = store_of(name)
        execution = ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(1))

        def once() -> tuple[list[str], list[tuple[object, ...]], str]:
            result = SingleAssetRunner(store, spec, config(execution=execution)).run(crossover())
            return (
                [e.hex() for e in result.equity.equity],
                [
                    (f.order_id, f.bar_index, f.price.hex(), f.side.value, f.quantity, f.tag)
                    for f in result.fills
                ],
                json.dumps(result.describe(), sort_keys=True),
            )

        assert once() == once()

    def test_a_fresh_runner_gives_the_same_result_as_a_reused_one(self, spec: InstrumentSpec):
        store = store_of("sinusoide")
        strategy = crossover()
        runner = SingleAssetRunner(store, spec, config())
        first = runner.run(strategy)
        second = SingleAssetRunner(store, spec, config()).run(crossover())
        assert [e.hex() for e in first.equity.equity] == [
            e.hex() for e in second.equity.equity
        ]

    def test_a_reused_strategy_object_is_reset(self, spec: InstrumentSpec):
        """Sans `reset`, le second run partirait d'une position heritee."""
        store = store_of("rampe")
        runner = SingleAssetRunner(store, spec, config())
        strategy = BuyAndHold(SYMBOL, 1)
        first = runner.run(strategy)
        second = runner.run(strategy)
        assert first.final_equity == second.final_equity
        assert len(first.fills) == len(second.fills) == 1

    def test_order_ids_are_sequential_and_reproducible(self, spec: InstrumentSpec):
        store = store_of("sinusoide")
        runner = SingleAssetRunner(store, spec, config())
        first = [f.order_id for f in runner.run(crossover()).fills]
        second = [f.order_id for f in runner.run(crossover()).fills]
        assert first == second
        assert first == sorted(first)
