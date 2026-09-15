"""Les recettes de composition : elles se construisent, ou la suite casse.

Ce que ces tests empechent
---------------------------
Une recette est une forme JUSTE, montree a un auteur - humain ou machine - qui
ne peut pas la deviner en lisant une liste de types de noeuds. Il n'existe
aucun noeud `vwap` ; le VWAP ancre est un quotient de deux `cumulative`, et
personne ne trouve cette forme seul.

Le risque est evident : une recette ecrite une fois, jamais executee, qui
cesse d'etre exprimable quand le vocabulaire bouge. C'est exactement ce qui
est arrive au recensement de couverture, dont **deux verdicts sur quatre**
etaient devenus faux sans que rien ne le signale ([[lessons]] L36).

D'ou ce fichier : chaque recette est CONSTRUITE par `build_signal`. Une forme
qui cesserait d'etre valide fait echouer la suite, et le message nomme
laquelle.
"""

from __future__ import annotations

import json

import pytest

from rsl.compositions import COMPOSITIONS, describe_compositions
from rsl.skeleton import build_skeleton
from rsl.strategies.signals import build_signal

IDS = [c.nom for c in COMPOSITIONS]


class TestChaqueRecetteEstExecutable:
    @pytest.mark.parametrize("composition", COMPOSITIONS, ids=IDS)
    def test_elle_se_construit(self, composition):
        """Le seul test qui compte vraiment : la forme est-elle encore
        exprimable ?"""
        assert build_signal(composition.arbre) is not None

    @pytest.mark.parametrize("composition", COMPOSITIONS, ids=IDS)
    def test_elle_declare_un_warmup_fini(self, composition):
        """Un warmup infini signalerait une forme qui ne pourrait jamais
        servir."""
        signal = build_signal(composition.arbre)
        assert 0 <= signal.warmup_bars < 100_000

    @pytest.mark.parametrize("composition", COMPOSITIONS, ids=IDS)
    def test_elle_se_reconstruit_depuis_sa_propre_description(self, composition):
        """Aller-retour : ce que le noeud DECRIT doit se rebatir a l'identique.

        Sans cela, la recette publiee au squelette pourrait differer de celle
        qui a ete testee - et c'est la publiee que l'auteur recopie.
        """
        construit = build_signal(composition.arbre)
        rebati = build_signal(construit.describe())
        assert rebati.describe() == construit.describe()


class TestLaFormeDesRecettes:
    @pytest.mark.parametrize("composition", COMPOSITIONS, ids=IDS)
    def test_elle_dit_ce_qu_elle_calcule_et_quand(self, composition):
        assert composition.resume.strip()
        assert composition.quand.strip()

    def test_les_noms_sont_uniques(self):
        noms = [c.nom for c in COMPOSITIONS]
        assert len(noms) == len(set(noms))

    @pytest.mark.parametrize("composition", COMPOSITIONS, ids=IDS)
    def test_un_avertissement_est_soit_absent_soit_substantiel(self, composition):
        """Une `attention` vide serait pire qu'absente : elle ferait croire
        qu'on a regarde."""
        if composition.attention is not None:
            assert len(composition.attention.strip()) > 40


class TestLesRecettesQuiPortentUnPiege:
    """Les formes ou le nom d'un terme promet autre chose que sa definition
    doivent le DIRE. Une recette juste qui tait son piege est un piege."""

    @pytest.mark.parametrize(
        ("nom", "attendu"),
        [
            ("cloture_forcee", "ATTEINDRE"),
            ("grille_semi_horaire", "JAMAIS zero"),
            ("plus_haut_de_la_veille", "REFUSE"),
            ("pertes_nettes_de_la_seance", "OBLIGATOIRE"),
            ("etendue_d_ouverture", "mask"),
            ("dispersion_au_meme_rang", "SEANCES"),
        ],
    )
    def test_le_piege_est_dit(self, nom: str, attendu: str):
        recette = next(c for c in COMPOSITIONS if c.nom == nom)
        assert recette.attention is not None, f"{nom} tait son piege"
        assert attendu in recette.attention


class TestLaPublicationAuSquelette:
    """Une recette connue du seul code source ne sert a personne."""

    def test_le_squelette_les_porte_toutes(self):
        squelette = build_skeleton()
        assert set(squelette["compositions"]) == {c.nom for c in COMPOSITIONS}

    def test_la_forme_publiee_est_celle_qui_est_testee(self):
        """Le lien qui rend ces tests utiles : c'est la forme PUBLIEE que
        l'auteur recopie, pas celle du code."""
        publie = describe_compositions()
        for composition in COMPOSITIONS:
            assert publie[composition.nom]["forme"] == composition.arbre
            assert build_signal(publie[composition.nom]["forme"]) is not None

    def test_le_squelette_porte_les_pieges_des_noeuds(self):
        """L'autre moitie de ce qu'un auteur ne peut pas deviner."""
        squelette = build_skeleton()
        session = squelette["noeuds"]["session"]
        assert "pieges" in session, "les pieges de `session` ne sont pas publies"
        champs = {p["champ"] for p in session["pieges"]}
        assert champs == {"is_last", "minutes_from_open"}

    def test_un_noeud_sans_piege_n_en_publie_pas(self):
        """« Audite, rien a signaler » ne doit pas ressembler a un piege vide."""
        squelette = build_skeleton()
        assert "pieges" not in squelette["noeuds"]["constant"]

    def test_le_squelette_reste_serialisable(self):
        """Il est destine a etre lu par une machine : tout doit passer en JSON."""
        assert json.loads(json.dumps(build_skeleton())) is not None


class TestCeQueLesRecettesNeSontPas:
    def test_aucune_n_est_une_strategie_complete(self):
        """Ce sont des GRANDEURS, pas des decisions. Une recette qui porterait
        des `rules` inviterait a la recopier telle quelle comme un resultat."""
        for composition in COMPOSITIONS:
            assert "rules" not in json.dumps(composition.arbre)
