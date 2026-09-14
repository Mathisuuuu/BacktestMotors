"""`is_last` ne marque QU'UNE barre par seance.

Ce qui est en jeu
------------------
« Sortir a la cloture » est la regle qui fait qu'une strategie est INTRADAY. Elle
s'ecrit `session.is_last == 1`.

Jusqu'au 2026-09-14, `is_last` valait `ts_ns >= heure_de_fermeture` - donc vrai
pour TOUTES les barres suivant la fermeture, et non pour la derniere. Une seance
declaree court jusqu'a l'ouverture suivante : les barres d'apres-cloture lui
appartiennent encore, et elles etaient toutes marquees.

Mesure sur ES en 30 minutes, seance declaree 08:30-15:00 America/Chicago :
**90 515 barres sur 125 806, soit 71,9 %** - trente par seance de trente-huit.
La regle « sortir a la cloture » etait donc vraie les trois quarts du temps.

Ce que cela produisait
-----------------------
Une sortie qui se declenche a chaque barre, suivie d'une re-entree quand la
condition d'entree tient encore : la strategie tournait en boucle, payant frais
et slippage a chaque tour. Sur un momentum ES 30 minutes, 37 115 trades sur
41 110 ne duraient qu'UNE barre.

Le document de reference dit « aucune barre n'est marquee derniere ce jour-la »,
au SINGULIER, et `is_first` ne marque bien qu'une barre. Le code contredisait la
norme ; c'est donc le code qui avait tort ([[CLAUDE.md]]).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from rsl.data.session import SessionCalendar, build_session_index

NS = 1_000_000_000


def index(heures: list[int], *, ouverture: str = "09:00", fermeture: str = "15:00",
          jours: int = 3):
    """Une barre horaire a chacune des `heures` (UTC), sur `jours` jours."""
    ts: list[int] = []
    base = dt.datetime(2024, 1, 2, 0, 0, tzinfo=dt.UTC)
    for j in range(jours):
        d = base + dt.timedelta(days=j)
        ts.extend(int((d + dt.timedelta(hours=h)).timestamp()) * NS for h in heures)
    tableau = np.asarray(sorted(ts), dtype=np.int64)
    un = np.ones(tableau.size)
    return build_session_index(
        tableau, un, un, un, un, un,
        SessionCalendar(start=ouverture, end=fermeture, timezone="UTC"),
    )


class TestUneSeuleBarreParSeance:
    def test_la_barre_de_cloture_et_elle_seule(self):
        """Seance 09:00-15:00, barres horaires de 09:00 a 23:00.

        Les barres de 16:00 a 23:00 suivent la fermeture et appartiennent encore
        a la seance. Une seule doit porter `is_last` : celle de 15:00.
        """
        idx = index(list(range(9, 24)), jours=2)
        for numero in (0, 1):
            dans_la_seance = idx.session_number == numero
            assert int(idx.is_last[dans_la_seance].sum()) == 1, (
                f"seance {numero} : {int(idx.is_last[dans_la_seance].sum())} barres"
            )

    def test_is_first_et_is_last_marquent_le_meme_nombre_de_barres(self):
        """L'invariant le plus simple, et celui qui manquait.

        Une seance complete a exactement une premiere barre et une derniere.
        Leur dissymetrie etait le signe du defaut.
        """
        idx = index(list(range(9, 24)), jours=3)
        assert int(idx.is_first.sum()) == int(idx.is_last.sum()) == 3

    def test_le_rang_de_la_derniere_est_bien_celui_de_la_cloture(self):
        idx = index(list(range(9, 24)), jours=1)
        rangs = idx.bar_in_session[idx.is_last]
        # Barres 09:00..23:00 ; la cloture declaree est 15:00, soit le rang 6.
        assert rangs.tolist() == [6]

    def test_une_seance_sans_barre_apres_la_cloture_n_en_marque_aucune(self):
        """Comportement DOCUMENTE, et conserve : la regle est causale, elle ne
        devine pas qu'une barre etait la derniere en voyant la suivante."""
        idx = index([9, 10, 11], jours=2)  # rien apres 11:00, cloture a 15:00
        assert int(idx.is_last.sum()) == 0
        assert int(idx.is_first.sum()) == 2

    def test_la_barre_exactement_a_la_cloture_compte(self):
        idx = index([9, 15], jours=1)
        assert idx.is_last.tolist() == [False, True]


class TestCeQueLeDefautProduisait:
    def test_l_ancienne_regle_aurait_marque_les_trois_quarts(self):
        """Fige l'ampleur du defaut : ce test ne verifie pas le correctif, il
        garde la trace de ce qu'on evite. `ts >= cloture` reste calculable."""
        idx = index(list(range(9, 24)), jours=2)
        # L'ancienne definition, recalculee a la main.
        ancienne = idx.minutes_from_open >= 6 * 60
        assert int(ancienne.sum()) == 18, "9 barres par seance apres la cloture"
        assert int(idx.is_last.sum()) == 2
        assert int(ancienne.sum()) / idx.is_last.size == pytest.approx(0.6)


class TestBornesDeSeance:
    def test_une_seance_a_cheval_sur_minuit(self):
        """Le cas qui a motive la declaration de seance : ES court de 17 h a
        16 h, et une frontiere a minuit la couperait en deux."""
        idx = index([18, 20, 22, 2, 4, 15, 16], ouverture="17:00",
                    fermeture="16:00", jours=3)
        for numero in set(idx.session_number.tolist()):
            dans = idx.session_number == numero
            assert int(idx.is_last[dans].sum()) <= 1
        assert int(idx.is_last.sum()) >= 1, "aucune seance close : fixture inutile"
