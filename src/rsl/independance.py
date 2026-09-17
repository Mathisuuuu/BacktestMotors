"""Combien d'essais INDEPENDANTS le compteur du Deflated Sharpe compte-t-il ?

Le probleme, et ce qu'on croyait qu'il etait
---------------------------------------------
Il etait ecrit depuis le 2026-09-12 que le DSR se degradait quand on ajoutait
des essais correles, et que « ce qu'il faudrait est une notion de distance
entre essais ». La mesure du 2026-09-17 montre que le diagnostic designait le
mauvais terme.

Le seuil est::

    E[max SR] = sqrt(V) * f(N)

avec `V` la variance des Sharpe essayes et `f` croissante en `N`. Decompose sur
le registre, le passage de 17 essais a 498 donne :

| Terme | Effet |
|---|---|
| `f(N)` — le COMPTE | 1,8281 -> 3,0513, soit **+66,9 %** |
| `sqrt(V)` — la DISPERSION | 0,1011 -> 0,0219, soit **-78,3 %** |
| seuil | 0,1848 -> **0,0669** |

**Le compte se comporte correctement.** Ajouter des essais monte bien la barre.
C'est `V` qui s'effondre : les 481 essais de la grille SMA ont un ecart-type de
Sharpe de **0,0093**, contre 0,1011 pour les dix-sept autres - un facteur onze.
Ce ne sont pas 481 mesures, c'est une mesure repetee 481 fois, et
`variance_of_sharpes` l'estime comme si c'etaient 481 tirages.

Ce que ce module fait, et ce qu'il ne fait PAS
-----------------------------------------------
Il **mesure** la structure de la population d'essais. Il ne corrige rien.

Corriger demanderait de decider ce qu'est un essai effectif, et cette decision
appartient a Bailey & Lopez de Prado, dont la source est encore `a-ingerer`.
Substituer ici une formule de mon cru produirait un DSR different, plausible, et
faux d'une facon que personne ne pourrait detecter - exactement la famille
[[lessons]] L30. Le DSR publie reste donc CELUI D'AVANT ; ce module le rend
seulement lisible.

Deux mesures, de portee differente
-----------------------------------
1. **Les familles d'echantillon** (`familles`). Deux essais qui portent les
   memes instruments sur le meme nombre d'observations sont sur le MEME
   echantillon. C'est verifiable depuis le registre seul, sans rien archiver de
   neuf, et cela suffit deja a montrer que 462 essais sur 498 partagent un
   unique echantillon de 2 501 rendements quotidiens.

2. **La correlation des rendements** (`correlations`). Beaucoup plus fine -
   deux strategies tres differentes sur le meme echantillon restent deux
   essais - mais elle exige la serie quotidienne, que le registre n'archivait
   pas avant le 2026-09-17. Elle ne dit donc rien des essais anterieurs, et
   c'est irrattrapable sans les rejouer.

La correlation se calcule sur l'INTERSECTION des dates, jamais sur des series
recadrees a la meme longueur : deux essais decales d'un an auraient sinon une
correlation calculee entre des jours qui n'ont rien a voir.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from rsl.metrics.statistics import Decomposition

SpecDict = dict[str, object]

MINIMUM_COMMUN = 30
"""Points communs exiges pour qu'une correlation soit calculee.

En dessous, elle n'est pas approximative : elle est du bruit. Rendre `None`
plutot qu'un nombre est le meme refus que partout ailleurs dans le socle -
une valeur absente se voit, une valeur fausse ne se voit pas.
"""


@dataclass(frozen=True, slots=True)
class Famille:
    """Un groupe d'essais portant sur le meme echantillon.

    « Meme echantillon » veut dire ici : memes instruments, meme nombre de
    rendements. C'est un critere GROSSIER - il ne dit pas que les strategies se
    ressemblent, seulement qu'elles ont ete jugees sur les memes donnees - et
    c'est justement pour cela qu'il est fiable : il ne suppose rien.
    """

    symbols: tuple[str, ...]
    n_returns: int
    labels: tuple[str, ...]
    sharpes: tuple[float, ...]

    @property
    def taille(self) -> int:
        return len(self.sharpes)

    @property
    def ecart_type(self) -> float:
        """Dispersion des Sharpe DANS la famille.

        C'est le chiffre qui trahit une famille degeneree : 0,0093 pour la
        grille SMA contre 0,1011 hors d'elle.
        """
        if self.taille < 2:
            return 0.0
        return float(np.std(np.asarray(self.sharpes, dtype=np.float64), ddof=1))

    def describe(self) -> SpecDict:
        return {
            "symbols": list(self.symbols),
            "n_returns": self.n_returns,
            "taille": self.taille,
            "ecart_type": self.ecart_type,
            "exemple": self.labels[0] if self.labels else "",
        }

    def render(self) -> str:
        noms = ",".join(self.symbols) or "-"
        return (
            f"{self.taille:>4} essai(s)  {self.n_returns:>6} obs  "
            f"ecart-type {self.ecart_type:.4f}  {noms[:34]:<34} {self.labels[0][:28]}"
        )


def familles(essais: Sequence[object]) -> list[Famille]:
    """Regroupe les essais par echantillon, du plus gros groupe au plus petit.

    Prend n'importe quel objet portant `symbols`, `n_returns`, `label` et
    `sharpe_per_period` : ce module n'a pas a connaitre `rsl.essais`, et
    l'inverse non plus.
    """
    groupes: dict[tuple[tuple[str, ...], int], list[object]] = {}
    for essai in essais:
        cle = (
            tuple(str(s) for s in getattr(essai, "symbols", ())),
            int(getattr(essai, "n_returns", 0)),
        )
        groupes.setdefault(cle, []).append(essai)

    rendu = [
        Famille(
            symbols=symboles,
            n_returns=n,
            labels=tuple(str(getattr(e, "label", "")) for e in membres),
            sharpes=tuple(float(getattr(e, "sharpe_per_period", 0.0)) for e in membres),
        )
        for (symboles, n), membres in groupes.items()
    ]
    return sorted(rendu, key=lambda f: (-f.taille, f.n_returns))


def correlation(
    ts_a: np.ndarray, ret_a: np.ndarray, ts_b: np.ndarray, ret_b: np.ndarray
) -> float | None:
    """Correlation de deux series quotidiennes, sur leurs dates COMMUNES.

    Rend `None` plutot qu'un nombre quand l'intersection est trop courte, ou
    quand l'une des deux series y est constante - une strategie qui n'a pas
    negocie sur la periode commune a une variance nulle, et la correlation n'y
    est pas « zero », elle est indefinie.

    Les rendements sont indexes par la date de FIN de leur periode : le
    rendement `i` court de `ts[i]` a `ts[i+1]`, donc c'est `ts[1:]` qui les
    designe. Aligner sur `ts[:-1]` decalerait les deux series d'un jour, ce qui
    est exactement le genre d'erreur qui produit un chiffre lisible et faux.
    """
    dates_a = np.asarray(ts_a, dtype=np.int64)[1:]
    dates_b = np.asarray(ts_b, dtype=np.int64)[1:]
    communes, ia, ib = np.intersect1d(dates_a, dates_b, return_indices=True)
    if communes.shape[0] < MINIMUM_COMMUN:
        return None
    a = np.asarray(ret_a, dtype=np.float64)[ia]
    b = np.asarray(ret_b, dtype=np.float64)[ib]
    if float(np.std(a)) == 0.0 or float(np.std(b)) == 0.0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def correlations(
    series: Mapping[str, tuple[np.ndarray, np.ndarray]],
) -> dict[tuple[str, str], float]:
    """Toutes les correlations deux a deux, les paires indefinies omises.

    Les paires sont ordonnees pour qu'une cle apparaisse une seule fois. Une
    paire absente signifie « indefinie », jamais « nulle ».
    """
    cles = sorted(series)
    rendu: dict[tuple[str, str], float] = {}
    for i, a in enumerate(cles):
        for b in cles[i + 1 :]:
            valeur = correlation(*series[a], *series[b])
            if valeur is not None:
                rendu[(a, b)] = valeur
    return rendu


__all__ = [
    "MINIMUM_COMMUN",
    "Decomposition",
    "Famille",
    "correlation",
    "correlations",
    "familles",
]
