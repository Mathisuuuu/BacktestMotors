"""Bandes et canaux : un niveau central, deux bornes.

Chaque famille se distingue par ce qui fixe la largeur - l'ecart-type pour
Bollinger, l'ATR pour Keltner, les extremes pour Donchian, un pourcentage fixe
pour l'enveloppe. Publier une primitive par famille, avec un parametre
`output`, evite de multiplier `bollinger_upper@1`, `bollinger_lower@1`... et
garantit que les trois bornes d'une meme bande sont toujours calculees avec
les memes reglages.
"""

from __future__ import annotations

from enum import StrEnum
from typing import cast

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import PrimitiveParams, WindowParams, window_warmup
from rsl.primitives.builtin.lissage import (
    ema_serie,
    securise,
    true_range_serie,
)
from rsl.primitives.builtin.params import FieldWindowParams
from rsl.primitives.registry import primitive


class BandOutput(StrEnum):
    """Quelle ligne de la bande lire."""

    UPPER = "upper"
    MIDDLE = "middle"
    LOWER = "lower"
    WIDTH = "width"
    PERCENT = "percent"


class BollingerParams(FieldWindowParams):
    """Bollinger : `multiplier` ecarts-types de part et d'autre d'une SMA."""

    multiplier: float = 2.0
    ddof: int = 1
    output: BandOutput = BandOutput.UPPER

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.multiplier <= 0.0:
            raise ValueError(f"multiplier doit etre > 0, recu {self.multiplier}")
        if self.ddof not in (0, 1):
            raise ValueError(f"ddof doit valoir 0 ou 1, recu {self.ddof}")
        if self.window <= self.ddof:
            raise ValueError(
                f"window ({self.window}) doit etre > ddof ({self.ddof}) : "
                f"sinon la variance n'est pas definie"
            )


class KeltnerParams(WindowParams):
    """Keltner : `multiplier` ATR de part et d'autre d'une EMA."""

    multiplier: float = 2.0
    seed_multiplier: int = 5
    output: BandOutput = BandOutput.UPPER

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.multiplier <= 0.0:
            raise ValueError(f"multiplier doit etre > 0, recu {self.multiplier}")
        if self.seed_multiplier < 2:
            raise ValueError(
                f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier}"
            )

    @property
    def lookback(self) -> int:
        return self.window * self.seed_multiplier


class DonchianParams(WindowParams):
    """Donchian : les extremes de la fenetre, sans lissage."""

    output: BandOutput = BandOutput.UPPER


class EnvelopeParams(FieldWindowParams):
    """Enveloppe : un pourcentage FIXE autour d'une SMA."""

    percent: float = 2.5
    output: BandOutput = BandOutput.UPPER

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.percent <= 0.0:
            raise ValueError(f"percent doit etre > 0, recu {self.percent}")


class AccelerationParams(WindowParams):
    """Bandes d'acceleration de Headley : largeur proportionnelle a l'amplitude."""

    factor: float = 4.0
    output: BandOutput = BandOutput.UPPER

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.factor <= 0.0:
            raise ValueError(f"factor doit etre > 0, recu {self.factor}")


def _lire(
    haut: float, milieu: float, bas: float, sortie: BandOutput, prix: float
) -> float | None:
    """Lecture commune : la sortie demandee, derivee du triplet.

    `width` et `percent` sont derives plutot que calcules a part - les trois
    lignes et les deux mesures ne peuvent donc pas se desynchroniser.
    """
    if sortie is BandOutput.UPPER:
        return haut
    if sortie is BandOutput.MIDDLE:
        return milieu
    if sortie is BandOutput.LOWER:
        return bas
    if sortie is BandOutput.WIDTH:
        return securise(haut - bas, milieu)
    return securise(prix - bas, haut - bas)


def keltner_warmup(params: PrimitiveParams) -> int:
    """L'EMA exige `lookback` barres, l'ATR une de plus (le True Range en
    consomme une pour la cloture precedente)."""
    return cast("KeltnerParams", params).lookback + 1


@primitive(
    "bollinger",
    version=1,
    params=BollingerParams,
    warmup=window_warmup(),
    summary="Bandes de Bollinger : upper, middle, lower, width ou percent_b.",
)
def bollinger(ctx: Context, params: BollingerParams) -> float | None:
    """SMA plus ou moins `multiplier` ecarts-types.

    `width` est la largeur relative (le « bandwidth »), `percent` la position
    du prix dans la bande (le « %B »), qui vaut 0 sur la borne basse et 1 sur
    la borne haute - et sort de `[0, 1]` quand le prix perce.

    Sur une serie plate l'ecart-type est nul : `width` et `percent` rendent
    alors `None` plutot que 0 ou une division par zero.
    """
    fenetre = ctx.values(params.field, params.window)
    milieu = float(np.mean(fenetre))
    ecart = float(np.std(fenetre, ddof=params.ddof))
    marge = params.multiplier * ecart
    return _lire(
        milieu + marge, milieu, milieu - marge, params.output, float(fenetre[-1])
    )


@primitive(
    "keltner",
    version=1,
    params=KeltnerParams,
    warmup=keltner_warmup,
    summary="Canal de Keltner : EMA plus ou moins `multiplier` ATR.",
)
def keltner(ctx: Context, params: KeltnerParams) -> float | None:
    """Meme forme que Bollinger, mais la largeur suit l'amplitude vraie.

    Difference qui compte : l'ecart-type de Bollinger ignore les gaps, l'ATR
    de Keltner les inclut. Sur des donnees a coupure de seance, les deux
    bandes ne disent pas la meme chose.
    """
    clotures = ctx.values(Field.CLOSE, params.lookback)
    milieu = float(ema_serie(clotures, params.window)[-1])

    besoin = params.window + 1
    trs = true_range_serie(
        ctx.values(Field.HIGH, besoin),
        ctx.values(Field.LOW, besoin),
        ctx.values(Field.CLOSE, besoin),
    )
    marge = params.multiplier * float(np.mean(trs))
    return _lire(
        milieu + marge, milieu, milieu - marge, params.output, float(clotures[-1])
    )


@primitive(
    "donchian",
    version=1,
    params=DonchianParams,
    warmup=window_warmup(),
    summary="Canal de Donchian : plus haut et plus bas des `window` dernieres barres.",
)
def donchian(ctx: Context, params: DonchianParams) -> float | None:
    """Le canal des suiveurs de tendance, sans aucun lissage.

    Attention a la lecture : la borne haute inclut la barre COURANTE, donc le
    prix ne peut jamais la depasser a la barre ou elle est lue. Une cassure se
    teste contre le canal decale - le noeud `lag` sert exactement a cela.
    """
    haut = float(np.max(ctx.values(Field.HIGH, params.window)))
    bas = float(np.min(ctx.values(Field.LOW, params.window)))
    return _lire(
        haut, (haut + bas) / 2.0, bas, params.output, ctx.value(Field.CLOSE)
    )


@primitive(
    "envelope",
    version=1,
    params=EnvelopeParams,
    warmup=window_warmup(),
    summary="Enveloppe a pourcentage fixe autour d'une moyenne simple.",
)
def envelope(ctx: Context, params: EnvelopeParams) -> float | None:
    """La bande la plus simple : elle ne s'adapte a rien.

    C'est son interet comme temoin : une strategie qui marche sur Bollinger
    mais pas sur l'enveloppe doit quelque chose a l'ADAPTATION de la largeur,
    pas au fait d'avoir une bande.
    """
    fenetre = ctx.values(params.field, params.window)
    milieu = float(np.mean(fenetre))
    marge = milieu * params.percent / 100.0
    return _lire(
        milieu + marge, milieu, milieu - marge, params.output, float(fenetre[-1])
    )


@primitive(
    "acceleration_bands",
    version=1,
    params=AccelerationParams,
    warmup=window_warmup(),
    summary="Bandes d'acceleration de Headley : largeur tiree de l'amplitude relative.",
)
def acceleration_bands(ctx: Context, params: AccelerationParams) -> float | None:
    """Largeur proportionnelle a `(high - low) / (high + low)`.

    Contrairement a Keltner, la largeur est calculee barre par barre PUIS
    moyennee : une seule barre tres large elargit moins la bande.
    """
    hauts = ctx.values(Field.HIGH, params.window)
    bas = ctx.values(Field.LOW, params.window)
    clotures = ctx.values(Field.CLOSE, params.window)

    sommes = hauts + bas
    if np.any(sommes <= 0.0):
        return None
    facteur = params.factor * (hauts - bas) / sommes
    superieure = float(np.mean(hauts * (1.0 + facteur)))
    inferieure = float(np.mean(bas * (1.0 - facteur)))
    milieu = float(np.mean(clotures))
    return _lire(
        superieure, milieu, inferieure, params.output, float(clotures[-1])
    )


@primitive(
    "squeeze",
    version=1,
    params=KeltnerParams,
    warmup=keltner_warmup,
    summary="Compression : 1 quand les bandes de Bollinger entrent dans le canal de Keltner.",
)
def squeeze(ctx: Context, params: KeltnerParams) -> float | None:
    """Le « TTM squeeze », reduit a son signal booleen.

    Vaut 1 quand la volatilite recente est basse au point que Bollinger tient
    a l'interieur de Keltner, 0 sinon. Ne dit RIEN de la direction : c'est un
    detecteur de compression, pas de tendance, et l'utiliser comme signal
    d'entree directionnel est une erreur de lecture classique.

    Les deux bandes sont calculees ici avec la meme fenetre et le meme
    multiplicateur, ce qui n'est pas la convention d'origine (20 / 2,0 pour
    Bollinger, 20 / 1,5 pour Keltner) mais rend la comparaison interpretable :
    un seul jeu de reglages a faire varier.
    """
    fenetre = ctx.values(Field.CLOSE, params.window)
    ecart = float(np.std(fenetre, ddof=1)) if params.window > 1 else 0.0
    demi_bollinger = params.multiplier * ecart

    besoin = params.window + 1
    trs = true_range_serie(
        ctx.values(Field.HIGH, besoin),
        ctx.values(Field.LOW, besoin),
        ctx.values(Field.CLOSE, besoin),
    )
    demi_keltner = params.multiplier * float(np.mean(trs))
    return 1.0 if demi_bollinger < demi_keltner else 0.0
