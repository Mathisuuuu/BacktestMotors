"""Probabilite de surapprentissage : PBO par CSCV.

Ce que le DSR ne repond pas
----------------------------
Le Deflated Sharpe demande « ce Sharpe est-il au-dessus de ce qu'on attendrait
du meilleur de N tirages sous H0 ». C'est une question sur UN chiffre.

La CSCV pose une autre question, et c'est celle qu'on a vraiment : **si je
choisis la meilleure configuration sur une moitie de l'echantillon, quelle est
la probabilite qu'elle soit sous la mediane sur l'autre moitie ?** Un
processus de selection peut produire un Sharpe honorable et n'avoir aucun
pouvoir predictif ; le DSR ne le verrait pas, la CSCV oui.

D'ou le nom : PBO mesure le SURAPPRENTISSAGE DU PROCESSUS, pas la qualite d'une
strategie. Une PBO de 0,5 veut dire que choisir le meilleur en echantillon
revient a tirer a pile ou face hors echantillon.

L'algorithme (Bailey, Borwein, Lopez de Prado, Zhu, 2014)
----------------------------------------------------------
1. Decouper l'echantillon en `S` sous-periodes disjointes, `S` pair.
2. Enumerer les `C(S, S/2)` facons de choisir la moitie des sous-periodes.
   Chaque choix donne un ensemble d'APPRENTISSAGE `J` et son complement de
   TEST `J`.
3. Pour chaque combinaison : retenir la configuration la meilleure sur `J`,
   puis regarder son RANG parmi toutes les configurations sur le complement.
4. Le rang relatif `w` devient un logit `ln(w / (1 - w))`. Negatif = la
   gagnante en echantillon est passee sous la mediane hors echantillon.
5. PBO = part des combinaisons a logit negatif ou nul.

« Symetrique » est le mot qui compte : chaque combinaison sert d'apprentissage
dans un sens et de test dans l'autre. Aucune moitie n'est privilegiee, donc
aucun choix d'auteur ne se glisse dans le resultat.

Ce que cette implementation approxime, et il faut le savoir
------------------------------------------------------------
L'article travaille sur une matrice de RENDEMENTS, et la performance d'une
configuration sur `J` y est le Sharpe de la serie concatenee. Le protocole fige
dans ce depot le 2026-09-10 (`OverfittingEstimator`) prend une matrice de
PERFORMANCES deja agregees, une par (configuration, sous-periode) : combiner
plusieurs sous-periodes revient donc a en faire la MOYENNE.

Ce n'est pas la meme chose, et l'ecart a ete mesure ailleurs dans ce depot le
2026-09-12 : sur un walk-forward de neuf plis, la moyenne des Sharpe par pli
donne 0,32 la ou la serie groupee donne 0,62. Une moyenne donne le meme poids a
une sous-periode qui a negocie une fois et a une qui a negocie tout du long.

Pourquoi c'est acceptable ICI, et seulement ici : la CSCV n'utilise ces nombres
que pour CLASSER les configurations entre elles, sous-periode par sous-periode.
Un biais qui frappe toutes les configurations de la meme facon ne change pas
leur ordre. Ce qui resterait faux, c'est de lire les valeurs de la matrice
comme des Sharpe publiables - elles ne le sont pas.

Ce qu'une PBO ne dit pas
-------------------------
- Rien sur une strategie prise seule. La PBO qualifie une GRILLE et le fait
  d'en avoir choisi le maximum. Avec une seule configuration il n'y a pas de
  selection, donc pas de surapprentissage de selection - et le calcul est
  refuse plutot que rendu a zero.
- Rien sur l'independance des essais. Deux configurations quasi identiques
  comptent pour deux ; la grille doit etre construite honnetement.
- Rien sur le look-ahead, le roulement, ou la qualite des donnees. La CSCV
  prend la matrice qu'on lui donne.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import numpy.typing as npt

from rsl.errors import ConfigurationError

SpecDict = dict[str, object]
FloatArray = npt.NDArray[np.float64]

COMBINAISONS_MAX = 20_000
"""Au-dela, la CSCV est refusee plutot que lancee.

`C(S, S/2)` explose : 252 a S=10, 184 756 a S=20, 155 millions a S=30. Un
`S` choisi sans y penser transformerait une mesure en attente indeterminee. Le
refus nomme la valeur et propose de baisser `S`."""

SEUIL_INQUIETANT = 0.5
"""Au-dessus, choisir le meilleur en echantillon ne vaut pas mieux qu'un tirage
a pile ou face. La convention de l'article."""


@dataclass(frozen=True, slots=True)
class ResultatPBO:
    """Sortie complete, avec ses entrees pour audit."""

    pbo: float
    """Part des combinaisons ou la gagnante en echantillon finit sous la
    mediane hors echantillon."""

    n_configurations: int
    n_sous_periodes: int
    n_combinaisons: int
    logits: tuple[float, ...]
    """Un logit par combinaison, dans l'ordre d'enumeration. Leur DISTRIBUTION
    dit plus que leur moyenne : une PBO de 0,5 obtenue avec des logits proches
    de zero n'est pas la meme chose qu'une obtenue avec des logits extremes."""

    rang_median: float
    """Rang relatif median de la gagnante hors echantillon, dans [0, 1]. A 0,5
    la selection n'apporte rien ; a 1 elle est parfaite."""

    n_gagnantes_distinctes: int
    """Nombre de configurations differentes elues au moins une fois.

    Une seule gagnante sur toutes les combinaisons veut dire que la grille est
    dominee par une configuration - la PBO mesure alors sa robustesse, pas le
    surapprentissage d'un choix."""

    warnings: tuple[str, ...] = ()

    @property
    def est_surapprise(self) -> bool:
        return self.pbo > SEUIL_INQUIETANT

    @property
    def logit_median(self) -> float:
        return float(np.median(np.asarray(self.logits, dtype=np.float64)))

    def describe(self) -> SpecDict:
        return {
            "pbo": self.pbo,
            "est_surapprise": self.est_surapprise,
            "n_configurations": self.n_configurations,
            "n_sous_periodes": self.n_sous_periodes,
            "n_combinaisons": self.n_combinaisons,
            "rang_median": self.rang_median,
            "logit_median": self.logit_median,
            "n_gagnantes_distinctes": self.n_gagnantes_distinctes,
            "warnings": list(self.warnings),
        }

    def render(self) -> str:
        verdict = "SURAPPRENTISSAGE" if self.est_surapprise else "acceptable"
        lignes = [
            f"PBO                           {self.pbo:.4f}  {verdict}",
            f"Rang median hors echantillon  {self.rang_median:.4f} "
            f"(0,5 = la selection n'apporte rien)",
            f"Logit median                  {self.logit_median:+.4f}",
            f"Grille                        {self.n_configurations} configurations, "
            f"{self.n_sous_periodes} sous-periodes, {self.n_combinaisons} combinaisons",
            f"Gagnantes distinctes          {self.n_gagnantes_distinctes}",
        ]
        lignes.extend(f"Avertissement  {a}" for a in self.warnings)
        return "\n".join(lignes)


def _valide(matrice: FloatArray, n_sous_periodes: int) -> list[str]:
    """Refuse ce qui ne peut pas donner un chiffre honnete.

    Chaque refus porte sur une facon precise de rendre la PBO trompeuse plutot
    que fausse - un resultat plausible qu'on lirait sans se mefier.
    """
    if matrice.ndim != 2:
        raise ConfigurationError(
            f"matrice de performances attendue en deux dimensions "
            f"(configurations x sous-periodes), recu {matrice.ndim}"
        )
    n_config, n_colonnes = matrice.shape
    if n_config < 2:
        raise ConfigurationError(
            f"{n_config} configuration(s) : la PBO mesure le surapprentissage d'une "
            f"SELECTION. Sans choix a faire, il n'y a rien a mesurer - et rendre "
            f"zero laisserait croire a une absence de surapprentissage."
        )
    if n_colonnes != n_sous_periodes:
        raise ConfigurationError(
            f"matrice a {n_colonnes} colonne(s) mais {n_sous_periodes} sous-periodes "
            f"annoncees"
        )
    if n_sous_periodes < 2 or n_sous_periodes % 2 != 0:
        raise ConfigurationError(
            f"S doit etre PAIR et >= 2, recu {n_sous_periodes}. La CSCV coupe "
            f"l'echantillon en deux moities de meme taille ; un S impair en "
            f"privilegierait une."
        )
    if not bool(np.all(np.isfinite(matrice))):
        raise ConfigurationError(
            "la matrice contient des valeurs non finies. Une configuration sans "
            "performance mesurable sur une sous-periode doit etre RETIREE de la "
            "grille, pas dotee d'un zero - un zero la classerait au milieu."
        )

    n_combinaisons = math.comb(n_sous_periodes, n_sous_periodes // 2)
    if n_combinaisons > COMBINAISONS_MAX:
        raise ConfigurationError(
            f"S={n_sous_periodes} donne {n_combinaisons} combinaisons, au-dela de "
            f"{COMBINAISONS_MAX}. Baisser S : le nombre de combinaisons croit "
            f"comme C(S, S/2)."
        )

    avertissements: list[str] = []
    if n_config < 10:
        avertissements.append(
            f"{n_config} configurations seulement : le rang hors echantillon ne "
            f"prend que {n_config} valeurs, donc la PBO est grossiere. "
            f"L'article travaille sur des centaines de configurations."
        )
    if n_sous_periodes < 8:
        avertissements.append(
            f"S={n_sous_periodes} donne {n_combinaisons} combinaison(s) : trop peu "
            f"pour que la part de logits negatifs soit stable."
        )
    return avertissements


def probability_of_backtest_overfitting(
    performance_matrix: FloatArray, n_partitions: int
) -> ResultatPBO:
    """PBO par CSCV. `performance_matrix` est `configurations x sous-periodes`.

    Implemente le protocole fige le 2026-09-10 dans
    `metrics.statistics.OverfittingEstimator`, et rend un resultat complet
    plutot qu'un flottant nu : une PBO sans le nombre de configurations ni la
    distribution des logits ne se relit pas.

    Deterministe de bout en bout. Les combinaisons sont enumerees par
    `itertools.combinations`, dont l'ordre est fixe ; les egalites sont
    tranchees par l'indice le plus petit, dans les deux sens. Sans cette
    seconde regle, deux configurations de meme performance donneraient une PBO
    dependante de l'ordre des lignes.
    """
    matrice = np.asarray(performance_matrix, dtype=np.float64)
    avertissements = _valide(matrice, n_partitions)

    n_config = matrice.shape[0]
    moitie = n_partitions // 2
    toutes = range(n_partitions)

    logits: list[float] = []
    gagnantes: set[int] = set()
    rangs: list[float] = []

    for apprentissage in combinations(toutes, moitie):
        test = [c for c in toutes if c not in set(apprentissage)]

        # La moyenne des sous-periodes retenues : voir l'en-tete du module sur
        # ce que cette agregation approxime.
        perf_apprentissage = matrice[:, list(apprentissage)].mean(axis=1)
        perf_test = matrice[:, test].mean(axis=1)

        # `argmax` rend deja le plus petit indice en cas d'egalite ; c'est
        # ecrit ici parce que la propriete est REQUISE, pas incidente.
        gagnante = int(np.argmax(perf_apprentissage))
        gagnantes.add(gagnante)

        # Rang hors echantillon : combien de configurations font STRICTEMENT
        # moins bien. Les ex aequo ne creditent pas la gagnante - c'est le
        # sens conservateur, celui qui ne minimise pas la PBO.
        rang = int(np.sum(perf_test < perf_test[gagnante]))
        relatif = (rang + 1) / (n_config + 1)
        rangs.append(relatif)
        logits.append(math.log(relatif / (1.0 - relatif)))

    tableau = np.asarray(logits, dtype=np.float64)
    pbo = float(np.mean(tableau <= 0.0))

    if len(gagnantes) == 1:
        avertissements.append(
            "une seule configuration est elue sur toutes les combinaisons : la "
            "grille est dominee par elle, et la PBO mesure sa robustesse plutot "
            "que le surapprentissage d'un choix."
        )

    return ResultatPBO(
        pbo=pbo,
        n_configurations=n_config,
        n_sous_periodes=n_partitions,
        n_combinaisons=len(logits),
        logits=tuple(logits),
        rang_median=float(np.median(np.asarray(rangs, dtype=np.float64))),
        n_gagnantes_distinctes=len(gagnantes),
        warnings=tuple(avertissements),
    )
