"""Volatilite : de combien ca bouge, independamment du sens.

Le depot porte deja `stdev@1` (dispersion des prix, en unites de prix),
`volatility@1` (dispersion des rendements, sans unite) et la famille ATR. Ce
module ajoute les mesures qui exploitent la barre ENTIERE plutot que la seule
cloture - Parkinson, Garman-Klass, Rogers-Satchell - et celles qui mesurent la
volatilite du RISQUE plutot que celle du prix.

Un point commun a retenir : aucune de ces mesures n'est annualisee. Le pas
d'annualisation se MESURE sur l'echantillon, il ne se suppose pas
(`Failed Ideas/ledger`, 2026-09-10). Multiplier ici par `sqrt(252)` reviendrait
a postuler un marche ouvert tous les jours ouvres et jamais autrement.
"""

from __future__ import annotations

from typing import cast

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import PrimitiveParams, WindowParams, window_warmup
from rsl.primitives.builtin.lissage import (
    securise,
    sma_serie,
    true_range_serie,
    wilder_serie,
)
from rsl.primitives.builtin.params import FieldWindowParams
from rsl.primitives.registry import primitive


class LogWindowParams(WindowParams):
    """Fenetre sur laquelle estimer une volatilite a partir des extremes."""

    log: bool = True


class DoubleWindowParams(WindowParams):
    """Une fenetre courte et une longue, pour un rapport de volatilites."""

    slow_window: int = 60

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.slow_window <= self.window:
            raise ValueError(
                f"slow_window ({self.slow_window}) doit etre > window ({self.window})"
            )


class WilderPctParams(WindowParams):
    """Fenetre de Wilder + profondeur de l'historique tronque."""

    seed_multiplier: int = 5

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.seed_multiplier < 2:
            raise ValueError(f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier}")

    @property
    def lookback(self) -> int:
        return self.window * self.seed_multiplier


class SeuilParams(FieldWindowParams):
    """Fenetre + seuil de reference des rendements."""

    threshold: float = 0.0


class MassParams(WindowParams):
    """Indice de masse : EMA imbriquees puis somme sur `sum_window`."""

    sum_window: int = 25
    seed_multiplier: int = 5

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.sum_window < 1:
            raise ValueError(f"sum_window doit etre >= 1, recu {self.sum_window}")
        if self.seed_multiplier < 2:
            raise ValueError(f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier}")

    @property
    def lookback(self) -> int:
        return self.window * self.seed_multiplier


def _rendements(ctx: Context, field: Field, n: int, log: bool) -> np.ndarray | None:
    """Les `n` rendements les plus recents, ou `None` si un prix est nul."""
    valeurs = ctx.values(field, n + 1)
    if np.any(valeurs <= 0.0):
        return None
    if log:
        return np.diff(np.log(valeurs))
    return np.diff(valeurs) / valeurs[:-1]


def chaikin_warmup(params: PrimitiveParams) -> int:
    """Le lissage consomme `window` barres, la comparaison `slow_window` de plus."""
    reglages = cast("DoubleWindowParams", params)
    return reglages.slow_window + reglages.window


def _mass_warmup(params: PrimitiveParams) -> int:
    reglages = cast("MassParams", params)
    return reglages.lookback + reglages.sum_window


@primitive(
    "natr",
    version=1,
    params=WindowParams,
    warmup=window_warmup(1),
    summary="ATR normalise par la cloture, en pourcentage : comparable entre marches.",
)
def natr(ctx: Context, params: WindowParams) -> float | None:
    """L'ATR rendu sans unite.

    C'est presque toujours celui-la qu'il faut : un ATR de 12 ne veut rien
    dire tant qu'on ne sait pas si le contrat vaut 100 ou 5 000, ni si on le
    compare a lui-meme dix ans plus tot.
    """
    besoin = params.window + 1
    trs = true_range_serie(
        ctx.values(Field.HIGH, besoin),
        ctx.values(Field.LOW, besoin),
        ctx.values(Field.CLOSE, besoin),
    )
    return securise(100.0 * float(np.mean(trs)), ctx.value(Field.CLOSE))


@primitive(
    "parkinson",
    version=1,
    params=LogWindowParams,
    warmup=window_warmup(),
    summary="Volatilite de Parkinson, estimee sur les extremes de chaque barre.",
)
def parkinson(ctx: Context, params: LogWindowParams) -> float | None:
    """Estimateur ~5 fois plus efficace que l'ecart-type des clotures.

    Il utilise l'amplitude `high/low` de chaque barre plutot que le seul
    deplacement de cloture a cloture, donc bien plus d'information par barre.

    Sa limite est structurelle : il suppose qu'il n'y a pas de gap et pas de
    derive. Sur des donnees a coupure de seance - le cas de toutes les series
    du depot - il SOUS-ESTIME la volatilite, puisque le saut d'ouverture
    n'apparait dans l'amplitude d'aucune barre.
    """
    hauts = ctx.values(Field.HIGH, params.window)
    bas = ctx.values(Field.LOW, params.window)
    if np.any(bas <= 0.0) or np.any(hauts <= 0.0):
        return None
    logs = np.log(hauts / bas)
    return float(np.sqrt(np.mean(logs * logs) / (4.0 * np.log(2.0))))


@primitive(
    "garman_klass",
    version=1,
    params=LogWindowParams,
    warmup=window_warmup(),
    summary="Volatilite de Garman-Klass : extremes ET ouverture / cloture combines.",
)
def garman_klass(ctx: Context, params: LogWindowParams) -> float | None:
    """Ameliore Parkinson en ajoutant le deplacement ouverture -> cloture.

    Plus efficace encore, et sujet a la meme reserve sur les gaps. La racine
    est prise sur une quantite qui peut etre negative sur une barre atypique -
    dans ce cas la primitive rend `None` plutot qu'un `NaN`.
    """
    hauts = ctx.values(Field.HIGH, params.window)
    bas = ctx.values(Field.LOW, params.window)
    ouvertures = ctx.values(Field.OPEN, params.window)
    clotures = ctx.values(Field.CLOSE, params.window)
    if np.any(bas <= 0.0) or np.any(ouvertures <= 0.0):
        return None
    amplitude = np.log(hauts / bas)
    deplacement = np.log(clotures / ouvertures)
    variance = float(
        np.mean(0.5 * amplitude * amplitude - (2.0 * np.log(2.0) - 1.0) * deplacement**2)
    )
    return float(np.sqrt(variance)) if variance > 0.0 else None


@primitive(
    "rogers_satchell",
    version=1,
    params=LogWindowParams,
    warmup=window_warmup(),
    summary="Volatilite de Rogers-Satchell : valide meme quand le prix derive.",
)
def rogers_satchell(ctx: Context, params: LogWindowParams) -> float | None:
    """Le seul de la famille qui reste juste en presence de TENDANCE.

    Parkinson et Garman-Klass supposent une derive nulle et surestiment la
    volatilite d'un marche qui monte regulierement. Celui-ci est construit
    pour s'annuler sur la derive - c'est sa raison d'etre, et ce qui le rend
    preferable sur des series longues.
    """
    hauts = ctx.values(Field.HIGH, params.window)
    bas = ctx.values(Field.LOW, params.window)
    ouvertures = ctx.values(Field.OPEN, params.window)
    clotures = ctx.values(Field.CLOSE, params.window)
    if np.any(bas <= 0.0) or np.any(ouvertures <= 0.0) or np.any(clotures <= 0.0):
        return None
    variance = float(
        np.mean(
            np.log(hauts / clotures) * np.log(hauts / ouvertures)
            + np.log(bas / clotures) * np.log(bas / ouvertures)
        )
    )
    return float(np.sqrt(variance)) if variance > 0.0 else None


@primitive(
    "chaikin_volatility",
    version=1,
    params=DoubleWindowParams,
    warmup=chaikin_warmup,
    summary="Volatilite de Chaikin : variation de l'amplitude moyenne, en pourcentage.",
)
def chaikin_volatility(ctx: Context, params: DoubleWindowParams) -> float | None:
    """Mesure l'ACCELERATION de la volatilite, pas son niveau.

    Positive quand les barres s'elargissent, negative quand elles se
    resserrent. `window` est la fenetre de lissage, `slow_window` l'horizon de
    comparaison.
    """
    besoin = params.slow_window + params.window
    amplitudes = ctx.values(Field.HIGH, besoin) - ctx.values(Field.LOW, besoin)
    lisse = sma_serie(amplitudes, params.window)
    if lisse.size <= params.slow_window:
        return None
    ancienne = float(lisse[-1 - params.slow_window])
    return securise(100.0 * (float(lisse[-1]) - ancienne), ancienne)


@primitive(
    "mass_index",
    version=1,
    params=MassParams,
    warmup=_mass_warmup,
    summary="Indice de masse : detecte un elargissement des barres, sans direction.",
)
def mass_index(ctx: Context, params: MassParams) -> float | None:
    """Rapport de deux EMA imbriquees de l'amplitude, somme sur `sum_window`.

    Concu pour anticiper un RETOURNEMENT : un elargissement prolonge des
    barres precede souvent un changement de sens. Il ne dit pas lequel - c'est
    un indicateur de forme, pas de direction, et l'employer seul est une
    erreur de lecture.
    """
    besoin = params.lookback + params.sum_window
    amplitudes = ctx.values(Field.HIGH, besoin) - ctx.values(Field.LOW, besoin)
    if np.any(amplitudes <= 0.0):
        return None
    from rsl.primitives.builtin.lissage import ema_serie

    premiere = ema_serie(amplitudes, params.window)
    if premiere.size < params.window:
        return None
    seconde = ema_serie(premiere, params.window)
    commun = min(premiere.size, seconde.size)
    rapports = premiere[-commun:] / seconde[-commun:]
    if rapports.size < params.sum_window:
        return None
    return float(np.sum(rapports[-params.sum_window :]))


@primitive(
    "ulcer_index",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Indice d'ulcere : ecart quadratique moyen au plus haut de la fenetre.",
)
def ulcer_index(ctx: Context, params: FieldWindowParams) -> float | None:
    """Mesure la DOULEUR du repli, pas la dispersion.

    Contrairement a l'ecart-type, il ne compte que les mouvements vers le BAS,
    et il penalise un repli profond plus que deux replis moitie moindres. Zero
    signifie que la serie n'a fait que des plus hauts sur la fenetre - ce qui
    est une valeur legitime, pas une absence de valeur.
    """
    valeurs = ctx.values(params.field, params.window)
    sommets = np.maximum.accumulate(valeurs)
    if np.any(sommets <= 0.0):
        return None
    replis = 100.0 * (valeurs - sommets) / sommets
    return float(np.sqrt(np.mean(replis * replis)))


@primitive(
    "max_drawdown",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Repli maximal sur la fenetre, en pourcentage, toujours negatif ou nul.",
)
def max_drawdown(ctx: Context, params: FieldWindowParams) -> float | None:
    """Le pire repli depuis un sommet, a l'interieur de la fenetre.

    Sur une fenetre glissante, a ne pas confondre avec le drawdown maximal
    d'une courbe d'equity depuis son origine : celui-ci se remet a zero des
    que la fenetre depasse le creux.
    """
    valeurs = ctx.values(params.field, params.window)
    sommets = np.maximum.accumulate(valeurs)
    if np.any(sommets <= 0.0):
        return None
    return float(np.min(100.0 * (valeurs - sommets) / sommets))


@primitive(
    "downside_deviation",
    version=1,
    params=SeuilParams,
    warmup=window_warmup(1),
    summary="Ecart-type des seuls rendements SOUS le seuil, sans unite.",
)
def downside_deviation(ctx: Context, params: SeuilParams) -> float | None:
    """Le denominateur du ratio de Sortino, calcule sur fenetre glissante.

    Sa difference avec l'ecart-type est conceptuelle : la volatilite a la
    HAUSSE n'est pas un risque. Les rendements au-dessus du seuil comptent
    comme zero - et non comme absents, ce qui changerait le denominateur et
    ferait d'un actif qui monte souvent un actif faussement risque.
    """
    rendements = _rendements(ctx, params.field, params.window, log=False)
    if rendements is None:
        return None
    sous = np.minimum(rendements - params.threshold, 0.0)
    return float(np.sqrt(np.mean(sous * sous)))


@primitive(
    "upside_deviation",
    version=1,
    params=SeuilParams,
    warmup=window_warmup(1),
    summary="Ecart-type des seuls rendements AU-DESSUS du seuil, sans unite.",
)
def upside_deviation(ctx: Context, params: SeuilParams) -> float | None:
    """Le miroir de `downside_deviation@1`.

    Son interet n'est pas de mesurer un risque mais de le comparer : le
    rapport des deux dit si la dispersion penche vers le haut ou vers le bas,
    ce qu'aucun ecart-type symetrique ne peut montrer.
    """
    rendements = _rendements(ctx, params.field, params.window, log=False)
    if rendements is None:
        return None
    au_dessus = np.maximum(rendements - params.threshold, 0.0)
    return float(np.sqrt(np.mean(au_dessus * au_dessus)))


@primitive(
    "volatility_ratio",
    version=1,
    params=DoubleWindowParams,
    warmup=lambda p: cast("DoubleWindowParams", p).slow_window + 1,
    summary="Rapport entre volatilite courte et volatilite longue : 1 = regime stable.",
)
def volatility_ratio(ctx: Context, params: DoubleWindowParams) -> float | None:
    """Detecteur de CHANGEMENT de regime, sans unite et sans seuil a calibrer.

    Au-dessus de 1, la volatilite recente depasse la volatilite de fond ; en
    dessous, le marche se calme. C'est la forme la plus robuste de detection
    de regime parce que les deux termes se normalisent mutuellement.
    """
    rendements = _rendements(ctx, Field.CLOSE, params.slow_window, log=True)
    if rendements is None:
        return None
    longue = float(np.std(rendements, ddof=1))
    courte = float(np.std(rendements[-params.window :], ddof=1))
    return securise(courte, longue)


@primitive(
    "atr_ratio",
    version=1,
    params=DoubleWindowParams,
    warmup=lambda p: cast("DoubleWindowParams", p).slow_window + 1,
    summary="Rapport entre ATR court et ATR long : compression ou expansion.",
)
def atr_ratio(ctx: Context, params: DoubleWindowParams) -> float | None:
    """Meme lecture que `volatility_ratio@1`, mais a travers le True Range.

    Les deux different sur les gaps : celui-ci les compte, l'autre non. Un
    ecart marque entre les deux signale que le mouvement se fait entre les
    barres plutot qu'a l'interieur.
    """
    besoin = params.slow_window + 1
    trs = true_range_serie(
        ctx.values(Field.HIGH, besoin),
        ctx.values(Field.LOW, besoin),
        ctx.values(Field.CLOSE, besoin),
    )
    return securise(float(np.mean(trs[-params.window :])), float(np.mean(trs)))


@primitive(
    "rvi_volatility",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Relative Volatility Index : un RSI calcule sur l'ecart-type, de 0 a 100.",
)
def rvi_volatility(ctx: Context, params: FieldWindowParams) -> float | None:
    """Repond a « la volatilite vient-elle plutot du haut ou du bas ? ».

    A ne pas confondre avec `rvgi@1`, le Relative Vigor Index, qui mesure tout
    autre chose. Les deux portent le sigle RVI dans la litterature ; ils sont
    nommes differemment ici precisement pour qu'on ne puisse pas les confondre
    dans une specification.
    """
    deltas = np.diff(ctx.values(params.field, params.window + 1))
    hausses = deltas[deltas > 0.0]
    baisses = deltas[deltas < 0.0]
    haut = float(np.std(hausses, ddof=0)) * hausses.size if hausses.size else 0.0
    bas = float(np.std(baisses, ddof=0)) * baisses.size if baisses.size else 0.0
    return securise(100.0 * haut, haut + bas)


@primitive(
    "atr_wilder_pct",
    version=1,
    params=WilderPctParams,
    warmup=lambda p: cast("WilderPctParams", p).lookback + 1,
    summary="ATR lisse a la Wilder, rapporte a la cloture, en pourcentage.",
)
def atr_wilder_pct(ctx: Context, params: WilderPctParams) -> float | None:
    """`natr@1` avec le lissage de Wilder au lieu de la moyenne simple.

    Les deux existent pour la meme raison que `atr@1` et `atr_wilder@1` : le
    lissage change le resultat, et le choisir doit etre un acte explicite, pas
    une consequence de la version resolue.
    """
    besoin = params.lookback + 1
    trs = true_range_serie(
        ctx.values(Field.HIGH, besoin),
        ctx.values(Field.LOW, besoin),
        ctx.values(Field.CLOSE, besoin),
    )
    lisse = float(wilder_serie(trs, params.window)[-1])
    return securise(100.0 * lisse, ctx.value(Field.CLOSE))
