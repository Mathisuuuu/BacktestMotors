"""Etat de position expose au `Context` : ce qu'il debloque, et ses limites.

La question qui a motive cette brique : « sortir apres N barres » et « stop
suiveur » n'etaient pas exprimables, parce qu'un signal est une fonction pure
du `Context` et ne sait rien de ce que la strategie a fait.

La reponse choisie : le RUNNER calcule l'etat et le depose dans le `Context`.
Un noeud a memoire aurait survecu d'un run a l'autre et casse le determinisme ;
le runner, lui, repart de zero par construction.
"""

from __future__ import annotations

import json

import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import FLAT, POSITION_FIELDS, BarStore, InstrumentSpec, PositionState
from rsl.engine.execution import ExecutionConfig, ZeroFee, ZeroSlippage
from rsl.engine.runner import RunConfig, SingleAssetRunner
from rsl.errors import ConfigurationError
from rsl.strategies.handwritten import BuyAndHold
from rsl.strategies.rules import FlatStrategy, RuleStrategy
from rsl.strategies.signals import (
    Arith,
    ArithOp,
    Compare,
    CompareOp,
    CrossesAbove,
    build_signal,
    const,
    position,
    price,
    prim,
)

SYMBOL = "TEST.v.0"
CASH = 500_000.0
SINE = synthetic.sine(600, 100.0, 10.0, 64)


def store_of(closes=SINE) -> BarStore:
    return synthetic.make_store(closes, symbol=SYMBOL)


def config() -> RunConfig:
    return RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()))


class TestPositionStateValue:
    def test_flat_is_the_default(self):
        assert FLAT.is_flat
        assert FLAT.quantity == 0
        assert FLAT.direction == 0

    def test_direction_follows_the_sign(self):
        assert PositionState(quantity=3).direction == 1
        assert PositionState(quantity=-3).direction == -1
        assert PositionState(quantity=0).direction == 0

    @pytest.mark.parametrize("name", POSITION_FIELDS)
    def test_every_published_field_is_readable(self, name):
        state = PositionState(
            quantity=2, bars_held=7, entry_price=99.0,
            high_since_entry=105.0, low_since_entry=97.0,
        )
        assert isinstance(state.field(name), float)

    def test_an_unknown_field_is_refused(self):
        with pytest.raises(ValueError, match="champ de position inconnu"):
            FLAT.field("prix_de_reve")

    def test_it_is_frozen(self):
        with pytest.raises(Exception, match=r"cannot assign|frozen"):
            FLAT.quantity = 5  # type: ignore[misc]


class TestContextExposure:
    def test_a_context_outside_a_runner_is_flat(self):
        """Il ne peut pas inventer une position que personne n'a prise."""
        ctx = BarContext(store_of())
        ctx._advance()
        assert ctx.position.is_flat

    def test_the_shifted_view_keeps_the_position(self):
        """Une expression evaluee 'telle qu'elle etait' voit la position telle
        qu'elle EST : la decaler remettrait la position a plat par accident."""
        ctx = BarContext(store_of())
        for _ in range(10):
            ctx._advance()
        ctx._set_position(PositionState(quantity=1, bars_held=4))
        assert ctx.shifted(3).position.quantity == 1


class TestTheRunnerFillsIt:
    def test_it_is_flat_before_any_entry(self, spec: InstrumentSpec):
        seen: list[PositionState] = []

        class Watcher(FlatStrategy):
            def on_bar(self, ctx):  # type: ignore[override]
                seen.append(ctx.position)
                return ()

        SingleAssetRunner(store_of(), spec, config()).run(Watcher())
        assert all(state.is_flat for state in seen)

    def test_bars_held_starts_at_zero_and_grows(self, spec: InstrumentSpec):
        seen: list[tuple[int, int]] = []

        class Watcher(BuyAndHold):
            def on_bar(self, ctx):  # type: ignore[override]
                seen.append((ctx.position.quantity, ctx.position.bars_held))
                return super().on_bar(ctx)

        SingleAssetRunner(store_of(), spec, config()).run(Watcher(SYMBOL, 1))
        held = [bars for quantity, bars in seen if quantity != 0]
        assert held[0] == 0, "la barre d'entree compte zero"
        assert held[:5] == [0, 1, 2, 3, 4]

    def test_the_entry_price_matches_the_fill(self, spec: InstrumentSpec):
        seen: list[float] = []

        class Watcher(BuyAndHold):
            def on_bar(self, ctx):  # type: ignore[override]
                if not ctx.position.is_flat:
                    seen.append(ctx.position.entry_price)
                return super().on_bar(ctx)

        store = store_of()
        result = SingleAssetRunner(store, spec, config()).run(Watcher(SYMBOL, 1))
        assert seen[0] == pytest.approx(result.fills[0].price)

    def test_the_extremes_since_entry_accumulate(self, spec: InstrumentSpec):
        seen: list[tuple[float, float]] = []

        class Watcher(BuyAndHold):
            def on_bar(self, ctx):  # type: ignore[override]
                if not ctx.position.is_flat:
                    seen.append(
                        (ctx.position.high_since_entry, ctx.position.low_since_entry)
                    )
                return super().on_bar(ctx)

        SingleAssetRunner(store_of(), spec, config()).run(Watcher(SYMBOL, 1))
        highs = [h for h, _ in seen]
        lows = [low for _, low in seen]
        assert highs == sorted(highs), "le plus haut depuis l'entree ne redescend jamais"
        assert lows == sorted(lows, reverse=True), "le plus bas ne remonte jamais"

    def test_it_resets_when_the_position_closes(self, spec: InstrumentSpec):
        strategy = RuleStrategy(
            symbol=SYMBOL,
            quantity=1,
            entry_long=CrossesAbove(prim("sma@1", window=5), prim("sma@1", window=20)),
            exit_long=Compare(position("bars_held"), CompareOp.GE, const(10.0)),
        )
        seen: list[int] = []
        original = strategy.on_bar

        def watch(ctx):
            seen.append(ctx.position.bars_held)
            return original(ctx)

        strategy.on_bar = watch  # type: ignore[method-assign]
        SingleAssetRunner(store_of(), spec, config()).run(strategy)
        assert 0 in seen
        assert max(seen) <= 11, "la duree en position ne peut pas depasser la regle"


class TestWhatItUnlocks:
    """Les deux regles qui etaient hors vocabulaire avant cette brique."""

    def test_exit_after_n_bars(self, spec: InstrumentSpec):
        strategy = RuleStrategy(
            symbol=SYMBOL,
            quantity=1,
            entry_long=CrossesAbove(prim("sma@1", window=5), prim("sma@1", window=20)),
            exit_long=Compare(position("bars_held"), CompareOp.GE, const(8.0)),
        )
        result = SingleAssetRunner(store_of(), spec, config()).run(strategy)
        assert len(result.portfolio.closed_trades) > 3
        for trade in result.portfolio.closed_trades:
            assert trade.closed_bar - trade.opened_bar <= 9

    def test_a_trailing_exit_on_the_high_since_entry(self, spec: InstrumentSpec):
        """Stop suiveur evalue A LA CLOTURE - pas en cours de barre."""
        trailing = Arith(
            position("high_since_entry"),
            ArithOp.SUB,
            Arith(const(2.0), ArithOp.MUL, prim("atr@1", window=14)),
        )
        strategy = RuleStrategy(
            symbol=SYMBOL,
            quantity=1,
            entry_long=CrossesAbove(prim("sma@1", window=5), prim("sma@1", window=20)),
            exit_long=Compare(price("close"), CompareOp.LT, trailing),
        )
        result = SingleAssetRunner(store_of(), spec, config()).run(strategy)
        assert len(result.portfolio.closed_trades) > 0

    def test_both_rules_are_expressible_in_json(self, spec: InstrumentSpec):
        rules: dict[str, object] = {
            "entry_long": {
                "type": "crosses_above",
                "fast": {"type": "primitive", "ref": "sma@1", "params": {"window": 5}},
                "slow": {"type": "primitive", "ref": "sma@1", "params": {"window": 20}},
            },
            "exit_long": {
                "type": "any_of",
                "operands": [
                    {
                        "type": "compare",
                        "op": ">=",
                        "left": {"type": "position", "field": "bars_held"},
                        "right": {"type": "constant", "value": 20.0},
                    },
                    {
                        "type": "compare",
                        "op": "<",
                        "left": {"type": "price", "field": "close"},
                        "right": {
                            "type": "arith",
                            "op": "-",
                            "left": {"type": "position", "field": "high_since_entry"},
                            "right": {
                                "type": "arith",
                                "op": "*",
                                "left": {"type": "constant", "value": 2.0},
                                "right": {
                                    "type": "primitive",
                                    "ref": "atr@1",
                                    "params": {"window": 14},
                                },
                            },
                        },
                    },
                ],
            },
        }
        strategy = RuleStrategy.from_spec(
            {"symbol": SYMBOL, "quantity": 1, "rules": rules}
        )
        result = SingleAssetRunner(store_of(), spec, config()).run(strategy)
        assert len(result.portfolio.closed_trades) > 0


class TestTheNode:
    def test_it_reads_no_history(self):
        assert position("bars_held").warmup_bars == 0

    def test_an_unknown_field_is_refused_at_construction(self):
        with pytest.raises(ConfigurationError, match="champ inconnu"):
            position("prix_de_reve")

    def test_it_round_trips_through_its_specification(self):
        node = position("high_since_entry")
        assert build_signal(node.describe()).describe() == node.describe()

    def test_the_specification_is_serialisable(self):
        described = position("entry_price").describe()
        assert json.loads(json.dumps(described)) == described

    def test_it_returns_zero_outside_a_runner(self):
        ctx = BarContext(store_of())
        ctx._advance()
        assert position("bars_held")(ctx) == 0.0


class TestDeterminismIsPreserved:
    """La raison pour laquelle c'est le runner qui calcule, pas un noeud."""

    def _strategy(self) -> RuleStrategy:
        return RuleStrategy(
            symbol=SYMBOL,
            quantity=1,
            entry_long=CrossesAbove(prim("sma@1", window=5), prim("sma@1", window=20)),
            exit_long=Compare(position("bars_held"), CompareOp.GE, const(8.0)),
        )

    def test_two_runs_are_identical(self, spec: InstrumentSpec):
        store = store_of()
        first = SingleAssetRunner(store, spec, config()).run(self._strategy())
        second = SingleAssetRunner(store, spec, config()).run(self._strategy())
        assert [e.hex() for e in first.equity.equity] == [
            e.hex() for e in second.equity.equity
        ]

    def test_a_reused_runner_does_not_inherit_the_previous_position(
        self, spec: InstrumentSpec
    ):
        """Le suivi est local au run : sans cela, le second partirait en position."""
        runner = SingleAssetRunner(store_of(), spec, config())
        strategy = self._strategy()
        first = runner.run(strategy)
        second = runner.run(strategy)
        assert first.final_equity == second.final_equity

    @pytest.mark.parametrize("cut", [100, 300])
    def test_corrupting_the_future_changes_nothing(self, spec: InstrumentSpec, cut: int):
        """L'etat de position derive de barres closes : le test n° 1 tient."""
        clean = store_of()
        dirty = synthetic.corrupt_future(clean, after_index=cut)
        stopped = RunConfig(
            CASH,
            ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()),
            stop=cut + 1,
        )
        reference = SingleAssetRunner(clean, spec, stopped).run(self._strategy())
        observed = SingleAssetRunner(dirty, spec, stopped).run(self._strategy())
        assert [e.hex() for e in observed.equity.equity] == [
            e.hex() for e in reference.equity.equity
        ]
