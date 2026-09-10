"""Signaux composables : semantique, propagation de `None`, aller-retour declaratif."""

from __future__ import annotations

import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore
from rsl.errors import ConfigurationError, RegistryError
from rsl.strategies.signals import (
    FALSE,
    TRUE,
    AllOf,
    AnyOf,
    Arith,
    ArithOp,
    Compare,
    CompareOp,
    Constant,
    CrossesAbove,
    CrossesBelow,
    Lag,
    Not,
    Price,
    PrimitiveSignal,
    all_of,
    any_of,
    build_signal,
    const,
    describe_node_types,
    get_node_type,
    list_node_types,
    price,
    prim,
    signal_node,
    warmup_of,
)


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


@pytest.fixture
def ctx() -> BarContext:
    return at(synthetic.make_store(synthetic.ramp(300, 100.0, 1.0)), 200)


class TestLeaves:
    def test_constant(self, ctx):
        assert Constant(3.5)(ctx) == 3.5
        assert Constant(3.5).warmup_bars == 0

    def test_price_reads_the_current_bar(self, ctx):
        assert price("close")(ctx) == pytest.approx(300.0)

    def test_price_with_lag_reads_the_past(self, ctx):
        assert price("close", lag=10)(ctx) == pytest.approx(290.0)
        assert price("close", lag=10).warmup_bars == 11

    def test_price_refuses_negative_lag(self):
        with pytest.raises(ConfigurationError, match="lag"):
            Price("close", -1)

    def test_primitive_leaf(self, ctx):
        assert prim("sma@1", window=10)(ctx) == pytest.approx(300.0 - 4.5)

    def test_primitive_leaf_reports_warmup(self):
        assert prim("sma@1", window=10).warmup_bars == 10


class TestCompare:
    @pytest.mark.parametrize(
        ("op", "expected"),
        [
            (CompareOp.GT, TRUE), (CompareOp.GE, TRUE), (CompareOp.LT, FALSE),
            (CompareOp.LE, FALSE), (CompareOp.EQ, FALSE), (CompareOp.NE, TRUE),
        ],
    )
    def test_operators(self, ctx, op, expected):
        assert Compare(const(2.0), op, const(1.0))(ctx) == expected

    def test_equality_is_exact(self, ctx):
        assert Compare(const(1.0), CompareOp.EQ, const(1.0))(ctx) == TRUE

    def test_undefined_operand_makes_the_result_undefined(self, ctx):
        """Un z-score indefini ne doit pas se transformer en 'condition fausse'."""
        flat = at(synthetic.make_store(synthetic.constant(100, 5.0)), 60)
        undefined = prim("zscore@1", window=10)
        assert undefined(flat) is None
        assert Compare(undefined, CompareOp.GT, const(0.0))(flat) is None

    def test_warmup_is_the_max_of_both_sides(self):
        node = Compare(prim("sma@1", window=50), CompareOp.GT, prim("sma@1", window=10))
        assert node.warmup_bars == 50


class TestArith:
    @pytest.mark.parametrize(
        ("op", "expected"),
        [(ArithOp.ADD, 7.0), (ArithOp.SUB, 1.0), (ArithOp.MUL, 12.0), (ArithOp.DIV, 4.0 / 3.0)],
    )
    def test_operators(self, ctx, op, expected):
        assert Arith(const(4.0), op, const(3.0))(ctx) == pytest.approx(expected)

    def test_division_by_zero_is_undefined_not_infinite(self, ctx):
        assert Arith(const(1.0), ArithOp.DIV, const(0.0))(ctx) is None

    def test_stop_level_expressed_as_price_minus_two_atr(self, ctx):
        two_atr = Arith(const(2.0), ArithOp.MUL, prim("atr@1", window=14))
        node = Arith(price("close"), ArithOp.SUB, two_atr)
        value = node(ctx)
        assert value is not None and value < 300.0


class TestBoolean:
    def test_all_of(self, ctx):
        assert all_of(const(TRUE), const(TRUE))(ctx) == TRUE
        assert all_of(const(TRUE), const(FALSE))(ctx) == FALSE

    def test_any_of(self, ctx):
        assert any_of(const(FALSE), const(TRUE))(ctx) == TRUE
        assert any_of(const(FALSE), const(FALSE))(ctx) == FALSE

    def test_not(self, ctx):
        assert Not(const(TRUE))(ctx) == FALSE
        assert Not(const(FALSE))(ctx) == TRUE
        assert Not(prim("zscore@1", window=10))(
            at(synthetic.make_store(synthetic.constant(100, 5.0)), 60)
        ) is None

    def test_undefined_is_not_absorbed_by_false(self, ctx):
        """`all_of(faux, indefini)` est indefini, pas faux.

        Absorber le `None` ferait disparaitre l'information "je ne sais pas".
        """
        flat = at(synthetic.make_store(synthetic.constant(100, 5.0)), 60)
        undefined = prim("zscore@1", window=10)
        assert AllOf((const(FALSE), undefined))(flat) is None
        assert AnyOf((const(TRUE), undefined))(flat) is None

    def test_empty_operands_refused(self):
        with pytest.raises(ConfigurationError, match="au moins un operande"):
            AllOf(())
        with pytest.raises(ConfigurationError, match="au moins un operande"):
            AnyOf(())


class TestLag:
    def test_lag_shifts_the_evaluation_into_the_past(self, ctx):
        assert Lag(price("close"), 10)(ctx) == pytest.approx(290.0)

    def test_lag_adds_to_warmup(self):
        assert Lag(prim("sma@1", window=20), 5).warmup_bars == 25

    def test_lag_below_one_refused(self):
        with pytest.raises(ConfigurationError, match=">= 1"):
            Lag(price("close"), 0)


class TestCrosses:
    def _crossing_context(self, index: int) -> BarContext:
        """Sinusoide : les croisements de moyennes y sont frequents et connus."""
        return at(synthetic.make_store(synthetic.sine(600, 100.0, 10.0, 64)), index)

    def test_crossing_is_detected_exactly_once_per_crossing(self):
        fast, slow = prim("sma@1", window=5), prim("sma@1", window=20)
        node = CrossesAbove(fast, slow)
        store = synthetic.make_store(synthetic.sine(600, 100.0, 10.0, 64))

        hits = 0
        state_changes = 0
        previous_above: bool | None = None
        for i in range(node.warmup_bars, 600):
            ctx = at(store, i)
            if node(ctx) == TRUE:
                hits += 1
            fast_value, slow_value = fast(ctx), slow(ctx)
            assert fast_value is not None and slow_value is not None
            above = fast_value > slow_value
            if previous_above is not None and above and not previous_above:
                state_changes += 1
            previous_above = above

        assert hits > 0
        assert hits == state_changes

    def test_crosses_below_is_the_mirror(self):
        fast, slow = prim("sma@1", window=5), prim("sma@1", window=20)
        up, down = CrossesAbove(fast, slow), CrossesBelow(fast, slow)
        store = synthetic.make_store(synthetic.sine(600, 100.0, 10.0, 64))
        for i in range(up.warmup_bars, 600, 7):
            ctx = at(store, i)
            assert not (up(ctx) == TRUE and down(ctx) == TRUE)

    def test_no_crossing_on_a_monotonic_ramp(self, ctx):
        node = CrossesBelow(prim("sma@1", window=5), prim("sma@1", window=20))
        assert node(ctx) == FALSE

    def test_warmup_includes_the_previous_bar(self):
        node = CrossesAbove(prim("sma@1", window=5), prim("sma@1", window=20))
        assert node.warmup_bars == 21


class TestDeclarativeRoundTrip:
    def _tree(self):
        return all_of(
            CrossesAbove(prim("sma@1", window=10), prim("sma@1", window=50)),
            Compare(prim("zscore@1", window=100), CompareOp.LT, const(2.0)),
            Not(Compare(price("volume"), CompareOp.EQ, const(0.0))),
        )

    def test_describe_then_build_reproduces_the_tree(self, ctx):
        original = self._tree()
        rebuilt = build_signal(original.describe())
        assert rebuilt.describe() == original.describe()
        assert rebuilt.warmup_bars == original.warmup_bars
        assert rebuilt(ctx) == original(ctx)

    def test_describe_pins_primitive_versions(self):
        spec = prim("sma", window=10).describe()
        assert spec["ref"] == "sma@1"

    def test_spec_is_json_serialisable(self):
        import json

        assert json.loads(json.dumps(self._tree().describe())) == self._tree().describe()

    def test_hand_written_spec_builds(self, ctx):
        spec = {
            "type": "compare",
            "op": ">",
            "left": {"type": "primitive", "ref": "sma@1", "params": {"window": 10}},
            "right": {"type": "price", "field": "close"},
        }
        assert build_signal(spec)(ctx) in (TRUE, FALSE)


class TestBuilderErrors:
    def test_missing_type(self):
        with pytest.raises(ConfigurationError, match="type"):
            build_signal({"op": ">"})

    def test_unknown_type(self):
        with pytest.raises(RegistryError, match="inconnu"):
            build_signal({"type": "nope"})

    def test_unknown_version(self):
        with pytest.raises(RegistryError, match="Versions"):
            build_signal({"type": "constant", "version": 99, "value": 1.0})

    def test_non_numeric_constant(self):
        with pytest.raises(ConfigurationError, match="numerique"):
            build_signal({"type": "constant", "value": "beaucoup"})

    def test_invalid_operator(self):
        with pytest.raises(ConfigurationError, match="operateur invalide"):
            build_signal(
                {
                    "type": "compare",
                    "op": "=>",
                    "left": {"type": "constant", "value": 1.0},
                    "right": {"type": "constant", "value": 2.0},
                }
            )

    def test_child_must_be_a_node_spec(self):
        with pytest.raises(ConfigurationError, match="specification de noeud"):
            build_signal({"type": "not", "inner": 3})

    def test_operands_must_be_a_non_empty_list(self):
        with pytest.raises(ConfigurationError, match="liste non vide"):
            build_signal({"type": "all_of", "operands": []})

    def test_unknown_price_field(self):
        with pytest.raises(ConfigurationError, match="champ inconnu"):
            build_signal({"type": "price", "field": "vwap"})

    def test_primitive_ref_must_be_text(self):
        with pytest.raises(ConfigurationError, match="'ref' textuel"):
            build_signal({"type": "primitive", "ref": 42})


class TestNodeRegistry:
    def test_listing_is_sorted_and_stable(self):
        names = [(n.name, n.version) for n in list_node_types()]
        assert names == sorted(names)
        assert names == [(n.name, n.version) for n in list_node_types()]

    def test_catalogue_shape(self):
        entry = next(e for e in describe_node_types() if e["type"] == "compare")
        assert entry["version"] == 1
        assert isinstance(entry["summary"], str)

    def test_unversioned_lookup_returns_latest(self):
        assert get_node_type("compare").version == 1

    def test_reregistering_a_published_node_is_refused(self):
        with pytest.raises(RegistryError, match="deja enregistre"):

            @signal_node("compare", version=1)
            class _Dup:  # pragma: no cover
                @classmethod
                def from_spec(cls, spec, build) -> object:
                    raise NotImplementedError

    def test_node_without_from_spec_is_refused(self):
        with pytest.raises(RegistryError, match="from_spec"):

            @signal_node("test_no_builder_probe")
            class _NoBuilder:  # pragma: no cover
                pass


class TestWarmupHelper:
    def test_empty_is_zero(self):
        assert warmup_of([]) == 0

    def test_max_wins(self):
        assert warmup_of([prim("sma@1", window=5), prim("sma@1", window=80)]) == 80


class TestPrimitiveSignalHelper:
    def test_of_builds_from_a_ref(self, ctx):
        assert PrimitiveSignal.of("sma@1", window=5)(ctx) == pytest.approx(300.0 - 2.0)
