"""Attribution INTRADAY : ce que la strategie fait selon l'heure de la seance.

Pourquoi ce module existe
--------------------------
Pour une strategie intraday, « ca marche a 10 h et pas a 14 h » est le premier
diagnostic qu'on veut poser, et il etait inaccessible : le rapport agrege tout
l'echantillon, et rien ne distinguait l'ouverture de la cloture.

Ce n'est pas un raffinement. Une strategie qui gagne sur l'ouverture et perd
tout le reste de la journee rend un chiffre global mediocre, indistinguable
d'une strategie mediocre partout - alors que les deux appellent des decisions
opposees.

Ce que ce module N'EST PAS
---------------------------
Ce n'est pas un outil d'optimisation. Decouper l'echantillon par heure puis
retenir les heures qui gagnent est du sur-ajustement, et un sur-ajustement
particulierement seduisant parce que chaque tranche a l'air d'un resultat
propre. Les tranches ne sont pas des essais independants : elles partagent les
memes seances, les memes regimes et la meme strategie.

La PBO et le Deflated Sharpe du depot existent pour qualifier ce genre de
selection. Choisir une plage horaire sur ce tableau sans l'enregistrer comme
essai gonfle mecaniquement tous les autres chiffres du registre.

L'usage legitime est DIAGNOSTIQUE : constater qu'une strategie ne negocie
jamais apres 14 h, ou que ses pertes se concentrent sur la derniere demi-heure,
dit quelque chose sur sa MECANIQUE - pas sur les seuils qu'il faudrait choisir.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from rsl.data.schema import BarStore
from rsl.engine.portfolio import ClosedTrade
from rsl.errors import ConfigurationError

SpecDict = dict[str, object]

MINUTES_PAR_TRANCHE: Final[int] = 60
"""Largeur d'une tranche. L'heure est l'unite a laquelle un humain raisonne."""


@dataclass(frozen=True, slots=True)
class TrancheHoraire:
    """Ce qu'une plage de la seance a produit.

    `debut_minute` compte depuis l'OUVERTURE DECLAREE, jamais depuis minuit :
    une strategie sur ES et une sur FDAX doivent pouvoir se lire dans le meme
    tableau, et leurs ouvertures ne tombent pas a la meme heure UTC.
    """

    debut_minute: int
    n_trades: int
    pnl_net: float
    n_gagnants: int

    @property
    def hit_rate(self) -> float | None:
        return None if self.n_trades == 0 else self.n_gagnants / self.n_trades

    def describe(self) -> SpecDict:
        return {
            "debut_minute": self.debut_minute,
            "n_trades": self.n_trades,
            "pnl_net": self.pnl_net,
            "n_gagnants": self.n_gagnants,
            "hit_rate": self.hit_rate,
        }


@dataclass(frozen=True, slots=True)
class AttributionHoraire:
    """Les tranches, plus ce qu'il faut savoir pour les lire honnetement."""

    tranches: tuple[TrancheHoraire, ...]
    n_trades_classes: int
    n_trades_hors_seance: int
    """Trades ouverts sur une barre qu'aucune seance declaree ne couvre.

    Compte separement plutot que range dans une tranche : les ranger
    silencieusement ferait croire a une couverture complete.
    """

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_net for t in self.tranches)

    def describe(self) -> SpecDict:
        return {
            "minutes_par_tranche": MINUTES_PAR_TRANCHE,
            "n_trades_classes": self.n_trades_classes,
            "n_trades_hors_seance": self.n_trades_hors_seance,
            "tranches": [t.describe() for t in self.tranches],
        }

    def render(self) -> list[str]:
        """Une ligne par tranche NON VIDE, plus une ligne de garde.

        Les tranches vides sont tues : une strategie qui ne decide qu'a
        l'ouverture n'a pas besoin de vingt lignes a zero. Mais leur ABSENCE
        est elle-meme l'information - d'ou le total, qui permet de constater
        qu'une plage entiere manque.
        """
        if not self.tranches:
            return []
        lignes = ["Par heure    depuis l'ouverture declaree   trades   P&L net   hit"]
        for t in self.tranches:
            if t.n_trades == 0:
                continue
            heure = t.debut_minute // 60
            hit = "n/d" if t.hit_rate is None else f"{t.hit_rate * 100:5.1f} %"
            lignes.append(
                f"             +{heure:>2} h a +{heure + 1:>2} h"
                f"{t.n_trades:>22,}{t.pnl_net:>10,.0f}   {hit}"
            )
        if self.n_trades_hors_seance:
            lignes.append(
                f"             {self.n_trades_hors_seance} trade(s) ouverts hors de "
                f"toute seance declaree, non classes"
            )
        return lignes


def attribution_horaire(
    trades: Sequence[ClosedTrade], stores: dict[str, BarStore]
) -> AttributionHoraire | None:
    """Repartit les trades FERMES par heure de seance a leur OUVERTURE.

    A l'ouverture et non a la cloture : c'est a l'entree que la decision est
    prise, et c'est elle qu'on cherche a qualifier. Un trade ouvert a 9 h 45 et
    ferme a 15 h 30 dit quelque chose sur 9 h 45.

    Rend `None` quand aucun instrument ne declare de calendrier : sans seance,
    « l'heure de la seance » n'a pas de sens, et le socle ne devine pas de
    frontiere.
    """
    avec_seance = {s: st for s, st in stores.items() if st.sessions is not None}
    if not avec_seance:
        return None

    seaux: dict[int, list[float]] = {}
    hors = 0
    classes = 0
    for trade in trades:
        store = avec_seance.get(trade.symbol)
        if store is None:
            hors += 1
            continue
        index = store.sessions
        assert index is not None
        barre = int(trade.opened_bar)
        if not 0 <= barre < index.minutes_from_open.size:
            hors += 1
            continue
        minute = float(index.minutes_from_open[barre])
        if minute < 0.0:
            hors += 1
            continue
        debut = int(minute // MINUTES_PAR_TRANCHE) * MINUTES_PAR_TRANCHE
        seaux.setdefault(debut, []).append(float(trade.gross_pnl) - float(trade.fees))
        classes += 1

    tranches = tuple(
        TrancheHoraire(
            debut_minute=debut,
            n_trades=len(pnls),
            pnl_net=float(np.sum(pnls)),
            n_gagnants=int(sum(1 for p in pnls if p > 0.0)),
        )
        for debut, pnls in sorted(seaux.items())
    )
    return AttributionHoraire(
        tranches=tranches, n_trades_classes=classes, n_trades_hors_seance=hors
    )


def verifier_coherence(attribution: AttributionHoraire, total_attendu: int) -> None:
    """Refuse une attribution qui ne compte pas tous les trades.

    Un tableau par heure dont les lignes ne somment pas au total serait pire
    qu'absent : il aurait l'air complet.
    """
    compte = attribution.n_trades_classes + attribution.n_trades_hors_seance
    if compte != total_attendu:
        raise ConfigurationError(
            f"attribution horaire : {compte} trade(s) repartis pour "
            f"{total_attendu} fermes. Un tableau incomplet se lirait comme complet."
        )
