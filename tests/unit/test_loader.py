from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from fixtures import synthetic
from rsl.data.loader import (
    build_panel,
    file_sha256,
    load_bar_store,
    read_ohlcv_frame,
    validate_file,
)
from rsl.data.schema import ABSENT, TIMESTAMP_COLUMN, AlignPolicy, Granularity
from rsl.errors import ConfigurationError, DataValidationError

MINUTE = Granularity.minutes(1)


def write(frame: pl.DataFrame, path: Path) -> Path:
    frame.write_parquet(path)
    return path


class TestReadFrame:
    def test_selects_canonical_columns(self, parquet_path: Path):
        frame = read_ohlcv_frame(parquet_path)
        assert frame.columns == [TIMESTAMP_COLUMN, "open", "high", "low", "close", "volume"]

    def test_renames_alternative_timestamp_column(self, tmp_path: Path):
        frame = synthetic.make_frame(synthetic.ramp(20)).rename({TIMESTAMP_COLUMN: "timestamp"})
        loaded = read_ohlcv_frame(write(frame, tmp_path / "alt.parquet"))
        assert TIMESTAMP_COLUMN in loaded.columns

    def test_ambiguous_timestamp_column_refused(self, tmp_path: Path):
        frame = synthetic.make_frame(synthetic.ramp(20))
        frame = frame.with_columns(pl.col(TIMESTAMP_COLUMN).alias("timestamp"))
        with pytest.raises(ConfigurationError, match="plusieurs colonnes"):
            read_ohlcv_frame(write(frame, tmp_path / "ambig.parquet"))

    def test_ambiguity_resolved_by_explicit_choice(self, tmp_path: Path):
        frame = synthetic.make_frame(synthetic.ramp(20))
        frame = frame.with_columns(pl.col(TIMESTAMP_COLUMN).alias("timestamp"))
        path = write(frame, tmp_path / "ambig2.parquet")
        assert read_ohlcv_frame(path, timestamp_column="ts_event").height == 20

    def test_no_timestamp_column_refused(self, tmp_path: Path):
        frame = synthetic.make_frame(synthetic.ramp(20)).drop(TIMESTAMP_COLUMN)
        with pytest.raises(ConfigurationError, match="aucune colonne"):
            read_ohlcv_frame(write(frame, tmp_path / "none.parquet"))

    def test_unknown_explicit_column_refused(self, parquet_path: Path):
        with pytest.raises(ConfigurationError, match="absente"):
            read_ohlcv_frame(parquet_path, timestamp_column="nope")


class TestLoadBarStore:
    def test_round_trip_preserves_values(self, tmp_path: Path):
        closes = synthetic.ramp(200, 100.0, 0.25)
        frame = synthetic.make_frame(closes)
        path = write(frame, tmp_path / "rt.parquet")
        store, report = load_bar_store(path, symbol="RT.v.0", granularity=MINUTE)
        assert report.is_valid
        assert store.n_bars == 200
        assert np.allclose(store.close, closes)
        assert not store.close.flags.writeable

    def test_hash_is_recorded_and_stable(self, parquet_path: Path):
        store, _ = load_bar_store(parquet_path, symbol="H.v.0", granularity=MINUTE)
        assert store.source_hash == file_sha256(parquet_path)
        assert len(store.source_hash) == 64

    def test_hash_can_be_skipped(self, parquet_path: Path):
        store, _ = load_bar_store(
            parquet_path, symbol="H.v.0", granularity=MINUTE, with_hash=False
        )
        assert store.source_hash == ""

    def test_corrupt_file_is_rejected_with_report(self, tmp_path: Path):
        frame = synthetic.make_frame(synthetic.ramp(50))
        high = frame["high"].to_list()
        high[10] = float(frame["low"][10]) - 1.0
        path = write(frame.with_columns(pl.Series("high", high)), tmp_path / "bad.parquet")

        with pytest.raises(DataValidationError) as excinfo:
            load_bar_store(path, symbol="BAD.v.0", granularity=MINUTE)

        report = excinfo.value.report
        assert report is not None
        assert not report.is_valid  # type: ignore[union-attr]
        assert "high_low_ordering" in {v.rule for v in report.errors}  # type: ignore[union-attr]

    def test_validate_file_does_not_raise(self, tmp_path: Path):
        frame = synthetic.make_frame(synthetic.ramp(50))
        vol = frame["volume"].to_list()
        vol[3] = -1.0
        path = write(frame.with_columns(pl.Series("volume", vol)), tmp_path / "warn.parquet")
        report = validate_file(path, symbol="W.v.0")
        assert not report.is_valid


class TestBuildPanel:
    def _stores(self):
        a = synthetic.make_store(synthetic.ramp(100, 100.0, 1.0), symbol="A")
        b = synthetic.make_store(synthetic.ramp(60, 50.0, 0.5), symbol="B")
        return {"A": a, "B": b}

    def test_calendar_is_the_union(self):
        panel = build_panel(self._stores())
        assert panel.n_rows == 100
        assert panel.symbols == ("A", "B")

    def test_symbols_are_sorted_regardless_of_insertion_order(self):
        stores = self._stores()
        reversed_order = {"B": stores["B"], "A": stores["A"]}
        assert build_panel(reversed_order).symbols == ("A", "B")

    def test_absent_symbol_marked_absent_not_forward_filled(self):
        panel = build_panel(self._stores())
        assert int(panel.row_index["B"][59]) == 59
        assert int(panel.row_index["B"][60]) == ABSENT
        assert panel.present_symbols(60) == ("A",)
        assert panel.n_stale("B") == 0

    def test_ffill_requires_explicit_bound(self):
        with pytest.raises(ConfigurationError, match="max_ffill_bars"):
            build_panel(self._stores(), align_policy=AlignPolicy.FFILL)

    def test_ffill_is_bounded_and_flagged(self):
        panel = build_panel(
            self._stores(), align_policy=AlignPolicy.FFILL, max_ffill_bars=5
        )
        assert int(panel.row_index["B"][60]) == 59
        assert bool(panel.is_stale["B"][60])
        assert int(panel.row_index["B"][64]) == 59
        assert int(panel.row_index["B"][65]) == ABSENT
        assert panel.n_stale("B") == 5

    def test_ffill_zero_bars_fills_nothing(self):
        panel = build_panel(
            self._stores(), align_policy=AlignPolicy.FFILL, max_ffill_bars=0
        )
        assert int(panel.row_index["B"][60]) == ABSENT
        assert panel.n_stale("B") == 0

    def test_error_policy_rejects_any_absence(self):
        with pytest.raises(DataValidationError, match="manque a"):
            build_panel(self._stores(), align_policy=AlignPolicy.ERROR)

    def test_error_policy_accepts_fully_aligned_panel(self):
        aligned = {
            "A": synthetic.make_store(synthetic.ramp(40), symbol="A"),
            "B": synthetic.make_store(synthetic.constant(40), symbol="B"),
        }
        panel = build_panel(aligned, align_policy=AlignPolicy.ERROR)
        assert panel.n_rows == 40

    def test_heterogeneous_granularity_refused(self):
        stores = {
            "A": synthetic.make_store(synthetic.ramp(30), symbol="A"),
            "B": synthetic.make_store(
                synthetic.ramp(30), symbol="B", granularity=Granularity.minutes(5)
            ),
        }
        with pytest.raises(ConfigurationError, match="granularites heterogenes"):
            build_panel(stores)

    def test_empty_panel_refused(self):
        with pytest.raises(ConfigurationError, match="panneau vide"):
            build_panel({})

    def test_negative_ffill_bound_refused(self):
        with pytest.raises(ConfigurationError, match="max_ffill_bars"):
            build_panel(self._stores(), align_policy=AlignPolicy.FFILL, max_ffill_bars=-1)

    def test_disjoint_calendars_interleave(self):
        from datetime import timedelta

        a = synthetic.make_store(synthetic.ramp(10), symbol="A")
        b = synthetic.make_store(
            synthetic.ramp(10), symbol="B", start=synthetic.EPOCH + timedelta(seconds=30)
        )
        panel = build_panel({"A": a, "B": b})
        assert panel.n_rows == 20
        assert panel.present_symbols(0) == ("A",)
        assert panel.present_symbols(1) == ("B",)
