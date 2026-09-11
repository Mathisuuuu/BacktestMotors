"""Tableau de bord : extraction du carnet, filtrage, et calcul des indicateurs.

L'interface n'est pas testee - c'est du dessin. Ce qui est teste, c'est tout ce
qu'elle affiche. La garantie centrale est la derniere classe du fichier : sans
filtre, le tableau de bord doit rendre EXACTEMENT les chiffres du moteur. S'ils
divergent, c'est le tableau de bord qui a tort.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pytest

from rsl.data.schema import InstrumentSpec
from rsl.engine.execution import ExecutionConfig, ZeroFee, ZeroSlippage
from rsl.engine.orders import Fill, Side
from rsl.engine.portfolio import ClosedTrade, EquityRecorder, Portfolio
from rsl.engine.runner import RunConfig
from rsl.gui.model import (
    Bars,
    Dashboard,
    Filters,
    SideFilter,
    TradeRow,
    build_trade_rows,
    compute_stats,
    drawdown_series,
    format_duration,
    format_ts,
    mean_holding,
    reconstruct,
    select_trades,
    vwap,
    year_mask,
)
from rsl.metrics.performance import NS_PER_DAY, compute_performance

SYMBOL = "TEST.v.0"
CASH = 100_000.0
EPOCH = datetime(2021, 1, 1, tzinfo=UTC)


def instrument() -> InstrumentSpec:
    """Meme instrument que la fixture `spec` de `conftest`, construit ici parce
    qu'un helper de module ne peut pas consommer une fixture pytest."""
    return InstrumentSpec(
        symbol=SYMBOL, root="TEST", name="Instrument de test", exchange="CME",
        currency="USD", multiplier=50.0, tick_size=0.25,
        commission_per_contract=1.0, exchange_fee_per_contract=1.0,
        initial_margin=10_000.0, maintenance_margin=9_000.0,
    )


def ts_of(year: int, month: int = 6, day: int = 15) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp()) * 1_000_000_000


def days_ns(n: int) -> list[int]:
    base = int(EPOCH.timestamp() * 1_000_000_000)
    return [base + i * NS_PER_DAY for i in range(n)]


@dataclass
class FakeRun:
    equity: EquityRecorder
    portfolio: Portfolio
    config: RunConfig


def metrics_for(equity_values: list[float], ts: list[int] | None = None):
    """Vraies metriques du moteur sur une courbe fabriquee."""
    recorder = EquityRecorder()
    stamps = ts if ts is not None else days_ns(len(equity_values))
    for stamp, value in zip(stamps, equity_values, strict=True):
        recorder.record(stamp, value, value, 1)
    run = FakeRun(
        equity=recorder,
        portfolio=Portfolio(CASH, {SYMBOL: instrument()}),
        config=RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
    )
    return compute_performance(run)


def trade(*, year: int, direction: int, gross: float, fees: float = 10.0) -> TradeRow:
    return TradeRow(
        symbol=SYMBOL,
        entry_ts_ns=ts_of(year, 1, 5),
        exit_ts_ns=ts_of(year, 6, 15),
        direction=direction,
        quantity=1,
        entry_price=100.0,
        exit_price=110.0,
        gross_pnl=gross,
        fees=fees,
    )


def dashboard_of(trades: tuple[TradeRow, ...], equity_values: list[float] | None = None,
                 ts: list[int] | None = None) -> Dashboard:
    values = equity_values if equity_values is not None else [CASH + i for i in range(40)]
    stamps = ts if ts is not None else days_ns(len(values))
    return Dashboard(
        name="test",
        fingerprint="f" * 64,
        symbols=(SYMBOL,),
        equity_ts_ns=np.asarray(stamps, dtype=np.int64),
        equity=np.asarray(values, dtype=np.float64),
        trades=trades,
        metrics=metrics_for(values, stamps),
        is_reproducible=True,
        bars={},
    )


def fill(*, bar: int, price: float, quantity: int, ts: int = 0) -> Fill:
    return Fill(
        order_id=1, symbol=SYMBOL, side=Side.BUY, quantity=quantity, price=price,
        fee=1.0, slippage_cost=0.0, ts_ns=ts or ts_of(2021), bar_index=bar,
    )


# ---------------------------------------------------------------------------
# Extraction du carnet
# ---------------------------------------------------------------------------


class TestVwap:
    def test_un_seul_fill(self):
        assert vwap([fill(bar=0, price=100.0, quantity=2)]) == 100.0

    def test_pondere_par_les_quantites(self):
        """Deux fills sur la meme barre n'ont pas un prix unique."""
        fills = [fill(bar=0, price=100.0, quantity=1), fill(bar=0, price=110.0, quantity=3)]
        assert vwap(fills) == pytest.approx(107.5)

    def test_sans_fill_vaut_zero(self):
        assert vwap([]) == 0.0


class TestBuildTradeRows:
    def test_joint_les_prix_et_les_dates(self):
        fills = [
            fill(bar=3, price=100.0, quantity=1, ts=ts_of(2021, 1, 5)),
            fill(bar=9, price=130.0, quantity=1, ts=ts_of(2021, 6, 15)),
        ]
        ferme = ClosedTrade(symbol=SYMBOL, opened_bar=3, closed_bar=9, direction=1,
                            max_quantity=1, gross_pnl=30.0, fees=2.0)
        (row,) = build_trade_rows(fills, [ferme])
        assert row.entry_price == 100.0
        assert row.exit_price == 130.0
        assert row.entry_ts_ns == ts_of(2021, 1, 5)
        assert row.net_pnl == pytest.approx(28.0)
        assert row.side_label == "LONG"

    def test_fill_introuvable_ne_leve_pas(self):
        """Un carnet incomplet doit s'afficher, pas faire tomber la fenetre."""
        ferme = ClosedTrade(symbol=SYMBOL, opened_bar=3, closed_bar=9, direction=-1,
                            max_quantity=1, gross_pnl=30.0, fees=2.0)
        (row,) = build_trade_rows([], [ferme])
        assert row.entry_ts_ns == 0
        assert format_ts(row.entry_ts_ns) == "-"
        assert row.side_label == "SHORT"


class TestExitYear:
    def test_l_annee_retenue_est_celle_de_la_sortie(self):
        """Sinon, la somme des annees ne redonnerait pas le total."""
        row = TradeRow(symbol=SYMBOL, entry_ts_ns=ts_of(2020, 12, 28),
                       exit_ts_ns=ts_of(2021, 1, 4), direction=1, quantity=1,
                       entry_price=1.0, exit_price=2.0, gross_pnl=1.0, fees=0.0)
        assert row.exit_year == 2021


# ---------------------------------------------------------------------------
# Filtrage
# ---------------------------------------------------------------------------


class TestSelectTrades:
    def dashboard(self) -> Dashboard:
        return dashboard_of((
            trade(year=2021, direction=1, gross=100.0),
            trade(year=2021, direction=-1, gross=-50.0),
            trade(year=2022, direction=1, gross=200.0),
        ))

    def test_sans_filtre_tout_passe(self):
        assert len(select_trades(self.dashboard(), Filters())) == 3

    def test_par_annee(self):
        assert len(select_trades(self.dashboard(), Filters(year=2021))) == 2

    def test_long_seulement(self):
        retenus = select_trades(self.dashboard(), Filters(side=SideFilter.LONG))
        assert [t.direction for t in retenus] == [1, 1]

    def test_short_seulement(self):
        retenus = select_trades(self.dashboard(), Filters(side=SideFilter.SHORT))
        assert [t.direction for t in retenus] == [-1]

    def test_les_deux_filtres_se_combinent(self):
        retenus = select_trades(self.dashboard(), Filters(year=2021, side=SideFilter.LONG))
        assert len(retenus) == 1

    def test_long_et_short_partitionnent_l_ensemble(self):
        d = self.dashboard()
        longs = select_trades(d, Filters(side=SideFilter.LONG))
        shorts = select_trades(d, Filters(side=SideFilter.SHORT))
        assert len(longs) + len(shorts) == len(d.trades)

    def test_les_annees_listees_sont_celles_des_sorties(self):
        assert self.dashboard().years == (2021, 2022)


class TestYearMask:
    def test_borne_sur_l_annee_civile_utc(self):
        ts = np.asarray([ts_of(2020, 12, 31), ts_of(2021, 1, 1), ts_of(2021, 12, 31),
                         ts_of(2022, 1, 1)], dtype=np.int64)
        assert list(year_mask(ts, 2021)) == [False, True, True, False]


# ---------------------------------------------------------------------------
# Courbes
# ---------------------------------------------------------------------------


class TestReconstruction:
    def test_le_pnl_se_pose_a_la_date_de_sortie(self):
        stamps = days_ns(10)
        d = dashboard_of((), [CASH] * 10, stamps)
        row = TradeRow(symbol=SYMBOL, entry_ts_ns=stamps[1], exit_ts_ns=stamps[4],
                       direction=1, quantity=1, entry_price=1.0, exit_price=2.0,
                       gross_pnl=500.0, fees=0.0)
        courbe = reconstruct(d, (row,))
        assert courbe[3] == pytest.approx(CASH)
        assert courbe[4] == pytest.approx(CASH + 500.0)
        assert courbe[-1] == pytest.approx(CASH + 500.0)

    def test_la_courbe_garde_la_grille_du_run(self):
        """Meme longueur : c'est ce qui rend le Sharpe comparable."""
        d = dashboard_of((), [CASH] * 12)
        assert reconstruct(d, ()).size == d.equity.size

    def test_une_sortie_sans_horodatage_est_ignoree(self):
        d = dashboard_of((), [CASH] * 5)
        orphelin = TradeRow(symbol=SYMBOL, entry_ts_ns=0, exit_ts_ns=0, direction=1,
                            quantity=1, entry_price=0.0, exit_price=0.0,
                            gross_pnl=999.0, fees=0.0)
        assert float(reconstruct(d, (orphelin,))[-1]) == pytest.approx(CASH)


class TestDrawdownSeries:
    def test_nulle_sur_une_courbe_croissante(self):
        serie = drawdown_series(np.asarray([1.0, 2.0, 3.0], dtype=np.float64))
        assert list(serie) == [0.0, 0.0, 0.0]

    def test_mesure_l_ecart_au_plus_haut(self):
        serie = drawdown_series(np.asarray([100.0, 80.0, 90.0], dtype=np.float64))
        assert serie[1] == pytest.approx(-0.2)
        assert serie[2] == pytest.approx(-0.1)

    def test_jamais_positive(self):
        courbe = np.asarray([10.0, 5.0, 20.0, 1.0, 7.0], dtype=np.float64)
        assert bool(np.all(drawdown_series(courbe) <= 0.0))


# ---------------------------------------------------------------------------
# Indicateurs
# ---------------------------------------------------------------------------


class TestStats:
    def dashboard(self) -> Dashboard:
        return dashboard_of((
            trade(year=2021, direction=1, gross=310.0, fees=10.0),
            trade(year=2021, direction=-1, gross=-90.0, fees=10.0),
            trade(year=2022, direction=1, gross=110.0, fees=10.0),
        ))

    def test_gains_et_pertes_bruts_et_nets(self):
        s = compute_stats(self.dashboard(), Filters())
        assert s.gross_profit == pytest.approx(420.0)
        assert s.net_profit == pytest.approx(400.0)
        assert s.gross_loss == pytest.approx(90.0)
        assert s.net_loss == pytest.approx(100.0)

    def test_le_brut_et_le_net_different_des_frais(self):
        s = compute_stats(self.dashboard(), Filters())
        assert s.net_profit == pytest.approx(s.gross_profit - 20.0)

    def test_profit_factor_et_taux_de_reussite(self):
        s = compute_stats(self.dashboard(), Filters())
        assert s.profit_factor == pytest.approx(4.0)
        assert s.win_rate == pytest.approx(2 / 3)
        assert s.n_trades == 3

    def test_gain_et_perte_moyens(self):
        s = compute_stats(self.dashboard(), Filters())
        assert s.average_win == pytest.approx(200.0)
        assert s.average_loss == pytest.approx(-100.0)

    def test_profit_factor_absent_sans_perte(self):
        """`None` plutot qu'un infini : un `inf` polluerait l'export CSV."""
        d = dashboard_of((trade(year=2021, direction=1, gross=100.0),))
        assert compute_stats(d, Filters()).profit_factor is None

    def test_aucun_trade_retenu(self):
        s = compute_stats(self.dashboard(), Filters(year=1999))
        assert s.n_trades == 0
        assert s.win_rate is None
        assert s.profit_factor is None

    def test_la_somme_par_annee_redonne_le_total(self):
        d = self.dashboard()
        total = compute_stats(d, Filters()).net_profit
        par_annee = sum(compute_stats(d, Filters(year=a)).net_profit for a in d.years)
        assert par_annee == pytest.approx(total)

    def test_le_regime_est_annonce(self):
        d = self.dashboard()
        assert compute_stats(d, Filters()).regime == "MESUREE"
        assert compute_stats(d, Filters(side=SideFilter.LONG)).regime == "RECONSTRUITE"

    def test_un_filtre_de_sens_ne_touche_pas_la_vraie_courbe(self):
        d = self.dashboard()
        mesuree = compute_stats(d, Filters()).curve
        assert np.array_equal(mesuree, d.equity)


class TestAccordAvecLeMoteur:
    """Sans filtre, le tableau de bord ne doit rien recalculer autrement."""

    def dashboard(self) -> Dashboard:
        valeurs = [CASH * (1.0 + 0.004 * i - 0.00003 * i * i) for i in range(120)]
        return dashboard_of((
            trade(year=2021, direction=1, gross=310.0, fees=10.0),
            trade(year=2021, direction=-1, gross=-90.0, fees=10.0),
        ), valeurs)

    def test_sharpe_identique_a_celui_du_moteur(self):
        d = self.dashboard()
        assert compute_stats(d, Filters()).sharpe == pytest.approx(d.metrics.sharpe)

    def test_drawdown_max_identique_a_celui_du_moteur(self):
        d = self.dashboard()
        attendu = d.metrics.drawdown_full
        assert attendu is not None
        mesure = compute_stats(d, Filters()).drawdown_max
        assert mesure == pytest.approx(attendu.max_drawdown)

    def test_calmar_vaut_bien_cagr_sur_drawdown(self):
        d = self.dashboard()
        s = compute_stats(d, Filters())
        attendu = d.metrics.drawdown_full
        assert attendu is not None and s.calmar is not None
        assert d.metrics.cagr is not None
        assert s.calmar == pytest.approx(
            d.metrics.cagr / abs(attendu.max_drawdown), rel=0.02
        )


# ---------------------------------------------------------------------------
# Duree en position
# ---------------------------------------------------------------------------


class TestDureeEnPosition:
    def test_duree_d_un_trade(self):
        row = TradeRow(symbol=SYMBOL, entry_ts_ns=ts_of(2021, 1, 1),
                       exit_ts_ns=ts_of(2021, 1, 3), direction=1, quantity=1,
                       entry_price=1.0, exit_price=2.0, gross_pnl=1.0, fees=0.0)
        assert row.holding_seconds == pytest.approx(2 * 86400)

    def test_duree_absente_si_un_fill_manque(self):
        """Un trade dont le fill n'a pas ete retrouve n'a pas de duree
        connue - zero serait un chiffre faux, pas une absence."""
        row = TradeRow(symbol=SYMBOL, entry_ts_ns=0, exit_ts_ns=ts_of(2021), direction=1,
                       quantity=1, entry_price=1.0, exit_price=2.0, gross_pnl=1.0, fees=0.0)
        assert row.holding_seconds is None

    def test_moyenne_sur_plusieurs_trades(self):
        a = TradeRow(symbol=SYMBOL, entry_ts_ns=ts_of(2021, 1, 1),
                     exit_ts_ns=ts_of(2021, 1, 3), direction=1, quantity=1,
                     entry_price=1.0, exit_price=2.0, gross_pnl=1.0, fees=0.0)
        b = TradeRow(symbol=SYMBOL, entry_ts_ns=ts_of(2021, 2, 1),
                     exit_ts_ns=ts_of(2021, 2, 5), direction=1, quantity=1,
                     entry_price=1.0, exit_price=2.0, gross_pnl=1.0, fees=0.0)
        assert mean_holding((a, b)) == pytest.approx(3 * 86400)

    def test_les_trades_sans_duree_sont_exclus_pas_comptes_zero(self):
        bon = TradeRow(symbol=SYMBOL, entry_ts_ns=ts_of(2021, 1, 1),
                       exit_ts_ns=ts_of(2021, 1, 3), direction=1, quantity=1,
                       entry_price=1.0, exit_price=2.0, gross_pnl=1.0, fees=0.0)
        orphelin = TradeRow(symbol=SYMBOL, entry_ts_ns=0, exit_ts_ns=0, direction=1,
                            quantity=1, entry_price=0.0, exit_price=0.0,
                            gross_pnl=0.0, fees=0.0)
        assert mean_holding((bon, orphelin)) == pytest.approx(2 * 86400)

    def test_aucune_duree_connue(self):
        assert mean_holding(()) is None

    def test_la_duree_moyenne_entre_dans_les_stats(self):
        d = dashboard_of((trade(year=2021, direction=1, gross=100.0),))
        stats = compute_stats(d, Filters())
        assert stats.average_holding_seconds is not None
        assert stats.average_holding_seconds > 0.0

    @pytest.mark.parametrize(("secondes", "attendu"), [
        (None, "n/d"),
        (600.0, "10 min"),
        (7200.0, "2 h 00"),
        (9000.0, "2 h 30"),
        (86400.0, "1 j 00 h"),
        (2 * 86400 + 3 * 3600, "2 j 03 h"),
    ])
    def test_format_lisible(self, secondes, attendu):
        assert format_duration(secondes) == attendu


class TestBarres:
    def test_le_dashboard_porte_les_barres_par_symbole(self):
        barres = Bars(symbol=SYMBOL, ts_ns=np.asarray(days_ns(5), dtype=np.int64),
                      open=np.ones(5), high=np.ones(5) * 2, low=np.ones(5) * 0.5,
                      close=np.ones(5) * 1.5)
        d = dashboard_of(())
        enrichi = Dashboard(
            name=d.name, fingerprint=d.fingerprint, symbols=d.symbols,
            equity_ts_ns=d.equity_ts_ns, equity=d.equity, trades=d.trades,
            metrics=d.metrics, is_reproducible=d.is_reproducible,
            bars={SYMBOL: barres},
        )
        assert enrichi.bars[SYMBOL].close.size == 5
