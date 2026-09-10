"""Reechantillonnage : decoupage, agregation, horodatage de disponibilite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.loader import build_panel
from rsl.data.resample import (
    CloseStamp,
    Period,
    bucket_ids,
    granularity_of,
    period_end_ns,
    resample,
)
from rsl.data.schema import BarStore, Granularity, ns_to_datetime
from rsl.errors import ConfigurationError

DAY = Granularity(timedelta(days=1), name="1d")


def daily_store(n: int, start: datetime, closes=None, symbol: str = "D.v.0") -> BarStore:
    """Serie quotidienne : les frontieres de mois y sont lisibles a l'oeil."""
    values = synthetic.ramp(n, 100.0, 1.0) if closes is None else closes
    return synthetic.make_store(values, symbol=symbol, granularity=DAY, start=start)


class TestBucketIds:
    def test_days_are_consecutive(self):
        store = daily_store(10, datetime(2021, 1, 1, tzinfo=UTC))
        ids = bucket_ids(store.ts_event, Period.DAY)
        assert np.array_equal(ids, np.arange(ids[0], ids[0] + 10))

    def test_month_boundary_splits(self):
        store = daily_store(5, datetime(2021, 1, 30, tzinfo=UTC))
        ids = bucket_ids(store.ts_event, Period.MONTH)
        # 30, 31 janvier puis 1, 2, 3 fevrier
        assert ids[0] == ids[1]
        assert ids[2] == ids[3] == ids[4]
        assert ids[2] == ids[0] + 1

    def test_weeks_start_on_monday(self):
        # 2021-01-04 est un lundi
        store = daily_store(14, datetime(2021, 1, 4, tzinfo=UTC))
        ids = bucket_ids(store.ts_event, Period.WEEK)
        assert len(set(ids[:7].tolist())) == 1
        assert len(set(ids[7:].tolist())) == 1
        assert ids[7] == ids[0] + 1

    def test_quarter_groups_three_months(self):
        store = daily_store(1, datetime(2021, 1, 15, tzinfo=UTC))
        others = [
            daily_store(1, datetime(2021, m, 15, tzinfo=UTC)) for m in (2, 3, 4)
        ]
        base = int(bucket_ids(store.ts_event, Period.QUARTER)[0])
        got = [int(bucket_ids(o.ts_event, Period.QUARTER)[0]) for o in others]
        assert got == [base, base, base + 1]

    def test_ids_are_monotonic(self):
        store = daily_store(400, datetime(2020, 1, 1, tzinfo=UTC))
        for period in Period:
            ids = bucket_ids(store.ts_event, period)
            assert bool((np.diff(ids) >= 0).all()), period


class TestPeriodEnd:
    @pytest.mark.parametrize(
        ("period", "moment", "expected"),
        [
            (
                Period.DAY,
                datetime(2021, 3, 14, 13, 30, tzinfo=UTC),
                datetime(2021, 3, 15, tzinfo=UTC),
            ),
            (Period.MONTH, datetime(2021, 3, 14, tzinfo=UTC), datetime(2021, 4, 1, tzinfo=UTC)),
            (Period.MONTH, datetime(2021, 12, 31, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC)),
            (Period.QUARTER, datetime(2021, 5, 2, tzinfo=UTC), datetime(2021, 7, 1, tzinfo=UTC)),
            (Period.YEAR, datetime(2021, 8, 9, tzinfo=UTC), datetime(2022, 1, 1, tzinfo=UTC)),
            (Period.WEEK, datetime(2021, 1, 6, tzinfo=UTC), datetime(2021, 1, 11, tzinfo=UTC)),
        ],
    )
    def test_boundary(self, period, moment, expected):
        store = daily_store(1, moment)
        ids = bucket_ids(store.ts_event, period)
        assert ns_to_datetime(int(period_end_ns(ids, period)[0])) == expected

    def test_boundary_is_never_before_the_last_bar(self):
        """La propriete qui rend le choix sur : jamais anticipe."""
        store = daily_store(400, datetime(2020, 1, 1, tzinfo=UTC))
        for period in Period:
            aggregated, _ = resample(store, period)
            last_bar, _ = resample(store, period, close_stamp=CloseStamp.LAST_BAR)
            assert bool((aggregated.ts_close >= last_bar.ts_close).all()), period


class TestAggregation:
    def test_ohlcv_of_a_month(self):
        closes = synthetic.ramp(31, 100.0, 1.0)
        store = daily_store(31, datetime(2021, 1, 1, tzinfo=UTC), closes)
        monthly, _ = resample(store, Period.MONTH)

        assert monthly.n_bars == 1
        assert float(monthly.open[0]) == pytest.approx(float(store.open[0]))
        assert float(monthly.close[0]) == pytest.approx(float(store.close[30]))
        assert float(monthly.high[0]) == pytest.approx(float(store.high.max()))
        assert float(monthly.low[0]) == pytest.approx(float(store.low.min()))
        assert float(monthly.volume[0]) == pytest.approx(float(store.volume.sum()))

    def test_two_months_are_separated(self):
        store = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, report = resample(store, Period.MONTH)
        assert monthly.n_bars == 2
        assert report.n_periods == 2
        assert ns_to_datetime(int(monthly.ts_close[0])) == datetime(2021, 2, 1, tzinfo=UTC)
        assert ns_to_datetime(int(monthly.ts_close[1])) == datetime(2021, 3, 1, tzinfo=UTC)

    def test_open_is_the_first_of_the_period_not_the_previous_close(self):
        store = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, _ = resample(store, Period.MONTH)
        assert float(monthly.open[1]) == pytest.approx(float(store.open[31]))

    def test_granularity_carries_a_readable_name(self):
        store = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, _ = resample(store, Period.MONTH)
        assert str(monthly.granularity) == "1M"
        assert str(granularity_of(Period.QUARTER)) == "1Q"

    def test_source_hash_records_the_transformation(self):
        store = daily_store(40, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, _ = resample(store, Period.MONTH)
        assert monthly.source_hash.endswith("|resample:month")

    def test_aggregated_arrays_are_frozen(self):
        store = daily_store(40, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, _ = resample(store, Period.MONTH)
        assert not monthly.close.flags.writeable


class TestCloseStamp:
    def test_last_bar_uses_the_final_constituent(self):
        store = daily_store(31, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, _ = resample(store, Period.MONTH, close_stamp=CloseStamp.LAST_BAR)
        assert int(monthly.ts_close[0]) == int(store.ts_close[30])

    def test_period_end_is_the_default(self):
        store = daily_store(31, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, report = resample(store, Period.MONTH)
        assert report.close_stamp is CloseStamp.PERIOD_END
        assert ns_to_datetime(int(monthly.ts_close[0])) == datetime(2021, 2, 1, tzinfo=UTC)

    def test_period_end_aligns_instruments_that_close_at_different_times(self):
        """Le defaut qui a motive le choix.

        Deux instruments dont la derniere barre du mois differe de quelques
        minutes doivent produire UNE ligne de panneau, pas deux.
        """
        a = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC), symbol="A")
        b = synthetic.make_store(
            synthetic.ramp(59, 50.0, 0.5),
            symbol="B",
            granularity=DAY,
            start=datetime(2021, 1, 1, 0, 4, tzinfo=UTC),
        )
        stores = {
            "A": resample(a, Period.MONTH)[0],
            "B": resample(b, Period.MONTH)[0],
        }
        panel = build_panel(stores)
        assert panel.n_rows == 2
        assert panel.present_symbols(0) == ("A", "B")

    def test_last_bar_fragments_the_panel(self):
        """Garde-fou : sans lui, le test precedent pourrait passer par hasard."""
        a = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC), symbol="A")
        b = synthetic.make_store(
            synthetic.ramp(59, 50.0, 0.5),
            symbol="B",
            granularity=DAY,
            start=datetime(2021, 1, 1, 0, 4, tzinfo=UTC),
        )
        stores = {
            "A": resample(a, Period.MONTH, close_stamp=CloseStamp.LAST_BAR)[0],
            "B": resample(b, Period.MONTH, close_stamp=CloseStamp.LAST_BAR)[0],
        }
        panel = build_panel(stores)
        assert panel.n_rows == 4
        assert panel.present_symbols(0) == ("A",)


class TestMinBars:
    def test_incomplete_period_is_dropped(self):
        # janvier complet (31 jours) puis trois jours de fevrier
        store = daily_store(34, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, report = resample(store, Period.MONTH, min_bars=10)
        assert monthly.n_bars == 1
        assert report.n_dropped_incomplete == 1

    def test_nothing_is_dropped_by_default(self):
        store = daily_store(34, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, report = resample(store, Period.MONTH)
        assert monthly.n_bars == 2
        assert report.n_dropped_incomplete == 0

    def test_invalid_min_bars_refused(self):
        store = daily_store(10, datetime(2021, 1, 1, tzinfo=UTC))
        with pytest.raises(ConfigurationError, match="min_bars"):
            resample(store, Period.MONTH, min_bars=0)


class TestCausality:
    def test_a_period_only_uses_its_own_bars(self):
        """Corrompre fevrier ne doit pas toucher la barre de janvier."""
        clean = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC))
        dirty = synthetic.corrupt_future(clean, after_index=30)
        january_clean, _ = resample(clean, Period.MONTH)
        january_dirty, _ = resample(dirty, Period.MONTH)

        for field in ("open", "high", "low", "close", "volume", "ts_event", "ts_close"):
            assert getattr(january_clean, field)[0] == getattr(january_dirty, field)[0], field

    def test_february_does_change(self):
        clean = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC))
        dirty = synthetic.corrupt_future(clean, after_index=30)
        assert float(resample(clean, Period.MONTH)[0].close[1]) != float(
            resample(dirty, Period.MONTH)[0].close[1]
        )

    def test_a_context_reveals_a_period_only_once_it_is_over(self):
        from rsl.data.feed import BarFeed

        store = daily_store(90, datetime(2021, 1, 1, tzinfo=UTC))
        monthly, _ = resample(store, Period.MONTH)
        seen = [ctx.ts for ctx in BarFeed(monthly)]
        assert seen == [
            datetime(2021, 2, 1, tzinfo=UTC),
            datetime(2021, 3, 1, tzinfo=UTC),
            datetime(2021, 4, 1, tzinfo=UTC),
        ]


class TestReport:
    def test_contents(self):
        store = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC))
        _, report = resample(store, Period.MONTH)
        assert report.n_source_bars == 59
        assert report.n_periods == 2
        assert report.min_bars_in_a_period == 28
        assert report.max_bars_in_a_period == 31
        assert "59 barres -> 2 periodes" in report.render()

    def test_describe_is_serialisable(self):
        import json

        store = daily_store(59, datetime(2021, 1, 1, tzinfo=UTC))
        _, report = resample(store, Period.MONTH)
        assert json.loads(json.dumps(report.describe())) == report.describe()

    def test_empty_store_refused(self):
        empty = synthetic.make_store(synthetic.ramp(1), symbol="E").slice(0, 0)
        with pytest.raises(ConfigurationError, match="vide"):
            resample(empty, Period.MONTH)
