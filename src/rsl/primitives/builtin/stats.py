"""Primitives statistiques : rendements et normalisation glissante."""

from __future__ import annotations

import math

import numpy as np

from rsl.data.feed import Context
from rsl.primitives.base import window_warmup
from rsl.primitives.builtin.params import (
    DispersionParams,
    FieldWindowParams,
    ReturnsParams,
    VolatilityParams,
    ZScoreParams,
)
from rsl.primitives.registry import primitive


@primitive(
    "returns",
    version=1,
    params=ReturnsParams,
    warmup=window_warmup(1),
    summary="Rendement sur `window` barres, simple ou logarithmique.",
)
def returns(ctx: Context, params: ReturnsParams) -> float | None:
    """Rendement entre la barre courante et celle d'il y a `window` barres.

    Retourne `None` si le prix de reference est nul ou de signe oppose : le
    rendement n'y est pas defini, et un `NaN` s'y propagerait en silence.
    """
    current = ctx.value(params.field, lag=0)
    reference = ctx.value(params.field, lag=params.window)
    if reference == 0.0 or (params.log and (reference <= 0.0 or current <= 0.0)):
        return None
    if params.log:
        return math.log(current / reference)
    ratio = current / reference
    if ratio < 0.0:
        return None
    return ratio - 1.0


@primitive(
    "zscore",
    version=1,
    params=ZScoreParams,
    warmup=window_warmup(),
    summary="Z-score sur fenetre glissante passee. Aucun mode echantillon complet.",
)
def zscore(ctx: Context, params: ZScoreParams) -> float | None:
    """`(x - moyenne) / ecart-type` sur les `window` dernieres barres closes.

    La fenetre est strictement passee, barre courante incluse. Il n'existe pas
    de variante calculee sur l'echantillon complet : ce serait injecter le
    futur dans chaque point (`docs/no-lookahead.md` §1, fuite n° 4).

    Retourne `None` quand l'ecart-type est nul - une serie constante n'a pas de
    z-score, et diviser par zero donnerait `inf` ou `NaN`.
    """
    values = ctx.values(params.field, params.window)
    std = float(np.std(values, ddof=params.ddof))
    if std == 0.0 or not math.isfinite(std):
        return None
    return (float(values[-1]) - float(np.mean(values))) / std


@primitive(
    "stdev",
    version=1,
    params=DispersionParams,
    warmup=window_warmup(),
    summary="Ecart-type sur fenetre glissante, en unites du champ mesure.",
)
def stdev(ctx: Context, params: DispersionParams) -> float | None:
    """Ecart-type des `window` dernieres valeurs.

    Debloque a lui seul les bandes de Bollinger, qui n'etaient jusqu'ici
    accessibles qu'indirectement par `zscore` : la largeur de bande s'ecrit
    `2 * stdev / sma`, et le seuil superieur `sma + 2 * stdev`.
    """
    values = ctx.values(params.field, params.window)
    deviation = float(np.std(values, ddof=params.ddof))
    return deviation if math.isfinite(deviation) else None


@primitive(
    "volatility",
    version=1,
    params=VolatilityParams,
    warmup=window_warmup(1),
    summary="Ecart-type des RENDEMENTS, sans unite donc comparable entre instruments.",
)
def volatility(ctx: Context, params: VolatilityParams) -> float | None:
    """Volatilite des rendements sur `window` variations.

    `annualise` multiplie par `sqrt(n)`. Le nombre de periodes par an doit etre
    MESURE sur l'echantillon - `PerformanceMetrics.periods_per_year` le donne -
    et jamais suppose : a la minute, prendre 252 * 1440 supposerait un marche
    ouvert en continu et gonflerait le resultat d'un facteur deux.
    """
    values = ctx.values(params.field, params.window + 1)
    previous, current = values[:-1], values[1:]
    if bool(np.any(previous <= 0.0)):
        return None
    returns = (
        np.log(current / previous) if params.log else current / previous - 1.0
    )
    deviation = float(np.std(returns, ddof=params.ddof))
    if not math.isfinite(deviation):
        return None
    if params.annualise is not None:
        deviation *= math.sqrt(params.annualise)
    return deviation


@primitive(
    "slope",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Pente d'une regression lineaire sur la fenetre, en unites par barre.",
)
def slope(ctx: Context, params: FieldWindowParams) -> float | None:
    """Pente des moindres carres sur les `window` dernieres barres.

    Mesure une tendance sans l'inertie d'une moyenne mobile : la pente reagit
    au dernier point autant qu'au premier, la ou une SMA le noie dans la masse.

    L'abscisse est le NUMERO DE BARRE, pas le temps. Sur des donnees trouees,
    une pente de 0,3 signifie 0,3 par barre, pas par minute - meme convention
    que toutes les fenetres du socle.
    """
    n = params.window
    if n < 2:
        return None
    values = ctx.values(params.field, n)
    x = np.arange(n, dtype=np.float64)
    x_centred = x - x.mean()
    denominator = float(np.dot(x_centred, x_centred))
    if denominator <= 0.0:
        return None
    return float(np.dot(x_centred, values - values.mean()) / denominator)
