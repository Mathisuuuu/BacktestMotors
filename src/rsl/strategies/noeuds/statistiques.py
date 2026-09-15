"""Noyaux numeriques des statistiques de fenetre, purs et isoles.

Pourquoi ce module existe a part
---------------------------------
Les statistiques deja presentes vivent dans le `match` de `Rolling.__call__`.
Elles y sont lisibles tant qu'elles tiennent en une ligne de numpy. Celles
ajoutees ici ne tiennent pas : `arg_max` porte une convention d'indexation
inversee, `decroissance_lineaire` une ponderation normalisee, `correlation`
un cas degenere qui doit rendre `None` et non zero. Chacune merite son test
propre, et un test ne s'ecrit proprement que contre une fonction qu'on peut
appeler seule.

Ces fonctions ne connaissent ni `Context`, ni barre, ni instrument. Elles
prennent un tableau et rendent un flottant. C'est ce qui rend le look-ahead
inexprimable ICI sans aucune garantie a ecrire : une fonction qui ne voit que
sa fenetre ne peut pas voir au-dela.

LA CONVENTION D'ORDRE, qui est la source d'erreur numero un
-------------------------------------------------------------
`valeurs_de_fenetre` rend les valeurs du **present vers le passe** :

    fenetre[0]  = la barre courante
    fenetre[-1] = la plus ancienne de la fenetre

C'est l'inverse de l'ordre chronologique, et l'inverse de ce qu'un lecteur
habitue a pandas suppose. Toutes les fonctions de ce module recoivent cet
ordre-la et le documentent une par une.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

__all__ = [
    "correlation",
    "covariance",
    "decroissance_lineaire",
    "produit",
    "puissance_signee",
    "rang_du_maximum",
    "rang_du_minimum",
]


def produit(fenetre: FloatArray) -> float | None:
    """Produit des valeurs de la fenetre (`ts_product`).

    Rend `None` plutot qu'un infini quand le produit deborde. Un `inf` qui
    circule dans une comparaison la rend vraie ou fausse en silence ; un
    `None` arrete la regle, ce que le socle exige partout ailleurs.

    Le debordement est ATTENDU, donc numpy ne doit pas s'en plaindre : un
    avertissement emis au moment ou la fonction se comporte correctement
    apprend a ignorer les avertissements.
    """
    with np.errstate(over="ignore", invalid="ignore"):
        valeur = float(np.prod(fenetre))
    return None if not np.isfinite(valeur) else valeur


def rang_du_maximum(fenetre: FloatArray) -> float:
    """`ts_argmax` : position du maximum, EN JOURS DEPUIS LE PLUS ANCIEN, base 1.

    C'est la convention de Kakushadze, et elle merite d'etre epelee parce
    qu'elle se trompe dans les deux sens :

    - si le maximum est la valeur **la plus recente**, le resultat vaut `d`,
      la taille de la fenetre ;
    - s'il est la **plus ancienne**, le resultat vaut `1` ;
    - il ne vaut JAMAIS `0`.

    Notre fenetre arrivant du present vers le passe, la conversion est
    `d - argmax(fenetre)`. En cas d'ex aequo, `np.argmax` rend le premier,
    c'est-a-dire le PLUS RECENT : l'ex aequo le plus proche du present gagne.

    >>> rang_du_maximum(np.array([5.0, 1.0, 2.0]))   # max au present
    3.0
    >>> rang_du_maximum(np.array([1.0, 2.0, 5.0]))   # max au plus ancien
    1.0
    """
    return float(fenetre.size - int(np.argmax(fenetre)))


def rang_du_minimum(fenetre: FloatArray) -> float:
    """`ts_argmin` : meme convention que [`rang_du_maximum`], pour le minimum."""
    return float(fenetre.size - int(np.argmin(fenetre)))


def decroissance_lineaire(fenetre: FloatArray) -> float:
    """`decay_linear` : moyenne ponderee, le plus RECENT pesant le plus.

    Poids `d, d-1, ..., 1` du present vers le passe, normalises pour sommer a
    un. La fenetre arrivant deja dans cet ordre, les poids se lisent
    directement : `fenetre[0]` recoit `d`, `fenetre[-1]` recoit `1`.

    Le denominateur est `d(d+1)/2`, jamais nul pour `d >= 1`.

    >>> decroissance_lineaire(np.array([3.0, 2.0, 1.0]))  # (3*3+2*2+1*1)/6
    2.3333333333333335
    """
    taille = fenetre.size
    poids = np.arange(taille, 0, -1, dtype=np.float64)
    return float(np.dot(fenetre, poids) / poids.sum())


def puissance_signee(valeur: float, exposant: float) -> float | None:
    """`signedpower(x, a)` = `sign(x) * abs(x) ** a`.

    Ce n'est pas `x ** a`, et la difference est le point : `(-8) ** (1/3)`
    n'existe pas dans les reels, tandis que `signedpower(-8, 1/3)` vaut -2.
    L'ecriture garde donc le signe du rendement tout en comprimant son
    amplitude, ce qui est l'usage courant sur des rendements.

    Rend `None` quand le resultat n'est pas defini ou pas fini.

    Le zero est traite AVANT l'elevation, et pas seulement teste apres : en
    Python, `0.0 ** -1.0` leve `ZeroDivisionError` au lieu de rendre `inf`,
    si bien qu'un garde-fou pose en aval ne serait jamais atteint. Pour un
    exposant positif, `signedpower(0, a)` vaut zero - le signe de zero etant
    zero, l'amplitude ne compte pas.
    """
    if valeur == 0.0:
        return 0.0 if exposant > 0.0 else None
    signe = 1.0 if valeur > 0.0 else -1.0
    resultat = signe * abs(valeur) ** exposant
    return None if not np.isfinite(resultat) else resultat


def covariance(gauche: FloatArray, droite: FloatArray) -> float | None:
    """Covariance d'echantillon des deux fenetres, `ddof=1`.

    Rend `None` sous deux observations : une covariance a un point n'existe
    pas, et rendre zero la ferait passer pour mesuree.
    """
    if gauche.size < 2:
        return None
    valeur = float(np.cov(gauche, droite, ddof=1)[0, 1])
    return None if not np.isfinite(valeur) else valeur


def correlation(gauche: FloatArray, droite: FloatArray) -> float | None:
    """Correlation de Pearson des deux fenetres.

    **Variance nulle d'un cote : `None`, pas zero.** C'est la regle explicite
    du prompt d'origine et elle est juste. Une serie plate n'est pas
    decorrelee de l'autre : sa correlation n'est pas definie. Rendre zero
    ferait entrer dans les statistiques des observations qui n'en sont pas,
    et un filtre `correlation(...) < 0` les compterait comme des faits.

    Le cas se produit reellement : volume constant sur une fenetre creuse,
    prix fige au limit-up, ou tout simplement une fenetre de deux barres
    identiques.
    """
    if gauche.size < 2:
        return None
    ecart_gauche = float(np.std(gauche, ddof=1))
    ecart_droite = float(np.std(droite, ddof=1))
    if ecart_gauche <= 0.0 or ecart_droite <= 0.0:
        return None
    valeur = float(np.corrcoef(gauche, droite)[0, 1])
    return None if not np.isfinite(valeur) else valeur
