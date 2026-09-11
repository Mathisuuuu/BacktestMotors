"""Boucle principale : ordre des etapes, lag, protections, liquidation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from fixtures import synthetic
from rsl.data.feed import Context
from rsl.data.schema import BarStore, InstrumentSpec
from rsl.engine.execution import (
    ExecutionConfig,
    IntrabarPriority,
    PerContractFee,
    TickSlippage,
    ZeroFee,
    ZeroSlippage,
)
from rsl.engine.risk import FixedContracts, RiskManager
from rsl.engine.runner import RunConfig, SingleAssetRunner
from rsl.errors import ConfigurationError
from rsl.orders import Fill, Order, Side
from rsl.strategies.base import Strategy
from rsl.strategies.handwritten import BuyAndHold
from rsl.strategies.rules import FlatStrategy

SYMBOL = "TEST.v.0"
CASH = 100_000.0


def store_of(closes) -> BarStore:
    return synthetic.make_store(closes, symbol=SYMBOL)


def run(store: BarStore, spec: InstrumentSpec, strategy: Strategy, **cfg: object):
    execution = cfg.pop("execution", ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()))
    risk = cfg.pop("risk", None)
    config = RunConfig(initial_cash=CASH, execution=execution, **cfg)  # type: ignore[arg-type]
    runner = SingleAssetRunner(store, spec, config, risk=risk)  # type: ignore[arg-type]
    return runner.run(strategy)


@dataclass(eq=False)
class ScriptedStrategy(Strategy):
    """Emet des ordres a des indices de barre precis. Sert a tester le moteur."""

    script: dict[int, list[Order]]
    warmup: int = 0
    seen: list[int] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    started: int = 0
    finished: int = 0

    @property
    def warmup_bars(self) -> int:
        return self.warmup

    def reset(self) -> None:
        self.seen = []
        self.fills = []
        self.started = 0
        self.finished = 0

    def on_start(self, ctx: Context) -> None:
        self.started += 1

    def on_finish(self) -> None:
        self.finished += 1

    def on_fill(self, fill: Fill) -> None:
        self.fills.append(fill)

    def on_bar(self, ctx: Context) -> Sequence[Order]:
        index = ctx.n_bars_seen - 1
        self.seen.append(index)
        return self.script.get(index, [])


BUY = Order(symbol=SYMBOL, side=Side.BUY, quantity=1, tag="buy")
SELL = Order(symbol=SYMBOL, side=Side.SELL, quantity=1, reduce_only=True, tag="sell")


class TestConstruction:
    def test_symbol_mismatch_refused(self, spec):
        store = synthetic.make_store(synthetic.ramp(50), symbol="AUTRE")
        with pytest.raises(ConfigurationError, match="ne concordent pas"):
            SingleAssetRunner(
                store,
                spec,
                RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
            )

    def test_non_positive_cash_refused(self):
        with pytest.raises(ConfigurationError, match="initial_cash"):
            RunConfig(0.0, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()))


class TestLifecycle:
    def test_every_bar_after_warmup_is_offered(self, spec):
        strategy = ScriptedStrategy({}, warmup=10)
        result = run(store_of(synthetic.ramp(100)), spec, strategy)
        assert strategy.seen == list(range(10, 100))
        assert result.counters.n_bars == 90
        assert len(result.equity) == 90

    def test_on_start_fires_once(self, spec):
        strategy = ScriptedStrategy({}, warmup=5)
        run(store_of(synthetic.ramp(60)), spec, strategy)
        assert strategy.started == 1
        assert strategy.finished == 1

    def test_stop_truncates_the_run(self, spec):
        result = run(store_of(synthetic.ramp(200)), spec, FlatStrategy(), stop=50)
        assert result.counters.n_bars == 50

    def test_warmup_is_the_max_of_strategy_and_risk(self, spec):
        from rsl.engine.risk import RiskFraction

        strategy = ScriptedStrategy({}, warmup=5)
        result = run(
            store_of(synthetic.ramp(200)),
            spec,
            strategy,
            risk=RiskManager(sizing=RiskFraction(0.01, atr_window=30)),
        )
        assert result.counters.warmup_bars == 31


class TestExecutionLag:
    def test_default_lag_fills_on_the_next_bar(self, spec):
        strategy = ScriptedStrategy({10: [BUY]})
        store = store_of(synthetic.ramp(50, 100.0, 1.0))
        result = run(store, spec, strategy)
        assert len(result.fills) == 1
        fill = result.fills[0]
        assert fill.bar_index == 11
        assert fill.price == pytest.approx(float(store.open[11]))

    def test_a_longer_lag_delays_the_fill(self, spec):
        strategy = ScriptedStrategy({10: [BUY]})
        store = store_of(synthetic.ramp(50, 100.0, 1.0))
        result = run(
            store,
            spec,
            strategy,
            execution=ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage(), execution_lag=3),
        )
        assert result.fills[0].bar_index == 13

    def test_the_signal_bar_is_never_the_fill_bar(self, spec):
        """La fuite la plus courante des backtests naifs."""
        strategy = ScriptedStrategy({i: [BUY] for i in range(0, 40, 4)})
        store = store_of(synthetic.ramp(50, 100.0, 1.0))
        result = run(store, spec, strategy, risk=RiskManager(max_gross_contracts=100))
        for fill in result.fills:
            assert fill.bar_index >= 1

    def test_an_order_submitted_too_late_expires_unfilled(self, spec):
        strategy = ScriptedStrategy({49: [BUY]})
        result = run(store_of(synthetic.ramp(50)), spec, strategy)
        assert result.fills == ()
        assert result.counters.n_orders_cancelled_unfilled == 1


class TestFillNotification:
    def test_the_strategy_learns_its_position_through_on_fill(self, spec):
        strategy = ScriptedStrategy({5: [BUY]})
        run(store_of(synthetic.ramp(30)), spec, strategy)
        assert len(strategy.fills) == 1
        assert strategy.fills[0].signed_quantity == 1

    def test_notification_happens_on_the_fill_bar(self, spec):
        strategy = ScriptedStrategy({5: [BUY]})
        run(store_of(synthetic.ramp(30)), spec, strategy)
        assert strategy.fills[0].bar_index == 6


class TestReduceOnly:
    def test_a_sell_without_position_does_nothing(self, spec):
        strategy = ScriptedStrategy({5: [SELL]})
        result = run(store_of(synthetic.ramp(30)), spec, strategy)
        assert result.fills == ()
        assert result.portfolio.quantity_of(SYMBOL) == 0

    def test_a_position_closed_before_the_exit_arrives_is_not_reopened(self, spec):
        """L'ordre est revalide au moment du fill, pas seulement a la soumission."""
        strategy = ScriptedStrategy({5: [BUY], 6: [SELL, SELL]})
        result = run(store_of(synthetic.ramp(30)), spec, strategy)
        assert result.portfolio.quantity_of(SYMBOL) == 0
        assert len([f for f in result.fills if f.side is Side.SELL]) == 1


class TestProtections:
    def _store_with_a_drop(self) -> BarStore:
        closes = synthetic.ramp(30, 100.0, 1.0)
        closes[15:] = 80.0
        return store_of(closes)

    def test_stop_loss_fires(self, spec):
        entry = Order(symbol=SYMBOL, side=Side.BUY, quantity=1, stop_loss=100.0)
        strategy = ScriptedStrategy({5: [entry]})
        result = run(self._store_with_a_drop(), spec, strategy)
        assert result.counters.n_protection_fills == 1
        assert result.portfolio.quantity_of(SYMBOL) == 0
        assert result.fills[-1].tag.endswith(":stop_loss")

    def test_stop_is_not_armed_on_the_entry_bar(self, spec):
        """Une position ne peut pas etre protegee par la barre qui l'ouvre."""
        closes = synthetic.ramp(30, 100.0, 1.0)
        store = store_of(closes)
        entry_bar = 6
        far_stop = float(store.low[entry_bar]) + 0.5  # touchable des la barre d'entree
        strategy = ScriptedStrategy(
            {5: [Order(symbol=SYMBOL, side=Side.BUY, quantity=1, stop_loss=far_stop)]}
        )
        result = run(store, spec, strategy)
        protection_fills = [f for f in result.fills if "stop_loss" in f.tag]
        assert all(f.bar_index > entry_bar for f in protection_fills)

    def test_take_profit_fires(self, spec):
        store = store_of(synthetic.ramp(30, 100.0, 1.0))
        strategy = ScriptedStrategy(
            {5: [Order(symbol=SYMBOL, side=Side.BUY, quantity=1, take_profit=110.0)]}
        )
        result = run(store, spec, strategy)
        assert result.counters.n_protection_fills == 1
        assert result.fills[-1].tag.endswith(":take_profit")

    def test_ambiguous_bar_is_counted_and_resolved_pessimistically(self, spec):
        """Stop et take-profit atteignables dans la meme barre."""
        closes = synthetic.constant(30, 100.0)
        store = synthetic.make_store(closes, symbol=SYMBOL, wick=0.10)
        order = Order(symbol=SYMBOL, side=Side.BUY, quantity=1, stop_loss=95.0, take_profit=105.0)
        result = run(store, spec, ScriptedStrategy({5: [order]}))
        assert result.counters.n_intrabar_ambiguous >= 1
        assert result.fills[-1].tag.endswith(":stop_loss")

    def test_optimistic_priority_picks_the_take_profit(self, spec):
        closes = synthetic.constant(30, 100.0)
        store = synthetic.make_store(closes, symbol=SYMBOL, wick=0.10)
        order = Order(symbol=SYMBOL, side=Side.BUY, quantity=1, stop_loss=95.0, take_profit=105.0)
        result = run(
            store,
            spec,
            ScriptedStrategy({5: [order]}),
            execution=ExecutionConfig(
                fees=ZeroFee(),
                slippage=ZeroSlippage(),
                intrabar_priority=IntrabarPriority.OPTIMISTIC,
            ),
        )
        assert result.fills[-1].tag.endswith(":take_profit")

    def test_protection_disappears_when_the_strategy_closes_first(self, spec):
        store = store_of(synthetic.ramp(30, 100.0, 1.0))
        strategy = ScriptedStrategy(
            {
                5: [Order(symbol=SYMBOL, side=Side.BUY, quantity=1, stop_loss=1.0)],
                8: [SELL],
            }
        )
        result = run(store, spec, strategy)
        assert result.portfolio.quantity_of(SYMBOL) == 0
        assert result.counters.n_protection_fills == 0


class TestMaxFillGap:
    """Un ordre soumis vendredi soir se remplit dimanche, apres 49 heures.

    C'est realiste, et c'est le defaut. Le seuil existe pour les strategies
    intraday qui n'en veulent pas (`docs/execution-model.md` §5).
    """

    def _weekend_store(self) -> BarStore:
        return synthetic.make_gapped_store(
            synthetic.ramp(30, 100.0, 1.0),
            gap_after=5,
            gap=timedelta(hours=49),
            symbol=SYMBOL,
        )

    def test_a_contiguous_series_has_no_gap_at_all(self, spec):
        """Sur une serie sans trou, `ts_close(t) == ts_event(t+1)` : ecart nul."""
        result = run(
            store_of(synthetic.ramp(30)),
            spec,
            ScriptedStrategy({5: [BUY]}),
            execution=ExecutionConfig(
                fees=ZeroFee(), slippage=ZeroSlippage(), max_fill_gap=timedelta(seconds=1)
            ),
        )
        assert result.counters.n_orders_expired_gap == 0
        assert len(result.fills) == 1

    def test_no_expiry_by_default_even_across_a_weekend(self, spec):
        result = run(self._weekend_store(), spec, ScriptedStrategy({5: [BUY]}))
        assert result.counters.n_orders_expired_gap == 0
        assert len(result.fills) == 1

    def test_order_expires_when_the_gap_exceeds_the_limit(self, spec):
        result = run(
            self._weekend_store(),
            spec,
            ScriptedStrategy({5: [BUY]}),
            execution=ExecutionConfig(
                fees=ZeroFee(), slippage=ZeroSlippage(), max_fill_gap=timedelta(minutes=5)
            ),
        )
        assert result.counters.n_orders_expired_gap == 1
        assert result.fills == ()

    def test_an_order_outside_the_gap_is_unaffected(self, spec):
        result = run(
            self._weekend_store(),
            spec,
            ScriptedStrategy({10: [BUY]}),
            execution=ExecutionConfig(
                fees=ZeroFee(), slippage=ZeroSlippage(), max_fill_gap=timedelta(minutes=5)
            ),
        )
        assert result.counters.n_orders_expired_gap == 0
        assert len(result.fills) == 1


class TestSizingIntegration:
    def test_the_risk_manager_overrides_the_quantity(self, spec):
        result = run(
            store_of(synthetic.ramp(30)),
            spec,
            ScriptedStrategy({5: [BUY]}),
            risk=RiskManager(sizing=FixedContracts(4)),
        )
        assert result.fills[0].quantity == 4
        assert result.portfolio.quantity_of(SYMBOL) == 4

    def test_dropped_orders_are_counted(self, spec):
        result = run(
            store_of(synthetic.ramp(30)),
            spec,
            ScriptedStrategy({5: [Order(symbol=SYMBOL, side=Side.BUY, quantity=50)]}),
        )
        assert result.counters.n_orders_dropped_risk == 1
        assert result.fills == ()


class TestTerminalLiquidation:
    def test_off_by_default(self, spec):
        result = run(store_of(synthetic.ramp(50)), spec, BuyAndHold(SYMBOL, 1))
        assert result.portfolio.quantity_of(SYMBOL) == 1
        assert not result.counters.terminal_liquidation

    def test_closes_the_position_and_costs_only_the_exit_fee(self, spec):
        store = store_of(synthetic.ramp(50, 100.0, 1.0))
        execution = ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(1))
        held = run(store, spec, BuyAndHold(SYMBOL, 2), execution=execution)
        closed = run(
            store, spec, BuyAndHold(SYMBOL, 2), execution=execution, liquidate_at_end=True
        )
        exit_fee = 2 * spec.fee_per_contract_per_side
        assert closed.portfolio.quantity_of(SYMBOL) == 0
        assert closed.counters.terminal_liquidation
        assert closed.final_equity == pytest.approx(held.final_equity - exit_fee)

    def test_the_curve_is_not_lengthened(self, spec):
        store = store_of(synthetic.ramp(50))
        held = run(store, spec, BuyAndHold(SYMBOL, 1))
        closed = run(store, spec, BuyAndHold(SYMBOL, 1), liquidate_at_end=True)
        assert len(closed.equity) == len(held.equity)


class TestRunResult:
    def test_describe_is_serialisable(self, spec):
        import json

        result = run(store_of(synthetic.ramp(40)), spec, BuyAndHold(SYMBOL, 1))
        described = result.describe()
        assert json.loads(json.dumps(described)) == described

    def test_total_return_matches_the_curve(self, spec):
        result = run(store_of(synthetic.ramp(40)), spec, BuyAndHold(SYMBOL, 1))
        assert result.total_return == pytest.approx(result.final_equity / CASH - 1.0)

    def test_equity_curve_is_timestamped_on_bar_closes(self, spec):
        store = store_of(synthetic.ramp(40))
        result = run(store, spec, FlatStrategy())
        assert result.equity.ts_ns[0] == int(store.ts_close[0])
        assert result.equity.ts_ns[-1] == int(store.ts_close[39])

    def test_exposure_tracks_the_position(self, spec):
        result = run(store_of(synthetic.ramp(40)), spec, ScriptedStrategy({5: [BUY]}))
        assert result.equity.exposure[0] == 0
        assert result.equity.exposure[-1] == 1


class TestRerun:
    def test_the_same_runner_can_be_reused(self, spec):
        store = store_of(synthetic.ramp(60, 100.0, 1.0))
        config = RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()))
        runner = SingleAssetRunner(store, spec, config)
        strategy = BuyAndHold(SYMBOL, 1)
        first = runner.run(strategy)
        second = runner.run(strategy)
        assert first.final_equity == second.final_equity
        assert [f.price for f in first.fills] == [f.price for f in second.fills]
