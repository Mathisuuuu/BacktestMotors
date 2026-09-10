"""Contrat des strategies, `RuleStrategy` et registre versionne."""

from __future__ import annotations

import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore
from rsl.engine.orders import Fill, Order, OrderType, Side
from rsl.errors import ConfigurationError, RegistryError
from rsl.strategies.base import (
    NoStrategyParams,
    Strategy,
    StrategyParams,
    build_strategy,
    describe_strategies,
    get_strategy,
    list_strategies,
    strategy,
)
from rsl.strategies.rules import FlatStrategy, RuleStrategy
from rsl.strategies.signals import (
    Arith,
    ArithOp,
    Compare,
    CompareOp,
    CrossesAbove,
    CrossesBelow,
    const,
    price,
    prim,
)

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


def crossover_strategy(**overrides: object) -> RuleStrategy:
    fast, slow = prim("sma@1", window=5), prim("sma@1", window=20)
    defaults: dict[str, object] = {
        "symbol": "SYNTH.v.0",
        "quantity": 1,
        "entry_long": CrossesAbove(fast, slow),
        "exit_long": CrossesBelow(fast, slow),
    }
    defaults.update(overrides)
    return RuleStrategy(**defaults)  # type: ignore[arg-type]


class TestOrderTypes:
    def test_quantity_must_be_positive(self):
        with pytest.raises(ConfigurationError, match="quantity"):
            Order(symbol="X", side=Side.BUY, quantity=0)

    def test_side_carries_the_direction(self):
        assert Order(symbol="X", side=Side.SELL, quantity=3).signed_quantity == -3
        assert Side.BUY.opposite is Side.SELL

    def test_limit_requires_a_level(self):
        with pytest.raises(ConfigurationError, match="LIMIT"):
            Order(symbol="X", side=Side.BUY, quantity=1, order_type=OrderType.LIMIT)

    def test_stop_requires_a_level(self):
        with pytest.raises(ConfigurationError, match="STOP"):
            Order(symbol="X", side=Side.BUY, quantity=1, order_type=OrderType.STOP)

    def test_market_refuses_a_useless_level(self):
        with pytest.raises(ConfigurationError, match="MARKET"):
            Order(symbol="X", side=Side.BUY, quantity=1, limit_price=100.0)

    def test_reduce_only_cannot_attach_protections(self):
        with pytest.raises(ConfigurationError, match="reduce_only"):
            Order(symbol="X", side=Side.SELL, quantity=1, reduce_only=True, stop_loss=90.0)

    def test_orders_are_frozen(self):
        order = Order(symbol="X", side=Side.BUY, quantity=1)
        with pytest.raises(Exception, match=r"cannot assign|frozen|immutable"):
            order.quantity = 2  # type: ignore[misc]

    def test_orders_carry_no_identifier(self):
        """Un identifiant genere par la strategie casserait le determinisme."""
        assert not hasattr(Order(symbol="X", side=Side.BUY, quantity=1), "id")


class TestFlatStrategy:
    def test_never_emits_an_order(self):
        store = synthetic.make_store(SINE)
        flat = FlatStrategy()
        assert flat.warmup_bars == 0
        for i in range(0, 600, 37):
            assert flat.on_bar(at(store, i)) == ()


class TestRuleStrategyWarmup:
    def test_warmup_is_the_deepest_rule(self):
        assert crossover_strategy().warmup_bars == 21

    def test_extra_warmup_is_added(self):
        assert crossover_strategy(extra_warmup=100).warmup_bars == 121

    def test_stop_rule_counts_towards_warmup(self):
        stop = Arith(price("close"), ArithOp.SUB, prim("atr@1", window=100))
        assert crossover_strategy(stop_loss=stop).warmup_bars == 101

    def test_negative_extra_warmup_refused(self):
        with pytest.raises(ConfigurationError, match="extra_warmup"):
            crossover_strategy(extra_warmup=-1)

    def test_a_strategy_without_any_entry_is_refused(self):
        with pytest.raises(ConfigurationError, match="FlatStrategy"):
            RuleStrategy(symbol="X", quantity=1)

    def test_non_positive_quantity_refused(self):
        with pytest.raises(ConfigurationError, match="quantity"):
            crossover_strategy(quantity=0)


class TestRuleStrategyBehaviour:
    def test_enters_long_on_a_bullish_cross(self):
        store = synthetic.make_store(SINE)
        strat = crossover_strategy()
        entries = [
            order
            for i in range(strat.warmup_bars, 600)
            for order in strat.on_bar(at(store, i))
        ]
        assert entries
        assert all(o.side is Side.BUY and o.tag == "entry_long" for o in entries)

    def test_does_not_pyramid_by_default(self):
        store = synthetic.make_store(SINE)
        strat = crossover_strategy()
        position = 0
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                position += order.signed_quantity
                assert abs(position) <= 1

    def test_pyramiding_can_be_enabled(self):
        store = synthetic.make_store(SINE)
        strat = crossover_strategy(allow_pyramiding=True)
        position = 0
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                position += order.signed_quantity
        assert position >= 1

    def test_exit_is_reduce_only(self):
        store = synthetic.make_store(SINE)
        strat = crossover_strategy()
        exits: list[Order] = []
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                if order.tag == "exit_long":
                    exits.append(order)
        assert exits
        assert all(o.reduce_only and o.side is Side.SELL for o in exits)

    def test_no_exit_is_emitted_while_flat(self):
        """Une sortie sans position ouvrirait une position inverse : interdit.

        La regle de sortie se declenche souvent alors que la strategie est
        plate (croisement baissier sans position). Le test verifie qu'aucun
        ordre `reduce_only` n'est emis dans ce cas - pas seulement qu'il serait
        neutralise plus tard par le moteur.
        """
        store = synthetic.make_store(SINE)
        strat = crossover_strategy()
        seen_flat_exit_opportunity = False
        for i in range(strat.warmup_bars, 600):
            position_before = strat._position
            orders = strat.on_bar(at(store, i))
            if position_before == 0:
                assert not [o for o in orders if o.reduce_only]
                if strat.exit_long is not None and strat.exit_long(at(store, i)) == 1.0:
                    seen_flat_exit_opportunity = True
            for order in orders:
                strat.on_fill(fill_for(order))
        assert seen_flat_exit_opportunity, "le scenario teste ne s'est jamais presente"

    def test_reset_clears_the_position(self):
        strat = crossover_strategy()
        strat.on_fill(fill_for(Order(symbol="SYNTH.v.0", side=Side.BUY, quantity=1)))
        assert strat._position == 1
        strat.reset()
        assert strat._position == 0

    def test_fills_of_another_symbol_are_ignored(self):
        strat = crossover_strategy()
        strat.on_fill(fill_for(Order(symbol="AUTRE", side=Side.BUY, quantity=5)))
        assert strat._position == 0

    def test_undefined_signal_triggers_nothing(self):
        """Un signal indefini n'est pas une raison d'agir."""
        flat_store = synthetic.make_store(synthetic.constant(300, 50.0))
        strat = RuleStrategy(
            symbol="SYNTH.v.0",
            quantity=1,
            entry_long=Compare(prim("zscore@1", window=20), CompareOp.GT, const(0.0)),
        )
        for i in range(strat.warmup_bars, 300, 13):
            assert strat.on_bar(at(flat_store, i)) == []

    def test_attached_stop_level_is_computed_from_the_signal(self):
        store = synthetic.make_store(SINE)
        stop = Arith(price("close"), ArithOp.SUB, prim("atr@1", window=14))
        strat = crossover_strategy(stop_loss=stop)
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                if order.tag == "entry_long":
                    assert order.stop_loss is not None
                    assert order.stop_loss < at(store, i).bar.close
                    return
        pytest.fail("aucune entree produite")

    def test_short_side_works_symmetrically(self):
        store = synthetic.make_store(SINE)
        fast, slow = prim("sma@1", window=5), prim("sma@1", window=20)
        strat = RuleStrategy(
            symbol="SYNTH.v.0",
            quantity=1,
            entry_short=CrossesBelow(fast, slow),
            exit_short=CrossesAbove(fast, slow),
        )
        position = 0
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                position += order.signed_quantity
                assert -1 <= position <= 0
        assert position <= 0


class TestRuleStrategySpec:
    def test_describe_then_rebuild_is_equivalent(self):
        original = crossover_strategy()
        rebuilt = RuleStrategy.from_spec(original.describe())
        assert rebuilt.describe() == original.describe()
        assert rebuilt.warmup_bars == original.warmup_bars

    def test_rebuilt_strategy_produces_the_same_orders(self):
        store = synthetic.make_store(SINE)
        original = crossover_strategy()
        rebuilt = RuleStrategy.from_spec(original.describe())
        for i in range(original.warmup_bars, 400):
            ctx = at(store, i)
            a, b = original.on_bar(ctx), rebuilt.on_bar(ctx)
            assert a == b
            for order in a:
                original.on_fill(fill_for(order))
            for order in b:
                rebuilt.on_fill(fill_for(order))

    def test_spec_is_json_serialisable(self):
        import json

        spec = crossover_strategy().describe()
        assert json.loads(json.dumps(spec)) == spec

    def test_missing_symbol_refused(self):
        with pytest.raises(ConfigurationError, match="symbol"):
            RuleStrategy.from_spec({"quantity": 1, "rules": {}})

    def test_missing_quantity_refused(self):
        with pytest.raises(ConfigurationError, match="quantity"):
            RuleStrategy.from_spec({"symbol": "X", "rules": {}})


class TestStrategyRegistry:
    def test_register_build_and_describe(self):
        class Params(StrategyParams):
            window: int = 10

        @strategy("test_probe_strategy", version=1, params=Params, summary="sonde")
        def _factory(params: StrategyParams) -> Strategy:
            assert isinstance(params, Params)
            return FlatStrategy()

        entry = get_strategy("test_probe_strategy")
        assert entry.version == 1
        assert entry.summary == "sonde"
        assert isinstance(entry.build({"window": 5}), FlatStrategy)
        assert any(e["ref"] == "test_probe_strategy@1" for e in describe_strategies())

    def test_build_from_spec(self):
        @strategy("test_spec_strategy", version=1)
        def _factory(params: StrategyParams) -> Strategy:
            return FlatStrategy()

        assert isinstance(build_strategy({"ref": "test_spec_strategy@1"}), FlatStrategy)
        assert isinstance(build_strategy({"ref": "test_spec_strategy"}), FlatStrategy)

    def test_unknown_strategy_raises(self):
        with pytest.raises(RegistryError, match="inconnue"):
            get_strategy("nope")

    def test_spec_without_ref_refused(self):
        with pytest.raises(ConfigurationError, match="'ref'"):
            build_strategy({"params": {}})

    def test_unknown_parameter_refused(self):
        class Params(StrategyParams):
            window: int = 10

        @strategy("test_strict_params", version=1, params=Params)
        def _factory(params: StrategyParams) -> Strategy:
            return FlatStrategy()

        with pytest.raises(Exception, match=r"extra|windwo"):
            build_strategy({"ref": "test_strict_params@1", "params": {"windwo": 3}})

    def test_listing_is_sorted(self):
        names = [(e.name, e.version) for e in list_strategies()]
        assert names == sorted(names)

    def test_no_params_model_accepts_empty(self):
        assert NoStrategyParams().model_dump() == {}
