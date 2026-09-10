from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from pydantic import ValidationError

from fixtures import synthetic
from rsl.data.schema import (
    ALL_FIELDS,
    BarStore,
    Field,
    Granularity,
    InstrumentSpec,
    datetime_to_ns,
    ns_to_datetime,
)


class TestGranularity:
    def test_minutes_rejects_non_positive(self):
        with pytest.raises(ValueError, match="doit etre > 0"):
            Granularity.minutes(0)

    @pytest.mark.parametrize(
        ("delta", "expected"),
        [
            (timedelta(minutes=1), "1m"),
            (timedelta(hours=4), "4h"),
            (timedelta(days=1), "1d"),
            (timedelta(seconds=30), "30s"),
        ],
    )
    def test_str(self, delta, expected):
        assert str(Granularity(delta)) == expected

    def test_nanoseconds(self):
        assert Granularity.minutes(1).nanoseconds == 60_000_000_000


class TestTimestampConversion:
    def test_round_trip(self):
        dt = datetime(2024, 3, 14, 13, 30, tzinfo=UTC)
        assert ns_to_datetime(datetime_to_ns(dt)) == dt

    def test_naive_datetime_refused(self):
        with pytest.raises(ValueError, match="naif"):
            datetime_to_ns(datetime(2024, 3, 14, 13, 30))


class TestBarStore:
    def test_arrays_are_frozen(self, ramp_store: BarStore):
        for f in ALL_FIELDS:
            column = ramp_store.column(f)
            assert not column.flags.writeable
            with pytest.raises(ValueError, match="read-only"):
                column[0] = 1.0
        assert not ramp_store.ts_event.flags.writeable
        assert not ramp_store.ts_close.flags.writeable

    def test_ts_close_is_ts_event_plus_granularity(self, ramp_store: BarStore):
        step = ramp_store.granularity.nanoseconds
        assert np.array_equal(ramp_store.ts_close, ramp_store.ts_event + step)

    def test_build_rejects_length_mismatch(self):
        n = 10
        with pytest.raises(ValueError, match="longueur"):
            BarStore.build(
                symbol="X",
                granularity=Granularity.minutes(1),
                ts_event=synthetic.timestamps(n),
                open_=np.ones(n),
                high=np.ones(n),
                low=np.ones(n),
                close=np.ones(n - 1),
                volume=np.ones(n),
            )

    def test_bar_at_matches_columns(self, sine_store: BarStore):
        bar = sine_store.bar_at(37)
        assert bar.close == pytest.approx(float(sine_store.close[37]))
        assert bar.field(Field.HIGH) == pytest.approx(float(sine_store.high[37]))
        assert bar.ts_close - bar.ts_event == sine_store.granularity.delta

    def test_slice_preserves_values(self, walk_store: BarStore):
        sub = walk_store.slice(10, 20)
        assert sub.n_bars == 10
        assert np.array_equal(sub.close, walk_store.close[10:20])
        assert not sub.close.flags.writeable

    def test_store_does_not_alias_input_arrays(self):
        closes = synthetic.ramp(20)
        store = synthetic.make_store(closes)
        original = float(store.close[5])
        closes[5] = -999.0
        assert float(store.close[5]) == original


class TestInstrumentSpec:
    def _spec(self, **overrides: object) -> InstrumentSpec:
        base: dict[str, object] = {
            "symbol": "ES.v.0", "root": "ES", "name": "S&P 500",
            "exchange": "CME", "currency": "USD",
            "multiplier": 50.0, "tick_size": 0.25,
            "commission_per_contract": 0.85, "exchange_fee_per_contract": 1.45,
            "initial_margin": 17_000.0, "maintenance_margin": 15_500.0,
        }
        base.update(overrides)
        return InstrumentSpec(**base)  # type: ignore[arg-type]

    def test_valid(self):
        spec = self._spec()
        assert spec.fee_per_contract_per_side == pytest.approx(2.30)

    def test_frozen(self):
        with pytest.raises(ValidationError):
            self._spec().multiplier = 1.0  # type: ignore[misc]

    @pytest.mark.parametrize("field", ["multiplier", "tick_size", "initial_margin"])
    def test_rejects_non_positive(self, field):
        with pytest.raises(ValidationError):
            self._spec(**{field: 0.0})

    def test_rejects_maintenance_above_initial(self):
        with pytest.raises(ValidationError, match="maintenance_margin"):
            self._spec(initial_margin=1_000.0, maintenance_margin=2_000.0)

    def test_rejects_unknown_field(self):
        with pytest.raises(ValidationError):
            self._spec(slippage=0.0)


class TestInstrumentTable:
    def test_tick_value_matches_exchange_published_values(self):
        from rsl.data.instruments import INSTRUMENTS

        expected = {
            "ES.v.0": 12.50, "NQ.v.0": 5.00, "YM.v.0": 5.00, "FDAX.v.0": 12.50,
            "GC.v.0": 10.00, "CL.v.0": 10.00, "6E.v.0": 6.25, "6B.v.0": 6.25,
            "6J.v.0": 6.25, "6A.v.0": 5.00,
        }
        for symbol, tick_value in expected.items():
            spec = INSTRUMENTS[symbol]
            assert spec.multiplier * spec.tick_size == pytest.approx(tick_value), symbol

    def test_lookup_by_root_and_symbol(self):
        from rsl.data.instruments import get_instrument

        assert get_instrument("ES") is get_instrument("ES.v.0")

    def test_unknown_instrument_raises(self):
        from rsl.data.instruments import get_instrument
        from rsl.errors import RegistryError

        with pytest.raises(RegistryError, match="inconnu"):
            get_instrument("ZZZ")
