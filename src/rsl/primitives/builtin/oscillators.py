"""Oscillateurs bornes.

Un oscillateur ramene une serie de prix dans un intervalle fixe, ce qui le rend
comparable d'un instrument a l'autre et d'une epoque a l'autre. C'est ce qui
manquait le plus au vocabulaire : sans lui, un seuil de sur-achat s'ecrit en
unites de prix et ne veut rien dire hors de son echantillon.
"""

from __future__ import annotations

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import window_warmup
from rsl.primitives.builtin.params import FieldWindowParams
from rsl.primitives.registry import primitive


@primitive(
    "rsi",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Relative Strength Index, moyennes SIMPLES des hausses et des baisses.",
)
def rsi(ctx: Context, params: FieldWindowParams) -> float | None:
    """RSI sur `window` variations.

        RSI = 100 - 100 / (1 + moyenne_hausses / moyenne_baisses)

    Moyennes arithmetiques, PAS le lissage de Wilder - meme raison que pour
    `atr@1` : le lissage de Wilder est une moyenne exponentielle deguisee, donc
    dependante de toute l'histoire depuis l'origine, ce qu'une primitive ne
    voit pas. Une variante Wilder pourra etre enregistree comme `rsi@2` sans
    toucher a celle-ci.

    Cas limites, traites explicitement plutot que subis :
    - aucune baisse sur la fenetre -> 100, la borne, et non une division par
      zero ;
    - aucune variation du tout -> `None`, parce qu'une serie plate n'a ni force
      ni faiblesse relative, et repondre 50 serait inventer une information.
    """
    values = ctx.values(params.field, params.window + 1)
    deltas = np.diff(values)
    gains = float(np.mean(np.maximum(deltas, 0.0)))
    losses = float(np.mean(np.maximum(-deltas, 0.0)))

    if gains == 0.0 and losses == 0.0:
        return None
    if losses == 0.0:
        return 100.0
    if gains == 0.0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


@primitive(
    "stochastic",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Position de la cloture dans l'amplitude des `window` dernieres barres, en %.",
)
def stochastic(ctx: Context, params: FieldWindowParams) -> float | None:
    """`%K` : ou se situe la cloture entre le plus bas et le plus haut recents.

    Retourne `None` quand l'amplitude est nulle - une barre sans amplitude n'a
    pas de position relative, et repondre 50 serait une invention.
    """
    highest = float(np.max(ctx.values(Field.HIGH, params.window)))
    lowest = float(np.min(ctx.values(Field.LOW, params.window)))
    amplitude = highest - lowest
    if amplitude <= 0.0:
        return None
    return 100.0 * (ctx.value(params.field) - lowest) / amplitude
