"""Test exige n° 9 : donnees pourries.

Chaque regle de validation a son test de rejet. Une regle sans test de rejet
est une regle dont on ne sait pas si elle se declenche.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import polars as pl
import pytest

from fixtures import synthetic
from rsl.data.schema import TIMESTAMP_COLUMN
from rsl.data.validation import (
    Severity,
    ValidationConfig,
    registered_rules,
    validate_frame,
    validation_rule,
)
from rsl.errors import RegistryError


def clean_frame(n: int = 100) -> pl.DataFrame:
    return synthetic.make_frame(synthetic.ramp(n, 100.0, 0.5))


def check(frame: pl.DataFrame, config: ValidationConfig | None = None):
    return validate_frame(frame, symbol="TEST", source="<test>", config=config)


def rule_names(report) -> set[str]:
    return {v.rule for v in report.violations}


def errors_of(report) -> set[str]:
    return {v.rule for v in report.errors}


class TestCleanData:
    def test_clean_frame_is_valid(self):
        report = check(clean_frame())
        assert report.is_valid
        assert not report.errors
        assert report.n_rows == 100

    def test_report_serialises(self):
        payload = check(clean_frame()).to_dict()
        assert payload["is_valid"] is True
        assert payload["symbol"] == "TEST"
        assert isinstance(payload["violations"], list)

    def test_report_renders(self):
        assert "VALIDE" in check(clean_frame()).render()


class TestStructuralRules:
    @pytest.mark.parametrize("dropped", ["open", "high", "low", "close", "volume"])
    def test_missing_column_rejected(self, dropped):
        report = check(clean_frame().drop(dropped))
        assert not report.is_valid
        assert "required_columns" in errors_of(report)

    def test_missing_timestamp_rejected(self):
        report = check(clean_frame().drop(TIMESTAMP_COLUMN))
        assert "required_columns" in errors_of(report)

    def test_naive_timestamp_rejected(self):
        frame = clean_frame().with_columns(
            pl.col(TIMESTAMP_COLUMN).dt.replace_time_zone(None)
        )
        report = check(frame)
        assert "timestamp_dtype" in errors_of(report)

    def test_non_utc_timestamp_rejected(self):
        frame = clean_frame().with_columns(
            pl.col(TIMESTAMP_COLUMN).dt.convert_time_zone("Europe/Paris")
        )
        report = check(frame)
        assert "timestamp_dtype" in errors_of(report)

    def test_integer_timestamp_rejected(self):
        frame = clean_frame().with_columns(pl.col(TIMESTAMP_COLUMN).dt.epoch("s"))
        report = check(frame)
        assert "timestamp_dtype" in errors_of(report)

    def test_null_timestamp_rejected(self):
        frame = clean_frame()
        ts = frame[TIMESTAMP_COLUMN].to_list()
        ts[10] = None
        report = check(frame.with_columns(pl.Series(TIMESTAMP_COLUMN, ts)))
        assert "timestamps_non_null" in errors_of(report)


class TestOrderingRules:
    def test_unsorted_timestamps_rejected(self):
        frame = clean_frame()
        rows = frame.to_dicts()
        rows[10], rows[20] = rows[20], rows[10]
        report = check(pl.DataFrame(rows, schema=frame.schema))
        assert "timestamps_strictly_monotonic" in errors_of(report)

    def test_duplicate_timestamps_rejected(self):
        frame = clean_frame()
        ts = frame[TIMESTAMP_COLUMN].to_list()
        ts[11] = ts[10]
        report = check(frame.with_columns(pl.Series(TIMESTAMP_COLUMN, ts)))
        violation = next(
            v for v in report.violations if v.rule == "timestamps_strictly_monotonic"
        )
        assert violation.severity is Severity.ERROR
        assert "1 doublon" in violation.message

    def test_loader_does_not_silently_sort(self):
        """Le rejet doit venir de la validation, pas d'un tri de complaisance."""
        frame = clean_frame()
        rows = frame.to_dicts()
        rows.reverse()
        report = check(pl.DataFrame(rows, schema=frame.schema))
        assert not report.is_valid


class TestPriceRules:
    @pytest.mark.parametrize("column", ["open", "high", "low", "close"])
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_price_rejected(self, column, bad):
        frame = clean_frame()
        values = frame[column].to_list()
        values[42] = bad
        report = check(frame.with_columns(pl.Series(column, values)))
        assert "prices_finite" in errors_of(report)

    def test_high_below_low_rejected(self):
        frame = clean_frame()
        high = frame["high"].to_list()
        high[7] = float(frame["low"][7]) - 1.0
        report = check(frame.with_columns(pl.Series("high", high)))
        assert "high_low_ordering" in errors_of(report)

    def test_close_above_high_rejected(self):
        frame = clean_frame()
        close = frame["close"].to_list()
        close[7] = float(frame["high"][7]) + 1.0
        report = check(frame.with_columns(pl.Series("close", close)))
        assert "open_close_within_range" in errors_of(report)

    def test_close_below_low_rejected(self):
        frame = clean_frame()
        close = frame["close"].to_list()
        close[7] = float(frame["low"][7]) - 1.0
        report = check(frame.with_columns(pl.Series("close", close)))
        assert "open_close_within_range" in errors_of(report)

    def test_open_out_of_range_rejected(self):
        frame = clean_frame()
        opens = frame["open"].to_list()
        opens[9] = float(frame["high"][9]) + 5.0
        report = check(frame.with_columns(pl.Series("open", opens)))
        assert "open_close_within_range" in errors_of(report)

    def test_negative_price_is_warning_by_default(self):
        """Le WTI a cote -37 $ : un prix negatif n'est pas en soi une corruption."""
        frame = clean_frame()
        for col in ("open", "high", "low", "close"):
            values = frame[col].to_list()
            values[3] = -5.0
            frame = frame.with_columns(pl.Series(col, values))
        # `high < low` reste faux ici : on a mis la meme valeur partout.
        report = check(frame)
        assert "non_positive_prices" in rule_names(report)
        assert "non_positive_prices" not in errors_of(report)

    def test_negative_price_rejected_when_configured(self):
        frame = clean_frame()
        for col in ("open", "high", "low", "close"):
            values = frame[col].to_list()
            values[3] = -5.0
            frame = frame.with_columns(pl.Series(col, values))
        report = check(frame, ValidationConfig(allow_non_positive_prices=False))
        assert "non_positive_prices" in errors_of(report)


class TestVolumeRule:
    def test_negative_volume_rejected(self):
        frame = clean_frame()
        vol = frame["volume"].to_list()
        vol[5] = -1.0
        report = check(frame.with_columns(pl.Series("volume", vol)))
        assert "volume_valid" in errors_of(report)

    def test_nan_volume_rejected(self):
        frame = clean_frame()
        vol = frame["volume"].to_list()
        vol[5] = float("nan")
        report = check(frame.with_columns(pl.Series("volume", vol)))
        assert "volume_valid" in errors_of(report)

    def test_zero_volume_accepted(self):
        frame = clean_frame()
        vol = frame["volume"].to_list()
        vol[5] = 0.0
        assert check(frame.with_columns(pl.Series("volume", vol))).is_valid


class TestGapRules:
    def _gapped(self) -> pl.DataFrame:
        frame = clean_frame(50)
        ts = frame[TIMESTAMP_COLUMN].to_list()
        shifted = ts[:25] + [t + timedelta(hours=6) for t in ts[25:]]
        return frame.with_columns(pl.Series(TIMESTAMP_COLUMN, shifted))

    def test_gap_accepted_when_rule_disabled(self):
        assert check(self._gapped()).is_valid

    def test_gap_rejected_when_threshold_set(self):
        report = check(self._gapped(), ValidationConfig(max_gap=timedelta(minutes=5)))
        assert "max_gap" in errors_of(report)

    def test_gap_profile_is_informational(self):
        report = check(self._gapped())
        profile = next(v for v in report.violations if v.rule == "gap_profile")
        assert profile.severity is Severity.INFO
        assert report.is_valid

    def test_regular_series_reports_no_irregular_gap(self):
        report = check(clean_frame())
        assert "gap_profile" not in rule_names(report)


class TestReturnRule:
    def test_jump_rejected_when_threshold_set(self):
        frame = clean_frame()
        closes = np.array(frame["close"].to_list())
        closes[30] = closes[30] * 3.0
        frame = frame.with_columns(
            pl.Series("close", closes),
            pl.Series("high", np.maximum(frame["high"].to_numpy(), closes * 1.01)),
        )
        report = check(frame, ValidationConfig(max_bar_return=0.1))
        assert "max_bar_return" in errors_of(report)

    def test_no_jump_rule_by_default(self):
        assert "max_bar_return" not in rule_names(check(clean_frame()))


class TestRegistry:
    def test_rules_order_is_deterministic(self):
        first = [r.__rsl_rule_name__ for r in registered_rules()]
        second = [r.__rsl_rule_name__ for r in registered_rules()]
        assert first == second
        assert first[0] == "required_columns"

    def test_duplicate_rule_name_refused(self):
        with pytest.raises(RegistryError, match="deja enregistree"):

            @validation_rule("required_columns")
            def _dup(frame, config):  # pragma: no cover - jamais appelee
                return None

    def test_new_rule_is_added_not_edited(self):
        """Extension par ajout : une regle neuve entre sans toucher aux anciennes."""
        before = len(registered_rules())

        @validation_rule("test_only_probe_rule")
        def _probe(frame, config):
            return None

        after = registered_rules()
        assert len(after) == before + 1
        assert after[-1].__rsl_rule_name__ == "test_only_probe_rule"
        assert after[0].__rsl_rule_name__ == "required_columns"
