"""Oscillateurs de momentum.

Ils mesurent tous la meme chose - la vitesse du prix - et different par ce
qu'ils normalisent et par ce qu'ils lissent. Les separer nommement plutot que
d'en faire des variantes d'un `momentum@1` parametre est delibere : leurs
bornes, leurs unites et leurs seuils d'usage ne sont pas les memes, et un
parametre `kind` laisserait croire qu'ils sont interchangeables.

Ceux qui portent une ligne de signal exposent un parametre `output`, comme
`macd@1` : les deux lignes d'un meme indicateur doivent etre calculees avec
les memes reglages, sinon leur croisement ne veut rien dire.
"""

from __future__ import annotations

from enum import StrEnum
from typing import cast

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import PrimitiveParams, WarmupFn, WindowParams, window_warmup
from rsl.primitives.builtin.lissage import (
    ema_serie,
    securise,
    sma_serie,
    wma_de,
)
from rsl.primitives.builtin.params import FieldWindowParams
from rsl.primitives.registry import primitive


class LineOutput(StrEnum):
    """Ligne principale, sa moyenne de signal, ou leur ecart."""

    LINE = "line"
    SIGNAL = "signal"
    HISTOGRAM = "histogram"


class DoubleOutput(StrEnum):
    """Les deux lignes d'un oscillateur stochastique."""

    K = "k"
    D = "d"


class SignalParams(FieldWindowParams):
    """Fenetre principale + fenetre de la ligne de signal."""

    signal_window: int = 9
    seed_multiplier: int = 5
    output: LineOutput = LineOutput.LINE

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.signal_window < 1:
            raise ValueError(f"signal_window doit etre >= 1, recu {self.signal_window}")
        if self.seed_multiplier < 2:
            raise ValueError(f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier}")

    @property
    def lookback(self) -> int:
        return self.window * self.seed_multiplier


class PairParams(FieldWindowParams):
    """Deux fenetres : `window` est la RAPIDE, `slow_window` la lente."""

    slow_window: int = 26
    signal_window: int = 9
    seed_multiplier: int = 5
    output: LineOutput = LineOutput.LINE

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.slow_window <= self.window:
            raise ValueError(
                f"slow_window ({self.slow_window}) doit etre > window "
                f"({self.window}) : sinon la lente est la rapide"
            )
        if self.signal_window < 1:
            raise ValueError(f"signal_window doit etre >= 1, recu {self.signal_window}")
        if self.seed_multiplier < 2:
            raise ValueError(f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier}")

    @property
    def lookback(self) -> int:
        return self.slow_window * self.seed_multiplier


class TripleParams(PrimitiveParams):
    """Trois fenetres, comme l'oscillateur ultime."""

    fast: int = 7
    medium: int = 14
    slow: int = 28

    def model_post_init(self, _context: object, /) -> None:
        if not 1 <= self.fast < self.medium < self.slow:
            raise ValueError(
                f"attendu 1 <= fast < medium < slow, recu "
                f"{self.fast}/{self.medium}/{self.slow}"
            )


class StochDoubleParams(WindowParams):
    """Stochastique lisse : `%K` lisse sur `smooth_k`, `%D` sur `smooth_d`."""

    smooth_k: int = 3
    smooth_d: int = 3
    output: DoubleOutput = DoubleOutput.K

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.smooth_k < 1 or self.smooth_d < 1:
            raise ValueError(
                f"smooth_k et smooth_d doivent etre >= 1, recus "
                f"{self.smooth_k}/{self.smooth_d}"
            )


class AwesomeParams(PrimitiveParams):
    """Oscillateur genial : deux SMA du prix median."""

    fast: int = 5
    slow: int = 34

    def model_post_init(self, _context: object, /) -> None:
        if not 1 <= self.fast < self.slow:
            raise ValueError(f"attendu 1 <= fast < slow, recu {self.fast}/{self.slow}")


def _signal_lookback(offset: int = 0) -> WarmupFn:
    def compute(params: PrimitiveParams) -> int:
        reglages = cast("SignalParams", params)
        return reglages.lookback + reglages.signal_window + offset

    return compute


def _pair_lookback(offset: int = 0) -> WarmupFn:
    def compute(params: PrimitiveParams) -> int:
        reglages = cast("PairParams", params)
        return reglages.lookback + reglages.signal_window + offset

    return compute


def dpo_warmup(params: PrimitiveParams) -> int:
    """La fenetre de moyenne PLUS le decalage causal."""
    fenetre = cast("FieldWindowParams", params).window
    return fenetre + fenetre // 2 + 1


def _sortie(ligne: float, signal: float, quoi: LineOutput) -> float:
    if quoi is LineOutput.LINE:
        return ligne
    if quoi is LineOutput.SIGNAL:
        return signal
    return ligne - signal


# ---------------------------------------------------------------------------
# Variation brute : les plus simples, et les plus lisibles
# ---------------------------------------------------------------------------


@primitive(
    "mom",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Momentum brut : difference entre la valeur courante et celle d'il y a `window`.",
)
def mom(ctx: Context, params: FieldWindowParams) -> float | None:
    """En unites de prix, donc non comparable entre instruments.

    `roc@1` est sa version relative, et c'est presque toujours celle qu'il
    faut quand on compare deux marches.
    """
    return ctx.value(params.field) - ctx.value(params.field, lag=params.window)


@primitive(
    "roc",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Taux de variation sur `window` barres, en pourcentage.",
)
def roc(ctx: Context, params: FieldWindowParams) -> float | None:
    """Version sans unite de `mom@1`."""
    ancien = ctx.value(params.field, lag=params.window)
    return securise(100.0 * (ctx.value(params.field) - ancien), ancien)


@primitive(
    "rocr",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Rapport de variation sur `window` barres : 1 signifie inchange.",
)
def rocr(ctx: Context, params: FieldWindowParams) -> float | None:
    """Meme information que `roc@1`, en ratio plutot qu'en pourcentage.

    Utile quand on veut composer des variations par multiplication plutot que
    par addition - un cumul de `roc` sur plusieurs fenetres est faux, un
    produit de `rocr` ne l'est pas.
    """
    return securise(ctx.value(params.field), ctx.value(params.field, lag=params.window))


@primitive(
    "bias",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Ecart relatif entre le prix et sa moyenne simple, en pourcentage.",
)
def bias(ctx: Context, params: FieldWindowParams) -> float | None:
    """« De combien sommes-nous au-dessus de la moyenne ? », en pourcentage.

    L'ecart a la moyenne le plus direct qui soit - et une brique frequente des
    strategies de retour a la moyenne.
    """
    fenetre = ctx.values(params.field, params.window)
    moyenne = float(np.mean(fenetre))
    return securise(100.0 * (float(fenetre[-1]) - moyenne), moyenne)


@primitive(
    "psl",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Ligne psychologique : part des barres en hausse sur la fenetre, en %.",
)
def psl(ctx: Context, params: FieldWindowParams) -> float | None:
    """Compte les hausses sans regarder leur AMPLITUDE.

    C'est ce qui le distingue du RSI : vingt hausses minuscules et une baisse
    massive donnent 95 ici, et bien moins la-bas.
    """
    valeurs = ctx.values(params.field, params.window + 1)
    hausses = int(np.count_nonzero(np.diff(valeurs) > 0.0))
    return 100.0 * hausses / params.window


@primitive(
    "cmo",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Chande Momentum Oscillator : hausses moins baisses, rapportees au total.",
)
def cmo(ctx: Context, params: FieldWindowParams) -> float | None:
    """Borne a `[-100, 100]`. C'est un RSI recentre sur zero.

    Rend `None` sur une serie plate : sans variation il n'y a ni force ni
    faiblesse, et repondre 0 laisserait croire a un equilibre mesure.
    """
    deltas = np.diff(ctx.values(params.field, params.window + 1))
    hausses = float(np.sum(np.maximum(deltas, 0.0)))
    baisses = float(np.sum(np.maximum(-deltas, 0.0)))
    return securise(100.0 * (hausses - baisses), hausses + baisses)


@primitive(
    "dpo",
    version=1,
    params=FieldWindowParams,
    warmup=dpo_warmup,
    summary="Oscillateur de prix detendu : ecart a la moyenne DECALEE dans le passe.",
)
def dpo(ctx: Context, params: FieldWindowParams) -> float | None:
    """Retire la tendance pour ne garder que le cycle.

    Attention : la version classique compare le prix a une moyenne CENTREE,
    donc decalee dans le FUTUR de `window/2 + 1` barres. Cette version-la est
    inexprimable ici, et c'est heureux : elle est une fuite du futur, et
    beaucoup d'implementations la publient sans le signaler.

    Ce qui est calcule ici est la variante causale : le prix d'il y a
    `window/2 + 1` barres, compare a la moyenne des `window` barres qui le
    precedent. Le cycle mis en evidence est le meme ; il arrive simplement
    avec le retard que la causalite impose.
    """
    decalage = params.window // 2 + 1
    valeurs = ctx.values(params.field, params.window + decalage)
    moyenne = float(np.mean(valeurs[: params.window]))
    return float(valeurs[params.window - 1]) - moyenne


@primitive(
    "qstick",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Qstick : moyenne de `close - open` sur la fenetre.",
)
def qstick(ctx: Context, _params: FieldWindowParams) -> float | None:
    """Mesure la pression intra-barre plutot que le deplacement du prix.

    Positive quand les bougies ferment au-dessus de leur ouverture en moyenne,
    meme si le prix n'a pas bouge d'une barre a l'autre.
    """
    fenetre = _params.window
    return float(
        np.mean(ctx.values(Field.CLOSE, fenetre) - ctx.values(Field.OPEN, fenetre))
    )


@primitive(
    "bop",
    version=1,
    params=WindowParams,
    warmup=window_warmup(),
    summary="Balance of Power : `(close - open) / (high - low)`, moyennee sur la fenetre.",
)
def bop(ctx: Context, params: WindowParams) -> float | None:
    """Qui, des acheteurs ou des vendeurs, a tenu la barre.

    Borne a `[-1, 1]` par construction. Les barres sans amplitude sont
    ecartees du calcul plutot que comptees a zero : une barre plate n'exprime
    aucun rapport de force.
    """
    ouvertures = ctx.values(Field.OPEN, params.window)
    hauts = ctx.values(Field.HIGH, params.window)
    bas = ctx.values(Field.LOW, params.window)
    clotures = ctx.values(Field.CLOSE, params.window)
    amplitudes = hauts - bas
    retenues = amplitudes > 0.0
    if not np.any(retenues):
        return None
    return float(
        np.mean((clotures[retenues] - ouvertures[retenues]) / amplitudes[retenues])
    )


@primitive(
    "elder_ray",
    version=1,
    params=WindowParams,
    warmup=window_warmup(),
    summary="Elder Ray : ecart moyen entre les extremes et la moyenne du prix.",
)
def elder_ray(ctx: Context, params: WindowParams) -> float | None:
    """`bull power` plus `bear power`, en une seule mesure signee.

    Positive quand les hauts s'eloignent de la moyenne plus que les bas n'en
    descendent : les acheteurs mènent. La version d'Elder publie les deux
    moities separement ; les additionner donne une lecture directionnelle
    unique, ce qui convient mieux a une composition par noeuds.
    """
    moyenne = float(np.mean(ctx.values(Field.CLOSE, params.window)))
    haut = ctx.value(Field.HIGH)
    bas = ctx.value(Field.LOW)
    return (haut - moyenne) + (bas - moyenne)


# ---------------------------------------------------------------------------
# Oscillateurs a deux moyennes : un rapide moins un lent
# ---------------------------------------------------------------------------


@primitive(
    "apo",
    version=1,
    params=PairParams,
    warmup=_pair_lookback(),
    summary="Oscillateur de prix absolu : EMA rapide moins EMA lente, en unites de prix.",
)
def apo(ctx: Context, params: PairParams) -> float | None:
    """Le MACD sans sa ligne de signal, et sans le nom.

    En unites de prix : deux instruments ne se comparent pas. `ppo@1` en est
    la version relative.
    """
    valeurs = ctx.values(params.field, params.lookback)
    rapide = float(ema_serie(valeurs, params.window)[-1])
    lente = float(ema_serie(valeurs, params.slow_window)[-1])
    return rapide - lente


@primitive(
    "ppo",
    version=1,
    params=PairParams,
    warmup=_pair_lookback(),
    summary="Oscillateur de prix en pourcentage : line, signal ou histogram.",
)
def ppo(ctx: Context, params: PairParams) -> float | None:
    """MACD normalise par la moyenne lente, donc comparable entre instruments.

    C'est la correction la plus utile au MACD : un ecart de 3 points ne dit
    rien tant qu'on ne sait pas si le sous-jacent vaut 30 ou 30 000.
    """
    valeurs = ctx.values(params.field, params.lookback + params.signal_window)
    rapide = ema_serie(valeurs, params.window)
    lente = ema_serie(valeurs, params.slow_window)
    commun = min(rapide.size, lente.size)
    if commun < params.signal_window:
        return None
    ecart = rapide[-commun:] - lente[-commun:]
    base = lente[-commun:]
    if np.any(base == 0.0):
        return None
    ligne_serie = 100.0 * ecart / base
    signal = float(ema_serie(ligne_serie, params.signal_window)[-1])
    return _sortie(float(ligne_serie[-1]), signal, params.output)


@primitive(
    "awesome",
    version=1,
    params=AwesomeParams,
    warmup=lambda p: cast("AwesomeParams", p).slow,
    summary="Oscillateur genial de Williams : SMA courte moins SMA longue du prix median.",
)
def awesome(ctx: Context, params: AwesomeParams) -> float | None:
    """Deux SMA du prix median `(high + low) / 2`, pas de la cloture.

    Le choix du prix median n'est pas cosmetique : il rend l'oscillateur
    insensible a l'endroit ou la barre a ferme, donc moins bruite sur les
    unites de temps courtes.
    """
    medians = (
        ctx.values(Field.HIGH, params.slow) + ctx.values(Field.LOW, params.slow)
    ) / 2.0
    return float(np.mean(medians[-params.fast :])) - float(np.mean(medians))


@primitive(
    "trix",
    version=1,
    params=SignalParams,
    warmup=_signal_lookback(1),
    summary="TRIX : taux de variation d'une triple EMA, en pourcentage.",
)
def trix(ctx: Context, params: SignalParams) -> float | None:
    """Triple lissage puis derivation : le bruit est ecrase avant derivation.

    L'ordre compte. Deriver puis lisser laisserait passer le bruit dans la
    derivee, ou il est amplifie.
    """
    valeurs = ctx.values(params.field, params.lookback + params.signal_window + 1)
    courant = valeurs
    for _ in range(3):
        if courant.size < params.window:
            return None
        courant = ema_serie(courant, params.window)
    if courant.size < params.signal_window + 1:
        return None
    variations = np.zeros(courant.size - 1, dtype=np.float64)
    precedents = courant[:-1]
    valides = precedents != 0.0
    variations[valides] = (
        100.0 * (courant[1:][valides] - precedents[valides]) / precedents[valides]
    )
    signal = float(np.mean(variations[-params.signal_window :]))
    return _sortie(float(variations[-1]), signal, params.output)


@primitive(
    "tsi",
    version=1,
    params=PairParams,
    warmup=_pair_lookback(1),
    summary="True Strength Index : momentum doublement lisse, borne a [-100, 100].",
)
def tsi(ctx: Context, params: PairParams) -> float | None:
    """Double lissage du momentum et de sa valeur absolue.

    `window` est la fenetre RAPIDE et `slow_window` la lente - dans la
    litterature elles valent 13 et 25, et l'ordre inverse donnerait un
    indicateur qui reagit a l'envers.
    """
    valeurs = ctx.values(params.field, params.lookback + 1)
    deltas = np.diff(valeurs)
    if deltas.size < params.slow_window:
        return None
    lisse_lent = ema_serie(deltas, params.slow_window)
    absolu_lent = ema_serie(np.abs(deltas), params.slow_window)
    if lisse_lent.size < params.window:
        return None
    numerateur = float(ema_serie(lisse_lent, params.window)[-1])
    denominateur = float(ema_serie(absolu_lent, params.window)[-1])
    return securise(100.0 * numerateur, denominateur)


@primitive(
    "pmo",
    version=1,
    params=PairParams,
    warmup=_pair_lookback(1),
    summary="Price Momentum Oscillator : taux de variation doublement lisse.",
)
def pmo(ctx: Context, params: PairParams) -> float | None:
    """Variante de DecisionPoint : ROC barre a barre, lisse deux fois.

    Proche du TSI dans l'esprit, mais normalise par le PRIX et non par
    l'amplitude du momentum : les deux ne repondent pas pareil a une serie qui
    accelere sans changer de direction.
    """
    valeurs = ctx.values(params.field, params.lookback + 1)
    precedents = valeurs[:-1]
    if np.any(precedents == 0.0):
        return None
    variations = 100.0 * (valeurs[1:] - precedents) / precedents
    if variations.size < params.slow_window:
        return None
    premier = ema_serie(variations, params.slow_window)
    if premier.size < params.window:
        return None
    return 10.0 * float(ema_serie(premier, params.window)[-1])


@primitive(
    "coppock",
    version=1,
    params=PairParams,
    warmup=lambda p: cast("PairParams", p).slow_window + cast("PairParams", p).window + 1,
    summary="Courbe de Coppock : WMA de la somme de deux taux de variation.",
)
def coppock(ctx: Context, params: PairParams) -> float | None:
    """Indicateur de long terme, concu pour les indices en donnees mensuelles.

    `window` et `slow_window` sont les deux horizons de ROC (11 et 14 dans la
    publication d'origine), `signal_window` la longueur de la WMA finale.
    L'employer sur des barres d'une minute n'a pas de sens documente - rien
    n'empeche de le faire, et rien ne l'appuie.
    """
    besoin = params.slow_window + params.window + 1
    valeurs = ctx.values(params.field, besoin)
    fenetre_wma = params.window
    sommes = np.empty(fenetre_wma, dtype=np.float64)
    for rang in range(fenetre_wma):
        fin = valeurs.size - fenetre_wma + rang
        actuel = float(valeurs[fin])
        court = float(valeurs[fin - params.window])
        long = float(valeurs[fin - params.slow_window])
        if court == 0.0 or long == 0.0:
            return None
        sommes[rang] = 100.0 * (actuel - court) / court + 100.0 * (actuel - long) / long
    return wma_de(sommes, fenetre_wma)


# ---------------------------------------------------------------------------
# Oscillateurs stochastiques et derives
# ---------------------------------------------------------------------------


@primitive(
    "stoch",
    version=1,
    params=StochDoubleParams,
    warmup=lambda p: cast("StochDoubleParams", p).window
    + cast("StochDoubleParams", p).smooth_k
    + cast("StochDoubleParams", p).smooth_d
    - 2,
    summary="Stochastique lisse : `%K` lisse, ou `%D` qui est la moyenne de `%K`.",
)
def stoch(ctx: Context, params: StochDoubleParams) -> float | None:
    """Le stochastique « lent », celui qu'on trace en pratique.

    `stochastic@1` publie le `%K` brut, tres bruite. Ici `%K` est deja lisse
    sur `smooth_k` barres et `%D` l'est encore sur `smooth_d` : c'est leur
    croisement qui sert de signal, pas leur valeur.

    Les barres ou l'amplitude est nulle sont ecartees du lissage. Si toute la
    fenetre est plate, le resultat est `None` - pas 50.
    """
    besoin = params.window + params.smooth_k + params.smooth_d - 2
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    n_brut = besoin - params.window + 1
    bruts = np.empty(n_brut, dtype=np.float64)
    for rang in range(n_brut):
        tranche = slice(rang, rang + params.window)
        plus_haut = float(np.max(hauts[tranche]))
        plus_bas = float(np.min(bas[tranche]))
        amplitude = plus_haut - plus_bas
        if amplitude <= 0.0:
            return None
        bruts[rang] = 100.0 * (float(clotures[tranche][-1]) - plus_bas) / amplitude

    k = sma_serie(bruts, params.smooth_k)
    if params.output is DoubleOutput.K:
        return float(k[-1])
    if k.size < params.smooth_d:
        return None
    return float(sma_serie(k, params.smooth_d)[-1])


@primitive(
    "stoch_rsi",
    version=1,
    params=StochDoubleParams,
    warmup=lambda p: 2 * cast("StochDoubleParams", p).window
    + cast("StochDoubleParams", p).smooth_k
    + cast("StochDoubleParams", p).smooth_d
    - 1,
    summary="Stochastique applique au RSI : ou se situe le RSI dans son propre range.",
)
def stoch_rsi(ctx: Context, params: StochDoubleParams) -> float | None:
    """Un stochastique dont l'entree est un RSI, pas un prix.

    Beaucoup plus reactif qu'un RSI seul - et beaucoup plus bruite. Il passe
    son temps colle a 0 ou a 100 ; lu comme un RSI ordinaire, il donne des
    signaux de survente en permanence.
    """
    fenetre = params.window
    besoin_rsi = fenetre + params.smooth_k + params.smooth_d - 2
    total = fenetre + besoin_rsi
    valeurs = ctx.values(Field.CLOSE, total + 1)
    deltas = np.diff(valeurs)

    rsis = np.empty(besoin_rsi, dtype=np.float64)
    for rang in range(besoin_rsi):
        tranche = deltas[rang : rang + fenetre]
        hausses = float(np.mean(np.maximum(tranche, 0.0)))
        baisses = float(np.mean(np.maximum(-tranche, 0.0)))
        if hausses == 0.0 and baisses == 0.0:
            return None
        rsis[rang] = 100.0 * hausses / (hausses + baisses)

    n_brut = besoin_rsi - fenetre + 1
    bruts = np.empty(n_brut, dtype=np.float64)
    for rang in range(n_brut):
        tranche = rsis[rang : rang + fenetre]
        etendue = float(np.max(tranche)) - float(np.min(tranche))
        if etendue <= 0.0:
            return None
        bruts[rang] = 100.0 * (float(tranche[-1]) - float(np.min(tranche))) / etendue

    k = sma_serie(bruts, params.smooth_k)
    if params.output is DoubleOutput.K:
        return float(k[-1])
    if k.size < params.smooth_d:
        return None
    return float(sma_serie(k, params.smooth_d)[-1])


@primitive(
    "ultimate",
    version=1,
    params=TripleParams,
    warmup=lambda p: cast("TripleParams", p).slow + 1,
    summary="Oscillateur ultime de Williams : trois horizons ponderes 4-2-1.",
)
def ultimate(ctx: Context, params: TripleParams) -> float | None:
    """Combine trois horizons pour eviter les divergences d'un seul.

    La ponderation 4-2-1 vient de la publication d'origine : le poids est
    inversement proportionnel a la duree, de sorte que les trois horizons
    contribuent a parts comparables.
    """
    besoin = params.slow + 1
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    precedentes = clotures[:-1]
    vrai_bas = np.minimum(bas[1:], precedentes)
    vrai_haut = np.maximum(hauts[1:], precedentes)
    achat = clotures[1:] - vrai_bas
    amplitude = vrai_haut - vrai_bas

    moyennes = []
    for duree in (params.fast, params.medium, params.slow):
        total = float(np.sum(amplitude[-duree:]))
        if total <= 0.0:
            return None
        moyennes.append(float(np.sum(achat[-duree:])) / total)
    return 100.0 * (4.0 * moyennes[0] + 2.0 * moyennes[1] + moyennes[2]) / 7.0


@primitive(
    "rvgi",
    version=1,
    params=WindowParams,
    warmup=window_warmup(3),
    summary="Relative Vigor Index : `(close - open)` rapporte a l'amplitude, lisse.",
)
def rvgi(ctx: Context, params: WindowParams) -> float | None:
    """Mesure si les clotures se font pres des hauts, sur la duree.

    Le lissage est une moyenne ponderee 1-2-2-1 sur quatre barres, convention
    d'origine : elle attenue le bruit d'une barre isolee sans introduire de
    retard notable.
    """
    besoin = params.window + 3
    ouvertures = ctx.values(Field.OPEN, besoin)
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    poids = np.array([1.0, 2.0, 2.0, 1.0])
    numerateurs = np.empty(params.window, dtype=np.float64)
    denominateurs = np.empty(params.window, dtype=np.float64)
    for rang in range(params.window):
        tranche = slice(rang, rang + 4)
        numerateurs[rang] = float(
            np.dot(clotures[tranche] - ouvertures[tranche], poids)
        ) / 6.0
        denominateurs[rang] = float(np.dot(hauts[tranche] - bas[tranche], poids)) / 6.0
    return securise(float(np.sum(numerateurs)), float(np.sum(denominateurs)))


@primitive(
    "fisher",
    version=1,
    params=SignalParams,
    warmup=_signal_lookback(),
    summary="Transformee de Fisher du prix normalise : rend les extremes tranches.",
)
def fisher(ctx: Context, params: SignalParams) -> float | None:
    """Transforme une serie bornee en une serie a queues gaussiennes.

    L'interet : les retournements deviennent des pics nets au lieu de plateaux
    flous. L'inconvenient : la transformee explose pres de `+/-1`, et la
    normalisation est donc bornee a `+/-0,999` - sans cette borne, une serie
    au plus haut de sa fenetre donnerait un infini.
    """
    besoin = params.window + params.signal_window
    medians = (
        ctx.values(Field.HIGH, besoin) + ctx.values(Field.LOW, besoin)
    ) / 2.0

    valeurs = np.empty(params.signal_window + 1, dtype=np.float64)
    for rang in range(valeurs.size):
        tranche = medians[rang : rang + params.window]
        plus_haut, plus_bas = float(np.max(tranche)), float(np.min(tranche))
        etendue = plus_haut - plus_bas
        if etendue <= 0.0:
            return None
        normalise = 2.0 * (float(tranche[-1]) - plus_bas) / etendue - 1.0
        borne = float(np.clip(normalise, -0.999, 0.999))
        valeurs[rang] = 0.5 * np.log((1.0 + borne) / (1.0 - borne))
    return _sortie(float(valeurs[-1]), float(valeurs[-2]), params.output)


@primitive(
    "smi",
    version=1,
    params=PairParams,
    warmup=lambda p: cast("PairParams", p).slow_window * cast("PairParams", p).seed_multiplier,
    summary="Stochastic Momentum Index : distance au MILIEU du range, doublement lissee.",
)
def smi(ctx: Context, params: PairParams) -> float | None:
    """Comme le stochastique, mais mesure par rapport au CENTRE du canal.

    Le stochastique dit « ou suis-je entre le plus bas et le plus haut » ; le
    SMI dit « de quel cote du milieu, et de combien ». Il est centre sur zero,
    ce qui rend le signe directement exploitable.
    """
    besoin = params.slow_window * params.seed_multiplier
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    n = besoin - params.window + 1
    ecarts = np.empty(n, dtype=np.float64)
    amplitudes = np.empty(n, dtype=np.float64)
    for rang in range(n):
        tranche = slice(rang, rang + params.window)
        plus_haut = float(np.max(hauts[tranche]))
        plus_bas = float(np.min(bas[tranche]))
        ecarts[rang] = float(clotures[tranche][-1]) - (plus_haut + plus_bas) / 2.0
        amplitudes[rang] = plus_haut - plus_bas

    lisse = params.signal_window
    if n < lisse:
        return None
    ecart_lisse = ema_serie(ema_serie(ecarts, lisse), lisse)
    amplitude_lisse = ema_serie(ema_serie(amplitudes, lisse), lisse)
    return securise(100.0 * float(ecart_lisse[-1]), float(amplitude_lisse[-1]) / 2.0)


@primitive(
    "pgo",
    version=1,
    params=WindowParams,
    warmup=window_warmup(1),
    summary="Pretty Good Oscillator : ecart a la moyenne, mesure en ATR.",
)
def pgo(ctx: Context, params: WindowParams) -> float | None:
    """L'ecart a la moyenne, exprime en unites de volatilite plutot qu'en prix.

    C'est ce qui le rend comparable d'un instrument a l'autre, la ou `bias@1`
    ne l'est qu'apres normalisation par le prix - deux normalisations qui ne
    disent pas la meme chose sur un marche qui change de regime.
    """
    besoin = params.window + 1
    clotures = ctx.values(Field.CLOSE, besoin)
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    precedentes = clotures[:-1]
    trs = np.maximum.reduce([
        hauts[1:] - bas[1:],
        np.abs(hauts[1:] - precedentes),
        np.abs(bas[1:] - precedentes),
    ])
    moyenne = float(np.mean(clotures[1:]))
    return securise(float(clotures[-1]) - moyenne, float(np.mean(trs)))


@primitive(
    "cfo",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Chande Forecast Oscillator : ecart relatif entre le prix et sa regression.",
)
def cfo(ctx: Context, params: FieldWindowParams) -> float | None:
    """De combien le prix s'ecarte de sa propre droite de regression, en %.

    Zero signifie que le prix est exactement sur sa tendance lineaire ; un
    ecart durablement positif signale une acceleration au-dela d'elle.
    """
    from rsl.primitives.builtin.lissage import pente_de

    fenetre = ctx.values(params.field, params.window)
    pente = pente_de(fenetre)
    prevision = float(np.mean(fenetre)) + pente * (params.window - 1) / 2.0
    prix = float(fenetre[-1])
    return securise(100.0 * (prix - prevision), prix)


@primitive(
    "center_of_gravity",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Centre de gravite d'Ehlers : barycentre pondere de la fenetre de prix.",
)
def center_of_gravity(ctx: Context, params: FieldWindowParams) -> float | None:
    """Ou se situe le « poids » du prix dans la fenetre.

    Sans unite de prix : le resultat est un RANG dans la fenetre, negatif par
    convention d'Ehlers. Il tourne autour de `-(window+1)/2` et s'en ecarte
    quand le prix se concentre d'un cote.
    """
    fenetre = ctx.values(params.field, params.window)
    rangs = np.arange(params.window, 0, -1, dtype=np.float64)
    return securise(-float(np.dot(fenetre, rangs)), float(np.sum(fenetre)))


@primitive(
    "inertia",
    version=1,
    params=FieldWindowParams,
    warmup=lambda p: 2 * cast("FieldWindowParams", p).window,
    summary="Inertie : regression lineaire de l'indice de volatilite relative.",
)
def inertia(ctx: Context, params: FieldWindowParams) -> float | None:
    """Direction de la volatilite, pas du prix.

    Au-dessus de 50, la dispersion se fait plutot a la hausse ; en dessous,
    plutot a la baisse. C'est un indicateur de REGIME : il ne dit pas ou va le
    prix, il dit dans quel sens penche le risque.
    """
    from rsl.primitives.builtin.lissage import pente_de

    fenetre = params.window
    valeurs = ctx.values(params.field, 2 * fenetre)
    deltas = np.diff(valeurs)

    n = deltas.size - fenetre + 1
    rvis = np.empty(n, dtype=np.float64)
    for rang in range(n):
        tranche = deltas[rang : rang + fenetre]
        hausses = tranche[tranche > 0.0]
        baisses = tranche[tranche < 0.0]
        # `np.std` d'un tableau VIDE rend `NaN`, pas zero - et `NaN <= 0` vaut
        # `False`, donc la garde en dessous laisserait passer le `NaN` jusqu'au
        # resultat. Cas atteint des qu'une fenetre entiere est plate.
        haut = float(np.std(hausses, ddof=0)) * hausses.size if hausses.size else 0.0
        bas = float(np.std(baisses, ddof=0)) * baisses.size if baisses.size else 0.0
        if haut + bas <= 0.0:
            return None
        rvis[rang] = 100.0 * haut / (haut + bas)
    utile = rvis[-fenetre:] if rvis.size >= fenetre else rvis
    return float(np.mean(utile)) + pente_de(utile) * (utile.size - 1) / 2.0
