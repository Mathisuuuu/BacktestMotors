"""Metriques de performance : briques pures et calcul complet.

Les briques sont verifiees contre des valeurs calculees a la main sur des
courbes de cinq points. Le calcul complet est verifie contre des formules
fermees, jamais contre une reimplementation du meme calcul.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

import numpy as np
import pytest

from fixtures import synthetic
from rsl.engine.execution import ExecutionConfig, ZeroFee, ZeroSlippage
from rsl.engine.portfolio import EquityRecorder, Portfolio
from rsl.engine.runner import RunConfig, SingleAssetRunner
from rsl.errors import ConfigurationError
from rsl.metrics.performance import (
    NS_PER_DAY,
    compute_performance,
    drawdown_stats,
    kurtosis,
    simple_returns,
    skewness,
    to_daily,
)
from rsl.orders import Fill, Side
from rsl.strategies.handwritten import BuyAndHold
from rsl.strategies.rules import FlatStrategy

SYMBOL = "TEST.v.0"
CASH = 100_000.0
EPOCH = datetime(2021, 1, 1, tzinfo=UTC)


def days_ns(n: int, *, start: datetime = EPOCH) -> list[int]:
    base = int(start.timestamp() * 1_000_000_000)
    return [base + i * NS_PER_DAY for i in range(n)]


@dataclass
class FakeRun:
    """Un resultat de run fabrique, pour piloter la courbe exactement."""

    equity: EquityRecorder
    portfolio: Portfolio
    config: RunConfig


def fake_run(
    equity_values: list[float],
    spec,
    *,
    ts: list[int] | None = None,
    exposure: list[int] | None = None,
    initial: float = CASH,
) -> FakeRun:
    recorder = EquityRecorder()
    stamps = ts if ts is not None else days_ns(len(equity_values))
    gross = exposure if exposure is not None else [1] * len(equity_values)
    for stamp, value, contracts in zip(stamps, equity_values, gross, strict=True):
        recorder.record(stamp, value, value, contracts)
    return FakeRun(
        equity=recorder,
        portfolio=Portfolio(initial, {SYMBOL: spec}),
        config=RunConfig(initial, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
    )


# ---------------------------------------------------------------------------
# Briques pures
# ---------------------------------------------------------------------------


class TestToDaily:
    def test_keeps_the_last_value_of_each_day(self):
        base = int(EPOCH.timestamp() * 1_000_000_000)
        minute = 60 * 1_000_000_000
        ts = [base, base + minute, base + NS_PER_DAY, base + NS_PER_DAY + minute]
        values = [100.0, 101.0, 102.0, 103.0]
        out_ts, out_values = to_daily(ts, values)
        assert list(out_values) == [101.0, 103.0]
        assert list(out_ts) == [ts[1], ts[3]]

    def test_a_daily_curve_is_unchanged(self):
        ts = days_ns(5)
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        out_ts, out_values = to_daily(ts, values)
        assert list(out_values) == values
        assert list(out_ts) == ts

    def test_a_monthly_curve_is_unchanged(self):
        """Une courbe plus large que la journee traverse l'operation intacte."""
        ts = [int(datetime(2021, m, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
              for m in range(1, 7)]
        values = [float(i) for i in range(6)]
        _, out_values = to_daily(ts, values)
        assert list(out_values) == values

    def test_empty_curve(self):
        out_ts, out_values = to_daily([], [])
        assert out_ts.size == 0 and out_values.size == 0

    def test_single_point(self):
        _, out_values = to_daily([0], [42.0])
        assert list(out_values) == [42.0]


class TestSimpleReturns:
    def test_hand_computed(self):
        got = simple_returns(np.array([100.0, 110.0, 99.0]))
        assert got == pytest.approx([0.1, -0.1])

    def test_needs_two_points(self):
        assert simple_returns(np.array([100.0])).size == 0

    def test_a_non_positive_denominator_is_skipped(self):
        """Une equity nulle n'a pas de rendement : on saute plutot qu'on invente."""
        got = simple_returns(np.array([100.0, 0.0, 50.0]))
        assert got == pytest.approx([-1.0])


class TestDrawdown:
    CURVE: ClassVar[list[float]] = [100.0, 120.0, 90.0, 110.0, 130.0]

    def test_hand_computed_case(self):
        stats = drawdown_stats(np.array(days_ns(5)), np.array(self.CURVE))
        assert stats is not None
        assert stats.max_drawdown == pytest.approx(90.0 / 120.0 - 1.0)
        assert stats.peak_index == 1
        assert stats.trough_index == 2
        assert stats.recovery_index == 4
        assert stats.recovered

    def test_underwater_duration(self):
        stats = drawdown_stats(np.array(days_ns(5)), np.array(self.CURVE))
        assert stats is not None
        # Du sommet (index 1) a sa recuperation (index 4) : trois periodes,
        # trois jours. Les deux grandeurs mesurent la meme chose.
        assert stats.longest_underwater_periods == 3
        assert stats.longest_underwater_days == pytest.approx(3.0)

    def test_a_never_recovered_drawdown(self):
        stats = drawdown_stats(np.array(days_ns(4)), np.array([100.0, 120.0, 90.0, 95.0]))
        assert stats is not None
        assert stats.recovery_index is None
        assert not stats.recovered

    def test_a_monotonic_curve_has_no_drawdown(self):
        stats = drawdown_stats(np.array(days_ns(5)), np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
        assert stats is not None
        assert stats.max_drawdown == pytest.approx(0.0)
        assert stats.longest_underwater_periods == 0

    def test_too_short_returns_none(self):
        assert drawdown_stats(np.array([0]), np.array([1.0])) is None


class TestMoments:
    def test_a_symmetric_sample_has_no_skew(self):
        assert skewness(np.array([-2.0, -1.0, 0.0, 1.0, 2.0])) == pytest.approx(0.0)

    def test_a_right_tail_gives_positive_skew(self):
        assert skewness(np.array([-1.0, -1.0, -1.0, 5.0])) > 0.0

    def test_kurtosis_is_not_excess(self):
        """Trois pour une gaussienne, pas zero."""
        rng = np.random.default_rng(4)
        assert kurtosis(rng.normal(size=200_000)) == pytest.approx(3.0, abs=0.05)

    def test_constant_sample_is_neutral(self):
        constant = np.full(10, 5.0)
        assert skewness(constant) == 0.0
        assert kurtosis(constant) == 3.0

    def test_short_samples_are_neutral(self):
        assert skewness(np.array([1.0, 2.0])) == 0.0
        assert kurtosis(np.array([1.0, 2.0, 3.0])) == 3.0


# ---------------------------------------------------------------------------
# Calcul complet
# ---------------------------------------------------------------------------


class TestSampleDescription:
    def test_periods_per_year_is_measured(self, spec):
        """252 points quotidiens sur un an -> environ 252 periodes/an."""
        run = fake_run([CASH + i for i in range(253)], spec)
        metrics = compute_performance(run)
        assert metrics.span_years == pytest.approx(252 / 365.2425, rel=1e-9)
        assert metrics.periods_per_year == pytest.approx(253 * 365.2425 / 252, rel=1e-9)
        assert metrics.annualisation_factor == pytest.approx(
            math.sqrt(metrics.periods_per_year)
        )

    def test_a_monthly_curve_annualises_on_twelve(self, spec):
        ts = [int(datetime(2015 + i // 12, i % 12 + 1, 1, tzinfo=UTC).timestamp() * 1e9)
              for i in range(61)]
        run = fake_run([CASH * (1.01**i) for i in range(61)], spec, ts=ts)
        metrics = compute_performance(run)
        assert metrics.periods_per_year == pytest.approx(12.2, abs=0.3)

    def test_too_few_periods_per_year_warns(self, spec):
        ts = [int(datetime(2015 + i, 1, 1, tzinfo=UTC).timestamp() * 1e9) for i in range(6)]
        run = fake_run([CASH * (1.05**i) for i in range(6)], spec, ts=ts)
        metrics = compute_performance(run)
        assert any("periode(s) par an" in w for w in metrics.warnings)

    def test_an_empty_curve_is_refused(self, spec):
        run = fake_run([], spec)
        with pytest.raises(ConfigurationError, match="vide"):
            compute_performance(run)


class TestReturnMetrics:
    def test_total_return(self, spec):
        metrics = compute_performance(fake_run([CASH, CASH * 1.5], spec))
        assert metrics.total_return == pytest.approx(0.5)

    def test_cagr_of_a_doubling_over_two_years(self, spec):
        two_years = 731
        run = fake_run(
            [CASH, CASH * 2.0], spec, ts=[days_ns(1)[0], days_ns(1)[0] + two_years * NS_PER_DAY]
        )
        metrics = compute_performance(run)
        expected_years = two_years / 365.2425
        assert metrics.cagr == pytest.approx(2.0 ** (1.0 / expected_years) - 1.0)

    def test_cagr_is_undefined_when_the_account_is_wiped_out(self, spec):
        metrics = compute_performance(fake_run([CASH, CASH / 2, 0.0], spec))
        assert metrics.cagr is None
        assert metrics.is_ruined
        assert any("zero" in w for w in metrics.warnings)


class TestRatios:
    def _run_with_returns(self, returns: list[float], spec) -> FakeRun:
        equity = [CASH]
        for r in returns:
            equity.append(equity[-1] * (1.0 + r))
        return fake_run(equity, spec)

    def test_sharpe_matches_the_closed_form(self, spec):
        rng = np.random.default_rng(1234)
        returns = list(rng.normal(0.0005, 0.01, size=500))
        run = self._run_with_returns(returns, spec)
        metrics = compute_performance(run)

        # Formule fermee, recalculee depuis la courbe telle que les metriques
        # la voient - pas depuis les rendements d'entree.
        realised = simple_returns(np.array(metrics_curve(run)))
        expected = float(np.mean(realised)) / float(np.std(realised, ddof=1))
        assert metrics.sharpe_per_period == pytest.approx(expected)
        assert metrics.sharpe == pytest.approx(expected * metrics.annualisation_factor)

    def test_a_constant_equity_has_no_sharpe(self, spec):
        metrics = compute_performance(fake_run([CASH] * 100, spec))
        assert metrics.sharpe is None
        assert metrics.volatility_annual == pytest.approx(0.0)
        assert metrics.total_return == 0.0
        assert any("bruit de calcul" in w for w in metrics.warnings)

    def test_sortino_uses_the_full_denominator(self, spec):
        """L'ecart-type a la baisse divise par TOUTES les observations."""
        returns = [0.02, -0.01, 0.03, -0.02, 0.01]
        run = self._run_with_returns(returns, spec)
        metrics = compute_performance(run)

        realised = simple_returns(np.array(metrics_curve(run)))
        downside = math.sqrt(float(np.mean(np.minimum(realised, 0.0) ** 2)))
        expected = float(np.mean(realised)) / downside * metrics.annualisation_factor
        assert metrics.sortino == pytest.approx(expected)

    def test_a_strategy_that_never_loses_has_no_sortino(self, spec):
        metrics = compute_performance(fake_run([CASH * (1.01**i) for i in range(50)], spec))
        assert metrics.sortino is None
        assert metrics.sharpe is None  # ecart-type nul : rendement constant

    def test_the_risk_free_rate_lowers_the_sharpe(self, spec):
        rng = np.random.default_rng(7)
        run = self._run_with_returns(list(rng.normal(0.001, 0.01, size=400)), spec)
        without = compute_performance(run).sharpe
        with_rf = compute_performance(run, risk_free_annual=0.05).sharpe
        assert without is not None and with_rf is not None
        assert with_rf < without

    def test_the_risk_free_rate_is_reported(self, spec):
        run = fake_run([CASH + i for i in range(50)], spec)
        assert compute_performance(run, risk_free_annual=0.04).risk_free_annual == 0.04

    def test_an_absurd_risk_free_rate_is_refused(self, spec):
        with pytest.raises(ConfigurationError, match="absurde"):
            compute_performance(fake_run([CASH, CASH], spec), risk_free_annual=-2.0)

    def test_few_returns_warns(self, spec):
        metrics = compute_performance(fake_run([CASH, CASH * 1.1, CASH * 1.05], spec))
        assert any("intervalle de confiance" in w for w in metrics.warnings)


def metrics_curve(run: FakeRun) -> list[float]:
    """La courbe quotidienne telle que les metriques la voient."""
    _, values = to_daily(run.equity.ts_ns, run.equity.equity)
    return list(values)


class TestDrawdownReporting:
    def test_both_granularities_are_reported_and_differ(self, spec):
        """Le drawdown intraday est reel et plus profond que le quotidien."""
        base = int(EPOCH.timestamp() * 1_000_000_000)
        hour = 3600 * 1_000_000_000
        ts = [base, base + hour, base + NS_PER_DAY, base + NS_PER_DAY + hour]
        run = fake_run([100.0, 50.0, 100.0, 100.0], spec, ts=ts, initial=100.0)
        metrics = compute_performance(run)

        assert metrics.drawdown_full is not None
        assert metrics.drawdown_daily is not None
        assert metrics.drawdown_full.max_drawdown == pytest.approx(-0.5)
        assert metrics.drawdown_daily.max_drawdown == pytest.approx(0.0)


class TestActivityMetrics:
    def _portfolio_with_trades(self, spec) -> Portfolio:
        portfolio = Portfolio(CASH, {SYMBOL: spec})

        def step(mark: float, *fills: Fill) -> None:
            portfolio.begin_bar()
            for f in fills:
                portfolio.apply_fill(f)
            portfolio.end_bar({SYMBOL: mark})

        def fill(side: Side, quantity: int, price: float, bar: int) -> Fill:
            return Fill(
                order_id=bar, symbol=SYMBOL, side=side, quantity=quantity, price=price,
                fee=0.0, slippage_cost=0.0, ts_ns=bar * NS_PER_DAY, bar_index=bar,
            )

        # Deux gagnants (+500 chacun), un perdant (-250)
        step(100.0, fill(Side.BUY, 1, 100.0, 0))
        step(110.0, fill(Side.SELL, 1, 110.0, 1))
        step(110.0, fill(Side.BUY, 1, 110.0, 2))
        step(120.0, fill(Side.SELL, 1, 120.0, 3))
        step(120.0, fill(Side.BUY, 1, 120.0, 4))
        step(115.0, fill(Side.SELL, 1, 115.0, 5))
        return portfolio

    def test_trade_statistics(self, spec):
        run = fake_run([CASH] * 6, spec)
        run.portfolio = self._portfolio_with_trades(spec)
        metrics = compute_performance(run)

        assert metrics.n_trades == 3
        assert metrics.hit_rate == pytest.approx(2 / 3)
        assert metrics.profit_factor == pytest.approx(1000.0 / 250.0)
        assert metrics.average_win == pytest.approx(500.0)
        assert metrics.average_loss == pytest.approx(-250.0)

    def test_no_trades_leaves_the_statistics_undefined(self, spec):
        metrics = compute_performance(fake_run([CASH] * 10, spec))
        assert metrics.n_trades == 0
        assert metrics.hit_rate is None
        assert metrics.profit_factor is None

    def test_a_strategy_without_losses_has_no_profit_factor(self, spec):
        """`inf` ne survivrait pas a une serialisation JSON : on declare l'absence."""
        run = fake_run([CASH] * 4, spec)
        portfolio = Portfolio(CASH, {SYMBOL: spec})

        def fill(side: Side, price: float, bar: int) -> Fill:
            return Fill(
                order_id=bar, symbol=SYMBOL, side=side, quantity=1, price=price,
                fee=0.0, slippage_cost=0.0, ts_ns=0, bar_index=bar,
            )

        portfolio.begin_bar()
        portfolio.apply_fill(fill(Side.BUY, 100.0, 0))
        portfolio.end_bar({SYMBOL: 100.0})
        portfolio.begin_bar()
        portfolio.apply_fill(fill(Side.SELL, 110.0, 1))
        portfolio.end_bar({SYMBOL: 110.0})
        run.portfolio = portfolio

        metrics = compute_performance(run)
        assert metrics.n_trades == 1
        assert metrics.profit_factor is None

    def test_exposure_is_the_fraction_of_bars_in_position(self, spec):
        run = fake_run([CASH] * 10, spec, exposure=[0, 0, 1, 1, 1, 2, 0, 0, 0, 0])
        metrics = compute_performance(run)
        assert metrics.exposure == pytest.approx(0.4)
        assert metrics.average_gross_contracts == pytest.approx(0.5)


class TestThroughTheEngine:
    def test_buy_and_hold_metrics_match_the_curve(self, spec):
        store = synthetic.make_store(synthetic.ramp(500, 100.0, 0.1), symbol=SYMBOL)
        result = SingleAssetRunner(
            store, spec,
            RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
        ).run(BuyAndHold(SYMBOL, 1))
        metrics = compute_performance(result)

        assert metrics.total_return == pytest.approx(result.total_return)
        assert metrics.final_equity == pytest.approx(result.final_equity)
        assert metrics.n_bars == len(result.equity)
        assert metrics.exposure == pytest.approx(499 / 500)

    def test_a_flat_strategy_has_no_ratios_and_no_drawdown(self, spec):
        store = synthetic.make_store(synthetic.random_walk(400, seed=3), symbol=SYMBOL)
        result = SingleAssetRunner(
            store, spec,
            RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
        ).run(FlatStrategy())
        metrics = compute_performance(result)

        assert metrics.total_return == 0.0
        assert metrics.sharpe is None
        assert metrics.n_trades == 0
        assert metrics.exposure == 0.0
        assert metrics.drawdown_full is not None
        assert metrics.drawdown_full.max_drawdown == pytest.approx(0.0)

    def test_describe_is_serialisable(self, spec):
        import json

        store = synthetic.make_store(synthetic.sine(400, 100.0, 10.0, 64), symbol=SYMBOL)
        result = SingleAssetRunner(
            store, spec,
            RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
        ).run(BuyAndHold(SYMBOL, 1))
        described = compute_performance(result).describe()
        assert json.loads(json.dumps(described)) == described

    def test_render_is_readable(self, spec):
        store = synthetic.make_store(synthetic.ramp(300, 100.0, 0.2), symbol=SYMBOL)
        result = SingleAssetRunner(
            store, spec,
            RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
        ).run(BuyAndHold(SYMBOL, 1))
        text = compute_performance(result).render()
        assert "Echantillon" in text
        assert "periodes/an (mesure)" in text

    def test_the_minute_curve_is_not_annualised_as_if_it_were_daily(self, spec):
        """La garantie de fond : 1 440 barres par jour ne font pas 1 440 periodes."""
        store = synthetic.make_store(
            synthetic.random_walk(5_000, seed=11), symbol=SYMBOL
        )
        result = SingleAssetRunner(
            store, spec,
            RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
        ).run(BuyAndHold(SYMBOL, 1))
        metrics = compute_performance(result)
        assert metrics.n_bars == 5_000
        assert metrics.n_daily_points <= 5
        # Annualiser a la minute donnerait ~525 600 periodes/an. On reste dans
        # l'ordre de grandeur d'un pas quotidien, meme sur un echantillon court.
        assert metrics.periods_per_year < 1_000
