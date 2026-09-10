"""Fermeture a la modification, ouverture a l'extension.

Le socle promet qu'on n'a jamais a toucher au code publie : une primitive
nouvelle, un type de noeud nouveau, une strategie nouvelle s'AJOUTENT. Ces
tests verifient la promesse par l'attaque - ils tentent de reecrire du publie,
et verifient qu'apres extension, l'ancien se comporte exactement comme avant.

L'enjeu n'est pas esthetique. Un rapport de run archive epingle `sma@1` ; si
`sma@1` change de sens un jour, le run n'est plus rejouable et la verite
terrain du projet est perdue.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext, Context
from rsl.data.schema import BarStore, Field
from rsl.errors import RegistryError
from rsl.primitives.base import PrimitiveParams, WindowParams
from rsl.primitives.registry import (
    _REGISTRY,
    bind_primitive,
    describe_registry,
    get_primitive,
    primitive,
)
from rsl.strategies.base import _STRATEGIES, Strategy, get_strategy, strategy
from rsl.strategies.rules import FlatStrategy
from rsl.strategies.signals import (
    _NODES,
    Builder,
    Compare,
    CompareOp,
    SpecDict,
    build_signal,
    const,
    describe_node_types,
    prim,
    signal_node,
)

pytestmark = pytest.mark.adversarial

WALK = synthetic.random_walk(400, seed=1234)


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


@pytest.fixture
def clean_registries() -> Iterator[None]:
    """Restaure les registres : un test ne doit pas polluer les suivants."""
    primitives = dict(_REGISTRY)
    nodes = dict(_NODES)
    strategies = dict(_STRATEGIES)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(primitives)
        _NODES.clear()
        _NODES.update(nodes)
        _STRATEGIES.clear()
        _STRATEGIES.update(strategies)


class TestPublishedCodeIsSealed:
    def test_reregistering_a_published_primitive_is_refused(self):
        with pytest.raises(RegistryError, match="deja enregistree"):

            @primitive("sma", version=1, params=WindowParams)
            def _hijack(ctx: Context, params: PrimitiveParams) -> float | None:
                return 0.0

    def test_the_error_names_the_incumbent_and_the_way_out(self):
        with pytest.raises(RegistryError) as excinfo:

            @primitive("sma", version=1, params=WindowParams)
            def _hijack(ctx: Context, params: PrimitiveParams) -> float | None:
                return 0.0

        message = str(excinfo.value)
        assert "trend" in message
        assert "sma@2" in message

    def test_reregistering_a_published_node_is_refused(self):
        with pytest.raises(RegistryError, match="deja enregistre"):

            @signal_node("compare", version=1)
            class _Hijack:
                @classmethod
                def from_spec(cls, spec: SpecDict, build: Builder) -> object:
                    raise NotImplementedError

    def test_reregistering_a_published_strategy_is_refused(self, clean_registries):
        @strategy("test_sealed_strategy", version=1)
        def _first(params: object) -> Strategy:
            return FlatStrategy()

        with pytest.raises(RegistryError, match="deja enregistree"):

            @strategy("test_sealed_strategy", version=1)
            def _second(params: object) -> Strategy:
                return FlatStrategy()


class TestNewVersionLeavesOldIntact:
    def test_v1_behaviour_is_unchanged_after_v2_lands(self, clean_registries):
        store = synthetic.make_store(WALK)
        ctx = at(store, 300)
        before = bind_primitive("sma@1", window=20)(ctx)

        @primitive(
            "sma",
            version=2,
            params=WindowParams,
            warmup=lambda p: int(p.window),
            summary="Variante deliberement differente.",
        )
        def _sma_v2(ctx_: Context, params: PrimitiveParams) -> float | None:
            return 0.0

        after = bind_primitive("sma@1", window=20)(ctx)
        assert before is not None
        assert after is not None
        assert before.hex() == after.hex()
        assert bind_primitive("sma@2", window=20)(ctx) == 0.0

    def test_unpinned_reference_follows_the_latest_version(self, clean_registries):
        assert get_primitive("sma").version == 1

        @primitive("sma", version=2, params=WindowParams, warmup=lambda p: 1)
        def _sma_v2(ctx_: Context, params: PrimitiveParams) -> float | None:
            return 0.0

        assert get_primitive("sma").version == 2
        assert get_primitive("sma@1").version == 1

    def test_an_archived_pinned_spec_still_rebuilds_identically(self, clean_registries):
        """Le scenario qui compte : un run d'il y a six mois, rejoue aujourd'hui."""
        store = synthetic.make_store(WALK)
        ctx = at(store, 300)
        archived = Compare(
            prim("sma@1", window=10), CompareOp.GT, prim("sma@1", window=50)
        ).describe()
        expected = build_signal(archived)(ctx)

        @primitive("sma", version=2, params=WindowParams, warmup=lambda p: 1)
        def _sma_v2(ctx_: Context, params: PrimitiveParams) -> float | None:
            return -1.0

        assert build_signal(archived)(ctx) == expected


class TestExtensionRequiresNoEdit:
    def test_a_new_primitive_appears_without_touching_the_others(self, clean_registries):
        before = {entry["ref"] for entry in describe_registry()}

        class Params(WindowParams):
            pass

        @primitive(
            "test_range_ratio",
            version=1,
            params=Params,
            warmup=lambda p: int(p.window),
            summary="Sonde d'extension.",
        )
        def _probe(ctx_: Context, params: PrimitiveParams) -> float | None:
            window = int(params.window)
            highs = ctx_.values(Field.HIGH, window)
            lows = ctx_.values(Field.LOW, window)
            return float(highs.max() - lows.min())

        after = {entry["ref"] for entry in describe_registry()}
        assert after - before == {"test_range_ratio@1"}

        ctx = at(synthetic.make_store(WALK), 300)
        value = bind_primitive("test_range_ratio@1", window=20)(ctx)
        assert value is not None and value > 0.0

    def test_a_new_node_type_plugs_into_the_builder_untouched(self, clean_registries):
        """`build_signal` ne connait aucun type de noeud : il delegue au registre."""

        @signal_node("test_clamp", version=1, summary="Borne un sous-signal.")
        class Clamp:
            NODE_TYPE: ClassVar[str] = "test_clamp"
            NODE_VERSION: ClassVar[int] = 1

            def __init__(self, inner: object, low: float, high: float) -> None:
                self.inner = inner
                self.low = low
                self.high = high

            @property
            def warmup_bars(self) -> int:
                return int(self.inner.warmup_bars)

            def __call__(self, ctx_: Context) -> float | None:
                value = self.inner(ctx_)  # type: ignore[operator]
                return None if value is None else max(self.low, min(self.high, value))

            def describe(self) -> SpecDict:
                return {
                    "type": self.NODE_TYPE,
                    "version": self.NODE_VERSION,
                    "low": self.low,
                    "high": self.high,
                    "inner": self.inner.describe(),  # type: ignore[union-attr]
                }

            @classmethod
            def from_spec(cls, spec: SpecDict, build: Builder) -> object:
                inner = spec["inner"]
                assert isinstance(inner, dict)
                return cls(build(inner), float(spec["low"]), float(spec["high"]))  # type: ignore[arg-type]

        ctx = at(synthetic.make_store(WALK), 300)
        spec: SpecDict = {
            "type": "test_clamp",
            "low": 0.0,
            "high": 1.0,
            "inner": {"type": "constant", "value": 5.0},
        }
        assert build_signal(spec)(ctx) == 1.0
        assert build_signal(build_signal(spec).describe())(ctx) == 1.0
        assert any(e["type"] == "test_clamp" for e in describe_node_types())

    def test_a_new_strategy_family_registers_without_touching_the_others(
        self, clean_registries
    ):
        before = {(e.name, e.version) for e in _STRATEGIES.values()}

        @strategy("test_new_family", version=1, summary="Sonde.")
        def _factory(params: object) -> Strategy:
            return FlatStrategy()

        assert get_strategy("test_new_family").summary == "Sonde."
        assert {(e.name, e.version) for e in _STRATEGIES.values()} - before == {
            ("test_new_family", 1)
        }


class TestSignalsAreImmuneToFutureCorruption:
    """Test n° 1 applique aux signaux composes, avant meme le moteur."""

    SPECS: ClassVar[tuple[SpecDict, ...]] = (
        {"type": "primitive", "ref": "sma@1", "params": {"window": 20}},
        {"type": "primitive", "ref": "zscore@1", "params": {"window": 50}},
        {"type": "primitive", "ref": "atr@1", "params": {"window": 14}},
        {
            "type": "crosses_above",
            "fast": {"type": "primitive", "ref": "sma@1", "params": {"window": 5}},
            "slow": {"type": "primitive", "ref": "sma@1", "params": {"window": 20}},
        },
        {
            "type": "all_of",
            "operands": [
                {
                    "type": "compare",
                    "op": ">",
                    "left": {"type": "price", "field": "close"},
                    "right": {"type": "primitive", "ref": "sma@1", "params": {"window": 50}},
                },
                {"type": "lag", "bars": 3, "inner": {"type": "price", "field": "close"}},
            ],
        },
    )

    @pytest.mark.parametrize("spec", SPECS, ids=lambda s: str(s["type"]))
    @pytest.mark.parametrize("cut", [80, 200, 398])
    def test_values_before_the_cut_are_unchanged(self, spec: SpecDict, cut: int):
        clean = synthetic.make_store(WALK, symbol="W.v.0")
        dirty = synthetic.corrupt_future(clean, after_index=cut)
        node = build_signal(spec)

        for i in range(node.warmup_bars, cut + 1):
            expected = node(at(clean, i))
            observed = node(at(dirty, i))
            assert observed == expected, f"fuite du futur a l'index {i}"

    def test_the_corruption_does_change_values_after_the_cut(self):
        """Garde-fou : sans lui, un corrupteur inerte validerait tout."""
        clean = synthetic.make_store(WALK, symbol="W.v.0")
        dirty = synthetic.corrupt_future(clean, after_index=200)
        node = build_signal(self.SPECS[0])
        assert node(at(clean, 250)) != node(at(dirty, 250))


class TestNoHiddenStateBetweenRuns:
    def test_a_signal_gives_the_same_value_whatever_the_call_order(self):
        """Les noeuds sont sans etat : evaluer 250 avant 100 ne change rien."""
        store = synthetic.make_store(WALK)
        node = build_signal(
            {
                "type": "crosses_above",
                "fast": {"type": "primitive", "ref": "sma@1", "params": {"window": 5}},
                "slow": {"type": "primitive", "ref": "sma@1", "params": {"window": 20}},
            }
        )
        forward = [node(at(store, i)) for i in range(50, 120)]
        backward = [node(at(store, i)) for i in reversed(range(50, 120))]
        assert forward == list(reversed(backward))

    def test_constant_folding_is_not_cached_across_contexts(self):
        node = Compare(prim("sma@1", window=10), CompareOp.GT, const(0.0))
        store_a = synthetic.make_store(synthetic.constant(200, 10.0), symbol="A")
        store_b = synthetic.make_store(synthetic.constant(200, 5.0), symbol="B")
        assert node(at(store_a, 100)) == node(at(store_b, 100)) == 1.0
        assert prim("sma@1", window=10)(at(store_a, 100)) == pytest.approx(10.0)
        assert prim("sma@1", window=10)(at(store_b, 100)) == pytest.approx(5.0)
