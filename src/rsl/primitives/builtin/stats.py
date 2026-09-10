"""Primitives statistiques : rendements et normalisation glissante."""

from __future__ import annotations

import math

import numpy as np

from rsl.data.feed import Context
from rsl.primitives.base import window_warmup
from rsl.primitives.builtin.params import ReturnsParams, ZScoreParams
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
