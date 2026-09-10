"""Modele de fill : declenchement, prix, gaps, ecretage, couts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rsl.data.schema import Bar, InstrumentSpec
from rsl.engine.execution import (
    ZERO_COST,
    BpsSlippage,
    ExecutionConfig,
    ExecutionEngine,
    FlatFee,
    IntrabarPriority,
    PerContractFee,
    TickSlippage,
    ZeroFee,
    ZeroSlippage,
    assert_within_bar,
)
from rsl.engine.orders import Order, OrderType, Side
from rsl.errors import ConfigurationError

TS = datetime(2024, 3, 14, 13, 30, tzinfo=UTC)


def bar(open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        ts_event=TS,
        ts_close=TS + timedelta(minutes=1),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
    )


def engine(**kwargs: object) -> ExecutionEngine:
    defaults: dict[str, object] = {"fees": ZeroFee(), "slippage": ZeroSlippage()}
    defaults.update(kwargs)
    return ExecutionEngine(ExecutionConfig(**defaults))  # type: ignore[arg-type]


def fill(eng: ExecutionEngine, order: Order, b: Bar, spec: InstrumentSpec):
    return eng.try_fill(order, bar=b, bar_index=7, spec=spec, order_id=42)


def buy(**kwargs: object) -> Order:
    return Order(symbol="X", side=Side.BUY, quantity=1, **kwargs)  # type: ignore[arg-type]


def sell(**kwargs: object) -> Order:
    return Order(symbol="X", side=Side.SELL, quantity=1, **kwargs)  # type: ignore[arg-type]


def limit_buy(price: float) -> Order:
    return buy(order_type=OrderType.LIMIT, limit_price=price)


def limit_sell(price: float) -> Order:
    return sell(order_type=OrderType.LIMIT, limit_price=price)


def stop_buy(price: float) -> Order:
    return buy(order_type=OrderType.STOP, stop_price=price)


def stop_sell(price: float) -> Order:
    return sell(order_type=OrderType.STOP, stop_price=price)


class TestConfigValidation:
    def test_costs_have_no_default(self):
        with pytest.raises(TypeError):
            ExecutionConfig()  # type: ignore[call-arg]

    @pytest.mark.parametrize("lag", [0, -1])
    def test_zero_or_negative_lag_refused(self, lag):
        with pytest.raises(ConfigurationError, match="execution_lag"):
            ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage(), execution_lag=lag)

    def test_default_lag_is_one_bar(self):
        assert ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()).execution_lag == 1

    def test_default_intrabar_priority_is_pessimistic(self):
        config = ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())
        assert config.intrabar_priority is IntrabarPriority.PESSIMISTIC

    def test_default_max_fill_gap_is_none(self):
        assert ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()).max_fill_gap is None

    def test_non_positive_gap_refused(self):
        with pytest.raises(ConfigurationError, match="max_fill_gap"):
            ExecutionConfig(
                fees=ZeroFee(), slippage=ZeroSlippage(), max_fill_gap=timedelta(0)
            )

    def test_zero_cost_config_carries_its_warning(self):
        described = ZERO_COST.describe()
        assert "warning" in described["fees"]  # type: ignore[operator]
        assert "warning" in described["slippage"]  # type: ignore[operator]


class TestCostModels:
    def test_per_contract_fee_reads_the_instrument(self, spec):
        assert PerContractFee().fee(spec, 3) == pytest.approx(6.0)

    def test_flat_fee(self, spec):
        assert FlatFee(0.5).fee(spec, 4) == pytest.approx(2.0)

    def test_negative_flat_fee_refused(self):
        with pytest.raises(ConfigurationError, match="per_contract"):
            FlatFee(-1.0)

    def test_tick_slippage_is_in_ticks(self, spec):
        assert TickSlippage(2).offset(spec, 4000.0) == pytest.approx(0.5)

    def test_bps_slippage_is_proportional(self, spec):
        assert BpsSlippage(10).offset(spec, 4000.0) == pytest.approx(4.0)

    @pytest.mark.parametrize("model", [TickSlippage, BpsSlippage])
    def test_negative_slippage_refused(self, model):
        with pytest.raises(ConfigurationError):
            model(-1.0)

    def test_zero_models_are_named_objects(self, spec):
        assert ZeroFee().fee(spec, 10) == 0.0
        assert ZeroSlippage().offset(spec, 4000.0) == 0.0


class TestMarketOrders:
    def test_fills_at_the_open(self, spec):
        f = fill(engine(), buy(), bar(100, 102, 98, 101), spec)
        assert f is not None
        assert f.price == pytest.approx(100.0)
        assert f.bar_index == 7

    def test_buy_slippage_raises_the_price(self, spec):
        f = fill(
            engine(slippage=TickSlippage(2)),
            buy(),
            bar(100, 102, 98, 101),
            spec,
        )
        assert f is not None
        assert f.price == pytest.approx(100.5)
        assert f.slippage_cost == pytest.approx(0.5)

    def test_sell_slippage_lowers_the_price(self, spec):
        f = fill(
            engine(slippage=TickSlippage(2)),
            sell(),
            bar(100, 102, 98, 101),
            spec,
        )
        assert f is not None
        assert f.price == pytest.approx(99.5)

    def test_fee_is_per_contract_per_side(self, spec):
        f = fill(
            engine(fees=PerContractFee()),
            Order(symbol="X", side=Side.BUY, quantity=3),
            bar(100, 102, 98, 101),
            spec,
        )
        assert f is not None
        assert f.fee == pytest.approx(6.0)


class TestSlippageClamping:
    def test_slippage_is_clamped_to_the_bar_high(self, spec):
        """Un doji : le slippage ne peut pas creer un prix qui n'a pas existe."""
        eng = engine(slippage=TickSlippage(100))
        f = fill(eng, buy(), bar(100, 100.5, 99.5, 100), spec)
        assert f is not None
        assert f.price == pytest.approx(100.5)
        assert f.was_clamped
        assert eng.stats.n_slippage_clamped == 1

    def test_slippage_is_clamped_to_the_bar_low(self, spec):
        eng = engine(slippage=TickSlippage(100))
        f = fill(eng, sell(), bar(100, 100.5, 99.5, 100), spec)
        assert f is not None
        assert f.price == pytest.approx(99.5)

    def test_reported_slippage_is_the_effective_one(self, spec):
        """Apres ecretage, on rapporte ce qui a ete paye, pas la theorie."""
        eng = engine(slippage=TickSlippage(100))
        f = fill(eng, buy(), bar(100, 100.5, 99.5, 100), spec)
        assert f is not None
        assert f.slippage_cost == pytest.approx(0.5)


class TestLimitOrders:
    def test_buy_limit_not_touched(self, spec):
        eng = engine()
        order = limit_buy(95.0)
        assert fill(eng, order, bar(100, 102, 98, 101), spec) is None
        assert eng.stats.n_limit_not_touched == 1

    def test_buy_limit_touched_fills_at_the_limit(self, spec):
        order = limit_buy(99.0)
        f = fill(engine(), order, bar(100, 102, 98, 101), spec)
        assert f is not None
        assert f.price == pytest.approx(99.0)

    def test_gap_below_the_limit_fills_at_the_open(self, spec):
        """La barre ouvre sous la limite d'achat : on paie moins, pas la limite."""
        order = limit_buy(99.0)
        f = fill(engine(), order, bar(97, 100, 96, 98), spec)
        assert f is not None
        assert f.price == pytest.approx(97.0)

    def test_sell_limit_symmetric(self, spec):
        order = limit_sell(101.0)
        f = fill(engine(), order, bar(100, 102, 98, 101), spec)
        assert f is not None
        assert f.price == pytest.approx(101.0)

    def test_limit_takes_no_slippage(self, spec):
        order = limit_buy(99.0)
        f = fill(engine(slippage=TickSlippage(4)), order, bar(100, 102, 98, 101), spec)
        assert f is not None
        assert f.price == pytest.approx(99.0)
        assert f.slippage_cost == pytest.approx(0.0)


class TestStopOrders:
    def test_sell_stop_not_triggered(self, spec):
        eng = engine()
        order = stop_sell(95.0)
        assert fill(eng, order, bar(100, 102, 98, 101), spec) is None
        assert eng.stats.n_stop_not_triggered == 1

    def test_sell_stop_triggered_fills_at_the_stop(self, spec):
        order = stop_sell(99.0)
        f = fill(engine(), order, bar(100, 102, 98, 101), spec)
        assert f is not None
        assert f.price == pytest.approx(99.0)

    def test_gap_through_a_sell_stop_fills_at_the_open(self, spec):
        """LE cas qui compte : la barre ouvre a 95 sous un stop a 99.

        Remplir a 99 serait un mensonge de 4 points en faveur de la strategie.
        """
        order = stop_sell(99.0)
        f = fill(engine(), order, bar(95, 96, 90, 92), spec)
        assert f is not None
        assert f.price == pytest.approx(95.0)

    def test_gap_through_a_buy_stop_fills_at_the_open(self, spec):
        order = stop_buy(101.0)
        f = fill(engine(), order, bar(105, 107, 104, 106), spec)
        assert f is not None
        assert f.price == pytest.approx(105.0)

    def test_stop_takes_slippage(self, spec):
        order = stop_sell(99.0)
        f = fill(engine(slippage=TickSlippage(2)), order, bar(100, 102, 98, 101), spec)
        assert f is not None
        assert f.price == pytest.approx(98.5)


class TestFillBounds:
    """Test exige n° 7, volet deterministe. Le volet property-based est adversarial."""

    @pytest.mark.parametrize(
        "order",
        [
            buy(),
            sell(),
            limit_buy(99.0),
            stop_sell(99.0),
        ],
    )
    @pytest.mark.parametrize(
        "slip", [ZeroSlippage(), TickSlippage(1), TickSlippage(1000), BpsSlippage(500)]
    )
    def test_every_fill_is_inside_the_bar(self, spec, order, slip):
        b = bar(100, 102, 98, 101)
        f = fill(engine(slippage=slip), order, b, spec)
        if f is not None:
            assert b.low <= f.price <= b.high

    def test_assert_within_bar_rejects_an_impossible_price(self):
        b = bar(100, 102, 98, 101)
        assert_within_bar(101.9, b)
        with pytest.raises(AssertionError, match="n'a jamais existe"):
            assert_within_bar(102.1, b)


class TestStatsAndReset:
    def test_counters_accumulate(self, spec):
        eng = engine()
        b = bar(100, 102, 98, 101)
        fill(eng, buy(), b, spec)
        fill(eng, buy(), b, spec)
        assert eng.stats.n_fills == 2

    def test_reset_clears_them(self, spec):
        eng = engine()
        fill(eng, buy(), bar(100, 102, 98, 101), spec)
        eng.reset()
        assert eng.stats.n_fills == 0

    def test_describe_is_serialisable(self):
        import json

        described = ZERO_COST.describe()
        assert json.loads(json.dumps(described)) == described
