"""Tendance et direction : y a-t-il une tendance, et dans quel sens.

A distinguer des oscillateurs de momentum, qui mesurent une VITESSE. Ici on
mesure plutot une QUALITE de mouvement : un marche peut monter vite en zigzag
(momentum fort, direction faible) ou deriver lentement en ligne droite
(momentum faible, direction forte). Confondre les deux familles est l'erreur
de lecture la plus courante sur l'ADX.

Les indicateurs recursifs de ce module (`psar`, `supertrend`) suivent la meme
convention que les EMA du depot : historique TRONQUE, amorce explicite,
resultat deterministe. Leur valeur exacte depend en theorie de toute
l'histoire ; ce qui est calcule ici ne depend que de `lookback` barres, et
c'est dit.
"""

from __future__ import annotations

from enum import StrEnum
from typing import cast

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import Field
from rsl.primitives.base import PrimitiveParams, WindowParams, window_warmup
from rsl.primitives.builtin.lissage import (
    pente_de,
    securise,
    true_range_serie,
    wilder_serie,
)
from rsl.primitives.builtin.params import FieldWindowParams
from rsl.primitives.registry import primitive


class AroonOutput(StrEnum):
    """Quelle branche de l'Aroon lire."""

    UP = "up"
    DOWN = "down"
    OSCILLATOR = "oscillator"


class VortexOutput(StrEnum):
    """Quelle branche du vortex lire."""

    PLUS = "plus"
    MINUS = "minus"
    DIFF = "diff"


class TrailOutput(StrEnum):
    """Niveau du stop suiveur, ou seulement le sens qu'il indique."""

    VALUE = "value"
    DIRECTION = "direction"


class AroonParams(WindowParams):
    """Aroon : depuis combien de barres remonte l'extreme de la fenetre."""

    output: AroonOutput = AroonOutput.UP


class VortexParams(WindowParams):
    """Vortex : mouvement haussier et baissier rapportes au True Range."""

    output: VortexOutput = VortexOutput.PLUS


class PsarParams(PrimitiveParams):
    """SAR parabolique : acceleration initiale, pas, et plafond."""

    step: float = 0.02
    maximum: float = 0.2
    lookback: int = 120
    output: TrailOutput = TrailOutput.VALUE

    def model_post_init(self, _context: object, /) -> None:
        if self.step <= 0.0:
            raise ValueError(f"step doit etre > 0, recu {self.step}")
        if self.maximum < self.step:
            raise ValueError(
                f"maximum ({self.maximum}) doit etre >= step ({self.step})"
            )
        if self.lookback < 10:
            raise ValueError(
                f"lookback doit etre >= 10, recu {self.lookback} : en dessous, "
                f"l'amorce domine le resultat"
            )


class SupertrendParams(WindowParams):
    """Supertrend : bandes ATR verrouillees dans le sens de la tendance."""

    multiplier: float = 3.0
    lookback_multiplier: int = 8
    output: TrailOutput = TrailOutput.VALUE

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.multiplier <= 0.0:
            raise ValueError(f"multiplier doit etre > 0, recu {self.multiplier}")
        if self.lookback_multiplier < 2:
            raise ValueError(
                f"lookback_multiplier doit etre >= 2, recu {self.lookback_multiplier}"
            )

    @property
    def lookback(self) -> int:
        return self.window * self.lookback_multiplier


class WilderWindowParams(WindowParams):
    """Fenetre de Wilder avec sa profondeur d'amorce."""

    seed_multiplier: int = 5

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.seed_multiplier < 2:
            raise ValueError(f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier}")

    @property
    def lookback(self) -> int:
        return self.window * self.seed_multiplier


def _wilder_warmup(params: PrimitiveParams) -> int:
    return cast("WilderWindowParams", params).lookback + 1


def _adxr_warmup(params: PrimitiveParams) -> int:
    """L'ADX lui-meme, plus `window` barres pour aller chercher sa valeur passee."""
    reglages = cast("WilderWindowParams", params)
    return reglages.lookback + reglages.window + 1


def _psar_warmup(params: PrimitiveParams) -> int:
    return cast("PsarParams", params).lookback


def _supertrend_warmup(params: PrimitiveParams) -> int:
    return cast("SupertrendParams", params).lookback + 1


def _mouvements_directionnels(
    hauts: np.ndarray, bas: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """`+DM` et `-DM` de Wilder : un seul des deux est non nul par barre.

    La regle « le plus grand des deux gagne, l'autre est mis a zero » est ce
    qui distingue le systeme directionnel d'une simple mesure d'amplitude.
    """
    hausse = hauts[1:] - hauts[:-1]
    baisse = bas[:-1] - bas[1:]
    plus = np.where((hausse > baisse) & (hausse > 0.0), hausse, 0.0)
    moins = np.where((baisse > hausse) & (baisse > 0.0), baisse, 0.0)
    return plus, moins


# ---------------------------------------------------------------------------
# Systeme directionnel de Wilder, les pieces que `adx@1` n'expose pas
# ---------------------------------------------------------------------------


@primitive(
    "dx",
    version=1,
    params=WilderWindowParams,
    warmup=_wilder_warmup,
    summary="Indice directionnel brut : ecart relatif entre `+DI` et `-DI`, non lisse.",
)
def dx(ctx: Context, params: WilderWindowParams) -> float | None:
    """L'etape avant l'ADX : `|+DI - -DI| / (+DI + -DI)`.

    Beaucoup plus nerveux que l'ADX, qui en est la moyenne lissee. Utile quand
    on veut detecter un changement de regime SANS le retard du lissage - au
    prix des faux signaux que ce lissage supprime.
    """
    besoin = params.lookback + 1
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    plus, moins = _mouvements_directionnels(hauts, bas)
    trs = true_range_serie(hauts, bas, clotures)
    tr_lisse = wilder_serie(trs, params.window)
    if tr_lisse[-1] <= 0.0:
        return None
    plus_di = 100.0 * float(wilder_serie(plus, params.window)[-1]) / float(tr_lisse[-1])
    moins_di = 100.0 * float(wilder_serie(moins, params.window)[-1]) / float(tr_lisse[-1])
    return securise(100.0 * abs(plus_di - moins_di), plus_di + moins_di)


@primitive(
    "adxr",
    version=1,
    params=WilderWindowParams,
    warmup=_adxr_warmup,
    summary="ADX moyenne avec sa propre valeur d'il y a `window` barres.",
)
def adxr(ctx: Context, params: WilderWindowParams) -> float | None:
    """Lissage supplementaire de l'ADX, par moyenne avec son passe.

    Wilder l'utilisait pour classer les marches par « negociabilite » plutot
    que pour declencher : il est encore plus lent que l'ADX, ce qui le rend
    inutilisable comme signal d'entree.
    """
    fenetre = params.window
    besoin = params.lookback + fenetre + 1
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    plus, moins = _mouvements_directionnels(hauts, bas)
    trs = true_range_serie(hauts, bas, clotures)
    tr_lisse = wilder_serie(trs, fenetre)
    plus_lisse = wilder_serie(plus, fenetre)
    moins_lisse = wilder_serie(moins, fenetre)

    valides = tr_lisse > 0.0
    if not np.all(valides):
        return None
    plus_di = 100.0 * plus_lisse / tr_lisse
    moins_di = 100.0 * moins_lisse / tr_lisse
    somme = plus_di + moins_di
    if np.any(somme <= 0.0):
        return None
    dxs = 100.0 * np.abs(plus_di - moins_di) / somme
    if dxs.size < fenetre:
        return None
    adxs = wilder_serie(dxs, fenetre)
    if adxs.size < fenetre + 1:
        return None
    return (float(adxs[-1]) + float(adxs[-1 - fenetre])) / 2.0


# ---------------------------------------------------------------------------
# Detecteurs de tendance qui ne passent pas par Wilder
# ---------------------------------------------------------------------------


@primitive(
    "aroon",
    version=1,
    params=AroonParams,
    warmup=window_warmup(),
    summary="Aroon : anciennete du plus haut et du plus bas, en % de la fenetre.",
)
def aroon(ctx: Context, params: AroonParams) -> float | None:
    """Mesure le TEMPS ecoule depuis l'extreme, pas son amplitude.

    C'est ce qui le rend complementaire de tout le reste : une tendance qui
    fait un nouveau plus haut chaque jour donne `up = 100` quelle que soit la
    taille des pas. L'oscillateur (`up - down`) est borne a `[-100, 100]`.
    """
    hauts = ctx.values(Field.HIGH, params.window)
    bas = ctx.values(Field.LOW, params.window)
    depuis_haut = params.window - 1 - int(np.argmax(hauts))
    depuis_bas = params.window - 1 - int(np.argmin(bas))
    haut = 100.0 * (params.window - depuis_haut) / params.window
    bas_pct = 100.0 * (params.window - depuis_bas) / params.window
    if params.output is AroonOutput.UP:
        return haut
    if params.output is AroonOutput.DOWN:
        return bas_pct
    return haut - bas_pct


@primitive(
    "vortex",
    version=1,
    params=VortexParams,
    warmup=window_warmup(1),
    summary="Vortex : mouvements haussier et baissier rapportes au True Range.",
)
def vortex(ctx: Context, params: VortexParams) -> float | None:
    """Deux courbes qui se croisent aux changements de tendance.

    `plus` et `minus` tournent autour de 1 ; leur croisement est le signal. La
    sortie `diff` (`plus - minus`) en donne directement le signe, ce qui evite
    d'avoir a composer deux primitives pour le tester.
    """
    besoin = params.window + 1
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    vm_plus = float(np.sum(np.abs(hauts[1:] - bas[:-1])))
    vm_moins = float(np.sum(np.abs(bas[1:] - hauts[:-1])))
    total_tr = float(np.sum(true_range_serie(hauts, bas, clotures)))
    if total_tr <= 0.0:
        return None
    plus, moins = vm_plus / total_tr, vm_moins / total_tr
    if params.output is VortexOutput.PLUS:
        return plus
    if params.output is VortexOutput.MINUS:
        return moins
    return plus - moins


@primitive(
    "chop",
    version=1,
    params=WindowParams,
    warmup=window_warmup(1),
    summary="Indice de choppiness : 100 en marche lateral, 0 en tendance franche.",
)
def chop(ctx: Context, params: WindowParams) -> float | None:
    """Compare le chemin PARCOURU a l'amplitude NETTE de la fenetre.

    Se lit a l'envers de l'ADX : ici un chiffre HAUT signale l'absence de
    tendance. C'est une mesure de regime, pas de direction - elle ne dit
    jamais dans quel sens aller.
    """
    besoin = params.window + 1
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    total_tr = float(np.sum(true_range_serie(hauts, bas, clotures)))
    etendue = float(np.max(hauts[1:])) - float(np.min(bas[1:]))
    if etendue <= 0.0 or total_tr <= 0.0:
        return None
    rapport = securise(total_tr, etendue)
    if rapport is None or rapport <= 0.0:
        return None
    return 100.0 * float(np.log10(rapport)) / float(np.log10(params.window))


@primitive(
    "vhf",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(1),
    summary="Vertical Horizontal Filter : amplitude nette sur somme des variations.",
)
def vhf(ctx: Context, params: FieldWindowParams) -> float | None:
    """Meme question que `chop@1`, posee sur un seul champ de prix.

    Se lit dans l'autre sens : un chiffre HAUT signale une tendance. Les deux
    sont publies parce qu'ils ne repondent pas pareil aux gaps - `chop@1`
    passe par le True Range, celui-ci non.
    """
    valeurs = ctx.values(params.field, params.window + 1)
    etendue = float(np.max(valeurs)) - float(np.min(valeurs))
    chemin = float(np.sum(np.abs(np.diff(valeurs))))
    return securise(etendue, chemin)


@primitive(
    "cti",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Correlation Trend Indicator : correlation du prix avec le temps, de -1 a 1.",
)
def cti(ctx: Context, params: FieldWindowParams) -> float | None:
    """A quel point le prix avance-t-il en ligne droite.

    Vaut 1 pour une rampe parfaitement croissante, -1 pour une decroissante,
    0 pour du bruit. Sans unite et borne, donc directement comparable entre
    instruments et entre epoques - ce que la pente de `slope@1` n'est pas.
    """
    fenetre = ctx.values(params.field, params.window)
    temps = np.arange(params.window, dtype=np.float64)
    ecart_prix = float(np.std(fenetre))
    if ecart_prix <= 0.0:
        return None
    return float(np.corrcoef(temps, fenetre)[0, 1])


@primitive(
    "linreg_r2",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Coefficient de determination de la regression lineaire, de 0 a 1.",
)
def linreg_r2(ctx: Context, params: FieldWindowParams) -> float | None:
    """Le carre de `cti@1` : la part de variance expliquee par la tendance.

    Ignore le SENS, contrairement a `cti@1`. Utile comme filtre de regime -
    « n'agir que si la tendance explique plus de 70 % du mouvement » - sans
    presumer de la direction.
    """
    valeur = cti(ctx, params)
    return None if valeur is None else valeur * valeur


@primitive(
    "linreg_angle",
    version=1,
    params=FieldWindowParams,
    warmup=window_warmup(),
    summary="Pente de la regression exprimee en degres, de -90 a 90.",
)
def linreg_angle(ctx: Context, params: FieldWindowParams) -> float | None:
    """L'angle de la droite de regression, une barre valant une unite.

    A manier avec prudence : l'angle depend de l'echelle des prix, donc un
    meme angle ne represente pas la meme chose sur ES et sur CL. Publie parce
    que la litterature l'emploie, pas parce qu'il est recommandable.
    """
    fenetre = ctx.values(params.field, params.window)
    return float(np.degrees(np.arctan(pente_de(fenetre))))


@primitive(
    "ttm_trend",
    version=1,
    params=WindowParams,
    warmup=window_warmup(),
    summary="TTM Trend : 1 si la cloture est au-dessus du prix median moyen, sinon 0.",
)
def ttm_trend(ctx: Context, params: WindowParams) -> float | None:
    """Reduction binaire de la tendance, pensee pour colorer des bougies.

    Ne donne aucune nuance : c'est son interet comme filtre, et sa limite
    comme signal.
    """
    medians = (
        ctx.values(Field.HIGH, params.window) + ctx.values(Field.LOW, params.window)
    ) / 2.0
    return 1.0 if ctx.value(Field.CLOSE) > float(np.mean(medians)) else 0.0


# ---------------------------------------------------------------------------
# Stops suiveurs : recursifs, donc sur historique tronque
# ---------------------------------------------------------------------------


@primitive(
    "psar",
    version=1,
    params=PsarParams,
    warmup=_psar_warmup,
    summary="SAR parabolique de Wilder : niveau du stop suiveur, ou son sens.",
)
def psar(ctx: Context, params: PsarParams) -> float | None:
    """Stop qui se rapproche du prix a vitesse croissante tant qu'il progresse.

    Recursif par nature : chaque valeur depend de la precedente et du sens en
    cours. Comme pour l'EMA, le calcul part d'un historique TRONQUE de
    `lookback` barres, amorce en supposant une tendance haussiere ancree sur
    le plus bas de la premiere barre.

    Consequence a connaitre : sur une serie ou la tendance initiale reelle
    etait baissiere, les premieres dizaines de barres de l'historique tronque
    peuvent differer d'un calcul depuis l'origine. Le retournement se produit
    vite - le SAR est concu pour cela - mais le resultat n'est pas exact au
    sens d'un calcul complet, seulement DETERMINISTE.

    `direction` vaut +1 en tendance haussiere et -1 en baissiere : c'est
    souvent ce qu'on veut composer, plutot que le niveau lui-meme.
    """
    hauts = ctx.values(Field.HIGH, params.lookback)
    bas = ctx.values(Field.LOW, params.lookback)

    haussier = True
    sar = float(bas[0])
    extreme = float(hauts[0])
    acceleration = params.step

    for rang in range(1, params.lookback):
        haut, bas_barre = float(hauts[rang]), float(bas[rang])
        sar = sar + acceleration * (extreme - sar)
        if haussier:
            sar = min(sar, float(bas[rang - 1]), bas_barre)
            if bas_barre < sar:
                haussier = False
                sar, extreme, acceleration = extreme, bas_barre, params.step
            elif haut > extreme:
                extreme = haut
                acceleration = min(acceleration + params.step, params.maximum)
        else:
            sar = max(sar, float(hauts[rang - 1]), haut)
            if haut > sar:
                haussier = True
                sar, extreme, acceleration = extreme, haut, params.step
            elif bas_barre < extreme:
                extreme = bas_barre
                acceleration = min(acceleration + params.step, params.maximum)

    if params.output is TrailOutput.DIRECTION:
        return 1.0 if haussier else -1.0
    return sar


@primitive(
    "supertrend",
    version=1,
    params=SupertrendParams,
    warmup=_supertrend_warmup,
    summary="Supertrend : bande ATR verrouillee dans le sens de la tendance.",
)
def supertrend(ctx: Context, params: SupertrendParams) -> float | None:
    """Bande de Keltner qui ne peut se resserrer que dans le sens du marche.

    Le verrouillage est ce qui la distingue d'un simple canal : tant que la
    tendance tient, la bande ne s'eloigne jamais du prix. C'est aussi ce qui
    la rend recursive, donc calculee sur historique tronque - meme reserve que
    pour `psar@1`.
    """
    besoin = params.lookback + 1
    hauts = ctx.values(Field.HIGH, besoin)
    bas = ctx.values(Field.LOW, besoin)
    clotures = ctx.values(Field.CLOSE, besoin)

    trs = true_range_serie(hauts, bas, clotures)
    atrs = wilder_serie(trs, params.window)
    debut = besoin - atrs.size

    medians = (hauts[debut:] + bas[debut:]) / 2.0
    hautes = medians + params.multiplier * atrs
    basses = medians - params.multiplier * atrs
    fermetures = clotures[debut:]

    haussier = True
    borne_haute = float(hautes[0])
    borne_basse = float(basses[0])
    for rang in range(1, fermetures.size):
        candidate_haute = float(hautes[rang])
        candidate_basse = float(basses[rang])
        precedente = float(fermetures[rang - 1])
        if candidate_haute < borne_haute or precedente > borne_haute:
            borne_haute = candidate_haute
        if candidate_basse > borne_basse or precedente < borne_basse:
            borne_basse = candidate_basse
        cloture = float(fermetures[rang])
        if cloture > borne_haute:
            haussier = True
        elif cloture < borne_basse:
            haussier = False

    if params.output is TrailOutput.DIRECTION:
        return 1.0 if haussier else -1.0
    return borne_basse if haussier else borne_haute
