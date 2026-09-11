"""Noyaux de lissage partages, sans registre.

Ce module n'enregistre rien : il porte les formules que plusieurs familles
d'indicateurs reutilisent. Les garder ici evite qu'une EMA soit reecrite dix
fois avec dix conventions d'amorce - et c'est l'amorce, pas la formule, qui
fait diverger deux implementations d'un meme indicateur.

**Convention d'amorce, commune a tout le depot.** Une moyenne exponentielle
depend en theorie de toute l'histoire depuis l'origine. Une primitive ne voit
que les `n` dernieres barres : elle est donc calculee sur un historique
TRONQUE, amorce par la moyenne simple des `window` premieres valeurs de cet
historique. Avec `seed_multiplier=5`, le poids residuel de l'amorce est de
l'ordre de `(1 - 2/(w+1))^(4w)`, soit environ 3e-4. Negligeable devant le
bruit de marche, et surtout DETERMINISTE - c'est l'exigence du socle, pas la
precision.

Voir `ema@1` (`trend.py`) et la famille de Wilder (`wilder.py`), qui ont pose
cette convention.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


def ema_serie(values: FloatArray, window: int) -> FloatArray:
    """EMA a chaque point de `values`, amorcee par la SMA des `window` premiers.

    Rend un tableau de longueur `len(values) - window + 1` : le premier point
    est l'amorce. Les indicateurs qui empilent deux lissages (`macd`, `tsi`,
    `trix`) ont besoin de la SERIE, pas seulement du dernier point.
    """
    if values.size < window:
        raise ValueError(f"{values.size} valeurs pour une fenetre de {window}")
    alpha = 2.0 / (window + 1.0)
    sortie = np.empty(values.size - window + 1, dtype=np.float64)
    courant = float(np.mean(values[:window]))
    sortie[0] = courant
    for rang, valeur in enumerate(values[window:], start=1):
        courant = alpha * float(valeur) + (1.0 - alpha) * courant
        sortie[rang] = courant
    return sortie


def ema_de(values: FloatArray, window: int) -> float:
    """Dernier point de `ema_serie`."""
    return float(ema_serie(values, window)[-1])


def wilder_serie(values: FloatArray, window: int) -> FloatArray:
    """Lissage de Wilder (`alpha = 1/window`), meme convention d'amorce."""
    if values.size < window:
        raise ValueError(f"{values.size} valeurs pour une fenetre de {window}")
    alpha = 1.0 / window
    sortie = np.empty(values.size - window + 1, dtype=np.float64)
    courant = float(np.mean(values[:window]))
    sortie[0] = courant
    for rang, valeur in enumerate(values[window:], start=1):
        courant = alpha * float(valeur) + (1.0 - alpha) * courant
        sortie[rang] = courant
    return sortie


def wma_de(values: FloatArray, window: int) -> float:
    """Moyenne ponderee lineairement : poids 1, 2, ..., window, le plus recent
    recevant le plus grand."""
    fenetre = values[-window:]
    poids = np.arange(1.0, window + 1.0)
    return float(np.dot(fenetre, poids) / poids.sum())


def wma_serie(values: FloatArray, window: int) -> FloatArray:
    """WMA a chaque point ou elle est definie."""
    poids = np.arange(1.0, window + 1.0)
    normalisation = poids.sum()
    n = values.size - window + 1
    sortie = np.empty(n, dtype=np.float64)
    for rang in range(n):
        sortie[rang] = np.dot(values[rang : rang + window], poids) / normalisation
    return sortie


def sma_serie(values: FloatArray, window: int) -> FloatArray:
    """SMA a chaque point, par somme cumulee - le seul de ces noyaux qui se
    vectorise sans accumulateur."""
    cumul = np.concatenate(([0.0], np.cumsum(values, dtype=np.float64)))
    return (cumul[window:] - cumul[:-window]) / window


def pente_de(values: FloatArray) -> float:
    """Pente d'une regression lineaire de `values` sur son index, par barre."""
    n = values.size
    x = np.arange(n, dtype=np.float64)
    variance = float(np.var(x))
    if variance <= 0.0:
        return 0.0
    return float(np.cov(x, values, bias=True)[0, 1] / variance)


def true_range_serie(
    high: FloatArray, low: FloatArray, close: FloatArray
) -> FloatArray:
    """True Range de chaque barre SAUF la premiere - elle n'a pas de cloture
    precedente, et la remplacer par `high - low` melangerait deux definitions.
    """
    precedent = close[:-1]
    empile = np.stack([
        high[1:] - low[1:],
        np.abs(high[1:] - precedent),
        np.abs(low[1:] - precedent),
    ])
    return np.asarray(np.max(empile, axis=0), dtype=np.float64)


def securise(numerateur: float, denominateur: float) -> float | None:
    """Division qui rend `None` plutot que d'inventer une valeur.

    Un denominateur nul arrive vraiment : seance sans echange, barre sans
    amplitude, serie plate. Rendre 0 ou 50 serait une invention ; rendre `inf`
    ou `NaN` contredirait le contrat `float | None`.
    """
    if denominateur == 0.0 or not np.isfinite(denominateur):
        return None
    resultat = numerateur / denominateur
    return resultat if np.isfinite(resultat) else None
