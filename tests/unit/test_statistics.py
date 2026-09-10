"""Deflated Sharpe Ratio, journal d'essais, decoupes walk-forward."""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, ClassVar

import pytest

from rsl.errors import ConfigurationError
from rsl.metrics.statistics import (
    EULER_MASCHERONI,
    AnchoredWalkForward,
    RollingWalkForward,
    Split,
    TrialLog,
    WalkForwardSplitter,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    fingerprint_of,
    probabilistic_sharpe_ratio,
)


class TestTrialLog:
    def test_records_and_counts(self):
        log = TrialLog()
        log.record({"window": 10}, 0.05)
        log.record({"window": 20}, 0.08)
        assert log.n_trials == 2

    def test_an_identical_specification_is_not_a_new_trial(self):
        """Rejouer un backtest n'est pas un essai de plus."""
        log = TrialLog()
        first = log.record({"window": 10}, 0.05)
        second = log.record({"window": 10}, 0.05)
        assert log.n_trials == 1
        assert first is second

    def test_key_order_does_not_create_a_duplicate(self):
        log = TrialLog()
        log.record({"a": 1, "b": 2}, 0.1)
        log.record({"b": 2, "a": 1}, 0.1)
        assert log.n_trials == 1

    def test_fingerprint_is_stable_and_short(self):
        assert fingerprint_of({"a": 1}) == fingerprint_of({"a": 1})
        assert fingerprint_of({"a": 1}) != fingerprint_of({"a": 2})
        assert len(fingerprint_of({"a": 1})) == 16

    def test_variance_of_sharpes(self):
        log = TrialLog()
        for i, sharpe in enumerate([0.0, 0.1, 0.2]):
            log.record({"i": i}, sharpe)
        assert log.variance_of_sharpes == pytest.approx(0.01)

    def test_a_single_trial_has_no_variance(self):
        log = TrialLog()
        log.record({"i": 0}, 0.3)
        assert log.variance_of_sharpes == 0.0

    def test_an_empty_log_is_neutral(self):
        log = TrialLog()
        assert log.n_trials == 0
        assert log.variance_of_sharpes == 0.0
        assert log.best is None

    def test_best_is_the_highest_sharpe(self):
        log = TrialLog()
        log.record({"i": 0}, 0.1, label="lent")
        log.record({"i": 1}, 0.4, label="rapide")
        log.record({"i": 2}, 0.2)
        assert log.best is not None
        assert log.best.label == "rapide"

    def test_a_non_finite_sharpe_is_refused(self):
        log = TrialLog()
        with pytest.raises(ConfigurationError, match="fini"):
            log.record({"i": 0}, float("inf"))

    def test_describe_is_serialisable(self):
        import json

        log = TrialLog()
        log.record({"window": 10}, 0.05, label="essai 1")
        assert json.loads(json.dumps(log.describe())) == log.describe()


class TestExpectedMaxSharpe:
    def test_a_single_trial_selects_nothing(self):
        assert expected_max_sharpe(1, 1.0) == 0.0

    def test_no_dispersion_means_no_correction(self):
        assert expected_max_sharpe(100, 0.0) == 0.0

    def test_reference_value(self):
        """Valeur de reference : dix essais, variance unitaire."""
        assert expected_max_sharpe(10, 1.0) == pytest.approx(1.574_598_301_345_75)

    def test_it_scales_with_the_standard_deviation(self):
        assert expected_max_sharpe(10, 4.0) == pytest.approx(2 * expected_max_sharpe(10, 1.0))

    def test_more_trials_raise_the_bar(self):
        values = [expected_max_sharpe(n, 1.0) for n in (2, 10, 100, 1000)]
        assert values == sorted(values)
        assert values[-1] > values[0]

    def test_the_euler_weights_are_the_published_ones(self):
        """Recompose la formule a partir de ses deux quantiles."""
        n, variance = 50, 0.04
        normal = NormalDist()
        expected = math.sqrt(variance) * (
            (1.0 - EULER_MASCHERONI) * normal.inv_cdf(1.0 - 1.0 / n)
            + EULER_MASCHERONI * normal.inv_cdf(1.0 - 1.0 / (n * math.e))
        )
        assert expected_max_sharpe(n, variance) == pytest.approx(expected)

    @pytest.mark.parametrize(("n", "variance"), [(0, 1.0), (-1, 1.0), (10, -0.1)])
    def test_invalid_arguments_refused(self, n, variance):
        with pytest.raises(ConfigurationError):
            expected_max_sharpe(n, variance)


class TestProbabilisticSharpe:
    BASE: ClassVar[dict[str, Any]] = {
        "sharpe_per_period": 0.1,
        "n_observations": 101,
        "skewness": 0.0,
        "kurtosis": 3.0,
    }

    def test_reference_value(self):
        assert probabilistic_sharpe_ratio(**self.BASE) == pytest.approx(0.840_741_327_801_35)

    def test_it_is_not_quite_the_naive_normal_probability(self):
        """Meme sur des rendements gaussiens, le terme de kurtosis mord."""
        naive = NormalDist().cdf(0.1 * math.sqrt(100))
        got = probabilistic_sharpe_ratio(**self.BASE)
        assert got is not None
        assert got < naive
        assert abs(got - naive) < 0.01

    def test_a_higher_sharpe_raises_the_probability(self):
        low = probabilistic_sharpe_ratio(**{**self.BASE, "sharpe_per_period": 0.05})
        high = probabilistic_sharpe_ratio(**{**self.BASE, "sharpe_per_period": 0.2})
        assert low is not None and high is not None
        assert high > low

    def test_more_observations_raise_the_probability(self):
        few = probabilistic_sharpe_ratio(**{**self.BASE, "n_observations": 30})
        many = probabilistic_sharpe_ratio(**{**self.BASE, "n_observations": 1000})
        assert few is not None and many is not None
        assert many > few

    def test_negative_skew_lowers_the_probability(self):
        """Une asymetrie a gauche rend le meme Sharpe moins credible."""
        symmetric = probabilistic_sharpe_ratio(**self.BASE)
        skewed = probabilistic_sharpe_ratio(**{**self.BASE, "skewness": -1.5})
        assert symmetric is not None and skewed is not None
        assert skewed < symmetric

    def test_fat_tails_lower_the_probability(self):
        normal = probabilistic_sharpe_ratio(**self.BASE)
        fat = probabilistic_sharpe_ratio(**{**self.BASE, "kurtosis": 12.0})
        assert normal is not None and fat is not None
        assert fat < normal

    def test_a_benchmark_lowers_the_probability(self):
        against_zero = probabilistic_sharpe_ratio(**self.BASE)
        against_bar = probabilistic_sharpe_ratio(**{**self.BASE, "benchmark_sharpe": 0.08})
        assert against_zero is not None and against_bar is not None
        assert against_bar < against_zero

    def test_too_few_observations_gives_nothing(self):
        assert probabilistic_sharpe_ratio(**{**self.BASE, "n_observations": 1}) is None

    def test_an_undefined_denominator_gives_nothing(self):
        """Hors du domaine ou la formule a un sens, on ne repond pas."""
        got = probabilistic_sharpe_ratio(
            sharpe_per_period=1.0, n_observations=100, skewness=10.0, kurtosis=3.0
        )
        assert got is None


class TestDeflatedSharpe:
    BASE: ClassVar[dict[str, Any]] = {
        "sharpe_per_period": 0.12,
        "n_observations": 500,
        "skewness": -0.2,
        "kurtosis": 5.0,
    }

    def test_a_single_trial_reduces_to_the_psr(self):
        result = deflated_sharpe_ratio(**self.BASE, n_trials=1, variance_of_trial_sharpes=0.01)
        assert result.expected_max_sharpe == 0.0
        assert result.deflated_sharpe == pytest.approx(result.probabilistic_sharpe)

    def test_a_single_trial_warns(self):
        result = deflated_sharpe_ratio(**self.BASE, n_trials=1, variance_of_trial_sharpes=0.01)
        assert any("un seul essai" in w for w in result.warnings)

    def test_more_trials_lower_the_deflated_sharpe(self):
        values = []
        for n in (2, 10, 100, 1000):
            result = deflated_sharpe_ratio(
                **self.BASE, n_trials=n, variance_of_trial_sharpes=0.005
            )
            assert result.deflated_sharpe is not None
            values.append(result.deflated_sharpe)
        assert values == sorted(values, reverse=True)

    def test_the_selection_penalty_can_destroy_an_impressive_sharpe(self):
        """Le point du DSR : chercher beaucoup rend un beau resultat banal."""
        honest = deflated_sharpe_ratio(**self.BASE, n_trials=1, variance_of_trial_sharpes=0.02)
        dredged = deflated_sharpe_ratio(
            **self.BASE, n_trials=5_000, variance_of_trial_sharpes=0.02
        )
        assert honest.is_significant
        assert not dredged.is_significant

    def test_a_null_dispersion_degenerates_and_warns(self):
        result = deflated_sharpe_ratio(
            **self.BASE, n_trials=50, variance_of_trial_sharpes=0.0
        )
        assert result.expected_max_sharpe == 0.0
        assert any("variance des Sharpe" in w for w in result.warnings)

    def test_few_observations_warn(self):
        result = deflated_sharpe_ratio(
            sharpe_per_period=0.2, n_observations=12, skewness=0.0, kurtosis=3.0,
            n_trials=5, variance_of_trial_sharpes=0.01,
        )
        assert any("observations seulement" in w for w in result.warnings)

    def test_an_undefined_result_is_reported_as_such(self):
        result = deflated_sharpe_ratio(
            sharpe_per_period=1.0, n_observations=100, skewness=10.0, kurtosis=3.0,
            n_trials=5, variance_of_trial_sharpes=0.01,
        )
        assert result.deflated_sharpe is None
        assert not result.is_significant
        assert any("denominateur" in w for w in result.warnings)

    def test_inputs_are_kept_for_audit(self):
        result = deflated_sharpe_ratio(
            **self.BASE, n_trials=42, variance_of_trial_sharpes=0.003
        )
        assert result.n_trials == 42
        assert result.variance_of_trial_sharpes == 0.003
        assert result.observed_sharpe_per_period == self.BASE["sharpe_per_period"]
        assert result.skewness == self.BASE["skewness"]

    def test_describe_and_render(self):
        import json

        result = deflated_sharpe_ratio(
            **self.BASE, n_trials=20, variance_of_trial_sharpes=0.01
        )
        assert json.loads(json.dumps(result.describe())) == result.describe()
        assert "Maximum attendu sous H0" in result.render()

    def test_it_composes_with_a_trial_log(self):
        """Le chemin nominal : le journal fournit les deux entrees du DSR."""
        log = TrialLog()
        for i, sharpe in enumerate([0.02, 0.05, 0.11, 0.03, 0.08]):
            log.record({"window": 10 * (i + 1)}, sharpe)
        best = log.best
        assert best is not None

        result = deflated_sharpe_ratio(
            sharpe_per_period=best.sharpe_per_period,
            n_observations=750,
            skewness=-0.1,
            kurtosis=4.0,
            n_trials=log.n_trials,
            variance_of_trial_sharpes=log.variance_of_sharpes,
        )
        assert result.n_trials == 5
        assert result.expected_max_sharpe > 0.0
        assert result.deflated_sharpe is not None


class TestSplit:
    def test_valid_split(self):
        split = Split(0, 100, 100, 150)
        assert split.describe() == {"train": [0, 100], "test": [100, 150]}

    def test_an_empty_training_window_is_refused(self):
        with pytest.raises(ConfigurationError, match="apprentissage vide"):
            Split(10, 10, 10, 20)

    def test_an_empty_test_window_is_refused(self):
        with pytest.raises(ConfigurationError, match="test vide"):
            Split(0, 10, 10, 10)

    def test_an_overlapping_split_is_refused(self):
        """Un walk-forward qui se chevauche ne teste rien."""
        with pytest.raises(ConfigurationError, match="avant la fin de l'apprentissage"):
            Split(0, 100, 50, 150)


class TestRollingWalkForward:
    def test_split_count_and_shape(self):
        splits = list(RollingWalkForward(train_bars=100, test_bars=20).split(200))
        assert len(splits) == 5
        assert splits[0] == Split(0, 100, 100, 120)
        assert splits[-1] == Split(80, 180, 180, 200)

    def test_the_default_step_is_the_test_window(self):
        assert RollingWalkForward(train_bars=10, test_bars=5).step == 5

    def test_an_explicit_step_changes_the_cadence(self):
        splits = list(
            RollingWalkForward(train_bars=100, test_bars=20, step_bars=50).split(300)
        )
        assert [s.train_start for s in splits] == [0, 50, 100, 150]

    def test_the_training_window_keeps_its_size(self):
        for split in RollingWalkForward(train_bars=100, test_bars=20).split(400):
            assert split.train_stop - split.train_start == 100

    def test_a_sample_too_short_yields_nothing(self):
        assert list(RollingWalkForward(train_bars=100, test_bars=20).split(50)) == []

    @pytest.mark.parametrize(
        "kwargs", [{"train_bars": 0, "test_bars": 5}, {"train_bars": 5, "test_bars": 0},
                   {"train_bars": 5, "test_bars": 5, "step_bars": 0}]
    )
    def test_invalid_parameters_refused(self, kwargs):
        with pytest.raises(ConfigurationError):
            RollingWalkForward(**kwargs)


class TestAnchoredWalkForward:
    def test_the_training_window_grows(self):
        splits = list(AnchoredWalkForward(initial_train_bars=100, test_bars=20).split(200))
        assert len(splits) == 5
        assert all(s.train_start == 0 for s in splits)
        assert [s.train_stop for s in splits] == [100, 120, 140, 160, 180]

    def test_the_test_window_always_follows_the_training_one(self):
        for split in AnchoredWalkForward(initial_train_bars=50, test_bars=10).split(200):
            assert split.test_start == split.train_stop

    def test_a_sample_too_short_yields_nothing(self):
        assert list(AnchoredWalkForward(initial_train_bars=100, test_bars=20).split(50)) == []

    def test_invalid_parameters_refused(self):
        with pytest.raises(ConfigurationError):
            AnchoredWalkForward(initial_train_bars=0, test_bars=5)


class TestSplitterProtocol:
    def test_both_splitters_conform(self):
        assert isinstance(RollingWalkForward(10, 5), WalkForwardSplitter)
        assert isinstance(AnchoredWalkForward(10, 5), WalkForwardSplitter)

    def test_describe_is_serialisable(self):
        import json

        for splitter in (RollingWalkForward(10, 5), AnchoredWalkForward(10, 5)):
            assert json.loads(json.dumps(splitter.describe())) == splitter.describe()

    def test_no_split_ever_looks_forward(self):
        """La propriete qui compte : le test est toujours apres l'apprentissage."""
        for splitter in (RollingWalkForward(30, 10), AnchoredWalkForward(30, 10)):
            for split in splitter.split(300):
                assert split.test_start >= split.train_stop
