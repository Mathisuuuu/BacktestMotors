"""Comptabilite : prix moyen, realisation, retournements, invariante.

L'invariante n'est pas verifiee comme une tautologie. Le portefeuille maintient
l'equity par deux chemins qui ne partagent aucun calcul - `cash + non realise`
d'un cote, attribution de P&L barre par barre de l'autre - et les compare.
"""

from __future__ import annotations

import pytest

from rsl.engine.orders import Fill, Side
from rsl.engine.portfolio import AccountingError, EquityRecorder, Portfolio, Position
from rsl.errors import ConfigurationError

SYMBOL = "TEST.v.0"
CASH = 100_000.0


def make_fill(side: Side, quantity: int, price: float, *, fee: float = 0.0, bar: int = 0) -> Fill:
    return Fill(
        order_id=0,
        symbol=SYMBOL,
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
        slippage_cost=0.0,
        ts_ns=bar * 60_000_000_000,
        bar_index=bar,
    )


@pytest.fixture
def portfolio(spec) -> Portfolio:
    return Portfolio(CASH, {SYMBOL: spec})


def step(portfolio: Portfolio, mark: float, *fills: Fill) -> float:
    """Une barre complete : ouverture, executions, marquage + invariante."""
    portfolio.begin_bar()
    for f in fills:
        portfolio.apply_fill(f)
    return portfolio.end_bar({SYMBOL: mark})


class TestConstruction:
    def test_non_positive_cash_refused(self, spec):
        with pytest.raises(ConfigurationError, match="initial_cash"):
            Portfolio(0.0, {SYMBOL: spec})

    def test_empty_specs_refused(self):
        with pytest.raises(ConfigurationError, match="specification"):
            Portfolio(CASH, {})

    def test_starts_flat_and_full_of_cash(self, portfolio):
        assert portfolio.cash == CASH
        assert portfolio.quantity_of(SYMBOL) == 0
        assert portfolio.equity({SYMBOL: 100.0}) == CASH

    def test_unknown_symbol_refused(self, portfolio):
        with pytest.raises(ConfigurationError, match="absent du portefeuille"):
            portfolio.spec_of("NOPE")


class TestBarProtocol:
    def test_apply_fill_outside_a_bar_is_refused(self, portfolio):
        with pytest.raises(AccountingError, match="begin_bar"):
            portfolio.apply_fill(make_fill(Side.BUY, 1, 100.0))

    def test_end_bar_without_begin_is_refused(self, portfolio):
        with pytest.raises(AccountingError, match="begin_bar"):
            portfolio.end_bar({SYMBOL: 100.0})


class TestLongPosition:
    def test_open_then_mark(self, portfolio, spec):
        equity = step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        assert portfolio.quantity_of(SYMBOL) == 1
        assert equity == pytest.approx(CASH)
        assert portfolio.cash == pytest.approx(CASH)

        equity = step(portfolio, 102.0)
        assert equity == pytest.approx(CASH + 1 * spec.multiplier * 2.0)

    def test_unrealised_does_not_touch_cash(self, portfolio):
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        step(portfolio, 130.0)
        assert portfolio.cash == pytest.approx(CASH)

    def test_closing_realises_into_cash(self, portfolio, spec):
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        step(portfolio, 110.0)
        equity = step(portfolio, 110.0, make_fill(Side.SELL, 1, 110.0, bar=2))
        expected = CASH + spec.multiplier * 10.0
        assert portfolio.cash == pytest.approx(expected)
        assert equity == pytest.approx(expected)
        assert portfolio.quantity_of(SYMBOL) == 0

    def test_average_entry_is_weighted(self, portfolio):
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        step(portfolio, 120.0, make_fill(Side.BUY, 3, 120.0, bar=1))
        assert portfolio.positions[SYMBOL].avg_entry == pytest.approx((100.0 + 3 * 120.0) / 4)

    def test_partial_close_realises_at_the_average(self, portfolio, spec):
        step(portfolio, 100.0, make_fill(Side.BUY, 4, 100.0))
        equity = step(portfolio, 110.0, make_fill(Side.SELL, 1, 110.0, bar=1))
        assert portfolio.quantity_of(SYMBOL) == 3
        assert portfolio.cash == pytest.approx(CASH + spec.multiplier * 10.0)
        assert equity == pytest.approx(CASH + 4 * spec.multiplier * 10.0)


class TestShortPosition:
    def test_short_gains_when_price_falls(self, portfolio, spec):
        step(portfolio, 100.0, make_fill(Side.SELL, 2, 100.0))
        equity = step(portfolio, 90.0)
        assert portfolio.quantity_of(SYMBOL) == -2
        assert equity == pytest.approx(CASH + 2 * spec.multiplier * 10.0)

    def test_short_realises_correctly(self, portfolio, spec):
        step(portfolio, 100.0, make_fill(Side.SELL, 2, 100.0))
        step(portfolio, 90.0, make_fill(Side.BUY, 2, 90.0, bar=1))
        assert portfolio.cash == pytest.approx(CASH + 2 * spec.multiplier * 10.0)
        assert portfolio.quantity_of(SYMBOL) == 0


class TestReversal:
    def test_flip_closes_then_reopens_at_the_fill_price(self, portfolio, spec):
        step(portfolio, 100.0, make_fill(Side.BUY, 2, 100.0))
        equity = step(portfolio, 110.0, make_fill(Side.SELL, 5, 110.0, bar=1))
        assert portfolio.quantity_of(SYMBOL) == -3
        assert portfolio.positions[SYMBOL].avg_entry == pytest.approx(110.0)
        assert portfolio.cash == pytest.approx(CASH + 2 * spec.multiplier * 10.0)
        assert equity == pytest.approx(CASH + 2 * spec.multiplier * 10.0)

    def test_flip_closes_the_trade_and_opens_a_new_one(self, portfolio):
        step(portfolio, 100.0, make_fill(Side.BUY, 2, 100.0))
        step(portfolio, 110.0, make_fill(Side.SELL, 5, 110.0, bar=1))
        assert len(portfolio.closed_trades) == 1
        assert portfolio.closed_trades[0].direction == 1
        step(portfolio, 105.0, make_fill(Side.BUY, 3, 105.0, bar=2))
        assert len(portfolio.closed_trades) == 2
        assert portfolio.closed_trades[1].direction == -1


class TestFeesAndStats:
    def test_fees_leave_cash_immediately(self, portfolio):
        equity = step(portfolio, 100.0, make_fill(Side.BUY, 2, 100.0, fee=4.0))
        assert portfolio.cash == pytest.approx(CASH - 4.0)
        assert equity == pytest.approx(CASH - 4.0)

    def test_stats_accumulate(self, portfolio, spec):
        step(portfolio, 100.0, make_fill(Side.BUY, 2, 100.0, fee=4.0))
        step(portfolio, 100.0, make_fill(Side.SELL, 2, 100.0, fee=4.0, bar=1))
        assert portfolio.stats.n_fills == 2
        assert portfolio.stats.fees_paid == pytest.approx(8.0)
        assert portfolio.stats.contracts_traded == 4
        assert portfolio.stats.turnover_notional == pytest.approx(4 * spec.multiplier * 100.0)

    def test_margin_is_tracked(self, portfolio, spec):
        step(portfolio, 100.0, make_fill(Side.BUY, 3, 100.0))
        assert portfolio.margin_required() == pytest.approx(3 * spec.initial_margin)
        assert portfolio.stats.max_margin_used == pytest.approx(3 * spec.initial_margin)
        step(portfolio, 100.0, make_fill(Side.SELL, 3, 100.0, bar=1))
        assert portfolio.margin_required() == pytest.approx(0.0)
        assert portfolio.stats.max_margin_used == pytest.approx(3 * spec.initial_margin)


class TestClosedTrades:
    def test_round_trip_is_recorded(self, portfolio, spec):
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0, fee=2.0))
        step(portfolio, 110.0, make_fill(Side.SELL, 1, 110.0, fee=2.0, bar=1))
        assert len(portfolio.closed_trades) == 1
        trade = portfolio.closed_trades[0]
        assert trade.direction == 1
        assert trade.opened_bar == 0
        assert trade.closed_bar == 1
        assert trade.gross_pnl == pytest.approx(spec.multiplier * 10.0)
        assert trade.fees == pytest.approx(4.0)
        assert trade.net_pnl == pytest.approx(spec.multiplier * 10.0 - 4.0)
        assert trade.is_win

    def test_a_losing_trade_is_not_a_win(self, portfolio):
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        step(portfolio, 95.0, make_fill(Side.SELL, 1, 95.0, bar=1))
        assert not portfolio.closed_trades[0].is_win

    def test_an_open_position_is_not_a_closed_trade(self, portfolio):
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        step(portfolio, 110.0)
        assert portfolio.closed_trades == []

    def test_pyramided_trade_records_its_peak_size(self, portfolio):
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        step(portfolio, 100.0, make_fill(Side.BUY, 4, 100.0, bar=1))
        step(portfolio, 100.0, make_fill(Side.SELL, 5, 100.0, bar=2))
        assert portfolio.closed_trades[0].max_quantity == 5


class TestInvariant:
    """Test exige n° 5, vu depuis le portefeuille."""

    def test_both_paths_agree_over_a_long_sequence(self, portfolio):
        import random

        rng = random.Random(1234)
        quantity = 0
        for i in range(300):
            portfolio.begin_bar()
            if rng.random() < 0.3:
                side = Side.BUY if rng.random() < 0.5 else Side.SELL
                size = rng.randint(1, 3)
                if not (side is Side.SELL and quantity - size < -5):
                    portfolio.apply_fill(
                        make_fill(side, size, 100.0 + rng.gauss(0, 5), fee=2.0 * size, bar=i)
                    )
                    quantity += side.sign * size
            mark = 100.0 + rng.gauss(0, 5)
            equity = portfolio.end_bar({SYMBOL: mark})
            assert equity == pytest.approx(portfolio.equity_incremental, rel=1e-12)

    def test_a_tampered_cash_balance_is_caught(self, portfolio):
        """Preuve que la verification n'est pas une tautologie."""
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        portfolio.cash += 1.0
        portfolio.begin_bar()
        with pytest.raises(AccountingError, match="invariante comptable violee"):
            portfolio.end_bar({SYMBOL: 100.0})

    def test_a_position_changed_without_a_fill_is_caught(self, portfolio):
        """Le bug que la verification vise : une position qui bouge sans fill.

        La quantite est modifiee APRES `begin_bar`, donc apres la photographie
        des positions : le chemin incremental attribue le P&L d'un contrat, le
        chemin d'etat en voit cinq, et les deux divergent.
        """
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        portfolio.begin_bar()
        portfolio.positions[SYMBOL].quantity = 5
        with pytest.raises(AccountingError, match="invariante comptable violee"):
            portfolio.end_bar({SYMBOL: 105.0})

    def test_the_check_covers_attribution_not_arbitrary_tampering(self, portfolio):
        """Limite assumee, documentee dans `portfolio.py`.

        Une position modifiee ENTRE deux barres est rephotographiee par
        `begin_bar` : les deux chemins repartent du meme etat et concordent. La
        verification porte sur l'attribution de P&L a l'interieur d'une barre,
        pas sur la detection d'une corruption de memoire.
        """
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        portfolio.positions[SYMBOL].quantity = 5
        portfolio.begin_bar()
        portfolio.end_bar({SYMBOL: 105.0})

    def test_check_can_be_disabled(self, portfolio):
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        portfolio.cash += 1.0
        portfolio.begin_bar()
        portfolio.end_bar({SYMBOL: 100.0}, check=False)

    def test_a_missing_mark_keeps_the_last_known_one(self, portfolio, spec):
        """Une position existe meme quand son marche est ferme."""
        step(portfolio, 100.0, make_fill(Side.BUY, 1, 100.0))
        step(portfolio, 110.0)
        portfolio.begin_bar()
        equity = portfolio.end_bar({})
        assert equity == pytest.approx(CASH + spec.multiplier * 10.0)


class TestReset:
    def test_reset_restores_the_initial_state(self, portfolio):
        step(portfolio, 100.0, make_fill(Side.BUY, 2, 100.0, fee=4.0))
        step(portfolio, 120.0)
        portfolio.reset()
        assert portfolio.cash == CASH
        assert portfolio.quantity_of(SYMBOL) == 0
        assert portfolio.equity_incremental == CASH
        assert portfolio.closed_trades == []
        assert portfolio.stats.n_fills == 0


class TestPositionHelper:
    def test_unrealised_of_a_flat_position_is_zero(self, spec):
        assert Position(SYMBOL).unrealized(spec, 100.0) == 0.0

    def test_margin_uses_the_absolute_quantity(self, spec):
        assert Position(SYMBOL, -3, 100.0).margin(spec) == pytest.approx(3 * spec.initial_margin)


class TestEquityRecorder:
    def test_records_and_clears(self):
        recorder = EquityRecorder()
        recorder.record(1, 100.0, 90.0, 1)
        recorder.record(2, 101.0, 90.0, 1)
        assert len(recorder) == 2
        assert recorder.equity == [100.0, 101.0]
        recorder.clear()
        assert len(recorder) == 0
