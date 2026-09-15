"""Les sept noyaux de `noeuds/statistiques.py`, un par un.

Toutes les valeurs attendues sont calculees A LA MAIN et ecrites en dur. Une
attente produite par le code testerait qu'il est stable, pas qu'il est juste :
c'est exactement ainsi que `stride: 390` a survecu trois semaines.

La convention d'ordre est rappelee dans chaque classe parce qu'elle est la
source d'erreur principale : `fenetre[0]` est le PRESENT.
"""

from __future__ import annotations

import numpy as np
import pytest

from rsl.strategies.noeuds.statistiques import (
    correlation,
    covariance,
    decroissance_lineaire,
    produit,
    puissance_signee,
    rang_du_maximum,
    rang_du_minimum,
)


def f(*valeurs: float) -> np.ndarray:
    """Une fenetre, ecrite DU PRESENT VERS LE PASSE."""
    return np.asarray(valeurs, dtype=np.float64)


class TestProduit:
    def test_il_multiplie(self):
        # 2 x 3 x 4 = 24
        assert produit(f(2.0, 3.0, 4.0)) == pytest.approx(24.0)

    def test_un_zero_annule(self):
        assert produit(f(2.0, 0.0, 4.0)) == pytest.approx(0.0)

    def test_les_signes_se_composent(self):
        # (-2) x 3 x (-4) = 24
        assert produit(f(-2.0, 3.0, -4.0)) == pytest.approx(24.0)

    def test_une_fenetre_d_un_point_rend_ce_point(self):
        assert produit(f(7.0)) == pytest.approx(7.0)

    def test_un_debordement_rend_none_et_non_inf(self):
        """Un `inf` rendrait une comparaison vraie en silence."""
        assert produit(f(1e300, 1e300)) is None


class TestRangDuMaximum:
    """`ts_argmax` : compte EN JOURS DEPUIS LE PLUS ANCIEN, base 1."""

    def test_le_maximum_au_present_rend_la_taille(self):
        # Le max est fenetre[0], donc le plus RECENT : 3 - 0 = 3.
        assert rang_du_maximum(f(9.0, 1.0, 2.0)) == 3.0

    def test_le_maximum_au_plus_ancien_rend_un(self):
        # Le max est fenetre[2], le plus VIEUX : 3 - 2 = 1.
        assert rang_du_maximum(f(1.0, 2.0, 9.0)) == 1.0

    def test_le_maximum_au_milieu(self):
        assert rang_du_maximum(f(1.0, 9.0, 2.0)) == 2.0

    def test_il_ne_rend_jamais_zero(self):
        """La base est 1 : zero signalerait un decalage d'un cran."""
        for taille in range(1, 8):
            for position in range(taille):
                fenetre = np.zeros(taille)
                fenetre[position] = 1.0
                assert rang_du_maximum(fenetre) >= 1.0

    def test_un_ex_aequo_choisit_le_plus_recent(self):
        # Deux 9 : celui de fenetre[0] gagne -> 3.
        assert rang_du_maximum(f(9.0, 9.0, 2.0)) == 3.0

    def test_une_fenetre_d_un_point_rend_un(self):
        assert rang_du_maximum(f(5.0)) == 1.0


class TestRangDuMinimum:
    def test_le_minimum_au_present_rend_la_taille(self):
        assert rang_du_minimum(f(0.0, 4.0, 7.0)) == 3.0

    def test_le_minimum_au_plus_ancien_rend_un(self):
        assert rang_du_minimum(f(7.0, 4.0, 0.0)) == 1.0

    def test_un_ex_aequo_choisit_le_plus_recent(self):
        assert rang_du_minimum(f(1.0, 1.0, 5.0)) == 3.0


class TestDecroissanceLineaire:
    """Poids `d, d-1, ..., 1` du present vers le passe, normalises."""

    def test_trois_points_a_la_main(self):
        # (3x3 + 2x2 + 1x1) / (3+2+1) = (9+4+1)/6 = 14/6
        assert decroissance_lineaire(f(3.0, 2.0, 1.0)) == pytest.approx(14.0 / 6.0)

    def test_le_present_pese_le_plus(self):
        """Meme serie, ordre inverse : le resultat doit CHANGER."""
        recent_fort = decroissance_lineaire(f(10.0, 0.0, 0.0))
        ancien_fort = decroissance_lineaire(f(0.0, 0.0, 10.0))
        # 10x3/6 = 5 contre 10x1/6 = 1,666...
        assert recent_fort == pytest.approx(5.0)
        assert ancien_fort == pytest.approx(10.0 / 6.0)
        assert recent_fort > ancien_fort

    def test_une_serie_constante_rend_la_constante(self):
        """Les poids sommant a un, une constante passe inchangee."""
        assert decroissance_lineaire(f(4.0, 4.0, 4.0, 4.0)) == pytest.approx(4.0)

    def test_une_fenetre_d_un_point_rend_ce_point(self):
        assert decroissance_lineaire(f(6.0)) == pytest.approx(6.0)

    def test_les_poids_sont_normalises_a_toute_taille(self):
        for taille in range(1, 12):
            assert decroissance_lineaire(np.ones(taille)) == pytest.approx(1.0)


class TestPuissanceSignee:
    def test_le_carre_garde_le_signe(self):
        """C'est toute la difference avec `x ** 2`."""
        assert puissance_signee(-3.0, 2.0) == pytest.approx(-9.0)
        assert puissance_signee(3.0, 2.0) == pytest.approx(9.0)

    def test_une_racine_cubique_negative_existe(self):
        # (-8) ** (1/3) n'est pas un reel ; signedpower(-8, 1/3) vaut -2.
        assert puissance_signee(-8.0, 1.0 / 3.0) == pytest.approx(-2.0)

    def test_zero_reste_zero(self):
        assert puissance_signee(0.0, 2.0) == pytest.approx(0.0)

    def test_l_exposant_un_est_l_identite(self):
        assert puissance_signee(-4.5, 1.0) == pytest.approx(-4.5)

    def test_un_resultat_non_fini_rend_none(self):
        """`signedpower(0, -1)` est une division par zero deguisee."""
        assert puissance_signee(0.0, -1.0) is None


class TestCovariance:
    def test_deux_series_a_la_main(self):
        # x = [1,2,3] moyenne 2 ; y = [2,4,6] moyenne 4
        # somme des produits d'ecarts = (-1)(-2) + 0 + (1)(2) = 4
        # ddof=1 -> 4 / 2 = 2
        assert covariance(f(1.0, 2.0, 3.0), f(2.0, 4.0, 6.0)) == pytest.approx(2.0)

    def test_une_serie_plate_donne_zero(self):
        """Une covariance nulle EST definie, contrairement a la correlation."""
        assert covariance(f(1.0, 2.0, 3.0), f(5.0, 5.0, 5.0)) == pytest.approx(0.0)

    def test_un_seul_point_rend_none(self):
        assert covariance(f(1.0), f(2.0)) is None


class TestCorrelation:
    def test_une_relation_lineaire_parfaite_rend_un(self):
        assert correlation(f(1.0, 2.0, 3.0), f(2.0, 4.0, 6.0)) == pytest.approx(1.0)

    def test_une_relation_inverse_rend_moins_un(self):
        assert correlation(f(1.0, 2.0, 3.0), f(6.0, 4.0, 2.0)) == pytest.approx(-1.0)

    def test_une_valeur_intermediaire_a_la_main(self):
        # x = [1,2,3], y = [1,3,2]
        # cov = ((-1)(-1) + 0x1 + 1x0) / 2 = 0,5
        # sx = sy = 1 -> r = 0,5
        assert correlation(f(1.0, 2.0, 3.0), f(1.0, 3.0, 2.0)) == pytest.approx(0.5)

    def test_une_variance_nulle_a_gauche_rend_none(self):
        """**Pas zero.** Une serie plate n'est pas decorrelee : elle n'a pas
        de correlation. Zero se lirait comme une mesure."""
        assert correlation(f(5.0, 5.0, 5.0), f(1.0, 2.0, 3.0)) is None

    def test_une_variance_nulle_a_droite_rend_none(self):
        assert correlation(f(1.0, 2.0, 3.0), f(5.0, 5.0, 5.0)) is None

    def test_deux_series_plates_rendent_none(self):
        assert correlation(f(5.0, 5.0), f(7.0, 7.0)) is None

    def test_un_seul_point_rend_none(self):
        assert correlation(f(1.0), f(2.0)) is None

    def test_elle_est_bornee(self):
        rng = np.random.default_rng(7)
        for _ in range(200):
            a, b = rng.normal(size=12), rng.normal(size=12)
            r = correlation(a, b)
            assert r is not None and -1.0 - 1e-12 <= r <= 1.0 + 1e-12


class TestLOrdreEstBienCeluiQuOnCroit:
    """Un noyau qui ne voit que sa fenetre ne peut pas voir au-dela.

    Ces fonctions ne prennent aucun contexte : le look-ahead n'y est pas
    empeche, il est INEXPRIMABLE. Ce que ces tests verifient, c'est la seule
    chose qui reste faillible - que les deux extremites ne soient pas
    interverties, faute qui ne produit aucune erreur et decale tout d'un cran.
    """

    def test_le_maximum_ne_confond_pas_les_extremites(self):
        au_present = f(100.0, 0.0, 0.0, 0.0)
        au_passe = au_present[::-1].copy()
        assert rang_du_maximum(au_present) == 4.0
        assert rang_du_maximum(au_passe) == 1.0

    def test_le_minimum_ne_confond_pas_les_extremites(self):
        au_present = f(-100.0, 0.0, 0.0, 0.0)
        au_passe = au_present[::-1].copy()
        assert rang_du_minimum(au_present) == 4.0
        assert rang_du_minimum(au_passe) == 1.0

    def test_la_decroissance_ne_confond_pas_les_extremites(self):
        au_present = f(10.0, 0.0, 0.0)
        au_passe = au_present[::-1].copy()
        assert decroissance_lineaire(au_present) == pytest.approx(5.0)
        assert decroissance_lineaire(au_passe) == pytest.approx(10.0 / 6.0)
