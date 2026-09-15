"""Ce qui s'est passe sans que le rapport le dise.

Pourquoi ce module existe
--------------------------
Le 2026-09-15, la replication de Zarattini a rendu un Sharpe de 0,99 contre
1,472 annonce. Cinq ecarts ont ete trouves en trois heures de mesure. Deux
d'entre eux etaient deja imprimes - `dropped_sizing`, `reduce_only_dropped` -
et ont ete diagnostiques en quelques minutes. Les trois autres etaient
SILENCIEUX, et ont coute le reste de la matinee :

- **17 sorties sur 1 846 fills remplies apres un gap de nuit (0,9 %).** La
  cloture forcee decide a la derniere barre de seance ; avec `lag_bars: 1` et
  `session_only: true`, la barre suivante est la premiere du LENDEMAIN. Gap
  subi : 31,00 points de moyenne, 14,00 de mediane, 179,00 au maximum - contre
  0,280 de moyenne sur une barre ordinaire.

  **Ce compteur a immediatement corrige son auteur.** J'avais annonce 2 658
  franchissements, en mesurant le gap sur les 2 658 dernieres barres de seance
  et en SUPPOSANT qu'une position y etait ouverte. Elle ne l'est que 17 fois :
  la quasi-totalite des trades sort avant la fin de seance, sur la bande
  opposee ou le VWAP, et la cloture forcee n'est qu'un filet. Un proxy
  plausible avait remplace la mesure ([[lessons]] L35).
- **90 seances sur 2 748 sans aucune cloture forcee.** Les demi-journees
  (13:00, 13:15) n'ont pas de barre a l'heure de fermeture DECLAREE, donc
  aucune barre n'y porte `is_last`. Le comportement est documente et voulu ;
  c'est la STRATEGIE qui avait tort d'y adosser une regle de securite.
- **26,4 % d'exposition supprimee par la troncature** en contrats entiers.

C'est la quatrieme occurrence de la meme famille - [[lessons]] L18, L25, L28,
L30 : un defaut qui produit un nombre parfaitement lisible. Le remede a chaque
fois a ete le meme, et il est ici generalise : **faire imprimer le chiffre**.

Ou vivent ces mesures, et pourquoi pas ailleurs
------------------------------------------------
Hors de `result_fingerprint`, qui ne hache que `counters` et `portfolio`. Ce
sont des DIAGNOSTICS : ils decrivent un run sans le definir, et les y inclure
aurait change les sept empreintes archivees sans qu'aucun comportement ne
change. Meme place, et meme raison, que `attribution_horaire`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from rsl.data.schema import BarStore
from rsl.orders import Fill

SpecDict = dict[str, object]


@dataclass(frozen=True, slots=True)
class FranchissementsDeNuit:
    """Fills tombes dans une seance autre que celle qui les a decides."""

    n_fills: int
    n_franchissements: int
    gap_moyen: float
    gap_median: float
    gap_max: float

    @property
    def part(self) -> float:
        return 0.0 if self.n_fills == 0 else self.n_franchissements / self.n_fills

    def describe(self) -> SpecDict:
        return {
            "n_fills": self.n_fills,
            "n_franchissements": self.n_franchissements,
            "part": self.part,
            "gap_moyen": self.gap_moyen,
            "gap_median": self.gap_median,
            "gap_max": self.gap_max,
        }


@dataclass(frozen=True, slots=True)
class SeancesSansCloture:
    """Seances dont aucune barre ne porte `is_last`.

    Une regle « sortir a la cloture » ecrite `session.is_last == 1` n'y
    declenche JAMAIS. Sur une strategie qui declare ne rien garder la nuit,
    c'est le contraire de ce qui est annonce - et rien ne le signalait.
    """

    n_seances: int
    n_sans_cloture: int

    @property
    def part(self) -> float:
        return 0.0 if self.n_seances == 0 else self.n_sans_cloture / self.n_seances

    def describe(self) -> SpecDict:
        return {
            "n_seances": self.n_seances,
            "n_sans_cloture": self.n_sans_cloture,
            "part": self.part,
        }


@dataclass(frozen=True, slots=True)
class Silences:
    """Les diagnostics qu'aucun compteur du moteur ne portait."""

    nuit: FranchissementsDeNuit | None
    cloture: SeancesSansCloture | None

    def describe(self) -> SpecDict:
        decrit: SpecDict = {}
        if self.nuit is not None:
            decrit["franchissements_de_nuit"] = self.nuit.describe()
        if self.cloture is not None:
            decrit["seances_sans_cloture"] = self.cloture.describe()
        return decrit

    @property
    def est_vide(self) -> bool:
        return self.nuit is None and self.cloture is None

    def render(self) -> list[str]:
        """Lignes du rapport texte. Vide quand il n'y a rien a signaler.

        Le seuil est ZERO : un seul franchissement de nuit sur une strategie
        qui se declare intraday est deja une contradiction, et une seance sans
        cloture forcee suffit a laisser une position ouverte.
        """
        lignes: list[str] = []
        nuit = self.nuit
        if nuit is not None and nuit.n_franchissements > 0:
            lignes.append(
                f"Nuit         {nuit.n_franchissements} fill(s) sur {nuit.n_fills} "
                f"({nuit.part * 100:.1f} %) executes dans une AUTRE seance que "
                f"leur decision"
            )
            lignes.append(
                f"             gap subi   moyen {nuit.gap_moyen:,.2f}   "
                f"median {nuit.gap_median:,.2f}   max {nuit.gap_max:,.2f} (points)"
            )
        cloture = self.cloture
        if cloture is not None and cloture.n_sans_cloture > 0:
            lignes.append(
                f"Cloture      {cloture.n_sans_cloture} seance(s) sur "
                f"{cloture.n_seances} ({cloture.part * 100:.1f} %) n'ont AUCUNE "
                f"barre `is_last`"
            )
            lignes.append(
                "             une regle « sortir a la cloture » n'y declenche "
                "jamais : la seance s'arrete avant l'heure declaree"
            )
        return lignes


def seances_sans_cloture(stores: Mapping[str, BarStore]) -> SeancesSansCloture | None:
    """Compte les seances ou `is_last` ne se declenche jamais.

    La regle du socle est causale : elle marque la premiere barre dont
    l'horodatage atteint la fermeture DECLAREE. Une seance qui s'arrete avant
    - demi-journee, trou de donnees - n'a donc aucune barre marquee. C'est
    voulu, documente, et invisible jusqu'ici.

    Sur plusieurs instruments les totaux sont AGREGES : chacun porte son
    propre calendrier, et un compte par symbole rendrait la ligne illisible
    sans rien apprendre - ce qui compte est qu'il y ait des trous, et combien.
    """
    total = 0
    marquees = 0
    vu = False
    for store in stores.values():
        index = store.sessions
        if index is None:
            continue
        vu = True
        marquees += int(np.count_nonzero(np.asarray(index.is_last)))
        total += int(index.n_sessions)
    if not vu:
        return None
    return SeancesSansCloture(n_seances=total, n_sans_cloture=max(total - marquees, 0))


def franchissements_de_nuit(
    stores: Mapping[str, BarStore], fills: Sequence[Fill], execution_lag: int
) -> FranchissementsDeNuit | None:
    """Fills executes dans une autre seance que la barre qui a decide.

    La barre de DECISION est `bar_index - execution_lag` : le moteur applique
    un differe fixe, donc l'antecedent d'un fill se retrouve par soustraction
    sans avoir a tracer les ordres.

    Le gap mesure est `|open(fill) - close(decision)|`, en points. Il n'est pas
    signe : une exposition nocturne subie est favorable une fois sur deux, et
    ce qu'elle coute a coup sur est de la VOLATILITE, donc du Sharpe.
    """
    avec_seance = {
        symbole: store
        for symbole, store in stores.items()
        if store.sessions is not None
    }
    if not avec_seance or not fills:
        return None

    gaps: list[float] = []
    for fill in fills:
        store = avec_seance.get(fill.symbol)
        if store is None:
            continue
        index = store.sessions
        if index is None:  # pragma: no cover - filtre ci-dessus
            continue
        numeros = np.asarray(index.session_number)
        arrivee = int(fill.bar_index)
        decision = arrivee - execution_lag
        if decision < 0 or arrivee >= numeros.size:
            continue
        if numeros[arrivee] == numeros[decision]:
            continue
        gaps.append(
            abs(float(store.open[arrivee]) - float(store.close[decision]))
        )

    if not gaps:
        return FranchissementsDeNuit(len(fills), 0, 0.0, 0.0, 0.0)
    ecarts = np.asarray(gaps, dtype=np.float64)
    return FranchissementsDeNuit(
        n_fills=len(fills),
        n_franchissements=int(ecarts.size),
        gap_moyen=float(ecarts.mean()),
        gap_median=float(np.median(ecarts)),
        gap_max=float(ecarts.max()),
    )


def mesurer_les_silences(
    stores: Mapping[str, BarStore], fills: Sequence[Fill], execution_lag: int
) -> Silences:
    """Toutes les mesures d'un coup. Rend des champs `None` quand la question
    ne se pose pas - sans seance declaree, il n'y a ni nuit ni cloture."""
    return Silences(
        nuit=franchissements_de_nuit(stores, fills, execution_lag),
        cloture=seances_sans_cloture(stores),
    )
