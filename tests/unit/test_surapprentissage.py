"""PBO par CSCV : le surapprentissage du PROCESSUS, pas d'une strategie.

Ce que ce fichier garde
-----------------------
1. **Les deux extremes sont CONSTRUITS, pas echantillonnes.** Une matrice ou la
   gagnante en echantillon est systematiquement derniere hors echantillon doit
   donner exactement 1,0 ; une matrice dominee par une configuration doit
   donner exactement 0,0. Verifier la PBO sur du bruit seul laisserait la
   tolerance statistique masquer une erreur de signe ou d'indice.
2. **Le determinisme.** Meme matrice, meme resultat ; et les egalites sont
   tranchees par l'indice le plus petit, dans les deux sens. Sans cette seconde
   regle, permuter deux lignes de meme performance changerait le chiffre.
3. **Les refus.** Chacun porte sur une facon precise de rendre la PBO plausible
   et fausse, pas seulement invalide.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rsl.errors import ConfigurationError
from rsl.metrics.surapprentissage import (
    COMBINAISONS_MAX,
    SEUIL_INQUIETANT,
    probability_of_backtest_overfitting,
)


def pbo(matrice, s: int):
    return probability_of_backtest_overfitting(np.asarray(matrice, float), s)


class TestLesDeuxExtremesSontConstruits:
    """Deux matrices dont la PBO se calcule de tete."""

    def test_une_inversion_parfaite_donne_un(self):
        """A gagne la periode 0 et perd la 1 ; B l'inverse. Avec S=2, les deux
        combinaisons elisent le champion d'une periode et le testent sur celle
        ou il est dernier. La selection n'a donc AUCUN pouvoir predictif, et
        c'est exactement ce que 1,0 veut dire."""
        resultat = pbo([[1.0, -1.0], [-1.0, 1.0]], 2)
        assert resultat.pbo == 1.0
        assert resultat.est_surapprise

    def test_une_domination_franche_donne_zero(self):
        """A est meilleure partout : la choisir en echantillon la retrouve
        premiere hors echantillon, toujours."""
        resultat = pbo([[2.0, 2.0], [0.0, 0.0]], 2)
        assert resultat.pbo == 0.0
        assert not resultat.est_surapprise

    def test_le_rang_median_accompagne_la_pbo(self):
        parfaite = pbo([[2.0, 2.0], [0.0, 0.0]], 2)
        inversee = pbo([[1.0, -1.0], [-1.0, 1.0]], 2)
        assert parfaite.rang_median > 0.5
        assert inversee.rang_median < 0.5

    def test_le_logit_median_change_de_signe(self):
        """Le logit est negatif quand la gagnante passe sous la mediane. C'est
        le signe qui definit la PBO ; l'inverser la retournerait sans qu'aucun
        test sur du bruit ne s'en apercoive."""
        assert pbo([[1.0, -1.0], [-1.0, 1.0]], 2).logit_median < 0
        assert pbo([[2.0, 2.0], [0.0, 0.0]], 2).logit_median > 0


class TestSurDuBruitLaSelectionNApporteRien:
    """La verification statistique, en complement des deux cas construits."""

    def test_la_pbo_du_bruit_pur_avoisine_un_demi(self):
        """Aucune configuration n'a de pouvoir predictif : choisir la meilleure
        en echantillon revient a tirer a pile ou face. On attend donc une PBO
        proche de 0,5 - legerement au-dessus, la gagnante en echantillon etant
        celle qui a eu de la chance."""
        rng = np.random.default_rng(7)
        resultat = pbo(rng.normal(size=(50, 10)), 10)
        assert 0.4 <= resultat.pbo <= 0.8

    def test_une_vraie_gagnante_ressort_du_bruit(self):
        rng = np.random.default_rng(7)
        matrice = rng.normal(size=(50, 10)) * 0.3
        matrice[7] += 2.0
        resultat = pbo(matrice, 10)
        assert resultat.pbo == 0.0
        assert resultat.n_gagnantes_distinctes == 1


class TestDeterminisme:
    def test_deux_appels_donnent_le_meme_resultat(self):
        rng = np.random.default_rng(3)
        matrice = rng.normal(size=(12, 6))
        assert pbo(matrice, 6).describe() == pbo(matrice, 6).describe()

    def test_les_egalites_sont_tranchees_par_le_plus_petit_indice(self):
        """Deux configurations identiques : la PBO ne doit pas dependre de
        laquelle `argmax` designe, donc la regle doit etre fixe."""
        matrice = [[1.0, 1.0], [1.0, 1.0], [0.0, 0.0]]
        resultat = pbo(matrice, 2)
        assert resultat.n_gagnantes_distinctes == 1

    def test_un_ex_aequo_ne_credite_pas_la_gagnante(self):
        """Le rang compte les configurations STRICTEMENT moins bonnes. Compter
        les ex aequo gonflerait le rang de la gagnante, donc minimiserait la
        PBO - le sens ou l'on se trompe en se flattant."""
        resultat = pbo([[1.0, 1.0], [1.0, 1.0]], 2)
        assert resultat.rang_median == pytest.approx(1 / 3)

    def test_le_nombre_de_combinaisons_est_c_de_s_sur_deux(self):
        rng = np.random.default_rng(5)
        for s, attendu in ((2, 2), (4, 6), (6, 20), (8, 70)):
            resultat = pbo(rng.normal(size=(6, s)), s)
            assert resultat.n_combinaisons == attendu
            assert resultat.n_combinaisons == math.comb(s, s // 2)


class TestLesRefus:
    """Chacun porte sur une facon de rendre la PBO plausible et fausse."""

    def test_une_seule_configuration_est_refusee(self):
        """Sans choix a faire, il n'y a pas de surapprentissage de SELECTION -
        et rendre zero laisserait croire a son absence."""
        with pytest.raises(ConfigurationError, match="SELECTION"):
            pbo([[1.0, 2.0]], 2)

    def test_un_s_impair_est_refuse(self):
        with pytest.raises(ConfigurationError, match="PAIR"):
            pbo([[1.0, 2.0, 3.0], [3.0, 2.0, 1.0]], 3)

    def test_le_message_dit_pourquoi_s_doit_etre_pair(self):
        with pytest.raises(ConfigurationError, match="privilegierait"):
            pbo([[1.0, 2.0, 3.0], [3.0, 2.0, 1.0]], 3)

    def test_une_valeur_non_finie_est_refusee(self):
        """Un NaN remplace par zero classerait la configuration au milieu du
        peloton, ce qui est une opinion."""
        with pytest.raises(ConfigurationError, match="RETIREE"):
            pbo([[1.0, float("nan")], [2.0, 3.0]], 2)

    def test_un_nombre_de_colonnes_incoherent_est_refuse(self):
        with pytest.raises(ConfigurationError, match="colonne"):
            pbo([[1.0, 2.0], [3.0, 4.0]], 4)

    def test_une_matrice_a_une_dimension_est_refusee(self):
        with pytest.raises(ConfigurationError, match="deux dimensions"):
            probability_of_backtest_overfitting(np.zeros(4), 2)

    def test_un_s_qui_ferait_exploser_les_combinaisons_est_refuse(self):
        """C(30,15) fait 155 millions : sans garde, la commande ne rendrait
        jamais la main et rien ne dirait pourquoi."""
        matrice = np.zeros((3, 30))
        matrice[0] = 1.0
        with pytest.raises(ConfigurationError, match=str(COMBINAISONS_MAX)):
            probability_of_backtest_overfitting(matrice, 30)


class TestLesAvertissementsDisentCeQuiEstFragile:
    def test_une_grille_etroite_est_signalee(self):
        """Le rang hors echantillon ne prend que N valeurs : avec trois
        configurations la PBO ne peut valoir que quelques nombres."""
        resultat = pbo([[1.0, 2.0], [2.0, 1.0], [1.5, 1.5]], 2)
        assert any("configurations seulement" in a for a in resultat.warnings)

    def test_un_s_petit_est_signale(self):
        resultat = pbo(np.eye(12)[:, :4] + 0.1, 4)
        assert any("combinaison" in a for a in resultat.warnings)

    def test_une_gagnante_unique_est_signalee(self):
        """La PBO mesure alors la robustesse d'une configuration dominante, pas
        le surapprentissage d'un choix."""
        rng = np.random.default_rng(11)
        matrice = rng.normal(size=(20, 8)) * 0.2
        matrice[3] += 5.0
        resultat = pbo(matrice, 8)
        assert resultat.n_gagnantes_distinctes == 1
        assert any("dominee" in a for a in resultat.warnings)

    def test_une_grille_large_ne_declenche_pas_l_avertissement_d_etroitesse(self):
        rng = np.random.default_rng(2)
        resultat = pbo(rng.normal(size=(40, 8)), 8)
        assert not any("configurations seulement" in a for a in resultat.warnings)


class TestLaSortie:
    def test_describe_est_serialisable(self):
        import json

        rng = np.random.default_rng(1)
        decrit = pbo(rng.normal(size=(10, 6)), 6).describe()
        assert json.loads(json.dumps(decrit)) == decrit

    def test_render_dit_le_verdict(self):
        assert "SURAPPRENTISSAGE" in pbo([[1.0, -1.0], [-1.0, 1.0]], 2).render()
        assert "acceptable" in pbo([[2.0, 2.0], [0.0, 0.0]], 2).render()

    def test_le_seuil_est_celui_de_l_article(self):
        assert SEUIL_INQUIETANT == 0.5

    def test_il_y_a_un_logit_par_combinaison(self):
        """Leur distribution dit plus que leur moyenne : une PBO de 0,5 avec
        des logits proches de zero n'est pas la meme chose qu'une obtenue avec
        des logits extremes."""
        rng = np.random.default_rng(4)
        resultat = pbo(rng.normal(size=(8, 6)), 6)
        assert len(resultat.logits) == resultat.n_combinaisons == 20
