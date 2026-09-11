"""Extraction, filtrage et calcul pour le tableau de bord. Sans tkinter.

Le rapport de run porte des agregats ; un tableau de bord a besoin du detail.
Ce module reconstitue le carnet d'ordres a partir des trades fermes et des
fills, puis recalcule les metriques sur n'importe quel sous-ensemble.

Deux regimes de mesure, et la distinction est affichee a l'ecran parce qu'elle
change le sens des chiffres :

- **MESUREE** : aucun filtre de sens actif. Les metriques de courbe (Sharpe,
  Calmar, drawdown) portent sur la vraie courbe d'equity du run, eventuellement
  tronquee a une annee.
- **RECONSTRUITE** : un filtre Long ou Short est actif. Il n'existe aucune
  courbe d'equity "longs seulement" - elle n'a jamais ete vecue. On en fabrique
  une en n'accumulant que le P&L des trades retenus, **sur la meme grille de
  barres**, pour que le Sharpe reste calcule sur une serie de meme periodicite
  et reste donc comparable. Ce n'est pas le resultat d'un backtest long-only :
  c'est la contribution des trades longs au resultat observe. La nuance est
  ecrite dans la fenetre, pas seulement ici.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from rsl.engine.orders import Fill
from rsl.engine.portfolio import ClosedTrade
from rsl.metrics.performance import DrawdownStats, PerformanceMetrics, drawdown_stats
from rsl.report import BacktestReport

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]

NS_PER_SECOND = 1_000_000_000
SECONDS_PER_YEAR = 365.25 * 24.0 * 3600.0


class SideFilter(StrEnum):
    """Filtre de sens. `ALL` laisse la vraie courbe d'equity faire foi."""

    ALL = "tous"
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True, slots=True)
class TradeRow:
    """Une ligne du carnet d'ordres : un aller-retour complet."""

    symbol: str
    entry_ts_ns: int
    exit_ts_ns: int
    direction: int
    quantity: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.fees

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0.0

    @property
    def side_label(self) -> str:
        return "LONG" if self.direction > 0 else "SHORT"

    @property
    def holding_seconds(self) -> float | None:
        """Temps passe en position, en secondes. `None` si un fill manque."""
        if self.entry_ts_ns <= 0 or self.exit_ts_ns <= 0:
            return None
        return (self.exit_ts_ns - self.entry_ts_ns) / NS_PER_SECOND

    @property
    def exit_year(self) -> int:
        """Annee de SORTIE : c'est la que le P&L est realise.

        Un trade ouvert en decembre et ferme en janvier compte pour l'annee
        suivante. Tout autre choix ferait qu'une somme par annee ne redonnerait
        pas le resultat total.
        """
        return to_datetime(self.exit_ts_ns).year


@dataclass(frozen=True, slots=True)
class Bars:
    """Barres OHLC d'un instrument, telles que le moteur les a vues.

    APRES reechantillonnage : un graphe de prix trace sur les barres d'origine
    montrerait autre chose que ce sur quoi la strategie a decide.
    """

    symbol: str
    ts_ns: IntArray
    open: FloatArray
    high: FloatArray
    low: FloatArray
    close: FloatArray


@dataclass(frozen=True, slots=True)
class Filters:
    """Etat des trois filtres de l'interface."""

    year: int | None = None
    side: SideFilter = SideFilter.ALL

    @property
    def is_active(self) -> bool:
        return self.year is not None or self.side is not SideFilter.ALL

    @property
    def needs_reconstruction(self) -> bool:
        """Un filtre de sens oblige a fabriquer une courbe qui n'a pas ete vecue."""
        return self.side is not SideFilter.ALL


@dataclass(frozen=True, slots=True)
class Dashboard:
    """Tout ce dont la fenetre a besoin, extrait une fois pour toutes."""

    name: str
    fingerprint: str
    symbols: tuple[str, ...]
    equity_ts_ns: IntArray
    equity: FloatArray
    trades: tuple[TradeRow, ...]
    metrics: PerformanceMetrics
    is_reproducible: bool
    bars: dict[str, Bars]

    @property
    def years(self) -> tuple[int, ...]:
        """Annees ou au moins un trade a ete FERME."""
        return tuple(sorted({t.exit_year for t in self.trades if t.exit_ts_ns > 0}))

    @property
    def initial_equity(self) -> float:
        return float(self.equity[0]) if self.equity.size else 0.0


@dataclass(frozen=True, slots=True)
class Stats:
    """Les indicateurs demandes, dans l'ordre de la specification."""

    sharpe: float | None
    calmar: float | None
    drawdown_current: float | None
    drawdown_max: float | None
    net_profit: float
    gross_profit: float
    net_loss: float
    gross_loss: float
    profit_factor: float | None
    win_rate: float | None
    n_trades: int
    average_win: float | None
    average_loss: float | None
    average_holding_seconds: float | None
    fees_total: float
    regime: str
    curve_ts_ns: IntArray
    curve: FloatArray


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def build_dashboard(
    report: BacktestReport,
    fills: Sequence[Fill],
    trades: Sequence[ClosedTrade],
    equity_ts_ns: Sequence[int],
    equity: Sequence[float],
    bars: dict[str, Bars] | None = None,
) -> Dashboard:
    """Assemble le jeu de donnees du tableau de bord."""
    return Dashboard(
        bars=bars if bars is not None else {},
        name=report.spec.name,
        fingerprint=report.result_fingerprint,
        symbols=report.symbols,
        equity_ts_ns=np.asarray(equity_ts_ns, dtype=np.int64),
        equity=np.asarray(equity, dtype=np.float64),
        trades=build_trade_rows(fills, trades),
        metrics=report.metrics,
        is_reproducible=report.manifest.is_reproducible,
    )


def build_trade_rows(fills: Sequence[Fill], trades: Sequence[ClosedTrade]) -> tuple[TradeRow, ...]:
    """Joint chaque trade ferme aux fills qui l'ont ouvert et ferme.

    Le prix retenu est le prix moyen pondere des fills de la barre concernee :
    une entree fractionnee en plusieurs fills sur la meme barre n'a pas un prix
    unique. Une entree etalee sur PLUSIEURS barres n'est pas representable en
    une ligne - seule la barre d'ouverture est lue. C'est une limite du format
    "une ligne par aller-retour", et `quantity` porte le maximum atteint par la
    position, pas la taille du premier fill.
    """
    par_barre: dict[tuple[str, int], list[Fill]] = defaultdict(list)
    for fill in fills:
        par_barre[(fill.symbol, fill.bar_index)].append(fill)

    rows: list[TradeRow] = []
    for trade in trades:
        entree = par_barre.get((trade.symbol, trade.opened_bar), [])
        sortie = par_barre.get((trade.symbol, trade.closed_bar), [])
        rows.append(
            TradeRow(
                symbol=trade.symbol,
                entry_ts_ns=entree[0].ts_ns if entree else 0,
                exit_ts_ns=sortie[0].ts_ns if sortie else 0,
                direction=trade.direction,
                quantity=trade.max_quantity,
                entry_price=vwap(entree),
                exit_price=vwap(sortie),
                gross_pnl=trade.gross_pnl,
                fees=trade.fees,
            )
        )
    return tuple(rows)


def vwap(fills: Sequence[Fill]) -> float:
    """Prix moyen pondere par les quantites. Zero si aucun fill."""
    if not fills:
        return 0.0
    quantite = sum(abs(f.quantity) for f in fills)
    if quantite == 0:
        return float(fills[0].price)
    return sum(f.price * abs(f.quantity) for f in fills) / quantite


def to_datetime(ts_ns: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_ns / NS_PER_SECOND, tz=dt.UTC)


def format_ts(ts_ns: int) -> str:
    """Horodatage lisible, ou un tiret si le fill n'a pas ete retrouve."""
    if ts_ns <= 0:
        return "-"
    return to_datetime(ts_ns).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Filtrage et calcul
# ---------------------------------------------------------------------------


def select_trades(dashboard: Dashboard, filters: Filters) -> tuple[TradeRow, ...]:
    """Sous-ensemble de trades retenu par les filtres."""
    retenus = dashboard.trades
    if filters.year is not None:
        retenus = tuple(t for t in retenus if t.exit_ts_ns > 0 and t.exit_year == filters.year)
    if filters.side is SideFilter.LONG:
        retenus = tuple(t for t in retenus if t.direction > 0)
    elif filters.side is SideFilter.SHORT:
        retenus = tuple(t for t in retenus if t.direction < 0)
    return retenus


def active_curve(dashboard: Dashboard, filters: Filters) -> tuple[IntArray, FloatArray, str]:
    """Courbe sur laquelle portent Sharpe, Calmar et drawdown.

    Sans filtre de sens : la vraie courbe, tronquee a l'annee si besoin.
    Avec filtre de sens : une courbe reconstruite sur la MEME grille de barres.
    """
    ts = dashboard.equity_ts_ns
    if ts.size == 0:
        return ts, dashboard.equity, "AUCUNE DONNEE"

    if filters.needs_reconstruction:
        courbe = reconstruct(dashboard, select_trades(dashboard, Filters(side=filters.side)))
        regime = "RECONSTRUITE"
    else:
        courbe = dashboard.equity
        regime = "MESUREE"

    if filters.year is not None:
        masque = year_mask(ts, filters.year)
        if not bool(masque.any()):
            vide_ts: IntArray = np.zeros(0, dtype=np.int64)
            vide_eq: FloatArray = np.zeros(0, dtype=np.float64)
            return vide_ts, vide_eq, regime
        return ts[masque], courbe[masque], regime
    return ts, courbe, regime


def year_mask(ts_ns: IntArray, year: int) -> BoolArray:
    """Masque des points appartenant a l'annee civile UTC demandee."""
    debut = int(dt.datetime(year, 1, 1, tzinfo=dt.UTC).timestamp()) * NS_PER_SECOND
    fin = int(dt.datetime(year + 1, 1, 1, tzinfo=dt.UTC).timestamp()) * NS_PER_SECOND
    return (ts_ns >= debut) & (ts_ns < fin)


def reconstruct(dashboard: Dashboard, trades: tuple[TradeRow, ...]) -> FloatArray:
    """Accumule le P&L net des trades retenus sur la grille de barres du run.

    L'alignement se fait par horodatage (`searchsorted`) et non par index de
    barre : rien ne garantit que l'indice d'un fill soit l'indice de la courbe
    d'equity, et une hypothese fausse a cet endroit decalerait tout le graphe
    sans rien lever.
    """
    ts = dashboard.equity_ts_ns
    deltas: FloatArray = np.zeros(ts.size, dtype=np.float64)
    for trade in trades:
        if trade.exit_ts_ns <= 0:
            continue
        position = int(np.searchsorted(ts, trade.exit_ts_ns, side="left"))
        deltas[min(position, ts.size - 1)] += trade.net_pnl
    return dashboard.initial_equity + np.cumsum(deltas)


def drawdown_series(courbe: FloatArray) -> FloatArray:
    """Serie du drawdown, en fraction du plus haut atteint. Negative ou nulle."""
    if courbe.size == 0:
        return np.zeros(0, dtype=np.float64)
    sommets = np.maximum.accumulate(courbe)
    return np.asarray(np.where(sommets > 0.0, courbe / sommets - 1.0, 0.0), dtype=np.float64)


def compute_stats(dashboard: Dashboard, filters: Filters) -> Stats:
    """Les indicateurs de la specification, pour l'etat de filtre donne."""
    trades = select_trades(dashboard, filters)
    ts, courbe, regime = active_curve(dashboard, filters)

    gagnants = [t for t in trades if t.net_pnl > 0.0]
    perdants = [t for t in trades if t.net_pnl < 0.0]

    net_profit = sum(t.net_pnl for t in gagnants)
    gross_profit = sum(t.gross_pnl for t in gagnants)
    net_loss = -sum(t.net_pnl for t in perdants)
    gross_loss = -sum(t.gross_pnl for t in perdants)

    # Meme definition que `rsl.metrics.performance._activity` : sur le P&L NET,
    # et `None` plutot qu'un infini quand aucune perte n'a ete subie - un `inf`
    # se propagerait dans l'export CSV.
    profit_factor = (net_profit / net_loss) if (trades and net_loss > 0.0) else None

    dd = drawdown_stats(ts, courbe) if courbe.size >= 2 else None
    sharpe = sharpe_of(courbe, dashboard.metrics)
    if not filters.is_active and dashboard.metrics.sharpe is not None:
        # Sans aucun filtre, l'autorite est le moteur, pas ce module.
        sharpe = dashboard.metrics.sharpe

    return Stats(
        sharpe=sharpe,
        calmar=calmar_of(ts, courbe, dd),
        drawdown_current=current_drawdown(courbe),
        drawdown_max=None if dd is None else dd.max_drawdown,
        net_profit=net_profit,
        gross_profit=gross_profit,
        net_loss=net_loss,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        win_rate=(len(gagnants) / len(trades)) if trades else None,
        n_trades=len(trades),
        average_win=(net_profit / len(gagnants)) if gagnants else None,
        average_loss=(-net_loss / len(perdants)) if perdants else None,
        average_holding_seconds=mean_holding(trades),
        fees_total=sum(t.fees for t in trades),
        regime=regime,
        curve_ts_ns=ts,
        curve=courbe,
    )


def mean_holding(trades: Sequence[TradeRow]) -> float | None:
    """Duree moyenne en position, en secondes.

    Les trades dont un fill n'a pas ete retrouve sont exclus du calcul plutot
    que comptes pour zero : une duree nulle tirerait la moyenne vers le bas
    sans qu'aucun trade n'ait reellement ete si court.
    """
    durees = [d for t in trades if (d := t.holding_seconds) is not None]
    if not durees:
        return None
    return sum(durees) / len(durees)


def format_duration(secondes: float | None) -> str:
    """Duree lisible : jours et heures, ou heures et minutes si moins d'un jour."""
    if secondes is None:
        return "n/d"
    if secondes < 3600:
        return f"{secondes / 60:.0f} min"
    if secondes < 86400:
        heures, reste = divmod(secondes, 3600)
        return f"{heures:.0f} h {reste / 60:02.0f}"
    jours, reste = divmod(secondes, 86400)
    return f"{jours:.0f} j {reste / 3600:02.0f} h"


def current_drawdown(courbe: FloatArray) -> float | None:
    """Ecart entre le dernier point et le plus haut atteint, en fraction."""
    if courbe.size == 0:
        return None
    sommet = float(np.max(courbe))
    if sommet <= 0.0:
        return None
    return float(courbe[-1]) / sommet - 1.0


def sharpe_of(courbe: FloatArray, metrics: PerformanceMetrics) -> float | None:
    """Sharpe annualise, avec le facteur d'annualisation MESURE du run.

    Le facteur vient de `metrics` et n'est jamais suppose : c'est une regle du
    depot, un facteur suppose gonfle le Sharpe d'un facteur deux sur des
    donnees minute (voir le ledger).
    """
    if courbe.size < 3:
        return None
    base = courbe[:-1]
    if bool(np.any(base <= 0.0)):
        return None
    rendements = np.diff(courbe) / base
    deviation = float(np.std(rendements, ddof=1))
    if deviation <= 0.0 or not np.isfinite(deviation):
        return None
    par_periode = float(np.mean(rendements)) / deviation
    return float(par_periode * metrics.annualisation_factor)


def calmar_of(ts: IntArray, courbe: FloatArray, dd: DrawdownStats | None) -> float | None:
    """CAGR divise par la valeur absolue du drawdown maximal.

    Absent des metriques du moteur : calcule ici, sur la courbe active.
    """
    if dd is None or courbe.size < 2 or ts.size < 2:
        return None
    plancher = abs(dd.max_drawdown)
    if plancher <= 0.0:
        return None
    annees = (int(ts[-1]) - int(ts[0])) / (NS_PER_SECOND * SECONDS_PER_YEAR)
    if annees <= 0.0 or float(courbe[0]) <= 0.0:
        return None
    croissance = float(courbe[-1]) / float(courbe[0])
    if croissance <= 0.0:
        return None
    cagr = float(croissance ** (1.0 / annees)) - 1.0
    return cagr / plancher
