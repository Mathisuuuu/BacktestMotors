"""Transformations de prix : recombinaisons d'une barre, sans fenetre.

Ces primitives ne lissent rien et ne comparent rien - elles recombinent les
champs d'une barre, ou de la barre precedente. Elles sont ici parce que les
indicateurs classiques les supposent : le CCI travaille sur le prix typique,
les pivots sur la barre precedente, et les reecrire a chaque fois ferait
diverger les conventions.

Toutes ont un warmup de 1 ou 2 barres : c'est leur interet, elles sont
disponibles immediatement.
"""

from __future__ import annotations

from enum import StrEnum

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import NoParams, PrimitiveParams
from rsl.primitives.builtin.lissage import securise
from rsl.primitives.registry import primitive


class PivotOutput(StrEnum):
    """Quel niveau du systeme de pivots lire."""

    PP = "pp"
    R1 = "r1"
    R2 = "r2"
    R3 = "r3"
    S1 = "s1"
    S2 = "s2"
    S3 = "s3"


class PivotParams(PrimitiveParams):
    """Pivots classiques, calcules sur la barre PRECEDENTE."""

    output: PivotOutput = PivotOutput.PP


class HeikinOutput(StrEnum):
    """Quel champ de la bougie Heikin-Ashi lire."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"


class HeikinParams(PrimitiveParams):
    """Heikin-Ashi sur historique tronque."""

    lookback: int = 50
    output: HeikinOutput = HeikinOutput.CLOSE

    def model_post_init(self, _context: object, /) -> None:
        if self.lookback < 2:
            raise ValueError(f"lookback doit etre >= 2, recu {self.lookback}")


@primitive(
    "typical_price",
    version=1,
    params=NoParams,
    warmup=1,
    summary="Prix typique de la barre : `(high + low + close) / 3`.",
)
def typical_price(ctx: Context, _params: PrimitiveParams) -> float | None:
    """L'entree canonique du CCI, du MFI et du VWAP."""
    return (
        ctx.value(Field.HIGH) + ctx.value(Field.LOW) + ctx.value(Field.CLOSE)
    ) / 3.0


@primitive(
    "median_price",
    version=1,
    params=NoParams,
    warmup=1,
    summary="Milieu de la barre : `(high + low) / 2`.",
)
def median_price(ctx: Context, _params: PrimitiveParams) -> float | None:
    """Ignore la cloture : utile quand elle est bruitee par le carnet."""
    return (ctx.value(Field.HIGH) + ctx.value(Field.LOW)) / 2.0


@primitive(
    "weighted_close",
    version=1,
    params=NoParams,
    warmup=1,
    summary="Cloture ponderee : `(high + low + 2*close) / 4`.",
)
def weighted_close(ctx: Context, _params: PrimitiveParams) -> float | None:
    """Prix typique qui donne double poids a la cloture."""
    return (
        ctx.value(Field.HIGH) + ctx.value(Field.LOW) + 2.0 * ctx.value(Field.CLOSE)
    ) / 4.0


@primitive(
    "average_price",
    version=1,
    params=NoParams,
    warmup=1,
    summary="Moyenne des quatre prix de la barre : `(open + high + low + close) / 4`.",
)
def average_price(ctx: Context, _params: PrimitiveParams) -> float | None:
    """Le seul de la famille qui tienne compte de l'ouverture."""
    return (
        ctx.value(Field.OPEN)
        + ctx.value(Field.HIGH)
        + ctx.value(Field.LOW)
        + ctx.value(Field.CLOSE)
    ) / 4.0


@primitive(
    "bar_range",
    version=1,
    params=NoParams,
    warmup=1,
    summary="Amplitude brute de la barre : `high - low`, en unites de prix.",
)
def bar_range(ctx: Context, _params: PrimitiveParams) -> float | None:
    """A distinguer du True Range, qui inclut le gap avec la barre precedente."""
    return ctx.value(Field.HIGH) - ctx.value(Field.LOW)


@primitive(
    "bar_range_pct",
    version=1,
    params=NoParams,
    warmup=1,
    summary="Amplitude de la barre rapportee a sa cloture, en pourcentage.",
)
def bar_range_pct(ctx: Context, _params: PrimitiveParams) -> float | None:
    """Version sans unite de `bar_range@1`, donc comparable entre instruments."""
    return securise(
        100.0 * (ctx.value(Field.HIGH) - ctx.value(Field.LOW)),
        ctx.value(Field.CLOSE),
    )


@primitive(
    "gap",
    version=1,
    params=NoParams,
    warmup=2,
    summary="Ecart entre l'ouverture et la cloture precedente, en pourcentage.",
)
def gap(ctx: Context, _params: PrimitiveParams) -> float | None:
    """Mesure ce que la barre a saute a l'ouverture.

    Sur les series `.v.0` continues du depot, un gap non nul signale une
    coupure de seance ou un week-end - le socle ne les devine pas, mais
    l'indicateur les rend lisibles.
    """
    return securise(
        100.0 * (ctx.value(Field.OPEN) - ctx.value(Field.CLOSE, lag=1)),
        ctx.value(Field.CLOSE, lag=1),
    )


@primitive(
    "body_ratio",
    version=1,
    params=NoParams,
    warmup=1,
    summary="Part du corps de la bougie dans son amplitude totale, de 0 a 1.",
)
def body_ratio(ctx: Context, _params: PrimitiveParams) -> float | None:
    """Proche de 0 : bougie en doji. Proche de 1 : marubozu.

    Rend `None` sur une barre sans amplitude - une barre plate n'a pas de
    proportion de corps, et repondre 0 la confondrait avec un doji parfait.
    """
    return securise(
        abs(ctx.value(Field.CLOSE) - ctx.value(Field.OPEN)),
        ctx.value(Field.HIGH) - ctx.value(Field.LOW),
    )


@primitive(
    "close_location",
    version=1,
    params=NoParams,
    warmup=1,
    summary="Position de la cloture dans la barre, de -1 (au plus bas) a +1.",
)
def close_location(ctx: Context, _params: PrimitiveParams) -> float | None:
    """Le « CLV » de Chaikin, brique de l'accumulation / distribution."""
    haut, bas, cloture = ctx.value(Field.HIGH), ctx.value(Field.LOW), ctx.value(Field.CLOSE)
    return securise((cloture - bas) - (haut - cloture), haut - bas)


@primitive(
    "pivot",
    version=1,
    params=PivotParams,
    warmup=2,
    summary="Pivots classiques calcules sur la barre PRECEDENTE : pp, r1..r3, s1..s3.",
)
def pivot(ctx: Context, params: PivotParams) -> float | None:
    """Niveaux de support et resistance de la seance, formule classique.

    Calcules sur la barre precedente, jamais sur la barre courante : un pivot
    de la barre en cours utiliserait son `high` et son `low`, qui ne sont
    connus qu'a sa cloture. C'est exactement la fuite que le socle interdit,
    et c'est l'erreur la plus repandue dans les implementations de pivots.

    Sur des barres quotidiennes, ce sont les pivots du jour. Sur des barres
    d'une minute, ce sont les pivots de la minute precedente - le socle ne
    connait pas la notion de seance ici ; c'est le role du noeud `session`.
    """
    haut = ctx.value(Field.HIGH, lag=1)
    bas = ctx.value(Field.LOW, lag=1)
    cloture = ctx.value(Field.CLOSE, lag=1)
    pp = (haut + bas + cloture) / 3.0
    amplitude = haut - bas
    niveaux = {
        PivotOutput.PP: pp,
        PivotOutput.R1: 2.0 * pp - bas,
        PivotOutput.S1: 2.0 * pp - haut,
        PivotOutput.R2: pp + amplitude,
        PivotOutput.S2: pp - amplitude,
        PivotOutput.R3: haut + 2.0 * (pp - bas),
        PivotOutput.S3: bas - 2.0 * (haut - pp),
    }
    return niveaux[params.output]


@primitive(
    "heikin_ashi",
    version=1,
    params=HeikinParams,
    warmup=lambda p: max(getattr(p, "lookback", 50), 2),
    summary="Bougie Heikin-Ashi : open, high, low ou close de la bougie lissee.",
)
def heikin_ashi(ctx: Context, params: HeikinParams) -> float | None:
    """Bougie lissee, definie par recurrence sur l'ouverture.

    `ha_open[t] = (ha_open[t-1] + ha_close[t-1]) / 2` depend en theorie de
    toute l'histoire depuis l'origine. Comme pour l'EMA, elle est calculee sur
    un historique TRONQUE de `lookback` barres, amorce par la moyenne
    `(open + close) / 2` de la premiere barre de cet historique.

    La convergence est rapide - le poids de l'amorce est divise par deux a
    chaque barre, donc 2^-50 apres 50 barres - mais elle n'est pas exacte, et
    ce module ne pretend pas l'inverse.
    """
    opens = ctx.values(Field.OPEN, params.lookback)
    highs = ctx.values(Field.HIGH, params.lookback)
    lows = ctx.values(Field.LOW, params.lookback)
    closes = ctx.values(Field.CLOSE, params.lookback)

    ha_close = (opens + highs + lows + closes) / 4.0
    ha_open = float(opens[0] + closes[0]) / 2.0
    for rang in range(1, params.lookback):
        ha_open = (ha_open + float(ha_close[rang - 1])) / 2.0

    dernier_close = float(ha_close[-1])
    if params.output is HeikinOutput.CLOSE:
        return dernier_close
    if params.output is HeikinOutput.OPEN:
        return ha_open
    if params.output is HeikinOutput.HIGH:
        return max(float(highs[-1]), ha_open, dernier_close)
    return min(float(lows[-1]), ha_open, dernier_close)
