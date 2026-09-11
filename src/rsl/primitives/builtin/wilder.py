"""Famille de Wilder : lissage exponentiel a `alpha = 1/window`.

`atr@1` et `rsi@1` utilisent des moyennes ARITHMETIQUES, et leurs docstrings
proposent une variante Wilder en `@2`. Ce module prend le parti inverse, sous
des noms distincts, pour une raison mecanique : `get_primitive` resout une
reference SANS version vers la **plus recente**. Publier le lissage de Wilder
en `atr@2` ferait donc basculer, sans aucun changement de code, toute
specification ecrite `"ref": "atr"` - d'une moyenne simple a une moyenne
exponentielle, en silence. Un nom different ne peut pas produire cet effet.

Le lissage de Wilder depend en theorie de toute l'histoire depuis l'origine.
Il est ici calcule sur un historique TRONQUE de `window * seed_multiplier`
barres, amorce par la moyenne simple des `window` premieres - exactement la
convention deja retenue par `ema@1`, pour la meme raison : le resultat doit
etre deterministe et ne dependre que de ce que le contexte donne a voir.
"""

from __future__ import annotations

from enum import StrEnum
from typing import cast

import numpy as np
import numpy.typing as npt

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import WindowParams
from rsl.primitives.registry import primitive

FloatArray = npt.NDArray[np.float64]


class WilderParams(WindowParams):
    """Fenetre de Wilder, plus la profondeur d'amorce."""

    seed_multiplier: int = 5

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.seed_multiplier < 2:
            raise ValueError(
                f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier} : "
                f"en dessous, l'amorce domine le resultat"
            )

    @property
    def lookback(self) -> int:
        return self.window * self.seed_multiplier


class WilderFieldParams(WilderParams):
    """Lissage de Wilder applique a un champ OHLCV."""

    field: Field = Field.CLOSE


class DirectionalOutput(StrEnum):
    """Quelle sortie du systeme directionnel lire."""

    ADX = "adx"
    PLUS_DI = "plus_di"
    MINUS_DI = "minus_di"


class AdxParams(WilderParams):
    """Systeme directionnel de Wilder, avec selection de sortie.

    Une primitive rend UN scalaire. Plutot que trois primitives qui
    recalculeraient trois fois la meme chose, une seule avec un selecteur -
    le choix est explicite dans la specification, donc lisible.
    """

    output: DirectionalOutput = DirectionalOutput.ADX


def wilder_smooth(values: FloatArray, window: int) -> FloatArray:
    """Serie lissee a la Wilder, amorcee par la moyenne simple des `window` premieres.

    Rend un tableau de `len(values) - window + 1` elements : le premier est
    l'amorce, le dernier la valeur courante. Boucle explicite - la recursion
    n'est pas vectorisable sans accumulateur, et la correction prime sur la
    vitesse a cette etape.
    """
    sortie = np.empty(values.size - window + 1, dtype=np.float64)
    courant = float(np.mean(values[:window]))
    sortie[0] = courant
    for indice, valeur in enumerate(values[window:], start=1):
        courant += (float(valeur) - courant) / window
        sortie[indice] = courant
    return sortie


def true_range_series(high: FloatArray, low: FloatArray, close: FloatArray) -> FloatArray:
    """True Range de chaque barre sauf la premiere, qui n'a pas de cloture avant elle."""
    precedente = close[:-1]
    return np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - precedente), np.abs(low[1:] - precedente)),
    )


@primitive(
    "atr_wilder",
    version=1,
    params=WilderParams,
    warmup=lambda p: cast("WilderParams", p).lookback + 1,
    summary="Average True Range lisse a la WILDER (a distinguer de `atr@1`, moyenne simple).",
)
def atr_wilder(ctx: Context, params: WilderParams) -> float | None:
    """ATR de Wilder sur historique tronque."""
    n = params.lookback
    high = ctx.values(Field.HIGH, n + 1)
    low = ctx.values(Field.LOW, n + 1)
    close = ctx.values(Field.CLOSE, n + 1)
    ranges = true_range_series(high, low, close)
    return float(wilder_smooth(ranges, params.window)[-1])


@primitive(
    "rsi_wilder",
    version=1,
    params=WilderFieldParams,
    warmup=lambda p: cast("WilderFieldParams", p).lookback + 1,
    summary="Relative Strength Index lisse a la WILDER (a distinguer de `rsi@1`).",
)
def rsi_wilder(ctx: Context, params: WilderFieldParams) -> float | None:
    """RSI de Wilder.

    Memes cas limites que `rsi@1`, traites de la meme facon : aucune baisse
    rend 100, aucune hausse rend 0, une serie parfaitement plate rend `None` -
    une serie sans variation n'a ni force ni faiblesse relative, et repondre 50
    serait inventer une information.
    """
    valeurs = ctx.values(params.field, params.lookback + 1)
    deltas = np.diff(valeurs)
    hausses = float(wilder_smooth(np.maximum(deltas, 0.0), params.window)[-1])
    baisses = float(wilder_smooth(np.maximum(-deltas, 0.0), params.window)[-1])

    if hausses == 0.0 and baisses == 0.0:
        return None
    if baisses == 0.0:
        return 100.0
    if hausses == 0.0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + hausses / baisses)


@primitive(
    "adx",
    version=1,
    params=AdxParams,
    warmup=lambda p: cast("AdxParams", p).lookback + cast("AdxParams", p).window + 1,
    summary="Systeme directionnel de Wilder : `adx`, `plus_di` ou `minus_di` au choix.",
)
def adx(ctx: Context, params: AdxParams) -> float | None:
    """ADX et ses deux composantes directionnelles.

    L'ADX est un lissage de DX, lui-meme derive de deux series deja lissees :
    il faut donc `window` barres de plus que `plus_di` et `minus_di`, d'ou le
    warmup plus long. Rend `None` quand `+DI + -DI` vaut zero - un marche sans
    aucun mouvement directionnel n'a pas d'indice directionnel, et zero serait
    une reponse, pas une absence.
    """
    total = params.lookback + params.window
    high = ctx.values(Field.HIGH, total + 1)
    low = ctx.values(Field.LOW, total + 1)
    close = ctx.values(Field.CLOSE, total + 1)

    montee = high[1:] - high[:-1]
    descente = low[:-1] - low[1:]
    plus_dm = np.where((montee > descente) & (montee > 0.0), montee, 0.0)
    minus_dm = np.where((descente > montee) & (descente > 0.0), descente, 0.0)
    ranges = true_range_series(high, low, close)

    tr_lisse = wilder_smooth(ranges, params.window)
    plus_lisse = wilder_smooth(plus_dm, params.window)
    minus_lisse = wilder_smooth(minus_dm, params.window)

    utilisable = tr_lisse > 0.0
    if not bool(utilisable[-1]):
        return None
    plus_di = np.where(utilisable, 100.0 * plus_lisse / np.where(utilisable, tr_lisse, 1.0), 0.0)
    minus_di = np.where(utilisable, 100.0 * minus_lisse / np.where(utilisable, tr_lisse, 1.0), 0.0)

    if params.output is DirectionalOutput.PLUS_DI:
        return float(plus_di[-1])
    if params.output is DirectionalOutput.MINUS_DI:
        return float(minus_di[-1])

    somme = plus_di + minus_di
    if not bool(np.all(somme > 0.0)):
        return None
    dx = 100.0 * np.abs(plus_di - minus_di) / somme
    if dx.size < params.window:
        return None
    return float(wilder_smooth(dx, params.window)[-1])


__all__ = [
    "AdxParams",
    "DirectionalOutput",
    "WilderFieldParams",
    "WilderParams",
    "adx",
    "atr_wilder",
    "rsi_wilder",
    "true_range_series",
    "wilder_smooth",
]
