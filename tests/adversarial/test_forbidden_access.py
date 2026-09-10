"""Test exige n° 2 : acces interdit.

Toute tentative de lire une barre `> t` depuis un `Context` doit lever une
exception. Ce fichier essaie activement de contourner le contrat, y compris par
les chemins detournes que `numpy` offre gratuitement.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures import synthetic
from rsl.data.feed import BarContext, BarFeed
from rsl.data.schema import ALL_FIELDS, BarStore, Field
from rsl.errors import InsufficientHistoryError, LookAheadError

pytestmark = pytest.mark.adversarial


def advanced(store: BarStore, n: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(n):
        ctx._advance()
    return ctx


class TestNegativeLagIsLookAhead:
    @pytest.mark.parametrize("lag", [-1, -2, -100])
    @pytest.mark.parametrize("field", list(ALL_FIELDS))
    def test_value_with_negative_lag_raises(self, ramp_store: BarStore, lag, field):
        ctx = advanced(ramp_store, 50)
        with pytest.raises(LookAheadError, match="lag negatif"):
            ctx.value(field, lag=lag)

    def test_bar_at_with_negative_lag_raises(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 50)
        with pytest.raises(LookAheadError):
            ctx.bar_at(-1)

    @pytest.mark.parametrize("lag", [-1, -50])
    def test_shifted_view_cannot_look_forward(self, ramp_store: BarStore, lag):
        ctx = advanced(ramp_store, 50)
        with pytest.raises(LookAheadError):
            ctx.shifted(lag)

    def test_shifted_view_stays_in_the_past(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 50)
        past = ctx.shifted(10)
        assert past.n_bars_seen == ctx.n_bars_seen - 10
        assert past.value(Field.CLOSE) == pytest.approx(ctx.value(Field.CLOSE, lag=10))
        with pytest.raises(InsufficientHistoryError):
            past.history(past.n_bars_seen + 1)

    def test_look_ahead_error_is_not_swallowed_as_value_error(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 10)
        with pytest.raises(LookAheadError):
            ctx.value(Field.CLOSE, lag=-1)

    @given(lag=st.integers(min_value=-10_000, max_value=-1), cursor=st.integers(1, 400))
    @settings(max_examples=200, deadline=None)
    def test_property_every_negative_lag_raises(self, lag, cursor):
        store = synthetic.make_store(synthetic.ramp(500), symbol="P.v.0")
        ctx = advanced(store, cursor)
        with pytest.raises(LookAheadError):
            ctx.value(Field.CLOSE, lag=lag)


class TestMissingHistoryIsNotNaN:
    """Une fenetre trop longue leve, elle ne renvoie pas de `NaN`.

    Un `NaN` traverse une moyenne puis une comparaison, et toute comparaison
    avec `NaN` vaut `False` : le backtest tourne, ne signale rien, et se trompe.
    """

    def test_window_too_long_raises(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 5)
        with pytest.raises(InsufficientHistoryError):
            ctx.history(6)

    def test_lag_beyond_history_raises(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 5)
        with pytest.raises(InsufficientHistoryError):
            ctx.value(Field.CLOSE, lag=5)

    def test_no_nan_is_ever_returned(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 3)
        for n in (1, 2, 3):
            assert np.isfinite(ctx.history(n).close).all()
        with pytest.raises(InsufficientHistoryError):
            ctx.history(4)

    @given(cursor=st.integers(1, 200), extra=st.integers(1, 500))
    @settings(max_examples=200, deadline=None)
    def test_property_window_exceeding_history_always_raises(self, cursor, extra):
        store = synthetic.make_store(synthetic.ramp(500), symbol="P.v.0")
        ctx = advanced(store, cursor)
        with pytest.raises(InsufficientHistoryError):
            ctx.history(cursor + extra)


class TestNoFutureThroughReturnedArrays:
    """`numpy` offre deux portes derobees : `.base` et l'ecriture en place."""

    def test_history_arrays_own_their_data(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 100)
        window = ctx.history(10)
        for array in (window.open, window.high, window.low, window.close, window.volume):
            assert array.base is None, "une vue exposerait le tableau complet via .base"
        assert window.ts_close.base is None

    def test_values_array_owns_its_data(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 100)
        assert ctx.values(Field.CLOSE, 10).base is None

    def test_returned_arrays_are_read_only(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 100)
        window = ctx.history(10)
        with pytest.raises(ValueError, match="read-only"):
            window.close[0] = 0.0
        with pytest.raises(ValueError, match="read-only"):
            ctx.values(Field.CLOSE, 10)[0] = 0.0

    def test_window_cannot_reach_beyond_the_cursor(self, ramp_store: BarStore):
        """Meme en indexant hors bornes, la fenetre ne contient que le passe."""
        ctx = advanced(ramp_store, 100)
        window = ctx.history(10)
        assert float(window.close.max()) <= float(ramp_store.close[99])
        with pytest.raises(IndexError):
            _ = window.close[10]

    def test_mutating_a_window_cannot_corrupt_another_context(self, ramp_store: BarStore):
        a = advanced(ramp_store, 50)
        b = advanced(ramp_store, 50)
        window = a.history(5)
        with pytest.raises(ValueError, match="read-only"):
            window.close[:] = 0.0
        assert b.value(Field.CLOSE) == pytest.approx(float(ramp_store.close[49]))


class TestNoSampleLengthLeak:
    """Regle 4 : une strategie ne doit pas pouvoir deviner la fin de l'echantillon."""

    FORBIDDEN = ("__len__", "total_bars", "n_bars", "end_date", "last_ts", "store", "df", "raw")

    def test_position_state_describes_the_past_not_the_future(self, ramp_store: BarStore):
        """`position` a rejoint la surface publique : elle decrit ce que la
        strategie a FAIT, jamais ce que le marche fera."""
        ctx = advanced(ramp_store, 10)
        assert ctx.position.is_flat
        assert ctx.position.bars_held == 0
        assert ctx.position.entry_price == 0.0

    @pytest.mark.parametrize("attribute", FORBIDDEN)
    def test_context_does_not_expose_the_sample_length(self, ramp_store: BarStore, attribute):
        ctx = advanced(ramp_store, 10)
        assert not hasattr(ctx, attribute), f"'{attribute}' fuite la taille de l'echantillon"

    def test_public_surface_is_the_declared_one(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 10)
        public = {name for name in dir(ctx) if not name.startswith("_")}
        assert public == {
            "bar", "bar_at", "granularity", "history", "n_bars_seen", "peer", "peers",
            "position", "shifted", "symbol", "ts", "ts_event", "value", "values",
        }

    def test_n_bars_seen_never_anticipates(self, ramp_store: BarStore):
        for i, ctx in enumerate(BarFeed(ramp_store, stop=40)):
            assert ctx.n_bars_seen == i + 1


class TestFeedCursorMonotonic:
    def test_cursor_only_moves_forward(self, walk_store: BarStore):
        previous = None
        for ctx in BarFeed(walk_store, stop=100):
            current = ctx.ts
            if previous is not None:
                assert current > previous
            previous = current
