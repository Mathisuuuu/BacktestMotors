from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext, BarFeed, Context, MultiContext, PanelFeed
from rsl.data.loader import build_panel
from rsl.data.schema import AlignPolicy, BarStore, Field, Granularity
from rsl.errors import ConfigurationError, InsufficientHistoryError, SymbolNotAvailableError


class TestBarContextBasics:
    def test_satisfies_the_protocol(self, ramp_store: BarStore):
        # `isinstance` sur un Protocol evalue les proprietes : il faut donc une
        # barre close, sinon `ts` leve avant meme la verification.
        ctx = BarContext(ramp_store)
        ctx._advance()
        assert isinstance(ctx, Context)

    def test_cursor_starts_before_the_first_bar(self, ramp_store: BarStore):
        ctx = BarContext(ramp_store)
        assert ctx.n_bars_seen == 0
        with pytest.raises(InsufficientHistoryError):
            _ = ctx.bar

    def test_value_tracks_the_cursor(self, ramp_store: BarStore):
        ctx = BarContext(ramp_store)
        for i in range(10):
            ctx._advance()
            assert ctx.value(Field.CLOSE) == pytest.approx(float(ramp_store.close[i]))
            assert ctx.n_bars_seen == i + 1

    def test_lag_reads_the_past(self, ramp_store: BarStore):
        ctx = BarContext(ramp_store)
        for _ in range(20):
            ctx._advance()
        assert ctx.value(Field.CLOSE, lag=0) == pytest.approx(float(ramp_store.close[19]))
        assert ctx.value(Field.CLOSE, lag=5) == pytest.approx(float(ramp_store.close[14]))

    def test_ts_is_the_close_not_the_open(self, ramp_store: BarStore):
        ctx = BarContext(ramp_store)
        ctx._advance()
        assert ctx.ts - ctx.ts_event == ramp_store.granularity.delta

    def test_bar_at_matches_store(self, sine_store: BarStore):
        ctx = BarContext(sine_store)
        for _ in range(30):
            ctx._advance()
        assert ctx.bar_at(3).close == pytest.approx(float(sine_store.close[26]))


class TestHistory:
    def test_window_content_and_order(self, ramp_store: BarStore):
        ctx = BarContext(ramp_store)
        for _ in range(50):
            ctx._advance()
        window = ctx.history(10)
        assert len(window) == 10
        assert np.allclose(window.close, ramp_store.close[40:50])
        assert window.close[-1] == pytest.approx(float(ramp_store.close[49]))

    def test_values_matches_history(self, walk_store: BarStore):
        ctx = BarContext(walk_store)
        for _ in range(80):
            ctx._advance()
        assert np.array_equal(ctx.values(Field.HIGH, 12), ctx.history(12).high)

    def test_full_history_allowed(self, ramp_store: BarStore):
        ctx = BarContext(ramp_store)
        for _ in range(7):
            ctx._advance()
        assert len(ctx.history(7)) == 7

    def test_window_beyond_history_raises(self, ramp_store: BarStore):
        ctx = BarContext(ramp_store)
        for _ in range(7):
            ctx._advance()
        with pytest.raises(InsufficientHistoryError, match="8 barres demandee"):
            ctx.history(8)

    @pytest.mark.parametrize("n", [0, -1])
    def test_non_positive_window_refused(self, ramp_store: BarStore, n):
        ctx = BarContext(ramp_store)
        ctx._advance()
        with pytest.raises(ValueError, match=">= 1"):
            ctx.history(n)

    def test_window_field_accessor(self, ramp_store: BarStore):
        ctx = BarContext(ramp_store)
        for _ in range(5):
            ctx._advance()
        window = ctx.history(5)
        assert np.array_equal(window.field(Field.LOW), window.low)


class TestBarFeed:
    def test_yields_every_bar(self, ramp_store: BarStore):
        seen = [ctx.value(Field.CLOSE) for ctx in BarFeed(ramp_store)]
        assert len(seen) == ramp_store.n_bars
        assert np.allclose(seen, ramp_store.close)

    def test_warmup_hides_the_first_bars_but_keeps_them_in_history(self, ramp_store: BarStore):
        feed = BarFeed(ramp_store, warmup_bars=20)
        first = next(iter(feed))
        assert first.n_bars_seen == 21
        assert len(first.history(21)) == 21
        assert feed.n_tradable_bars == ramp_store.n_bars - 20

    def test_stop_truncates_the_run(self, ramp_store: BarStore):
        assert len(list(BarFeed(ramp_store, stop=30))) == 30

    def test_stop_and_warmup_compose(self, ramp_store: BarStore):
        assert len(list(BarFeed(ramp_store, warmup_bars=10, stop=30))) == 20

    @pytest.mark.parametrize("kwargs", [{"warmup_bars": -1}, {"stop": -1}, {"stop": 10_000}])
    def test_invalid_bounds_refused(self, ramp_store: BarStore, kwargs):
        with pytest.raises(ConfigurationError):
            BarFeed(ramp_store, **kwargs)

    def test_feed_is_reiterable_from_scratch(self, ramp_store: BarStore):
        feed = BarFeed(ramp_store, stop=5)
        first = [c.value(Field.CLOSE) for c in feed]
        second = [c.value(Field.CLOSE) for c in feed]
        assert first == second


class TestMultiContext:
    def _panel(self, **kwargs):
        stores = {
            "A": synthetic.make_store(synthetic.ramp(100, 100.0, 1.0), symbol="A"),
            "B": synthetic.make_store(synthetic.ramp(60, 50.0, 0.5), symbol="B"),
        }
        return build_panel(stores, **kwargs)

    def test_present_symbols_shrink_when_an_instrument_stops(self):
        panel = self._panel()
        ctx = MultiContext(panel)
        ctx._seek_row(10)
        assert ctx.symbols == ("A", "B")
        ctx._seek_row(70)
        assert ctx.symbols == ("A",)

    def test_absent_symbol_raises_instead_of_returning_stale_price(self):
        ctx = MultiContext(self._panel())
        ctx._seek_row(70)
        with pytest.raises(SymbolNotAvailableError, match="ne cote pas"):
            _ = ctx["B"]

    def test_unknown_symbol_raises(self):
        ctx = MultiContext(self._panel())
        ctx._seek_row(0)
        with pytest.raises(SymbolNotAvailableError, match="ne fait pas partie"):
            _ = ctx["ZZ"]

    def test_contains_follows_presence(self):
        ctx = MultiContext(self._panel())
        ctx._seek_row(70)
        assert "A" in ctx
        assert "B" not in ctx

    def test_sub_context_is_positioned_on_its_own_bar(self):
        ctx = MultiContext(self._panel())
        ctx._seek_row(42)
        assert ctx["B"].value(Field.CLOSE) == pytest.approx(50.0 + 0.5 * 42)
        assert ctx["A"].value(Field.CLOSE) == pytest.approx(100.0 + 42)

    def test_ffill_exposes_the_bar_and_flags_it_stale(self):
        panel = self._panel(align_policy=AlignPolicy.FFILL, max_ffill_bars=3)
        ctx = MultiContext(panel)
        ctx._seek_row(61)
        assert "B" in ctx
        assert ctx.is_stale("B")
        assert ctx["B"].value(Field.CLOSE) == pytest.approx(50.0 + 0.5 * 59)

    def test_ts_is_the_panel_close(self):
        panel = self._panel()
        ctx = MultiContext(panel)
        ctx._seek_row(0)
        assert ctx.ts == synthetic.EPOCH + timedelta(minutes=1)


class TestPanelFeed:
    def test_iterates_every_row(self):
        stores = {
            "A": synthetic.make_store(synthetic.ramp(30), symbol="A"),
            "B": synthetic.make_store(synthetic.constant(20), symbol="B"),
        }
        panel = build_panel(stores)
        rows = [ctx.symbols for ctx in PanelFeed(panel)]
        assert len(rows) == 30
        assert rows[0] == ("A", "B")
        assert rows[-1] == ("A",)

    def test_stop_truncates(self):
        panel = build_panel({"A": synthetic.make_store(synthetic.ramp(30), symbol="A")})
        assert len(list(PanelFeed(panel, stop=7))) == 7

    def test_invalid_bounds_refused(self):
        panel = build_panel({"A": synthetic.make_store(synthetic.ramp(30), symbol="A")})
        with pytest.raises(ConfigurationError):
            PanelFeed(panel, warmup_rows=-1)


class TestGranularityIndependence:
    def test_context_works_at_any_granularity(self):
        store = synthetic.make_store(
            synthetic.ramp(50), granularity=Granularity.minutes(60)
        )
        ctx = BarContext(store)
        ctx._advance()
        assert ctx.ts - ctx.ts_event == timedelta(hours=1)
