"""Primitives : exactitude contre des valeurs calculees a la main, et registre.

Les series synthetiques sont choisies pour avoir une reponse fermee : une
constante, une rampe arithmetique. Comparer une primitive a une
reimplementation numpy ne prouverait rien - les deux pourraient etre fausses de
la meme facon.
"""

from __future__ import annotations

import math

import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, Field
from rsl.errors import ConfigurationError, RegistryError
from rsl.primitives import list_primitives
from rsl.primitives.base import PrimitiveRef
from rsl.primitives.registry import (
    _REGISTRY,
    bind_primitive,
    deprecate,
    deprecation_reason,
    describe_registry,
    get_primitive,
    latest_versions,
    primitive,
    resolve_pinned,
)

WICK = 0.001


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


class TestSma:
    def test_constant_series(self):
        ctx = at(synthetic.make_store(synthetic.constant(100, 42.0)), 50)
        assert bind_primitive("sma@1", window=10)(ctx) == pytest.approx(42.0)

    def test_arithmetic_ramp_closed_form(self):
        """Sur une rampe de pas `d`, SMA(w) au point i vaut close[i] - d*(w-1)/2."""
        store = synthetic.make_store(synthetic.ramp(200, 100.0, 1.0))
        ctx = at(store, 120)
        expected = (100.0 + 120) - 1.0 * (20 - 1) / 2
        assert bind_primitive("sma@1", window=20)(ctx) == pytest.approx(expected)

    def test_window_of_one_is_the_bar_itself(self):
        store = synthetic.make_store(synthetic.random_walk(100, seed=7))
        ctx = at(store, 60)
        assert bind_primitive("sma", window=1)(ctx) == pytest.approx(ctx.value(Field.CLOSE))

    def test_can_target_another_field(self):
        store = synthetic.make_store(synthetic.constant(50, 10.0))
        ctx = at(store, 30)
        assert bind_primitive("sma@1", window=5, field="high")(ctx) == pytest.approx(
            10.0 * (1 + WICK)
        )

    def test_warmup_is_the_window(self):
        assert bind_primitive("sma@1", window=33).warmup_bars == 33


class TestEma:
    def test_constant_series_is_the_constant(self):
        ctx = at(synthetic.make_store(synthetic.constant(200, 7.5)), 150)
        assert bind_primitive("ema@1", window=20)(ctx) == pytest.approx(7.5)

    def test_matches_hand_rolled_recursion(self):
        store = synthetic.make_store(synthetic.random_walk(300, seed=11))
        ctx = at(store, 250)
        window, mult = 10, 5
        values = ctx.values(Field.CLOSE, window * mult)
        alpha = 2.0 / (window + 1.0)
        expected = sum(values[:window]) / window
        for value in values[window:]:
            expected = alpha * float(value) + (1 - alpha) * expected
        assert bind_primitive("ema@1", window=window)(ctx) == pytest.approx(expected)

    def test_warmup_is_window_times_seed_multiplier(self):
        assert bind_primitive("ema@1", window=10).warmup_bars == 50
        assert bind_primitive("ema@1", window=10, seed_multiplier=8).warmup_bars == 80

    def test_seed_multiplier_below_two_refused(self):
        with pytest.raises(ValueError, match="seed_multiplier"):
            bind_primitive("ema@1", window=10, seed_multiplier=1)


class TestAtr:
    def test_constant_series_true_range_is_the_wick(self):
        """open = close = 100 ; high = 100.1 ; low = 99.9 -> TR = 0.2 a chaque barre."""
        ctx = at(synthetic.make_store(synthetic.constant(100, 100.0)), 60)
        assert bind_primitive("atr@1", window=14)(ctx) == pytest.approx(0.2)

    def test_warmup_needs_one_extra_bar_for_the_previous_close(self):
        assert bind_primitive("atr@1", window=14).warmup_bars == 15

    def test_atr_is_positive_on_a_random_walk(self):
        ctx = at(synthetic.make_store(synthetic.random_walk(200, seed=3)), 150)
        value = bind_primitive("atr@1", window=14)(ctx)
        assert value is not None and value > 0.0


class TestRollingExtremes:
    def test_high_defaults_to_the_high_field(self):
        store = synthetic.make_store(synthetic.ramp(100, 100.0, 1.0))
        ctx = at(store, 50)
        assert bind_primitive("rolling_high@1", window=10)(ctx) == pytest.approx(
            150.0 * (1 + WICK)
        )

    def test_low_defaults_to_the_low_field(self):
        store = synthetic.make_store(synthetic.ramp(100, 100.0, 1.0))
        ctx = at(store, 50)
        # low[i] = min(open[i], close[i]) * (1 - wick) = close[i-1] * (1 - wick)
        assert bind_primitive("rolling_low@1", window=10)(ctx) == pytest.approx(
            140.0 * (1 - WICK)
        )

    def test_extremes_on_a_sine_bracket_the_amplitude(self):
        store = synthetic.make_store(synthetic.sine(400, 100.0, 10.0, 64))
        ctx = at(store, 300)
        high = bind_primitive("rolling_high@1", window=64)(ctx)
        low = bind_primitive("rolling_low@1", window=64)(ctx)
        assert high is not None and low is not None
        assert high == pytest.approx(110.0 * (1 + WICK), rel=1e-2)
        assert low == pytest.approx(90.0 * (1 - WICK), rel=1e-2)


class TestReturns:
    def test_simple_return_on_a_ramp(self):
        store = synthetic.make_store(synthetic.ramp(100, 100.0, 1.0))
        ctx = at(store, 50)
        assert bind_primitive("returns@1", window=10)(ctx) == pytest.approx(150.0 / 140.0 - 1.0)

    def test_log_return(self):
        store = synthetic.make_store(synthetic.ramp(100, 100.0, 1.0))
        ctx = at(store, 50)
        assert bind_primitive("returns@1", window=10, log=True)(ctx) == pytest.approx(
            math.log(150.0 / 140.0)
        )

    def test_constant_series_returns_zero(self):
        ctx = at(synthetic.make_store(synthetic.constant(50, 3.0)), 30)
        assert bind_primitive("returns@1")(ctx) == pytest.approx(0.0)

    def test_default_window_is_one_bar(self):
        assert bind_primitive("returns@1").warmup_bars == 2


class TestZScore:
    def test_hand_computed_case(self):
        """Clotures 1, 2, 3 sur une fenetre de 3 : moyenne 2, ecart-type 1, z = 1."""
        store = synthetic.make_store(synthetic.ramp(20, 1.0, 1.0))
        ctx = at(store, 2)
        assert bind_primitive("zscore@1", window=3)(ctx) == pytest.approx(1.0)

    def test_constant_series_has_no_zscore(self):
        ctx = at(synthetic.make_store(synthetic.constant(50, 5.0)), 30)
        assert bind_primitive("zscore@1", window=10)(ctx) is None

    def test_ddof_zero_is_allowed(self):
        store = synthetic.make_store(synthetic.ramp(20, 1.0, 1.0))
        ctx = at(store, 2)
        expected = (3.0 - 2.0) / math.sqrt(2.0 / 3.0)
        assert bind_primitive("zscore@1", window=3, ddof=0)(ctx) == pytest.approx(expected)

    def test_window_must_exceed_ddof(self):
        with pytest.raises(ValueError, match="ddof"):
            bind_primitive("zscore@1", window=1, ddof=1)

    def test_there_is_no_full_sample_mode(self):
        params = get_primitive("zscore@1").params_model.model_fields
        assert "window" in params
        assert not any("full" in name or "expanding" in name for name in params)


class TestParamValidation:
    def test_unknown_parameter_is_refused(self):
        with pytest.raises(Exception, match=r"windwo|extra"):
            bind_primitive("sma@1", windwo=20)

    def test_missing_required_parameter_is_refused(self):
        with pytest.raises(Exception, match="window"):
            bind_primitive("sma@1")

    @pytest.mark.parametrize("window", [0, -5])
    def test_non_positive_window_refused(self, window):
        with pytest.raises(ValueError, match="window"):
            bind_primitive("sma@1", window=window)

    def test_params_are_frozen(self):
        bound = bind_primitive("sma@1", window=10)
        with pytest.raises(Exception, match=r"frozen|immutable"):
            bound.params.window = 20  # type: ignore[misc]


class TestDeterminism:
    @pytest.mark.parametrize(
        ("ref", "params"),
        [
            ("sma@1", {"window": 20}),
            ("ema@1", {"window": 20}),
            ("atr@1", {"window": 14}),
            ("zscore@1", {"window": 30}),
            ("returns@1", {"window": 5}),
        ],
    )
    def test_same_context_gives_bit_identical_results(self, ref, params):
        store = synthetic.make_store(synthetic.random_walk(500, seed=99))
        ctx = at(store, 400)
        bound = bind_primitive(ref, **params)
        first, second = bound(ctx), bound(ctx)
        assert first is not None
        assert first.hex() == float(second).hex()  # type: ignore[arg-type]


class TestRegistry:
    def test_all_seven_builtins_are_registered(self):
        names = {p.name for p in list_primitives()}
        assert names >= {"sma", "ema", "atr", "rolling_high", "rolling_low", "returns", "zscore"}

    def test_listing_is_sorted_and_stable(self):
        first = [str(p.ref) for p in list_primitives()]
        assert first == sorted(first)
        assert first == [str(p.ref) for p in list_primitives()]

    def test_unknown_primitive_raises(self):
        with pytest.raises(RegistryError, match="inconnue"):
            get_primitive("does_not_exist")

    def test_unknown_version_raises(self):
        with pytest.raises(RegistryError, match="Versions disponibles"):
            get_primitive("sma@99")

    def test_unversioned_ref_resolves_to_latest(self):
        assert get_primitive("sma") is get_primitive(PrimitiveRef("sma", 1))

    def test_resolve_pinned_returns_a_pinned_ref(self):
        pinned = resolve_pinned("sma")
        assert pinned.is_pinned
        assert str(pinned) == "sma@1"

    def test_malformed_version_refused(self):
        with pytest.raises(ConfigurationError, match="version invalide"):
            PrimitiveRef.parse("sma@latest")

    def test_latest_versions_map(self):
        assert latest_versions()["sma"] == 1

    def test_catalogue_exposes_json_schema(self):
        entry = next(e for e in describe_registry() if e["ref"] == "sma@1")
        schema = entry["params"]
        assert isinstance(schema, dict)
        assert "window" in schema["properties"]  # type: ignore[index]

    def test_deprecation_keeps_the_version_resolvable(self):
        name = "test_deprecation_probe"

        @primitive(name, version=1, summary="sonde")
        def _probe(ctx, params):
            return 1.0

        try:
            deprecate(name, 1, reason="remplacee par la sonde v2")
            assert get_primitive(f"{name}@1") is not None
            assert deprecation_reason(name, 1) == "remplacee par la sonde v2"
            entry = next(e for e in describe_registry() if e["ref"] == f"{name}@1")
            assert entry["deprecated"] == "remplacee par la sonde v2"
        finally:
            _REGISTRY.pop((name, 1), None)

    def test_deprecating_an_unknown_version_raises(self):
        with pytest.raises(RegistryError, match="rien a deprecier"):
            deprecate("sma", 42, reason="n/a")
