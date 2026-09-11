"""Momentum et convergence : MACD, CCI, Williams %R, ratio d'efficience.

Ces quatre-la ont un point commun : aucune ne se compose a partir des
primitives deja publiees. Une difference de deux EMA, si - c'est un `arith` -
mais la LIGNE DE SIGNAL du MACD est une EMA d'une expression, et `primitive`
est une feuille qui ne lit que des champs de prix. Le noeud `rolling` sait
desormais lisser une expression (`stat: "ema"`), mais sur la seule fenetre
qu'il voit ; `macd@1` porte ici la definition usuelle, amorcee sur un
historique plus profond.
"""

from __future__ import annotations

from enum import StrEnum
from typing import cast

import numpy as np
import numpy.typing as npt

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import PrimitiveParams, window_warmup
from rsl.primitives.builtin.params import FieldWindowParams
from rsl.primitives.registry import primitive

FloatArray = npt.NDArray[np.float64]


class MacdOutput(StrEnum):
    """Quelle des trois series du MACD lire."""

    LINE = "line"
    SIGNAL = "signal"
    HISTOGRAM = "histogram"


class MacdParams(PrimitiveParams):
    """Trois fenetres, un champ, une sortie.

    `fast < slow` est verifie : l'inverse produit un MACD de signe oppose, ce
    qui n'est pas une erreur mathematique mais presque surement une faute de
    frappe. Mieux vaut lever que trader l'inverse de ce qu'on croit.
    """

    fast: int = 12
    slow: int = 26
    signal: int = 9
    field: Field = Field.CLOSE
    seed_multiplier: int = 5
    output: MacdOutput = MacdOutput.LINE

    def model_post_init(self, _context: object, /) -> None:
        for nom, valeur in (("fast", self.fast), ("slow", self.slow), ("signal", self.signal)):
            if valeur < 1:
                raise ValueError(f"{nom} doit etre >= 1, recu {valeur}")
        if self.fast >= self.slow:
            raise ValueError(
                f"fast ({self.fast}) doit etre < slow ({self.slow}) : "
                f"l'inverse produit un MACD de signe oppose"
            )
        if self.seed_multiplier < 2:
            raise ValueError(
                f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier} : "
                f"en dessous, l'amorce domine le resultat"
            )

    @property
    def lookback(self) -> int:
        return self.slow * self.seed_multiplier + self.signal


def ema_series(values: FloatArray, window: int) -> FloatArray:
    """Serie d'EMA, amorcee par la moyenne simple des `window` premieres valeurs.

    Rend `len(values) - window + 1` elements. Meme convention d'amorce que
    `ema@1` : sur un historique tronque, le poids residuel de l'amorce decroit
    en `(1 - alpha)^k` et reste surtout DETERMINISTE.
    """
    alpha = 2.0 / (window + 1.0)
    sortie = np.empty(values.size - window + 1, dtype=np.float64)
    courant = float(np.mean(values[:window]))
    sortie[0] = courant
    for indice, valeur in enumerate(values[window:], start=1):
        courant = alpha * float(valeur) + (1.0 - alpha) * courant
        sortie[indice] = courant
    return sortie


@primitive(
    "macd",
    version=1,
    params=MacdParams,
    warmup=lambda p: cast("MacdParams", p).lookback,
    summary="MACD : `line`, `signal` ou `histogram` au choix, sur historique tronque.",
)
def macd(ctx: Context, params: MacdParams) -> float | None:
    """MACD et sa ligne de signal.

        line      = EMA(fast) - EMA(slow)
        signal    = EMA(line, signal)
        histogram = line - signal

    Les deux EMA sont calculees sur le MEME historique puis alignees sur la
    plus courte des deux series - celle de `slow`, qui demarre plus tard.
    Aligner sur la plus longue ferait entrer dans la difference des points ou
    l'une des deux n'est pas encore definie.
    """
    valeurs = ctx.values(params.field, params.lookback)
    rapide = ema_series(valeurs, params.fast)
    lente = ema_series(valeurs, params.slow)
    ligne = rapide[-lente.size :] - lente

    if params.output is MacdOutput.LINE:
        return float(ligne[-1])
    if ligne.size < params.signal:
        return None
    signal = ema_series(ligne, params.signal)
    if params.output is MacdOutput.SIGNAL:
        return float(signal[-1])
    return float(ligne[-1] - signal[-1])


@primitive(
    "cci",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Commodity Channel Index sur le prix typique (high + low + close) / 3.",
)
def cci(ctx: Context, params: FieldWindowParams) -> float | None:
    """CCI de Lambert.

        CCI = (prix_typique - SMA) / (0.015 * ecart absolu moyen)

    Le champ `field` est ignore : le CCI est defini sur le prix typique, pas
    sur une colonne au choix. Il reste dans les parametres pour que le modele
    soit celui, deja publie, des primitives a fenetre - le declarer et ne pas
    s'en servir serait pire, donc il est nomme ici.

    Rend `None` quand l'ecart absolu moyen est nul : une serie parfaitement
    plate n'a pas de deviation, et la division n'est pas definie.
    """
    n = params.window
    typique = (
        ctx.values(Field.HIGH, n) + ctx.values(Field.LOW, n) + ctx.values(Field.CLOSE, n)
    ) / 3.0
    moyenne = float(np.mean(typique))
    ecart = float(np.mean(np.abs(typique - moyenne)))
    if ecart <= 0.0:
        return None
    return (float(typique[-1]) - moyenne) / (0.015 * ecart)


@primitive(
    "williams_r",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Williams %R : position de la cloture dans l'amplitude, de -100 a 0.",
)
def williams_r(ctx: Context, params: FieldWindowParams) -> float | None:
    """%R de Williams.

        %R = -100 * (plus_haut - cloture) / (plus_haut - plus_bas)

    Proche du stochastique mais borne dans [-100, 0]. Rend `None` sur une
    amplitude nulle - `window` barres au meme prix ne situent la cloture nulle
    part.
    """
    n = params.window
    plus_haut = float(np.max(ctx.values(Field.HIGH, n)))
    plus_bas = float(np.min(ctx.values(Field.LOW, n)))
    amplitude = plus_haut - plus_bas
    if amplitude <= 0.0:
        return None
    return -100.0 * (plus_haut - ctx.value(Field.CLOSE)) / amplitude


@primitive(
    "efficiency_ratio",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Ratio d'efficience de Kaufman : trajet net rapporte au chemin parcouru.",
)
def efficiency_ratio(ctx: Context, params: FieldWindowParams) -> float | None:
    """Efficience directionnelle, entre 0 et 1.

        ER = |cloture_t - cloture_(t-n)| / somme(|variations|)

    Proche de 1 : le marche va droit. Proche de 0 : il fait le meme chemin en
    zigzag. C'est la mesure qui distingue une tendance d'un marche agite sans
    passer par la volatilite, laquelle confond les deux.

    Rend `None` si aucune variation : un marche immobile n'est ni efficient ni
    inefficient.
    """
    valeurs = ctx.values(params.field, params.window + 1)
    chemin = float(np.sum(np.abs(np.diff(valeurs))))
    if chemin <= 0.0:
        return None
    return abs(float(valeurs[-1]) - float(valeurs[0])) / chemin
