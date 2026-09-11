"""Primitives de volume : VWAP et OBV, toutes deux sur FENETRE.

Les deux sont usuellement definies depuis le debut de la seance ou depuis
l'origine de la serie. Aucune des deux formes n'est calculable ici, et pour la
meme raison : une primitive ne voit que les `n` dernieres barres closes, et le
socle ne connait pas de notion de seance - les series continues `.v.0` sont
trouees, avec des coupures de maintenance et des week-ends de 49 heures
(`docs/execution-model.md`).

Elles sont donc definies sur une fenetre glissante explicite. Ce n'est pas une
approximation cachee : un VWAP de 20 barres est une quantite bien definie, ce
n'est simplement pas le VWAP de seance. Le nom du parametre le dit.
"""

from __future__ import annotations

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import WindowParams, window_warmup
from rsl.primitives.registry import primitive


@primitive(
    "vwap",
    version=1,
    params=WindowParams,
    warmup=window_warmup(),
    summary="Prix moyen pondere par les volumes, sur FENETRE (pas sur la seance).",
)
def vwap(ctx: Context, params: WindowParams) -> float | None:
    """VWAP glissant sur `window` barres.

        VWAP = somme(prix_typique * volume) / somme(volume)

    Rend `None` quand le volume total est nul : sans echange, il n'y a pas de
    prix moyen pondere. Zero serait un prix, donc une reponse fausse.
    """
    n = params.window
    typique = (
        ctx.values(Field.HIGH, n) + ctx.values(Field.LOW, n) + ctx.values(Field.CLOSE, n)
    ) / 3.0
    volumes = ctx.values(Field.VOLUME, n)
    total = float(np.sum(volumes))
    if total <= 0.0:
        return None
    return float(np.sum(typique * volumes)) / total


@primitive(
    "obv",
    version=1,
    params=WindowParams,
    warmup=window_warmup(1),
    summary="On-Balance Volume cumule sur FENETRE (pas depuis l'origine).",
)
def obv(ctx: Context, params: WindowParams) -> float | None:
    """OBV sur `window` barres.

        OBV = somme(signe(variation de cloture) * volume)

    Une barre sans variation n'apporte rien, ni en plus ni en moins : c'est la
    convention de Granville, et elle evite d'attribuer une direction a un
    volume qui n'en exprime aucune.

    Le niveau absolu n'a pas de sens - il depend de la fenetre choisie. Ce qui
    se lit, c'est son signe et sa pente, par exemple via
    `rolling(stat="slope", inner=primitive("obv@1"))`.
    """
    n = params.window
    clotures = ctx.values(Field.CLOSE, n + 1)
    volumes = ctx.values(Field.VOLUME, n + 1)[1:]
    return float(np.sum(np.sign(np.diff(clotures)) * volumes))
