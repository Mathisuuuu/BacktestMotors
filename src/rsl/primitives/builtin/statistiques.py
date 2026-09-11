"""Statistiques descriptives sur fenetre glissante.

`stats.py` porte deja `stdev`, `zscore`, `slope`, `volatility`, `returns` et
`efficiency_ratio`. Ce module complete la description d'une distribution -
forme, dispersion robuste, rang - et ajoute les mesures de DEPENDANCE, qui
sont les seules a repondre a « ce mouvement ressemble-t-il au precedent ».

Toutes sont calculees sur la fenetre PASSEE, jamais sur l'echantillon complet.
Normaliser ou classer sur tout l'echantillon injecte le futur dans chaque
point - c'est la fuite n° 4 de `docs/no-lookahead.md`, et elle est ici
inexprimable : le contexte ne donne acces qu'au passe.
"""

from __future__ import annotations

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import WindowParams, window_warmup
from rsl.primitives.builtin.lissage import securise
from rsl.primitives.builtin.params import FieldWindowParams
from rsl.primitives.registry import primitive


class QuantileParams(FieldWindowParams):
    """Quantile empirique de la fenetre."""

    q: float = 0.5

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if not 0.0 <= self.q <= 1.0:
            raise ValueError(f"q doit etre dans [0, 1], recu {self.q}")


class LagParams(FieldWindowParams):
    """Fenetre + decalage de la comparaison."""

    lag: int = 1

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.lag < 1:
            raise ValueError(f"lag doit etre >= 1, recu {self.lag}")


class PaireParams(WindowParams):
    """Deux champs a comparer sur la meme fenetre."""

    field: Field = Field.CLOSE
    other: Field = Field.VOLUME


class EntropieParams(FieldWindowParams):
    """Entropie de Shannon sur un histogramme a `bins` classes."""

    bins: int = 8

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.bins < 2:
            raise ValueError(f"bins doit etre >= 2, recu {self.bins}")


# ---------------------------------------------------------------------------
# Forme de la distribution
# ---------------------------------------------------------------------------


@primitive(
    "variance",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Variance de la fenetre, en unites de prix au carre.",
)
def variance(ctx: Context, params: FieldWindowParams) -> float | None:
    """Le carre de `stdev@1`, publie parce que certaines formules l'attendent.

    En unites de prix AU CARRE : elle ne s'additionne pas a un prix et ne se
    compare pas entre instruments. `stdev@1` est presque toujours le bon choix.
    """
    return float(np.var(ctx.values(params.field, params.window), ddof=1))


@primitive(
    "skew",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Asymetrie des rendements de la fenetre : negatif = queue a gauche.",
)
def skew(ctx: Context, params: FieldWindowParams) -> float | None:
    """Mesure sur les RENDEMENTS, pas sur les prix.

    L'asymetrie d'une serie de prix en tendance mesure surtout la tendance ;
    celle des rendements mesure ce qu'on veut vraiment savoir - de quel cote
    se trouvent les mouvements extremes. Une asymetrie negative marquee signale
    un actif qui monte doucement et chute brutalement.
    """
    valeurs = ctx.values(params.field, params.window + 1)
    if np.any(valeurs[:-1] <= 0.0):
        return None
    rendements = np.diff(valeurs) / valeurs[:-1]
    ecart = float(np.std(rendements, ddof=0))
    if ecart <= 0.0:
        return None
    centres = rendements - float(np.mean(rendements))
    return float(np.mean(centres**3)) / (ecart**3)


@primitive(
    "kurtosis",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Kurtosis EXCEDENTAIRE des rendements : 0 pour une loi normale.",
)
def kurtosis(ctx: Context, params: FieldWindowParams) -> float | None:
    """Epaisseur des queues, referencee a la loi normale.

    Excedentaire, c'est-a-dire diminuee de 3 : une valeur positive signifie
    des extremes plus frequents qu'une gaussienne. Sur des rendements de
    marche elle est presque toujours positive, et c'est precisement pour cela
    que les modeles gaussiens sous-estiment le risque de queue.
    """
    valeurs = ctx.values(params.field, params.window + 1)
    if np.any(valeurs[:-1] <= 0.0):
        return None
    rendements = np.diff(valeurs) / valeurs[:-1]
    ecart = float(np.std(rendements, ddof=0))
    if ecart <= 0.0:
        return None
    centres = rendements - float(np.mean(rendements))
    return float(np.mean(centres**4)) / (ecart**4) - 3.0


@primitive(
    "median",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Mediane de la fenetre : la moyenne qui ignore les valeurs aberrantes.",
)
def median(ctx: Context, params: FieldWindowParams) -> float | None:
    """Insensible a une barre aberrante, contrairement a `sma@1`.

    Sur des donnees de marche brutes, ou une impression erronee arrive, c'est
    souvent la difference entre un signal et un accident.
    """
    return float(np.median(ctx.values(params.field, params.window)))


@primitive(
    "quantile",
    version=1,
    params=QuantileParams,
    warmup=window_warmup(),
    summary="Quantile empirique de la fenetre, `q` entre 0 et 1.",
)
def quantile(ctx: Context, params: QuantileParams) -> float | None:
    """Generalise `median@1`, `rolling_high@1` et `rolling_low@1`.

    `q=0` donne le minimum, `q=1` le maximum, `q=0.5` la mediane. Utile pour
    des seuils robustes : un stop au quantile 10 % de la fenetre ignore le
    creux accidentel que le minimum retiendrait.
    """
    return float(np.quantile(ctx.values(params.field, params.window), params.q))


@primitive(
    "mad",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Ecart absolu moyen a la moyenne : dispersion robuste, en unites de prix.",
)
def mad(ctx: Context, params: FieldWindowParams) -> float | None:
    """Dispersion qui ne met pas les ecarts au carre.

    Moins sensible aux extremes que l'ecart-type, et c'est son interet. C'est
    aussi le denominateur du CCI, ce qui explique qu'il soit publie ici.
    """
    fenetre = ctx.values(params.field, params.window)
    return float(np.mean(np.abs(fenetre - float(np.mean(fenetre)))))


@primitive(
    "stderr",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Erreur type de la moyenne : ecart-type divise par la racine de la fenetre.",
)
def stderr(ctx: Context, params: FieldWindowParams) -> float | None:
    """De combien la moyenne de la fenetre est-elle elle-meme incertaine.

    Repond a une question differente de `stdev@1` : celle-ci mesure la
    dispersion des observations, celle-la la precision de leur moyenne. Diviser
    par la racine de la taille est ce qui fait qu'une fenetre plus longue donne
    une moyenne plus sure - au prix du retard.
    """
    fenetre = ctx.values(params.field, params.window)
    return float(np.std(fenetre, ddof=1)) / float(np.sqrt(params.window))


@primitive(
    "percentile_rank",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Rang de la valeur courante dans sa fenetre passee, de 0 a 100.",
)
def percentile_rank(ctx: Context, params: FieldWindowParams) -> float | None:
    """Ou se situe le present par rapport a son propre passe recent.

    Sans unite et borne : c'est la facon la plus robuste de comparer deux
    instruments dont les echelles n'ont rien a voir. Un rang de 95 dit « plus
    haut que 95 % des barres de la fenetre », ce qui a le meme sens partout.
    """
    fenetre = ctx.values(params.field, params.window)
    courante = float(fenetre[-1])
    return 100.0 * float(np.count_nonzero(fenetre <= courante)) / params.window


@primitive(
    "entropy",
    version=1,
    params=EntropieParams,
    warmup=window_warmup(1),
    summary="Entropie de Shannon des rendements, normalisee entre 0 et 1.",
)
def entropy(ctx: Context, params: EntropieParams) -> float | None:
    """Mesure le DESORDRE des rendements, sans hypothese de distribution.

    Proche de 1 : les rendements se repartissent uniformement, le marche est
    imprevisible. Proche de 0 : ils se concentrent dans quelques classes, donc
    une structure existe.

    L'histogramme est construit sur la fenetre elle-meme, donc les classes
    changent a chaque barre. Ce n'est pas une fuite - elles ne dependent que du
    passe - mais cela rend deux valeurs successives moins comparables qu'il n'y
    parait.
    """
    valeurs = ctx.values(params.field, params.window + 1)
    if np.any(valeurs[:-1] <= 0.0):
        return None
    rendements = np.diff(valeurs) / valeurs[:-1]
    etendue = float(np.max(rendements)) - float(np.min(rendements))
    if etendue <= 0.0:
        return None
    effectifs, _ = np.histogram(rendements, bins=params.bins)
    total = float(np.sum(effectifs))
    if total <= 0.0:
        return None
    parts = effectifs[effectifs > 0] / total
    brute = -float(np.sum(parts * np.log(parts)))
    return brute / float(np.log(params.bins))


# ---------------------------------------------------------------------------
# Dependance : ce mouvement ressemble-t-il a un autre
# ---------------------------------------------------------------------------


@primitive(
    "autocorrelation",
    version=1,
    params=LagParams,
    warmup=lambda p: getattr(p, "window", 20) + getattr(p, "lag", 1) + 1,
    summary="Autocorrelation des rendements au decalage `lag`, de -1 a 1.",
)
def autocorrelation(ctx: Context, params: LagParams) -> float | None:
    """Un rendement ressemble-t-il a celui d'il y a `lag` barres.

    Positive : le mouvement persiste, un suivi de tendance a un fondement.
    Negative : il se retourne, un retour a la moyenne en a un. Proche de zero :
    ni l'un ni l'autre, et aucune des deux familles n'a de raison de marcher.

    C'est une des rares mesures qui dise QUEL TYPE de strategie a une chance,
    au lieu de dire quoi faire maintenant.
    """
    besoin = params.window + params.lag + 1
    valeurs = ctx.values(params.field, besoin)
    if np.any(valeurs[:-1] <= 0.0):
        return None
    rendements = np.diff(valeurs) / valeurs[:-1]
    presents = rendements[params.lag :]
    passes = rendements[: rendements.size - params.lag]
    if float(np.std(presents)) <= 0.0 or float(np.std(passes)) <= 0.0:
        return None
    return float(np.corrcoef(presents, passes)[0, 1])


@primitive(
    "correlation",
    version=1,
    params=PaireParams,
    warmup=window_warmup(),
    summary="Correlation entre deux champs de la MEME barre, sur la fenetre.",
)
def correlation(ctx: Context, params: PaireParams) -> float | None:
    """Correlation entre deux colonnes du meme instrument.

    L'usage principal est `close` contre `volume` : une correlation positive
    dit que les hausses se font a volume croissant.

    Pour correler DEUX INSTRUMENTS, cette primitive ne convient pas - elle ne
    voit qu'un magasin. Il faut composer avec le noeud `peer`, qui est fait
    pour cela.
    """
    a = ctx.values(params.field, params.window)
    b = ctx.values(params.other, params.window)
    if float(np.std(a)) <= 0.0 or float(np.std(b)) <= 0.0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


@primitive(
    "beta",
    version=1,
    params=PaireParams,
    warmup=window_warmup(1),
    summary="Pente de la regression des rendements d'un champ sur ceux d'un autre.",
)
def beta(ctx: Context, params: PaireParams) -> float | None:
    """Sensibilite d'un champ aux variations d'un autre.

    Meme reserve que `correlation@1` : sur un seul instrument, l'usage est
    limite. Le beta qui interesse vraiment - celui d'un instrument par rapport
    a un indice - se compose avec `peer`.
    """
    besoin = params.window + 1
    a = ctx.values(params.field, besoin)
    b = ctx.values(params.other, besoin)
    if np.any(a[:-1] <= 0.0) or np.any(b[:-1] <= 0.0):
        return None
    ra = np.diff(a) / a[:-1]
    rb = np.diff(b) / b[:-1]
    return securise(
        float(np.cov(ra, rb, bias=True)[0, 1]), float(np.var(rb))
    )


@primitive(
    "hurst",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Exposant de Hurst : 0,5 = marche aleatoire, >0,5 = persistance.",
)
def hurst(ctx: Context, params: FieldWindowParams) -> float | None:
    """Estime si la serie a de la memoire, par la methode des moments.

    Au-dessus de 0,5 les mouvements persistent, en dessous ils se retournent,
    a 0,5 c'est une marche aleatoire.

    Estimateur simplifie, sur fenetre COURTE : son biais est reel et connu, et
    l'exposant estime sur quelques dizaines de barres est une indication de
    regime, pas une mesure fiable de la memoire longue. L'employer comme seuil
    binaire (« > 0,5 donc tendance ») est un abus.
    """
    valeurs = ctx.values(params.field, params.window + 1)
    if np.any(valeurs[:-1] <= 0.0):
        return None
    rendements = np.diff(np.log(valeurs))
    if rendements.size < 8:
        return None

    echelles = [2, 4, 8]
    echelles = [e for e in echelles if rendements.size // e >= 2]
    if len(echelles) < 2:
        return None

    x, y = [], []
    for echelle in echelles:
        blocs = rendements.size // echelle
        sommes = np.array(
            [float(np.sum(rendements[i * echelle : (i + 1) * echelle])) for i in range(blocs)]
        )
        dispersion = float(np.std(sommes, ddof=0))
        if dispersion <= 0.0:
            return None
        x.append(np.log(echelle))
        y.append(np.log(dispersion))
    variance_x = float(np.var(x))
    if variance_x <= 0.0:
        return None
    return float(np.cov(x, y, bias=True)[0, 1] / variance_x)
