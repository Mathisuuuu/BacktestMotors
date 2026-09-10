"""Strategies de reference : croisement SMA et momentum transversal 12-1.

Le test le plus utile de ce fichier est `TestSmaAgainstComposition` : la
strategie ecrite a la main et sa traduction en noeuds de signaux doivent
produire la MEME suite d'ordres, barre par barre. Deux implementations
independantes qui concordent valent mieux qu'une seule verifiee contre
elle-meme, et c'est la couche de signaux qui est controlee au passage.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext, MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import BarStore, Granularity, InstrumentSpec
from rsl.engine.cross_sectional import CrossSectionalRunner
from rsl.engine.execution import ExecutionConfig, ZeroFee, ZeroSlippage
from rsl.engine.orders import Fill, Order, Side
from rsl.engine.runner import RunConfig, SingleAssetRunner
from rsl.errors import ConfigurationError
from rsl.strategies.base import build_strategy, get_strategy
from rsl.strategies.handwritten import CrossSectionalMomentum, SmaCrossover
from rsl.strategies.rules import RuleStrategy
from rsl.strategies.signals import Arith, ArithOp, CrossesAbove, CrossesBelow, const, price, prim

SYMBOL = "TEST.v.0"
CASH = 1_000_000.0
DAY = Granularity(timedelta(days=1), name="1d")
EPOCH = datetime(2021, 1, 1, tzinfo=UTC)

SINE = synthetic.sine(600, 100.0, 10.0, 64)


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


def fill_for(order: Order, price_: float = 100.0) -> Fill:
    return Fill(
        order_id=0,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        price=price_,
        fee=0.0,
        slippage_cost=0.0,
        ts_ns=0,
        bar_index=0,
        tag=order.tag,
    )


# ---------------------------------------------------------------------------
# Croisement de moyennes
# ---------------------------------------------------------------------------


class TestSmaCrossoverValidation:
    def test_fast_must_be_shorter_than_slow(self):
        with pytest.raises(ConfigurationError, match="pas de croisement"):
            SmaCrossover(SYMBOL, fast_window=50, slow_window=50)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"fast_window": 0, "slow_window": 20},
            {"fast_window": 5, "slow_window": 0},
            {"fast_window": 5, "slow_window": 20, "quantity": 0},
            {"fast_window": 5, "slow_window": 20, "atr_window": 0},
            {"fast_window": 5, "slow_window": 20, "atr_multiple": 0.0},
        ],
    )
    def test_invalid_parameters_refused(self, kwargs):
        with pytest.raises(ConfigurationError):
            SmaCrossover(SYMBOL, **kwargs)

    def test_warmup_covers_the_slow_window_and_the_previous_bar(self):
        strategy = SmaCrossover(SYMBOL, fast_window=5, slow_window=20, atr_window=14)
        assert strategy.warmup_bars == 21

    def test_warmup_can_be_driven_by_the_atr(self):
        strategy = SmaCrossover(SYMBOL, fast_window=5, slow_window=20, atr_window=100)
        assert strategy.warmup_bars == 102


class TestSmaCrossoverBehaviour:
    def _strategy(self) -> SmaCrossover:
        return SmaCrossover(SYMBOL, fast_window=5, slow_window=20, atr_multiple=2.0)

    def test_enters_long_on_a_bullish_cross(self):
        store = synthetic.make_store(SINE, symbol=SYMBOL)
        strategy = self._strategy()
        entries = []
        for i in range(strategy.warmup_bars, 600):
            for order in strategy.on_bar(at(store, i)):
                strategy.on_fill(fill_for(order))
                if order.tag == "sma_entry":
                    entries.append(order)
        assert entries
        assert all(o.side is Side.BUY for o in entries)

    def test_attaches_a_stop_below_the_close(self):
        store = synthetic.make_store(SINE, symbol=SYMBOL)
        strategy = self._strategy()
        for i in range(strategy.warmup_bars, 600):
            ctx = at(store, i)
            for order in strategy.on_bar(ctx):
                strategy.on_fill(fill_for(order))
                if order.tag == "sma_entry":
                    assert order.stop_loss is not None
                    assert order.stop_loss < ctx.bar.close
                    return
        pytest.fail("aucune entree produite")

    def test_never_pyramids(self):
        store = synthetic.make_store(SINE, symbol=SYMBOL)
        strategy = self._strategy()
        position = 0
        for i in range(strategy.warmup_bars, 600):
            for order in strategy.on_bar(at(store, i)):
                strategy.on_fill(fill_for(order))
                position += order.signed_quantity
                assert 0 <= position <= 1

    def test_exit_is_reduce_only_and_sized_to_the_position(self):
        store = synthetic.make_store(SINE, symbol=SYMBOL)
        strategy = self._strategy()
        for i in range(strategy.warmup_bars, 600):
            for order in strategy.on_bar(at(store, i)):
                if order.tag == "sma_exit":
                    assert order.reduce_only
                    assert order.quantity == abs(strategy._position)
                strategy.on_fill(fill_for(order))

    def test_no_signal_on_a_monotonic_ramp(self):
        store = synthetic.make_store(synthetic.ramp(300, 100.0, 1.0), symbol=SYMBOL)
        strategy = self._strategy()
        for i in range(strategy.warmup_bars, 300):
            assert strategy.on_bar(at(store, i)) == ()

    def test_reset_clears_the_position(self):
        strategy = self._strategy()
        strategy.on_fill(fill_for(Order(symbol=SYMBOL, side=Side.BUY, quantity=1)))
        assert strategy._position == 1
        strategy.reset()
        assert strategy._position == 0

    def test_fills_of_another_symbol_are_ignored(self):
        strategy = self._strategy()
        strategy.on_fill(fill_for(Order(symbol="AUTRE", side=Side.BUY, quantity=4)))
        assert strategy._position == 0

    def test_a_flat_series_attaches_no_stop(self):
        """ATR nul : pas de stop plutot qu'un stop a un prix impossible."""
        store = synthetic.make_store(synthetic.constant(300, 100.0), symbol=SYMBOL, wick=0.0)
        strategy = self._strategy()
        assert strategy._stop_level(at(store, 200)) is None


class TestSmaAgainstComposition:
    """La strategie ecrite a la main et sa composition doivent concorder."""

    FAST, SLOW, ATR, MULT = 5, 20, 14, 2.0

    def _handwritten(self) -> SmaCrossover:
        return SmaCrossover(
            SYMBOL,
            fast_window=self.FAST,
            slow_window=self.SLOW,
            atr_window=self.ATR,
            atr_multiple=self.MULT,
        )

    def _composed(self) -> RuleStrategy:
        fast = prim("sma@1", window=self.FAST)
        slow = prim("sma@1", window=self.SLOW)
        return RuleStrategy(
            symbol=SYMBOL,
            quantity=1,
            entry_long=CrossesAbove(fast, slow),
            exit_long=CrossesBelow(fast, slow),
            stop_loss=Arith(
                price("close"),
                ArithOp.SUB,
                Arith(const(self.MULT), ArithOp.MUL, prim("atr@1", window=self.ATR)),
            ),
        )

    def test_same_warmup(self):
        assert self._handwritten().warmup_bars == self._composed().warmup_bars

    @pytest.mark.parametrize(
        "series",
        [
            synthetic.sine(600, 100.0, 10.0, 64),
            synthetic.sine(600, 100.0, 25.0, 40),
            synthetic.random_walk(600, seed=7),
            synthetic.random_walk(600, seed=99),
        ],
        ids=["sinus_64", "sinus_40", "walk_7", "walk_99"],
    )
    def test_same_orders_bar_by_bar(self, series):
        store = synthetic.make_store(series, symbol=SYMBOL)
        handwritten, composed = self._handwritten(), self._composed()
        assert handwritten.warmup_bars == composed.warmup_bars

        produced = 0
        for i in range(handwritten.warmup_bars, 600):
            ctx = at(store, i)
            a = list(handwritten.on_bar(ctx))
            b = list(composed.on_bar(ctx))
            assert [(o.side, o.quantity, o.reduce_only) for o in a] == [
                (o.side, o.quantity, o.reduce_only) for o in b
            ], f"divergence a l'index {i}"
            for x, y in zip(a, b, strict=True):
                if x.stop_loss is None:
                    assert y.stop_loss is None
                else:
                    assert y.stop_loss == pytest.approx(x.stop_loss)
            produced += len(a)
            for order in a:
                handwritten.on_fill(fill_for(order))
            for order in b:
                composed.on_fill(fill_for(order))

        assert produced > 5, "le scenario ne produit presque aucun ordre : test creux"


class TestSmaThroughTheEngine:
    def test_a_full_run_holds_the_invariant(self, spec: InstrumentSpec):
        store = synthetic.make_store(SINE, symbol=SYMBOL)
        strategy = SmaCrossover(SYMBOL, fast_window=5, slow_window=20)
        result = SingleAssetRunner(
            store, spec, RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()))
        ).run(strategy)
        assert result.counters.n_bars > 0
        assert len(result.fills) > 0

    def test_registered_and_buildable_from_a_spec(self):
        entry = get_strategy("sma_crossover")
        assert entry.version == 1
        built = build_strategy(
            {"ref": "sma_crossover@1", "params": {"symbol": SYMBOL, "fast_window": 3,
                                                  "slow_window": 9}}
        )
        assert isinstance(built, SmaCrossover)
        assert built.slow_window == 9

    def test_describe_is_serialisable(self):
        import json

        described = SmaCrossover(SYMBOL).describe()
        assert json.loads(json.dumps(described)) == described


# ---------------------------------------------------------------------------
# Momentum transversal 12-1
# ---------------------------------------------------------------------------

SLOPES = {"S0": 5.0, "S1": 4.0, "S2": 3.0, "S3": 2.0, "S4": 1.0, "S5": 0.0}


def momentum_panel(n: int = 40):
    """Six rampes de pentes decroissantes : le classement est connu d'avance."""
    stores = {
        name: synthetic.make_store(
            synthetic.ramp(n, 100.0, slope), symbol=name, granularity=DAY, start=EPOCH
        )
        for name, slope in SLOPES.items()
    }
    return build_panel(stores), stores


def multi_at(panel, row: int) -> MultiContext:
    ctx = MultiContext(panel)
    ctx._seek_row(row)
    return ctx


class TestMomentumValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"lookback": 1},
            {"skip": 12},
            {"skip": -1},
            {"n_long": 0},
            {"n_short": 0},
            {"quantity": 0},
        ],
    )
    def test_invalid_parameters_refused(self, kwargs):
        with pytest.raises(ConfigurationError):
            CrossSectionalMomentum(**kwargs)

    def test_short_leg_may_be_absent_when_long_only(self):
        strategy = CrossSectionalMomentum(n_short=0, long_short=False)
        assert strategy.required_universe == strategy.n_long

    def test_warmup_allows_reading_the_oldest_lag(self):
        assert CrossSectionalMomentum(lookback=12).warmup_bars == 13

    def test_required_universe_covers_both_legs(self):
        assert CrossSectionalMomentum(n_long=3, n_short=3).required_universe == 6


class TestMomentumRanking:
    def test_scores_follow_the_slopes(self):
        panel, _ = momentum_panel()
        strategy = CrossSectionalMomentum(lookback=12, skip=1, n_long=2, n_short=2)
        scores = strategy._scores(multi_at(panel, 20))
        assert set(scores) == set(SLOPES)
        assert sorted(scores, key=lambda s: -scores[s]) == ["S0", "S1", "S2", "S3", "S4", "S5"]

    def test_score_matches_the_closed_form(self):
        panel, stores = momentum_panel()
        strategy = CrossSectionalMomentum(lookback=12, skip=1)
        row = 20
        scores = strategy._scores(multi_at(panel, row))
        closes = stores["S0"].close
        assert scores["S0"] == pytest.approx(
            float(closes[row - 1]) / float(closes[row - 12]) - 1.0
        )

    def test_the_most_recent_period_is_skipped(self):
        """Le "-1" du nom : la barre `t` n'entre pas dans le score."""
        panel, _ = momentum_panel()
        strategy = CrossSectionalMomentum(lookback=12, skip=1)
        row = 20
        before = strategy._scores(multi_at(panel, row))["S0"]

        closes = synthetic.ramp(40, 100.0, 5.0).copy()
        closes[row] = 10_000.0  # barre courante rendue absurde
        tampered = {
            name: synthetic.make_store(
                closes if name == "S0" else synthetic.ramp(40, 100.0, SLOPES[name]),
                symbol=name,
                granularity=DAY,
                start=EPOCH,
            )
            for name in SLOPES
        }
        after = strategy._scores(multi_at(build_panel(tampered), row))["S0"]
        assert after == pytest.approx(before)

    def test_an_instrument_without_enough_history_is_not_scored(self):
        panel, _ = momentum_panel()
        strategy = CrossSectionalMomentum(lookback=12)
        assert strategy._scores(multi_at(panel, 5)) == {}

    def test_targets_take_the_extremes(self):
        panel, _ = momentum_panel()
        strategy = CrossSectionalMomentum(lookback=12, skip=1, n_long=2, n_short=2)
        targets = strategy._targets(strategy._scores(multi_at(panel, 20)))
        assert targets == {"S0": 1, "S1": 1, "S4": -1, "S5": -1}

    def test_long_only_has_no_short_leg(self):
        panel, _ = momentum_panel()
        strategy = CrossSectionalMomentum(lookback=12, n_long=2, n_short=2, long_short=False)
        targets = strategy._targets(strategy._scores(multi_at(panel, 20)))
        assert targets == {"S0": 1, "S1": 1}

    def test_ties_are_broken_alphabetically(self):
        """Sans seconde cle de tri, deux runs identiques pourraient differer."""
        strategy = CrossSectionalMomentum(n_long=2, n_short=2)
        scores = {"D": 0.1, "A": 0.1, "C": 0.1, "B": 0.1}
        assert strategy._targets(scores) == {"A": 1, "B": 1, "C": -1, "D": -1}


class TestMomentumOrders:
    def _strategy(self) -> CrossSectionalMomentum:
        return CrossSectionalMomentum(lookback=12, skip=1, n_long=2, n_short=2)

    def test_opens_both_legs_from_flat(self):
        panel, _ = momentum_panel()
        strategy = self._strategy()
        orders = strategy.on_rebalance(multi_at(panel, 20))
        assert {(o.symbol, o.side) for o in orders} == {
            ("S0", Side.BUY), ("S1", Side.BUY), ("S4", Side.SELL), ("S5", Side.SELL)
        }
        assert all(not o.reduce_only for o in orders)

    def test_a_kept_leg_produces_no_order(self):
        panel, _ = momentum_panel()
        strategy = self._strategy()
        for order in strategy.on_rebalance(multi_at(panel, 20)):
            strategy.on_fill(fill_for(order))
        assert strategy.on_rebalance(multi_at(panel, 21)) == []

    def test_a_dropped_leg_is_closed_with_reduce_only(self):
        panel, _ = momentum_panel()
        strategy = self._strategy()
        strategy.on_fill(fill_for(Order(symbol="S2", side=Side.BUY, quantity=1)))
        orders = strategy.on_rebalance(multi_at(panel, 20))
        exits = [o for o in orders if o.reduce_only]
        assert len(exits) == 1
        assert exits[0].symbol == "S2"
        assert exits[0].side is Side.SELL

    def test_a_reversed_leg_is_closed_then_reopened(self):
        panel, _ = momentum_panel()
        strategy = self._strategy()
        strategy.on_fill(fill_for(Order(symbol="S0", side=Side.SELL, quantity=1)))
        orders = strategy.on_rebalance(multi_at(panel, 20))
        on_s0 = [o for o in orders if o.symbol == "S0"]
        assert len(on_s0) == 2
        assert on_s0[0].reduce_only and on_s0[0].side is Side.BUY
        assert not on_s0[1].reduce_only and on_s0[1].side is Side.BUY
        assert orders.index(on_s0[0]) < orders.index(on_s0[1])

    def test_exits_come_before_entries(self):
        panel, _ = momentum_panel()
        strategy = self._strategy()
        strategy.on_fill(fill_for(Order(symbol="S2", side=Side.BUY, quantity=1)))
        orders = strategy.on_rebalance(multi_at(panel, 20))
        first_entry = next(i for i, o in enumerate(orders) if not o.reduce_only)
        assert all(o.reduce_only for o in orders[:first_entry])

    def test_order_emission_is_deterministic(self):
        panel, _ = momentum_panel()

        def once():
            strategy = self._strategy()
            strategy.on_fill(fill_for(Order(symbol="S2", side=Side.BUY, quantity=1)))
            return [(o.symbol, o.side.value, o.quantity, o.reduce_only)
                    for o in strategy.on_rebalance(multi_at(panel, 20))]

        assert once() == once()

    def test_a_universe_too_narrow_holds_instead_of_liquidating(self):
        """Manquer de donnees n'est pas une raison de vendre."""
        panel, _ = momentum_panel()
        strategy = CrossSectionalMomentum(lookback=12, n_long=4, n_short=4)
        strategy.on_fill(fill_for(Order(symbol="S0", side=Side.BUY, quantity=1)))
        assert strategy.on_rebalance(multi_at(panel, 20)) == ()
        assert strategy._skipped_rebalances == 1
        assert strategy._positions == {"S0": 1}

    def test_reset_clears_positions_and_counters(self):
        strategy = self._strategy()
        strategy.on_fill(fill_for(Order(symbol="S0", side=Side.BUY, quantity=1)))
        strategy.reset()
        assert strategy._positions == {}
        assert strategy._rebalances == 0

    def test_a_closed_position_leaves_the_dictionary(self):
        strategy = self._strategy()
        strategy.on_fill(fill_for(Order(symbol="S0", side=Side.BUY, quantity=2)))
        strategy.on_fill(fill_for(Order(symbol="S0", side=Side.SELL, quantity=2)))
        assert strategy._positions == {}


class TestMomentumThroughTheEngine:
    def test_a_full_run_trades_and_holds_the_invariant(self, spec: InstrumentSpec):
        panel, _ = momentum_panel(60)
        specs = {
            name: spec.model_copy(update={"symbol": name, "root": name}) for name in SLOPES
        }
        strategy = CrossSectionalMomentum(lookback=12, skip=1, n_long=2, n_short=2)
        result = CrossSectionalRunner(
            panel, specs, RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()))
        ).run(strategy)

        assert result.counters.n_rebalances > 0
        assert len(result.fills) == 4, "les rampes ne changent jamais d'ordre : 4 entrees"
        assert result.portfolio.quantity_of("S0") == 1
        assert result.portfolio.quantity_of("S5") == -1

    def test_registered_and_buildable_from_a_spec(self):
        entry = get_strategy("cross_sectional_momentum")
        assert entry.cross_sectional
        built = build_strategy(
            {"ref": "cross_sectional_momentum@1", "params": {"lookback": 6, "n_long": 1}}
        )
        assert isinstance(built, CrossSectionalMomentum)
        assert built.lookback == 6

    def test_describe_is_serialisable(self):
        import json

        described = CrossSectionalMomentum().describe()
        assert json.loads(json.dumps(described)) == described
