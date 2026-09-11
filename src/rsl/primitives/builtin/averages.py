"""Moyennes et lissages.

Une moyenne mobile est le plus petit indicateur qui existe, et c'est pour cela
qu'il y en a tant : chacune fait un compromis different entre retard et bruit.
Les nommer separement plutot que d'ajouter un parametre `kind` a `sma@1` est
delibere - un parametre aurait force `sma@1` a changer de sens, ce que le
registre versionne interdit.

Les formes recursives suivent la convention d'amorce de `lissage.py` :
historique tronque, amorce par une SMA, resultat deterministe.
"""

from __future__ import annotations

from math import lgamma
from typing import cast

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import PrimitiveParams, WarmupFn, WindowParams, window_warmup
from rsl.primitives.builtin.lissage import (
    ema_de,
    ema_serie,
    pente_de,
    securise,
    sma_serie,
    wilder_serie,
    wma_de,
    wma_serie,
)
from rsl.primitives.builtin.params import FieldWindowParams
from rsl.primitives.registry import primitive


class SeedParams(FieldWindowParams):
    """Fenetre + profondeur de l'historique tronque des formes recursives."""

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


class AlmaParams(FieldWindowParams):
    """ALMA : `offset` place le sommet de la gaussienne, `sigma` sa largeur."""

    offset: float = 0.85
    sigma: float = 6.0

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if not 0.0 <= self.offset <= 1.0:
            raise ValueError(f"offset doit etre dans [0, 1], recu {self.offset}")
        if self.sigma <= 0.0:
            raise ValueError(f"sigma doit etre > 0, recu {self.sigma}")


class T3Params(SeedParams):
    """T3 de Tillson : `volume_factor` regle l'agressivite de la correction."""

    volume_factor: float = 0.7

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if not 0.0 <= self.volume_factor <= 1.0:
            raise ValueError(
                f"volume_factor doit etre dans [0, 1], recu {self.volume_factor}"
            )

    @property
    def lookback(self) -> int:
        """Assez de barres pour SIX EMA imbriquees, pas seulement pour une.

        Chaque EMA consomme `window - 1` barres de son entree. Six empilees en
        consomment donc `6 * (window - 1)`, plus `window` pour la derniere
        amorce. Avec le `seed_multiplier` de 5 commun au reste du depot, une
        fenetre de 10 demandait 64 barres et n'en recevait que 50 : la
        primitive rendait `None` a CHAQUE barre, sans erreur et sans trace.

        Defaut du meme genre que celui de [[lessons]] L13 - une capacite
        publiee, atteignable par personne. Trouve par le test de forme fermee
        « une moyenne d'une constante vaut la constante », pas par relecture.
        """
        return max(super().lookback, 6 * (self.window - 1) + self.window)


class KamaParams(SeedParams):
    """KAMA : bornes rapide et lente entre lesquelles le lissage s'adapte."""

    fast: int = 2
    slow: int = 30

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.fast < 1 or self.slow < 1:
            raise ValueError(f"fast et slow doivent etre >= 1, recus {self.fast}/{self.slow}")
        if self.fast >= self.slow:
            raise ValueError(
                f"fast ({self.fast}) doit etre < slow ({self.slow}) : sinon "
                f"l'adaptation se fait a l'envers"
            )


def seed_warmup(offset: int = 0) -> WarmupFn:
    """Warmup des primitives a historique tronque."""

    def compute(params: PrimitiveParams) -> int:
        return cast("SeedParams", params).lookback + offset

    return compute


def zlema_warmup(params: PrimitiveParams) -> int:
    """L'historique tronque PLUS le decalage de la correction de retard.

    Oublier ce decalage fait lever `InsufficientHistoryError` en plein run :
    la primitive lit `lookback + retard` barres. Attrape par le parcours du
    registre (`tests/adversarial/test_registre_primitives.py`), jamais par
    une relecture.
    """
    reglages = cast("SeedParams", params)
    return reglages.lookback + (reglages.window - 1) // 2


def hull_warmup(params: PrimitiveParams) -> int:
    fenetre = cast("FieldWindowParams", params).window
    return fenetre + max(int(np.sqrt(fenetre)), 1)


def trima_warmup(params: PrimitiveParams) -> int:
    demi = (cast("FieldWindowParams", params).window + 1) // 2
    return 2 * demi - 1


# ---------------------------------------------------------------------------
# Ponderations fixes : une somme ponderee de la fenetre, sans recursion
# ---------------------------------------------------------------------------


@primitive(
    "wma",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Moyenne ponderee lineairement : poids 1..window, le plus recent le plus lourd.",
)
def wma(ctx: Context, params: FieldWindowParams) -> float | None:
    """Reduit le retard d'une SMA sans introduire de recursion.

    Le retard d'une SMA(w) sur une rampe est `(w-1)/2` barres ; celui d'une
    WMA(w) est `(w-1)/3`. C'est tout ce qu'elle apporte, et c'est verifiable.
    """
    return wma_de(ctx.values(params.field, params.window), params.window)


@primitive(
    "trima",
    version=1,
    params=FieldWindowParams,
    warmup=trima_warmup,
    summary="Moyenne triangulaire : une SMA appliquee a une SMA, poids en triangle.",
)
def trima(ctx: Context, params: FieldWindowParams) -> float | None:
    """SMA d'une SMA : deux fois plus lisse qu'une SMA, deux fois plus en retard.

    Les deux sous-fenetres valent `(window+1)//2`, convention de TA-Lib. Pour
    une fenetre paire le triangle n'est pas symetrique ; choisir l'autre
    arrondi donnerait un indicateur different sous le meme nom.
    """
    demi = (params.window + 1) // 2
    valeurs = ctx.values(params.field, 2 * demi - 1)
    return float(sma_serie(sma_serie(valeurs, demi), demi)[-1])


@primitive(
    "swma",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Moyenne ponderee SYMETRIQUE : poids en triangle centre sur la fenetre.",
)
def swma(ctx: Context, params: FieldWindowParams) -> float | None:
    """Poids symetriques, donc aucun privilege a la barre la plus recente.

    A utiliser en connaissance de cause : centrer les poids sur une fenetre
    PASSEE ne regarde pas le futur, mais decale le resultat d'environ
    `(window-1)/2` barres. Un filtre centre au sens du traitement du signal
    exigerait des barres futures - il est inexprimable ici, et c'est voulu.
    """
    fenetre = ctx.values(params.field, params.window)
    milieu = (params.window - 1) / 2.0
    poids = (milieu + 1.0) - np.abs(np.arange(params.window, dtype=np.float64) - milieu)
    return securise(float(np.dot(fenetre, poids)), float(poids.sum()))


def _log_binomial(n: int, k: int) -> float:
    """En logarithmes : `comb(60, 30)` depasse 1e17 et perdrait des chiffres."""
    return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)


@primitive(
    "pwma",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Moyenne ponderee par les coefficients binomiaux (triangle de Pascal).",
)
def pwma(ctx: Context, params: FieldWindowParams) -> float | None:
    """Ponderation binomiale : l'approximation discrete d'une gaussienne."""
    fenetre = ctx.values(params.field, params.window)
    n = params.window - 1
    poids = np.exp(
        np.array([_log_binomial(n, k) for k in range(params.window)], dtype=np.float64)
    )
    return securise(float(np.dot(fenetre, poids)), float(poids.sum()))


@primitive(
    "alma",
    version=1,
    params=AlmaParams,
    warmup=window_warmup(),
    summary="Arnaud Legoux : gaussienne decalee, compromis reglable retard / bruit.",
)
def alma(ctx: Context, params: AlmaParams) -> float | None:
    """Gaussienne dont `offset` deplace le sommet vers le present.

    `offset=1` donne tout le poids a la barre la plus recente (aucun retard,
    aucun lissage), `offset=0` a la plus ancienne. Le defaut 0,85 est celui de
    la publication d'origine.
    """
    fenetre = ctx.values(params.field, params.window)
    sommet = params.offset * (params.window - 1)
    largeur = params.window / params.sigma
    indices = np.arange(params.window, dtype=np.float64)
    poids = np.exp(-((indices - sommet) ** 2) / (2.0 * largeur * largeur))
    return securise(float(np.dot(fenetre, poids)), float(poids.sum()))


# ---------------------------------------------------------------------------
# Formes recursives : historique tronque, amorce par une SMA
# ---------------------------------------------------------------------------


@primitive(
    "smma",
    version=1,
    params=SeedParams,
    warmup=seed_warmup(),
    summary="Moyenne lissee de Wilder (`alpha = 1/window`), dite aussi RMA.",
)
def smma(ctx: Context, params: SeedParams) -> float | None:
    """La moyenne qui sous-tend `rsi_wilder@1` et `atr_wilder@1`.

    Publiee separement parce qu'elle sert d'entree a d'autres indicateurs :
    sans elle, chacun la reimplementerait avec sa propre amorce.
    """
    valeurs = ctx.values(params.field, params.lookback)
    return float(wilder_serie(valeurs, params.window)[-1])


@primitive(
    "dema",
    version=1,
    params=SeedParams,
    warmup=seed_warmup(),
    summary="Double EMA : `2*EMA - EMA(EMA)`, deux fois moins en retard.",
)
def dema(ctx: Context, params: SeedParams) -> float | None:
    """Corrige le retard de l'EMA en soustrayant son propre retard.

    Contrepartie assumee : l'extrapolation depasse les extremes de la serie.
    Une DEMA n'est PAS bornee par `[min, max]` de sa fenetre, contrairement a
    une SMA - un test le verifie, pour que ce ne soit pas decouvert en run.
    """
    valeurs = ctx.values(params.field, params.lookback)
    premiere = ema_serie(valeurs, params.window)
    if premiere.size < params.window:
        return None
    seconde = ema_serie(premiere, params.window)
    return 2.0 * float(premiere[-1]) - float(seconde[-1])


@primitive(
    "tema",
    version=1,
    params=SeedParams,
    warmup=seed_warmup(),
    summary="Triple EMA : `3*EMA - 3*EMA(EMA) + EMA(EMA(EMA))`.",
)
def tema(ctx: Context, params: SeedParams) -> float | None:
    """Meme idee que `dema@1`, poussee d'un cran - et meme depassement."""
    valeurs = ctx.values(params.field, params.lookback)
    un = ema_serie(valeurs, params.window)
    if un.size < params.window:
        return None
    deux = ema_serie(un, params.window)
    if deux.size < params.window:
        return None
    trois = ema_serie(deux, params.window)
    return 3.0 * float(un[-1]) - 3.0 * float(deux[-1]) + float(trois[-1])


@primitive(
    "t3",
    version=1,
    params=T3Params,
    warmup=seed_warmup(),
    summary="T3 de Tillson : six EMA combinees, lissage fort a retard contenu.",
)
def t3(ctx: Context, params: T3Params) -> float | None:
    """Combinaison polynomiale de six EMA successives.

    `volume_factor` regle l'agressivite : 0 donne un lissage triple ordinaire,
    1 le maximum de correction de retard - et le maximum de depassement.
    """
    courant = ctx.values(params.field, params.lookback)
    etapes: list[float] = []
    for _ in range(6):
        if courant.size < params.window:
            return None
        courant = ema_serie(courant, params.window)
        etapes.append(float(courant[-1]))
    v = params.volume_factor
    c1 = -(v**3)
    c2 = 3.0 * v * v + 3.0 * v**3
    c3 = -6.0 * v * v - 3.0 * v - 3.0 * v**3
    c4 = 1.0 + 3.0 * v + v**3 + 3.0 * v * v
    return c1 * etapes[5] + c2 * etapes[4] + c3 * etapes[3] + c4 * etapes[2]


@primitive(
    "zlema",
    version=1,
    params=SeedParams,
    warmup=zlema_warmup,
    summary="EMA a retard reduit, lissee sur la serie corrigee de son propre retard.",
)
def zlema(ctx: Context, params: SeedParams) -> float | None:
    """EMA appliquee a `2*x[t] - x[t-lag]`, avec `lag = (window-1)//2`.

    La correction n'utilise QUE des barres passees : elle extrapole la
    tendance recente, elle ne lit pas en avant.
    """
    retard = (params.window - 1) // 2
    valeurs = ctx.values(params.field, params.lookback + retard)
    if retard == 0:
        return ema_de(valeurs, params.window)
    corrigee = 2.0 * valeurs[retard:] - valeurs[: valeurs.size - retard]
    return ema_de(corrigee, params.window)


@primitive(
    "hma",
    version=1,
    params=FieldWindowParams,
    warmup=hull_warmup,
    summary="Hull : `WMA(2*WMA(w/2) - WMA(w), sqrt(w))`, tres peu de retard.",
)
def hma(ctx: Context, params: FieldWindowParams) -> float | None:
    """La moyenne la plus reactive de la famille, au prix d'un depassement net.

    Elle exige `window + sqrt(window)` barres : la WMA finale porte sur
    `sqrt(window)` valeurs d'une serie deja calculee sur `window`.
    """
    racine = max(int(np.sqrt(params.window)), 1)
    demi = max(params.window // 2, 1)
    valeurs = ctx.values(params.field, params.window + racine)
    rapide = wma_serie(valeurs, demi)[-racine:]
    lente = wma_serie(valeurs, params.window)[-racine:]
    if rapide.size < racine or lente.size < racine:
        return None
    return wma_de(2.0 * rapide - lente, racine)


@primitive(
    "kama",
    version=1,
    params=KamaParams,
    warmup=seed_warmup(1),
    summary="Kaufman adaptative : rapide en tendance, lente en marche lateral.",
)
def kama(ctx: Context, params: KamaParams) -> float | None:
    """Le lissage suit le ratio d'efficience : trajet net / chemin parcouru.

    Quand le marche avance en ligne droite, le ratio tend vers 1 et la moyenne
    devient quasi instantanee ; quand il oscille, il tend vers 0 et elle se
    fige. C'est l'adaptation la plus simple qui fonctionne.
    """
    valeurs = ctx.values(params.field, params.lookback + 1)
    rapide = 2.0 / (params.fast + 1.0)
    lente = 2.0 / (params.slow + 1.0)
    fenetre = params.window
    courant = float(np.mean(valeurs[: fenetre + 1]))
    for rang in range(fenetre + 1, valeurs.size):
        tranche = valeurs[rang - fenetre : rang + 1]
        direction = abs(float(tranche[-1]) - float(tranche[0]))
        chemin = float(np.sum(np.abs(np.diff(tranche))))
        efficience = 0.0 if chemin == 0.0 else direction / chemin
        alpha = (efficience * (rapide - lente) + lente) ** 2
        courant += alpha * (float(valeurs[rang]) - courant)
    return courant


# ---------------------------------------------------------------------------
# Moyennes qui regardent autre chose que le seul champ de prix
# ---------------------------------------------------------------------------


@primitive(
    "vwma",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Moyenne ponderee par les VOLUMES de la fenetre.",
)
def vwma(ctx: Context, params: FieldWindowParams) -> float | None:
    """Donne du poids aux barres ou il s'est vraiment passe quelque chose.

    A distinguer de `vwap@1`, qui pondere le prix TYPIQUE : ici c'est le champ
    demande qui est pondere, et le resultat reste une moyenne mobile.
    """
    prix = ctx.values(params.field, params.window)
    volumes = ctx.values(Field.VOLUME, params.window)
    return securise(float(np.dot(prix, volumes)), float(volumes.sum()))


@primitive(
    "midpoint",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Milieu entre le plus haut et le plus bas du champ, sur la fenetre.",
)
def midpoint(ctx: Context, params: FieldWindowParams) -> float | None:
    """Centre du canal, sur UN champ.

    `midprice@1` fait la meme chose sur la paire high/low, ce qui n'est pas
    equivalent des que les meches comptent.
    """
    fenetre = ctx.values(params.field, params.window)
    return (float(np.max(fenetre)) + float(np.min(fenetre))) / 2.0


@primitive(
    "midprice",
    version=1,
    params=WindowParams,
    warmup=window_warmup(),
    summary="Milieu entre le plus haut des `high` et le plus bas des `low`.",
)
def midprice(ctx: Context, params: WindowParams) -> float | None:
    """Le centre du canal de Donchian, sans ses bornes."""
    haut = float(np.max(ctx.values(Field.HIGH, params.window)))
    bas = float(np.min(ctx.values(Field.LOW, params.window)))
    return (haut + bas) / 2.0


@primitive(
    "linreg",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Valeur de la droite de regression a la DERNIERE barre de la fenetre.",
)
def linreg(ctx: Context, params: FieldWindowParams) -> float | None:
    """Moyenne mobile au sens des moindres carres.

    Elle n'extrapole pas : la valeur rendue est celle de la droite AU point
    courant. `linreg_forecast@1` fait la projection, sous un nom different pour
    que le choix soit explicite.
    """
    fenetre = ctx.values(params.field, params.window)
    return float(np.mean(fenetre)) + pente_de(fenetre) * (params.window - 1) / 2.0


@primitive(
    "linreg_forecast",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Projection de la droite de regression UNE barre en avant.",
)
def linreg_forecast(ctx: Context, params: FieldWindowParams) -> float | None:
    """Extrapolation d'un pas, calculee sur des barres closes uniquement.

    Ce n'est pas du look-ahead : la droite est ajustee sur le passe seul et la
    valeur rendue est une PREVISION, pas une lecture. Elle peut etre fausse ;
    elle ne peut pas etre informee par le futur.
    """
    fenetre = ctx.values(params.field, params.window)
    return float(np.mean(fenetre)) + pente_de(fenetre) * (params.window + 1) / 2.0


@primitive(
    "linreg_intercept",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Ordonnee a l'origine de la droite de regression sur la fenetre.",
)
def linreg_intercept(ctx: Context, params: FieldWindowParams) -> float | None:
    """Valeur de la droite a la PREMIERE barre de la fenetre."""
    fenetre = ctx.values(params.field, params.window)
    return float(np.mean(fenetre)) - pente_de(fenetre) * (params.window - 1) / 2.0
