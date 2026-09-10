"""Primitives : exactitude contre des valeurs calculees a la main, et registre.

Les series synthetiques sont choisies pour avoir une reponse fermee : une
constante, une rampe arithmetique. Comparer une primitive a une
reimplementation numpy ne prouverait rien - les deux pourraient etre fausses de
la meme facon.
"""

from __future__ import annotations

import math

import numpy as np
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


# ---------------------------------------------------------------------------
# Primitives ajoutees apres la premiere vague
# ---------------------------------------------------------------------------


class TestRsi:
    def test_a_pure_uptrend_saturates_at_a_hundred(self):
        """Aucune baisse sur la fenetre : la borne, pas une division par zero."""
        ctx = at(synthetic.make_store(synthetic.ramp(100, 100.0, 1.0)), 60)
        assert bind_primitive("rsi@1", window=14)(ctx) == pytest.approx(100.0)

    def test_a_pure_downtrend_saturates_at_zero(self):
        ctx = at(synthetic.make_store(synthetic.ramp(100, 300.0, -1.0)), 60)
        assert bind_primitive("rsi@1", window=14)(ctx) == pytest.approx(0.0)

    def test_alternating_equal_moves_give_fifty(self):
        """Hausses et baisses de meme ampleur : force et faiblesse a egalite."""
        closes = np.array([100.0 + (i % 2) for i in range(60)], dtype=np.float64)
        ctx = at(synthetic.make_store(closes), 50)
        assert bind_primitive("rsi@1", window=10)(ctx) == pytest.approx(50.0)

    def test_a_flat_series_has_no_rsi(self):
        """Une serie plate n'a ni force ni faiblesse : 50 serait une invention."""
        ctx = at(synthetic.make_store(synthetic.constant(60, 100.0)), 40)
        assert bind_primitive("rsi@1", window=14)(ctx) is None

    def test_it_stays_within_its_bounds(self):
        store = synthetic.make_store(synthetic.random_walk(400, seed=17))
        bound = bind_primitive("rsi@1", window=14)
        for i in range(20, 400, 7):
            value = bound(at(store, i))
            assert value is None or 0.0 <= value <= 100.0

    def test_warmup_needs_one_extra_bar_for_the_first_variation(self):
        assert bind_primitive("rsi@1", window=14).warmup_bars == 15


class TestStochastic:
    def test_a_centred_bar_gives_fifty(self):
        """Cloture a 100, meches a 99,9 et 100,1 : exactement au milieu."""
        ctx = at(synthetic.make_store(synthetic.constant(60, 100.0)), 40)
        assert bind_primitive("stochastic@1", window=14)(ctx) == pytest.approx(50.0)

    def test_an_uptrend_sits_near_the_top(self):
        ctx = at(synthetic.make_store(synthetic.ramp(100, 100.0, 1.0)), 60)
        value = bind_primitive("stochastic@1", window=14)(ctx)
        assert value is not None and value > 95.0

    def test_a_downtrend_sits_near_the_bottom(self):
        ctx = at(synthetic.make_store(synthetic.ramp(100, 300.0, -1.0)), 60)
        value = bind_primitive("stochastic@1", window=14)(ctx)
        assert value is not None and value < 5.0

    def test_a_bar_without_amplitude_has_no_position(self):
        ctx = at(synthetic.make_store(synthetic.constant(60, 100.0), wick=0.0), 40)
        assert bind_primitive("stochastic@1", window=14)(ctx) is None


class TestStdev:
    def test_hand_computed_case(self):
        """Clotures 1, 2, 3 sur trois barres : ecart-type non biaise de 1."""
        ctx = at(synthetic.make_store(synthetic.ramp(20, 1.0, 1.0)), 2)
        assert bind_primitive("stdev@1", window=3)(ctx) == pytest.approx(1.0)

    def test_a_constant_series_has_no_dispersion(self):
        ctx = at(synthetic.make_store(synthetic.constant(50, 7.0)), 30)
        assert bind_primitive("stdev@1", window=10)(ctx) == pytest.approx(0.0)

    def test_it_unlocks_bollinger_bands(self):
        """La bande haute s'ecrit `sma + 2 * stdev`, sans primitive dediee."""
        store = synthetic.make_store(synthetic.random_walk(300, seed=5))
        ctx = at(store, 200)
        upper = bind_primitive("sma@1", window=20)(ctx) + 2 * bind_primitive(
            "stdev@1", window=20
        )(ctx)
        assert upper > ctx.value(Field.CLOSE) or upper > 0.0

    def test_ddof_zero_is_smaller(self):
        store = synthetic.make_store(synthetic.random_walk(100, seed=2))
        ctx = at(store, 60)
        assert bind_primitive("stdev@1", window=20, ddof=0)(ctx) < bind_primitive(
            "stdev@1", window=20, ddof=1
        )(ctx)


class TestVolatility:
    def test_a_geometric_series_has_zero_volatility(self):
        """Rendements constants : dispersion nulle, meme si les prix montent."""
        closes = 100.0 * np.power(1.01, np.arange(60, dtype=np.float64))
        ctx = at(synthetic.make_store(closes), 40)
        assert bind_primitive("volatility@1", window=20)(ctx) == pytest.approx(0.0, abs=1e-12)

    def test_it_matches_the_standard_deviation_of_returns(self):
        store = synthetic.make_store(synthetic.random_walk(300, seed=9))
        ctx = at(store, 200)
        closes = ctx.values(Field.CLOSE, 21)
        expected = float(np.std(closes[1:] / closes[:-1] - 1.0, ddof=1))
        assert bind_primitive("volatility@1", window=20)(ctx) == pytest.approx(expected)

    def test_annualisation_multiplies_by_the_square_root(self):
        store = synthetic.make_store(synthetic.random_walk(300, seed=9))
        ctx = at(store, 200)
        plain = bind_primitive("volatility@1", window=20)(ctx)
        annual = bind_primitive("volatility@1", window=20, annualise=252.0)(ctx)
        assert annual == pytest.approx(plain * math.sqrt(252.0))

    def test_log_returns_are_available(self):
        store = synthetic.make_store(synthetic.random_walk(300, seed=9))
        ctx = at(store, 200)
        assert bind_primitive("volatility@1", window=20, log=True)(ctx) is not None

    def test_warmup_needs_one_extra_bar(self):
        assert bind_primitive("volatility@1", window=20).warmup_bars == 21


class TestSlope:
    def test_a_ramp_recovers_its_own_step(self):
        """La pente d'une rampe de pas d vaut exactement d."""
        for step in (0.25, 1.0, -2.0):
            store = synthetic.make_store(synthetic.ramp(100, 500.0, step))
            ctx = at(store, 60)
            assert bind_primitive("slope@1", window=20)(ctx) == pytest.approx(step)

    def test_a_constant_series_has_no_slope(self):
        ctx = at(synthetic.make_store(synthetic.constant(60, 100.0)), 40)
        assert bind_primitive("slope@1", window=20)(ctx) == pytest.approx(0.0)

    def test_a_window_of_one_is_undefined(self):
        ctx = at(synthetic.make_store(synthetic.ramp(60)), 40)
        assert bind_primitive("slope@1", window=1)(ctx) is None

    def test_it_reacts_faster_than_a_moving_average(self):
        """Une rupture recente pese autant que le reste : c'est l'interet."""
        closes = np.concatenate(
            [synthetic.constant(40, 100.0), synthetic.ramp(10, 100.0, 5.0)]
        )
        store = synthetic.make_store(closes)
        ctx = at(store, 49)
        assert bind_primitive("slope@1", window=20)(ctx) > 1.0


class TestTrueRange:
    def test_hand_computed_case(self):
        """open = close = 100, meches a 99,9 et 100,1 -> TR = 0,2."""
        ctx = at(synthetic.make_store(synthetic.constant(60, 100.0)), 30)
        assert bind_primitive("true_range@1")(ctx) == pytest.approx(0.2)

    def test_it_is_the_brick_the_atr_averages(self):
        ctx = at(synthetic.make_store(synthetic.constant(60, 100.0)), 30)
        assert bind_primitive("true_range@1")(ctx) == pytest.approx(
            bind_primitive("atr@1", window=14)(ctx)
        )

    def test_it_needs_the_previous_close(self):
        assert bind_primitive("true_range@1").warmup_bars == 2

    def test_it_is_never_negative(self):
        store = synthetic.make_store(synthetic.random_walk(200, seed=31))
        bound = bind_primitive("true_range@1")
        for i in range(2, 200, 5):
            assert bound(at(store, i)) >= 0.0


class TestTheVocabularyGrew:
    def test_the_thirteen_primitives_are_registered(self):
        names = {p.name for p in list_primitives()}
        assert names >= {
            "atr", "ema", "returns", "rolling_high", "rolling_low", "rsi", "slope",
            "sma", "stdev", "stochastic", "true_range", "volatility", "zscore",
        }

    def test_each_new_one_publishes_its_parameter_schema(self):
        catalogue = {entry["ref"]: entry for entry in describe_registry()}
        for ref in ("rsi@1", "stdev@1", "volatility@1", "slope@1", "true_range@1"):
            schema = catalogue[ref]["params"]
            assert isinstance(schema, dict)
            assert "properties" in schema
