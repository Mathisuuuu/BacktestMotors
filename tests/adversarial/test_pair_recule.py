"""Une vue reculee doit voir ses PAIRS reculés, pas les pairs du present.

Le defaut corrige le 2026-09-11
--------------------------------
`BarContext.shifted(lag)` recopiait le resolveur de pairs sans le reculer. Une
expression evaluee « telle qu'elle etait il y a `lag` barres » voyait donc les
autres instruments a l'instant COURANT.

Conséquence mesurée, et elle n'est pas cosmetique : dans

    rolling(zscore, 120, close / peer(NQ, close))

les 120 clotures d'ES etaient divisees par la MEME cloture de NQ. Le z-score
etant invariant par changement d'echelle, le terme distant n'avait **aucun
effet** - ecart maximum 2,08e-14 avec un z-score d'ES seul. L'exemple
`examples/paire_es_nq.json`, presente comme une strategie de paires, negociait
ES tout court.

Ce que ces tests gardent
------------------------
1. Le pair RECULE avec la fenetre, et la valeur lue est verifiable a la main.
2. Il recule en passant par le PANNEAU : un instrument absent le reste. Lire
   directement le magasin du pair rendrait un « dernier prix connu », que
   `docs/no-lookahead.md` §4.1 refuse.
3. Rien de tout cela n'ouvre une fuite : corrompre le futur ne change aucune
   lecture reculée.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext, MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import ABSENT, AlignPolicy, BarStore, Granularity, Panel
from rsl.errors import InsufficientHistoryError, SymbolNotAvailableError
from rsl.strategies.signals import build_signal, peer, price, rolling

pytestmark = pytest.mark.adversarial

JOUR = Granularity.minutes(60 * 24)
N = 240


def magasin(depart: float, pas: float, symbole: str, n: int = N) -> BarStore:
    return synthetic.make_store(
        synthetic.ramp(n, depart, pas), symbol=symbole,
        granularity=JOUR, start=synthetic.EPOCH, wick=0.0,
    )


def panneau_rampes() -> Panel:
    """A monte de 1 par barre, B de 7 depuis 500.

    Des rampes et non des marches aleatoires : la valeur attendue se calcule a
    la main, donc un test qui passe prouve quelque chose.

    NON PROPORTIONNELLES, et c'est essentiel. Le premier montage prenait
    A = 100 + k et B = 1000 + 10k : leur ratio vaut 0,1 pour TOUT k, donc le
    test « le ratio n'est plus constant » echouait alors que le code etait
    juste. Deux rampes proportionnelles sont un cas degenere qui masque
    exactement ce qu'on veut voir.
    """
    return build_panel({"A": magasin(100.0, 1.0, "A"), "B": magasin(500.0, 7.0, "B")})


def vue(panneau: Panel, ligne: int, symbole: str = "A") -> BarContext:
    ctx = MultiContext(panneau)
    ctx._seek_row(ligne)
    return ctx[symbole]


class TestLePairRecule:
    def test_une_vue_reculee_lit_le_pair_recule(self):
        """B vaut 500 + 7k. A la ligne 200, reculee de 30, on doit lire
        B[170] = 1690 - et non B[200] = 1900."""
        courant = vue(panneau_rampes(), 200)
        distant = peer("B", price("close"))
        assert distant(courant) == pytest.approx(500.0 + 7 * 200)
        assert distant(courant.shifted(30)) == pytest.approx(500.0 + 7 * 170)

    def test_une_fenetre_glissante_voit_bouger_le_pair(self):
        """La moyenne de B sur 10 barres, lue depuis A. Avant la correction
        elle valait 10 fois B[courant], donc B[courant] tout court."""
        courant = vue(panneau_rampes(), 200)
        moyenne = rolling("mean", 10, peer("B", price("close")))
        attendu = float(np.mean([500.0 + 7 * k for k in range(191, 201)]))
        assert moyenne(courant) == pytest.approx(attendu)
        assert moyenne(courant) != pytest.approx(500.0 + 7 * 200)

    def test_le_ratio_de_deux_rampes_n_est_plus_constant_sur_la_fenetre(self):
        """Le cas exact de `examples/paire_es_nq.json`, en miniature."""
        courant = vue(panneau_rampes(), 200)
        ratio = build_signal({
            "type": "arith", "op": "/",
            "left": {"type": "price", "field": "close"},
            "right": {"type": "peer", "symbol": "B",
                      "inner": {"type": "price", "field": "close"}},
        })
        valeurs = [ratio(courant.shifted(k)) for k in range(5)]
        assert len(set(valeurs)) == 5, f"le ratio ne bouge pas : {valeurs}"
        for k, obtenue in enumerate(valeurs):
            attendu = (100.0 + (200 - k)) / (500.0 + 7 * (200 - k))
            assert obtenue == pytest.approx(attendu), k

    def test_le_zscore_d_un_ratio_cesse_d_egaler_le_zscore_du_numerateur(self):
        """La preuve directe que le terme distant compte enfin.

        L'invariance d'echelle du z-score est ce qui rendait le defaut
        invisible : tant que le denominateur etait constant sur la fenetre, il
        se simplifiait exactement.
        """
        panneau = build_panel({
            "A": synthetic.make_store(synthetic.random_walk(N, seed=1), symbol="A",
                                      granularity=JOUR, start=synthetic.EPOCH),
            "B": synthetic.make_store(synthetic.random_walk(N, seed=2), symbol="B",
                                      granularity=JOUR, start=synthetic.EPOCH),
        })
        courant = vue(panneau, 200)
        avec = rolling("zscore", 60, build_signal({
            "type": "arith", "op": "/",
            "left": {"type": "price", "field": "close"},
            "right": {"type": "peer", "symbol": "B",
                      "inner": {"type": "price", "field": "close"}},
        }))
        sans = rolling("zscore", 60, price("close"))
        assert abs(avec(courant) - sans(courant)) > 0.1

    def test_le_noeud_lag_recule_aussi_son_pair(self):
        """`lag` passe par `shifted` : il herite de la correction."""
        courant = vue(panneau_rampes(), 200)
        recule = build_signal({
            "type": "lag", "bars": 40,
            "inner": {"type": "peer", "symbol": "B",
                      "inner": {"type": "price", "field": "close"}},
        })
        assert recule(courant) == pytest.approx(500.0 + 7 * 160)

    def test_un_pair_imbrique_reste_au_meme_instant(self):
        """`peer(B, peer(A, close))` depuis une vue reculee doit rendre A au
        MEME instant recule, pas au present."""
        courant = vue(panneau_rampes(), 200)
        imbrique = peer("B", peer("A", price("close")))
        assert imbrique(courant.shifted(25)) == pytest.approx(100.0 + 175)


class TestLesReglesDuPanneauTiennentEnArRiere:
    """Reculer ne doit pas devenir une porte derobee vers le magasin brut."""

    def panneau_troue(self) -> Panel:
        """B ne cote qu'une barre sur deux : la moitie des lignes sont ABSENT."""
        a = magasin(100.0, 1.0, "A", n=120)
        closes_b = synthetic.ramp(60, 1000.0, 10.0)
        b = synthetic.make_store(
            closes_b, symbol="B",
            granularity=Granularity.minutes(2 * 60 * 24),
            start=synthetic.EPOCH, wick=0.0,
        )
        return build_panel({"A": a, "B": b}, allow_mixed_granularity=True)

    def test_un_instrument_absent_le_reste_vu_du_passe(self):
        """Sans forward-fill declare, absent ne veut pas dire « dernier prix
        connu » - y compris quand on remonte le temps."""
        panneau = self.panneau_troue()
        lignes_absentes = [
            k for k in range(60, 110) if int(panneau.row_index["B"][k]) == ABSENT
        ]
        assert lignes_absentes, "le montage doit produire des lignes absentes"

        courant = vue(panneau, 110)
        distant = peer("B", price("close"))
        cible = lignes_absentes[-1]
        recul = 110 - cible
        with pytest.raises(SymbolNotAvailableError):
            distant.inner(courant.shifted(recul).peer("B"))

    def test_le_signal_traduit_l_absence_en_indefini_et_non_en_erreur(self):
        """C'est la regle du noeud `peer`, inchangee : un instrument absent est
        un ETAT de marche, il donne `None`."""
        panneau = self.panneau_troue()
        courant = vue(panneau, 110)
        distant = peer("B", price("close"))
        lectures = [distant(courant.shifted(k)) for k in range(20)]
        assert any(v is None for v in lectures), "aucune absence rencontree"
        assert any(v is not None for v in lectures), "aucune valeur rencontree"

    def test_un_report_explicite_reste_borne_en_arriere(self):
        """Avec `ffill` declare, le report s'applique aussi aux vues reculees -
        et il reste borne par `max_ffill_bars`, comme a l'endroit."""
        panneau = build_panel(
            {"A": magasin(100.0, 1.0, "A", n=120),
             "B": synthetic.make_store(
                 synthetic.ramp(60, 1000.0, 10.0), symbol="B",
                 granularity=Granularity.minutes(2 * 60 * 24),
                 start=synthetic.EPOCH, wick=0.0)},
            align_policy=AlignPolicy.FFILL, max_ffill_bars=4,
            allow_mixed_granularity=True,
        )
        courant = vue(panneau, 110)
        distant = peer("B", price("close"))
        assert all(distant(courant.shifted(k)) is not None for k in range(20))

    def test_remonter_avant_le_debut_du_calendrier_leve(self):
        """Et leve `InsufficientHistoryError`, pas une erreur de programmation :
        c'est un manque d'historique, que `peer` traduit en `None`."""
        panneau = panneau_rampes()
        courant = vue(panneau, 3)
        with pytest.raises(InsufficientHistoryError):
            courant.shifted(10)


class TestAucuneFuiteIntroduite:
    """La correction fait reculer une lecture. Elle ne doit rien ouvrir."""

    def test_corrompre_le_futur_ne_change_aucune_lecture_reculee(self):
        propre = {"A": magasin(100.0, 1.0, "A"), "B": magasin(500.0, 7.0, "B")}
        sale = {
            "A": propre["A"],
            "B": synthetic.corrupt_future(propre["B"], after_index=150),
        }
        expression = rolling("mean", 30, peer("B", price("close")))

        a, b = build_panel(propre), build_panel(sale)
        for ligne in (100, 140, 150):
            assert expression(vue(a, ligne)) == pytest.approx(
                expression(vue(b, ligne))
            ), f"ligne {ligne} : la corruption du futur a change le passe"

    def test_apres_la_coupure_les_deux_divergent_bien(self):
        """Le pendant du precedent : sans lui, un test qui compare deux series
        identiques passerait pour une preuve."""
        propre = {"A": magasin(100.0, 1.0, "A"), "B": magasin(500.0, 7.0, "B")}
        sale = {
            "A": propre["A"],
            "B": synthetic.corrupt_future(propre["B"], after_index=150),
        }
        expression = rolling("mean", 30, peer("B", price("close")))
        a, b = build_panel(propre), build_panel(sale)
        assert expression(vue(a, 200)) != pytest.approx(expression(vue(b, 200)))

    def test_une_vue_reculee_ne_voit_jamais_un_pair_posterieur(self):
        """La propriete sous sa forme la plus directe : l'horodatage du pair
        lu ne depasse jamais celui de la vue."""
        panneau = panneau_rampes()
        courant = vue(panneau, 200)
        for recul in range(0, 60, 7):
            reculee = courant.shifted(recul)
            assert reculee.peer("B").ts <= reculee.ts, recul


class TestLaMemoisationResteRefusee:
    """Le pair devient une fonction de (serie, barre, PANNEAU). Pas de (serie, barre).

    Avant la correction, memoiser un sous-arbre contenant `peer` etait faux
    parce que la valeur dependait de la barre depuis laquelle on regardait.
    Apres, elle n'en depend plus - mais elle depend du panneau, que la cle de
    memoisation n'identifie pas. La conclusion ne change donc pas, et sa raison
    devient plus nette.
    """

    def test_un_sous_arbre_avec_pair_n_est_toujours_pas_memoisable(self):
        from rsl.strategies.memoire import memoisable

        assert not memoisable(peer("B", price("close")))

    def test_le_rolling_correspondant_n_a_pas_de_memoire(self):
        from rsl.strategies.memoire import MEMO_DESACTIVEE

        if MEMO_DESACTIVEE:
            pytest.skip("memoisation desactivee")
        assert rolling("mean", 10, peer("B", price("close")))._memoire is None
