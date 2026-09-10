"""Metriques de performance calculees sur une courbe d'equity.

Trois decisions structurent ce module, toutes prises dans
`docs/execution-model.md` §8.

**Le pas d'annualisation est MESURE, pas suppose.** A la minute,
`sqrt(252 * 1440)` supposerait un marche ouvert 24/7/365 et gonflerait le
Sharpe d'un facteur deux. Le nombre de periodes par an est compte sur
l'echantillon lui-meme, et figure dans le rapport. Un effet secondaire utile :
la meme fonction traite correctement une courbe mensuelle (12 periodes/an) et
une courbe minute, sans rien parametrer.

**La courbe est rameneee au pas quotidien avant tout ratio.** Un Sharpe calcule
sur des rendements a la minute mesure surtout du bruit de microstructure. Les
ratios portent donc sur la derniere valeur d'equity de chaque journee UTC.

**Le drawdown est rapporte deux fois.** A pleine granularite, parce qu'un
drawdown intraday est reel et qu'un investisseur le vit ; au pas quotidien,
parce que c'est ce que rapportent les publications auxquelles on se compare.
Les deux valeurs different, et masquer l'une des deux serait un choix.

Ce que ce module ne fait pas
---------------------------
Il ne juge pas. Un Sharpe de 2 sur un echantillon choisi apres coup ne vaut
rien, et aucune metrique de ce fichier ne peut le detecter. C'est le role de
`statistics.py` et de son compteur d'essais.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Protocol

import numpy as np

from rsl.engine.portfolio import EquityRecorder, Portfolio
from rsl.engine.runner import RunConfig
from rsl.errors import ConfigurationError

SpecDict = dict[str, object]

NS_PER_DAY: Final[int] = 86_400 * 1_000_000_000
DAYS_PER_YEAR: Final[float] = 365.2425

NEGLIGIBLE_DISPERSION: Final[float] = 1e-10
"""Seuil relatif sous lequel l'ecart-type des rendements est du bruit de calcul.

Une equity construite par `capital * (1 + r)**i` produit des rendements qui
devraient etre exactement constants mais dont l'ecart-type vaut ~1e-18 en
virgule flottante. Divise par une moyenne de 1e-2, cela donne un Sharpe de
l'ordre de 1e15 : un nombre absurde, mais un nombre - donc quelque chose qui
peut se retrouver dans un rapport et y etre pris au serieux. Au-dessous de ce
seuil, le ratio est declare indefini.
"""


class RunLike(Protocol):
    """Ce dont les metriques ont besoin d'un resultat de run.

    Les deux runners produisent des types differents ; ils partagent ces trois
    attributs, et c'est tout ce qui compte ici.
    """

    equity: EquityRecorder
    portfolio: Portfolio
    config: RunConfig


@dataclass(frozen=True, slots=True)
class DrawdownStats:
    """Drawdown maximal et duree, sur une courbe donnee."""

    max_drawdown: float
    """Fraction negative : -0,23 signifie -23 %."""

    peak_index: int
    trough_index: int
    recovery_index: int | None
    """`None` si le sommet n'a jamais ete retrouve avant la fin."""

    longest_underwater_periods: int
    """Plus longue duree entre un sommet et sa recuperation, en periodes.

    Mesuree du sommet a la recuperation, pas en nombre de barres basses : c'est
    la meme grandeur que `longest_underwater_days`, exprimee autrement.
    """

    longest_underwater_days: float

    @property
    def recovered(self) -> bool:
        return self.recovery_index is not None

    def describe(self) -> SpecDict:
        return {
            "max_drawdown": self.max_drawdown,
            "peak_index": self.peak_index,
            "trough_index": self.trough_index,
            "recovery_index": self.recovery_index,
            "recovered": self.recovered,
            "longest_underwater_periods": self.longest_underwater_periods,
            "longest_underwater_days": self.longest_underwater_days,
        }


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    """Resultat complet, serialisable pour le rapport de run."""

    # Echantillon
    n_bars: int
    n_daily_points: int
    span_years: float
    periods_per_year: float
    annualisation_factor: float
    risk_free_annual: float

    # Rendement
    initial_equity: float
    final_equity: float
    total_return: float
    cagr: float | None

    # Risque
    volatility_annual: float | None
    downside_deviation_annual: float | None
    sharpe: float | None
    sortino: float | None
    sharpe_per_period: float | None
    """Sharpe NON annualise. C'est celui qu'attend `statistics.py` : y passer le
    Sharpe annualise donnerait un resultat faux mais plausible."""

    n_returns: int
    returns_skewness: float
    returns_kurtosis: float
    drawdown_daily: DrawdownStats | None
    drawdown_full: DrawdownStats | None

    # Activite
    n_trades: int
    hit_rate: float | None
    profit_factor: float | None
    average_win: float | None
    average_loss: float | None
    turnover_annual: float | None
    exposure: float
    average_gross_contracts: float
    fees_paid: float
    slippage_paid: float

    # Sante
    is_ruined: bool
    """L'equity est passee a zero ou en dessous : les ratios n'ont plus de sens."""

    warnings: tuple[str, ...] = ()

    def describe(self) -> SpecDict:
        return {
            "sample": {
                "n_bars": self.n_bars,
                "n_daily_points": self.n_daily_points,
                "span_years": self.span_years,
                "periods_per_year": self.periods_per_year,
                "annualisation_factor": self.annualisation_factor,
                "risk_free_annual": self.risk_free_annual,
            },
            "return": {
                "initial_equity": self.initial_equity,
                "final_equity": self.final_equity,
                "total_return": self.total_return,
                "cagr": self.cagr,
            },
            "risk": {
                "volatility_annual": self.volatility_annual,
                "downside_deviation_annual": self.downside_deviation_annual,
                "sharpe": self.sharpe,
                "sortino": self.sortino,
                "sharpe_per_period": self.sharpe_per_period,
                "n_returns": self.n_returns,
                "returns_skewness": self.returns_skewness,
                "returns_kurtosis": self.returns_kurtosis,
                "drawdown_daily": (
                    None if self.drawdown_daily is None else self.drawdown_daily.describe()
                ),
                "drawdown_full": (
                    None if self.drawdown_full is None else self.drawdown_full.describe()
                ),
            },
            "activity": {
                "n_trades": self.n_trades,
                "hit_rate": self.hit_rate,
                "profit_factor": self.profit_factor,
                "average_win": self.average_win,
                "average_loss": self.average_loss,
                "turnover_annual": self.turnover_annual,
                "exposure": self.exposure,
                "average_gross_contracts": self.average_gross_contracts,
                "fees_paid": self.fees_paid,
                "slippage_paid": self.slippage_paid,
            },
            "is_ruined": self.is_ruined,
            "warnings": list(self.warnings),
        }

    def render(self) -> str:
        def pct(value: float | None) -> str:
            return "n/d" if value is None else f"{value * 100:+.2f} %"

        def num(value: float | None, digits: int = 2) -> str:
            return "n/d" if value is None else f"{value:.{digits}f}"

        lines = [
            f"Echantillon  {self.n_bars} barres, {self.span_years:.2f} an(s), "
            f"{self.periods_per_year:.1f} periodes/an (mesure)",
            f"Rendement    total {pct(self.total_return)}   CAGR {pct(self.cagr)}",
            f"Risque       vol {pct(self.volatility_annual)}   Sharpe {num(self.sharpe)}   "
            f"Sortino {num(self.sortino)}",
        ]
        if self.drawdown_daily is not None:
            lines.append(
                f"Drawdown     quotidien {pct(self.drawdown_daily.max_drawdown)} "
                f"({self.drawdown_daily.longest_underwater_days:.0f} j sous l'eau"
                f"{'' if self.drawdown_daily.recovered else ', jamais recupere'})"
            )
        if self.drawdown_full is not None:
            lines.append(
                f"             pleine granularite {pct(self.drawdown_full.max_drawdown)}"
            )
        lines.append(
            f"Activite     {self.n_trades} trades   hit {pct(self.hit_rate)}   "
            f"profit factor {num(self.profit_factor)}   exposition {pct(self.exposure)}"
        )
        lines.append(
            f"Couts        frais {self.fees_paid:,.2f}   slippage {self.slippage_paid:,.2f}"
        )
        if self.is_ruined:
            lines.append("RUINE        l'equity est passee a zero : les ratios sont caducs")
        lines.extend(f"Avertissement  {w}" for w in self.warnings)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Briques de calcul
# ---------------------------------------------------------------------------


def to_daily(
    ts_ns: list[int] | np.ndarray, equity: list[float] | np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Derniere valeur d'equity de chaque journee UTC.

    Sur une courbe deja plus large que la journee (mensuelle, par exemple),
    l'operation est l'identite : chaque point est seul dans sa journee.
    """
    ts = np.asarray(ts_ns, dtype=np.int64)
    values = np.asarray(equity, dtype=np.float64)
    if ts.shape[0] == 0:
        return ts, values
    days = ts // NS_PER_DAY
    last_of_day = np.flatnonzero(np.diff(days)) if days.shape[0] > 1 else np.array([], dtype=int)
    keep = np.append(last_of_day, days.shape[0] - 1)
    return ts[keep], values[keep]


def simple_returns(equity: np.ndarray) -> np.ndarray:
    """Rendements simples, ignorant les pas dont le denominateur est <= 0.

    Une equity nulle ou negative n'a pas de rendement defini ; la ruine est
    signalee a part plutot que travestie en `inf`.
    """
    if equity.shape[0] < 2:
        return np.array([], dtype=np.float64)
    previous, current = equity[:-1], equity[1:]
    valid = previous > 0.0
    out = np.zeros(previous.shape[0], dtype=np.float64)
    out[valid] = current[valid] / previous[valid] - 1.0
    return out[valid]


def drawdown_stats(
    ts_ns: np.ndarray, equity: np.ndarray
) -> DrawdownStats | None:
    """Drawdown maximal, et plus longue periode passee sous un sommet."""
    if equity.shape[0] < 2:
        return None

    running_peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = np.where(running_peak > 0.0, equity / running_peak - 1.0, 0.0)

    trough = int(np.argmin(drawdown))
    peak = int(np.argmax(equity[: trough + 1])) if trough > 0 else 0

    after = np.flatnonzero(equity[trough:] >= equity[peak])
    recovery = int(trough + after[0]) if after.size else None

    # Une periode sous l'eau va du SOMMET a sa recuperation. Compter les seules
    # barres passees sous le sommet donnerait une duree en periodes et une duree
    # en jours qui ne mesurent pas la meme chose - et l'ecart passerait inapercu.
    at_new_high = equity >= running_peak
    longest, longest_start, longest_end = 0, 0, 0
    underwater_since: int | None = None
    for i in range(equity.shape[0]):
        if at_new_high[i]:
            if underwater_since is not None:
                duration = i - underwater_since
                if duration > longest:
                    longest, longest_start, longest_end = duration, underwater_since, i
                underwater_since = None
        elif underwater_since is None:
            underwater_since = i - 1
    if underwater_since is not None:
        duration = equity.shape[0] - 1 - underwater_since
        if duration > longest:
            longest = duration
            longest_start, longest_end = underwater_since, equity.shape[0] - 1

    underwater_days = (
        (int(ts_ns[longest_end]) - int(ts_ns[longest_start])) / NS_PER_DAY if longest else 0.0
    )

    return DrawdownStats(
        max_drawdown=float(drawdown.min()),
        peak_index=peak,
        trough_index=trough,
        recovery_index=recovery,
        longest_underwater_periods=longest,
        longest_underwater_days=underwater_days,
    )


def skewness(values: np.ndarray) -> float:
    """Asymetrie, moments de population (convention de Bailey & Lopez de Prado)."""
    if values.shape[0] < 3:
        return 0.0
    centred = values - values.mean()
    m2 = float(np.mean(centred**2))
    if m2 <= 0.0:
        return 0.0
    return float(np.mean(centred**3) / m2**1.5)


def kurtosis(values: np.ndarray) -> float:
    """Kurtosis NON excedentaire : 3 pour une loi normale."""
    if values.shape[0] < 4:
        return 3.0
    centred = values - values.mean()
    m2 = float(np.mean(centred**2))
    if m2 <= 0.0:
        return 3.0
    return float(np.mean(centred**4) / m2**2)


# ---------------------------------------------------------------------------
# Point d'entree
# ---------------------------------------------------------------------------


def compute_performance(
    result: RunLike, *, risk_free_annual: float = 0.0
) -> PerformanceMetrics:
    """Toutes les metriques d'un run.

    `risk_free_annual` vaut zero par defaut, et c'est un CHOIX, pas une
    neutralite. Sur 2016-2026 le taux sans risque en dollars est passe de 0 a
    plus de 5 % : un Sharpe calcule a taux nul sur cette periode est
    optimiste, et d'autant plus que la strategie est peu volatile. La valeur
    retenue figure dans le rapport.
    """
    if risk_free_annual < -1.0:
        raise ConfigurationError(f"risk_free_annual absurde : {risk_free_annual}")

    warnings: list[str] = []
    equity_full = np.asarray(result.equity.equity, dtype=np.float64)
    ts_full = np.asarray(result.equity.ts_ns, dtype=np.int64)
    initial = result.config.initial_cash

    if equity_full.shape[0] == 0:
        raise ConfigurationError("courbe d'equity vide : aucun run n'a eu lieu")

    final = float(equity_full[-1])
    is_ruined = bool(equity_full.min() <= 0.0)
    if is_ruined:
        warnings.append(
            "l'equity est passee a zero ou en dessous : les ratios calcules sur les "
            "rendements ne decrivent plus rien de reel"
        )

    span_ns = int(ts_full[-1]) - int(ts_full[0])
    span_years = span_ns / (NS_PER_DAY * DAYS_PER_YEAR) if span_ns > 0 else 0.0

    ts_daily, equity_daily = to_daily(ts_full, equity_full)
    returns = simple_returns(equity_daily)

    periods_per_year = (
        equity_daily.shape[0] / span_years if span_years > 0.0 else 0.0
    )
    annualisation = math.sqrt(periods_per_year) if periods_per_year > 0.0 else 0.0
    if 0.0 < periods_per_year < 4.0:
        warnings.append(
            f"seulement {periods_per_year:.1f} periode(s) par an : les ratios annualises "
            f"reposent sur trop peu de points pour signifier quelque chose"
        )

    total_return = final / initial - 1.0
    cagr = _cagr(initial, final, span_years)

    rf_per_period = (
        (1.0 + risk_free_annual) ** (1.0 / periods_per_year) - 1.0
        if periods_per_year > 0.0 and risk_free_annual != 0.0
        else 0.0
    )
    excess = returns - rf_per_period

    volatility = _annual_volatility(returns, annualisation)
    downside = _annual_downside(excess, annualisation)
    sharpe_period = _sharpe_per_period(excess)
    sharpe = None if sharpe_period is None else sharpe_period * annualisation
    sortino = _sortino(excess, downside, annualisation)
    if sharpe is None and returns.shape[0] >= 2:
        warnings.append(
            "dispersion des rendements nulle ou au niveau du bruit de calcul : "
            "le Sharpe n'est pas defini"
        )

    if returns.shape[0] < 30:
        warnings.append(
            f"{returns.shape[0]} rendement(s) seulement : Sharpe et Sortino ont un "
            f"intervalle de confiance tres large"
        )

    activity = _activity(result, equity_full, span_years)

    return PerformanceMetrics(
        n_bars=int(equity_full.shape[0]),
        n_daily_points=int(equity_daily.shape[0]),
        span_years=span_years,
        periods_per_year=periods_per_year,
        annualisation_factor=annualisation,
        risk_free_annual=risk_free_annual,
        initial_equity=initial,
        final_equity=final,
        total_return=total_return,
        cagr=cagr,
        volatility_annual=volatility,
        downside_deviation_annual=downside,
        sharpe=sharpe,
        sortino=sortino,
        sharpe_per_period=sharpe_period,
        n_returns=int(excess.shape[0]),
        returns_skewness=skewness(excess),
        returns_kurtosis=kurtosis(excess),
        drawdown_daily=drawdown_stats(ts_daily, equity_daily),
        drawdown_full=drawdown_stats(ts_full, equity_full),
        is_ruined=is_ruined,
        warnings=tuple(warnings),
        n_trades=activity.n_trades,
        hit_rate=activity.hit_rate,
        profit_factor=activity.profit_factor,
        average_win=activity.average_win,
        average_loss=activity.average_loss,
        turnover_annual=activity.turnover_annual,
        exposure=activity.exposure,
        average_gross_contracts=activity.average_gross_contracts,
        fees_paid=activity.fees_paid,
        slippage_paid=activity.slippage_paid,
    )


def _cagr(initial: float, final: float, span_years: float) -> float | None:
    if span_years <= 0.0 or initial <= 0.0 or final <= 0.0:
        return None
    return float((final / initial) ** (1.0 / span_years)) - 1.0


def _annual_volatility(returns: np.ndarray, annualisation: float) -> float | None:
    if returns.shape[0] < 2 or annualisation <= 0.0:
        return None
    return float(np.std(returns, ddof=1)) * annualisation


def _annual_downside(excess: np.ndarray, annualisation: float) -> float | None:
    """Ecart-type des rendements NEGATIFS, denominateur complet.

    Le denominateur est le nombre total d'observations, pas le nombre de
    negatives : c'est la definition de Sortino, et diviser par les seules
    negatives gonflerait le ratio des strategies qui perdent rarement mais gros.
    """
    if excess.shape[0] < 2 or annualisation <= 0.0:
        return None
    below = np.minimum(excess, 0.0)
    return float(math.sqrt(float(np.mean(below**2)))) * annualisation


def _sharpe_per_period(excess: np.ndarray) -> float | None:
    """Sharpe brut, sans annualisation. L'ecart-type est non biaise (ddof=1)."""
    if excess.shape[0] < 2:
        return None
    deviation = float(np.std(excess, ddof=1))
    if _is_negligible(deviation, float(np.mean(excess))):
        return None
    return float(np.mean(excess)) / deviation


def _is_negligible(deviation: float, mean: float) -> bool:
    """La dispersion est-elle indiscernable de zero ?"""
    if deviation <= 0.0 or not math.isfinite(deviation):
        return True
    return deviation <= NEGLIGIBLE_DISPERSION * max(abs(mean), 1.0)


def _sortino(
    excess: np.ndarray, downside: float | None, annualisation: float
) -> float | None:
    if excess.shape[0] < 2 or downside is None or annualisation <= 0.0:
        return None
    if _is_negligible(downside / annualisation, float(np.mean(excess))):
        return None
    return float(np.mean(excess)) * annualisation**2 / downside


@dataclass(frozen=True, slots=True)
class _Activity:
    """Bloc "activite" des metriques. Typé plutot que deballé depuis un dict :
    un `**dict[str, object]` fait perdre le controle de types sur douze champs."""

    n_trades: int
    hit_rate: float | None
    profit_factor: float | None
    average_win: float | None
    average_loss: float | None
    turnover_annual: float | None
    exposure: float
    average_gross_contracts: float
    fees_paid: float
    slippage_paid: float


def _activity(result: RunLike, equity_full: np.ndarray, span_years: float) -> _Activity:
    trades = result.portfolio.closed_trades
    wins = [t.net_pnl for t in trades if t.net_pnl > 0.0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0.0]

    gross_win = sum(wins)
    gross_loss = -sum(losses)
    profit_factor: float | None
    if not trades:
        profit_factor = None
    elif gross_loss <= 0.0:
        # Aucune perte : le ratio est infini. On le declare absent plutot que
        # d'ecrire `inf`, qui se propagerait dans un rapport JSON.
        profit_factor = None
    else:
        profit_factor = gross_win / gross_loss

    exposure_array = np.asarray(result.equity.exposure, dtype=np.float64)
    mean_equity = float(np.mean(equity_full))
    turnover: float | None = (
        float(result.portfolio.stats.turnover_notional / (mean_equity * span_years))
        if span_years > 0.0 and mean_equity > 0.0
        else None
    )

    return _Activity(
        n_trades=len(trades),
        hit_rate=(len(wins) / len(trades)) if trades else None,
        profit_factor=profit_factor,
        average_win=(gross_win / len(wins)) if wins else None,
        average_loss=(-gross_loss / len(losses)) if losses else None,
        turnover_annual=turnover,
        exposure=float(np.mean(exposure_array > 0.0)) if exposure_array.size else 0.0,
        average_gross_contracts=(
            float(np.mean(exposure_array)) if exposure_array.size else 0.0
        ),
        fees_paid=result.portfolio.stats.fees_paid,
        slippage_paid=result.portfolio.stats.slippage_paid,
    )
