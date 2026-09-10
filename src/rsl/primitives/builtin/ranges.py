"""Primitives d'amplitude : ATR, extremes glissants."""

from __future__ import annotations

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import NoParams, PrimitiveParams, WindowParams, window_warmup
from rsl.primitives.builtin.params import HighWindowParams, LowWindowParams
from rsl.primitives.registry import primitive


@primitive(
    "atr",
    version=1,
    params=WindowParams,
    warmup=window_warmup(1),
    summary="Average True Range, moyenne SIMPLE des True Ranges (pas le lissage de Wilder).",
)
def atr(ctx: Context, params: WindowParams) -> float | None:
    """ATR en moyenne arithmetique des `window` derniers True Ranges.

    Volontairement la moyenne simple, pas le lissage de Wilder : celui-ci est
    une EMA deguisee et depend donc de toute l'histoire depuis l'origine. Une
    variante Wilder pourra etre enregistree comme `atr@2` sans toucher a
    celle-ci.

    `True Range = max(high - low, |high - close_prec|, |low - close_prec|)`
    exige la cloture precedente : d'ou un warmup de `window + 1` barres.
    """
    n = params.window
    high = ctx.values(Field.HIGH, n + 1)
    low = ctx.values(Field.LOW, n + 1)
    close = ctx.values(Field.CLOSE, n + 1)

    prev_close = close[:-1]
    true_range = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
    )
    return float(np.mean(true_range))


@primitive(
    "rolling_high",
    version=1,
    params=HighWindowParams,
    warmup=window_warmup(),
    summary="Plus haut des `window` dernieres barres closes.",
)
def rolling_high(ctx: Context, params: HighWindowParams) -> float | None:
    """Extreme haut glissant. Le defaut porte sur `high`, pas sur `close`."""
    return float(np.max(ctx.values(params.field, params.window)))


@primitive(
    "rolling_low",
    version=1,
    params=LowWindowParams,
    warmup=window_warmup(),
    summary="Plus bas des `window` dernieres barres closes.",
)
def rolling_low(ctx: Context, params: LowWindowParams) -> float | None:
    """Extreme bas glissant. Le defaut porte sur `low`, pas sur `close`."""
    return float(np.min(ctx.values(params.field, params.window)))


@primitive(
    "true_range",
    version=1,
    params=NoParams,
    warmup=2,
    summary="True Range de la barre courante, sans moyennage.",
)
def true_range(ctx: Context, params: PrimitiveParams) -> float | None:
    """`max(high - low, |high - close_prec|, |low - close_prec|)`.

    C'est la brique dont `atr` est la moyenne. Utile seule pour un stop cale
    sur l'amplitude de la SEULE barre d'entree, la ou l'ATR lisserait sur
    quatorze - et lisser, ici, c'est retarder.
    """
    previous_close = ctx.value(Field.CLOSE, lag=1)
    high = ctx.value(Field.HIGH)
    low = ctx.value(Field.LOW)
    return max(
        high - low,
        abs(high - previous_close),
        abs(low - previous_close),
    )
