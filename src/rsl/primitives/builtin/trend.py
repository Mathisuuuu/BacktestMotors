"""Primitives de tendance : moyennes mobiles."""

from __future__ import annotations

from typing import cast

import numpy as np

from rsl.data.feed import Context
from rsl.primitives.base import window_warmup
from rsl.primitives.builtin.params import EmaParams, FieldWindowParams
from rsl.primitives.registry import primitive


@primitive(
    "sma",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Moyenne simple des `window` dernieres barres closes.",
)
def sma(ctx: Context, params: FieldWindowParams) -> float | None:
    """Moyenne simple sur fenetre glissante passee."""
    values = ctx.values(params.field, params.window)
    return float(np.mean(values))


@primitive(
    "ema",
    version=1,
    params=EmaParams,
    warmup=lambda p: cast("EmaParams", p).lookback,
    summary="Moyenne exponentielle sur historique tronque, amorcee par une SMA.",
)
def ema(ctx: Context, params: EmaParams) -> float | None:
    """Moyenne exponentielle deterministe.

    Boucle explicite : la recursion de l'EMA n'est pas vectorisable sans
    accumulateur, et la correction prime sur la vitesse a cette etape.
    """
    values = ctx.values(params.field, params.lookback)
    alpha = 2.0 / (params.window + 1.0)
    current = float(np.mean(values[: params.window]))
    for value in values[params.window :]:
        current = alpha * float(value) + (1.0 - alpha) * current
    return current
