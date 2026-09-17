"""Combien d'essais INDEPENDANTS le compteur du Deflated Sharpe compte-t-il ?

Le defaut que ce fichier rend visible
--------------------------------------
Le seuil de deflation est un PRODUIT :

    E[max SR] = sqrt(V) * f(N)

Il etait ecrit depuis le 2026-09-12 qu'ajouter des essais correles degradait le
DSR, et que « ce qu'il faudrait est une notion de distance entre essais ». La
decomposition du 2026-09-17 montre que le diagnostic designait le mauvais
terme :

| Terme | 17 essais -> 498 |
|---|---|
| `f(N)` — le COMPTE | 1,8281 -> 3,0513, **+66,9 %** |
| `sqrt(V)` — la DISPERSION | 0,1011 -> 0,0219, **-78,3 %** |
| seuil | 0,1848 -> **0,0669** |

**Le compte se comporte correctement.** C'est `V` qui s'effondre : 462 essais
sur 498 portent le meme echantillon, avec un ecart-type de Sharpe de 0,0093
contre 0,0723 pour les 36 autres.

Ce que ces tests garantissent, et ce qu'ils ne garantissent pas
----------------------------------------------------------------
Ils garantissent que la STRUCTURE est mesuree et affichee. Ils ne garantissent
aucune correction du DSR : decider ce qu'est un essai effectif demande la
source, encore `a-ingerer`. Une formule inventee ici rendrait un DSR different,
plausible et faux - la famille [[lessons]] L30.

Le chiffre qui justifie d'archiver la serie quotidienne
--------------------------------------------------------
Mesure du 2026-09-17, sur quatre essais reels :

| Paire | Correlation |
|---|---|
| SMA(20,100) vs SMA(22,100) | **+0,9920** |
| SMA(20,100) vs SMA(2,20) | +0,4907 |
| SMA(20,100) vs RSI hors lundi | +0,1617 |
| SMA(2,20) vs RSI hors lundi | +0,0578 |

Deux voisins de la grille ne sont pas deux essais. Et la vue par FAMILLE, qui
les met tous dans un seul groupe, sur-regroupe : elle ne distingue pas 0,99 de
0,49. C'est pourquoi la serie est archivee - la famille est ce qu'on sait dire
sans elle, pas ce qu'on voudrait dire.
"""

from __future__ import annotations

import math
import pathlib
import tempfile
from dataclasses import dataclass

import numpy as np
import pytest

from rsl.errors import ConfigurationError
from rsl.essais import Essai, Registre
from rsl.independance import MINIMUM_COMMUN, correlation, correlations, familles
from rsl.metrics.performance import DailySeries
from rsl.metrics.statistics import Decomposition, expected_max_sharpe

JOUR = 86_400_000_000_000


@dataclass(frozen=True)
class FauxEssai:
    """Le minimum que `familles` lit. Ce module ne connait pas `rsl.essais`."""

    symbols: tuple[str, ...]
    n_returns: int
    label: str
    sharpe_per_period: float


def serie(n: int, *, debut: int = 0, graine: int = 0) -> tuple[np.ndarray, np.ndarray]:
    generateur = np.random.default_rng(graine)
    ts = np.arange(n + 1, dtype=np.int64) * JOUR + debut * JOUR
    return ts, generateur.normal(0.0, 0.01, size=n)


class TestLaDecomposition:
    def test_le_seuil_est_celui_de_la_source(self):
        """Pas une seconde ecriture de la formule : la MEME."""
        d = Decomposition(n_trials=50, variance=0.01)
        assert d.seuil == expected_max_sharpe(50, 0.01)

    def test_le_produit_des_deux_facteurs_redonne_le_seuil(self):
        d = Decomposition(n_trials=120, variance=0.004)
        assert d.dispersion * d.count_factor == pytest.approx(d.seuil, rel=1e-12)

    def test_la_dispersion_est_la_racine_de_la_variance(self):
        d = Decomposition(n_trials=10, variance=0.0025)
        assert d.dispersion == pytest.approx(0.05)

    def test_le_facteur_de_compte_croit_avec_le_nombre_d_essais(self):
        petits = Decomposition(n_trials=10, variance=1.0).count_factor
        grands = Decomposition(n_trials=500, variance=1.0).count_factor
        assert grands > petits > 0.0

    def test_le_facteur_ne_depend_pas_de_la_variance(self):
        """C'est ce qui rend la decomposition informative : les deux termes
        bougent pour des raisons independantes."""
        a = Decomposition(n_trials=77, variance=0.001).count_factor
        b = Decomposition(n_trials=77, variance=9.0).count_factor
        assert a == b

    def test_un_seul_essai_ne_selectionne_rien(self):
        d = Decomposition(n_trials=1, variance=0.5)
        assert d.count_factor == 0.0
        assert d.seuil == 0.0

    def test_une_variance_nulle_donne_un_seuil_nul(self):
        assert Decomposition(n_trials=400, variance=0.0).seuil == 0.0

    def test_le_rendu_montre_les_deux_facteurs(self):
        rendu = Decomposition(n_trials=498, variance=0.00048).render()
        assert "dispersion" in rendu and "compte" in rendu


class TestLeDefautQueLaDecompositionExplique:
    """La reproduction en miniature du 0,1600 -> 0,0663."""

    def test_ajouter_des_essais_quasi_identiques_fait_baisser_le_seuil(self):
        varies = np.array([0.02, 0.05, -0.01, 0.08, 0.03, -0.04])
        avant = Decomposition(len(varies), float(np.var(varies, ddof=1)))

        jumeaux = np.concatenate([varies, np.full(400, 0.0301)])
        apres = Decomposition(len(jumeaux), float(np.var(jumeaux, ddof=1)))

        assert apres.count_factor > avant.count_factor, "le COMPTE monte, lui"
        assert apres.dispersion < avant.dispersion
        assert apres.seuil < avant.seuil, (
            "c'est le defaut : 400 essais de plus ABAISSENT la barre"
        )

    def test_ajouter_des_essais_varies_fait_monter_le_seuil(self):
        """Le controle. Sans lui, on pourrait croire que N est en cause."""
        generateur = np.random.default_rng(3)
        varies = generateur.normal(0.0, 0.05, size=6)
        avant = Decomposition(len(varies), float(np.var(varies, ddof=1)))
        plus = np.concatenate([varies, generateur.normal(0.0, 0.05, size=400)])
        apres = Decomposition(len(plus), float(np.var(plus, ddof=1)))
        assert apres.seuil > avant.seuil


class TestLesFamilles:
    def test_les_essais_du_meme_echantillon_se_regroupent(self):
        essais = [
            FauxEssai(("ES.v.0",), 2501, f"sma-{i}", 0.03 + i * 1e-4) for i in range(5)
        ] + [FauxEssai(("NQ.v.0",), 800, "autre", 0.09)]
        groupes = familles(essais)
        assert [g.taille for g in groupes] == [5, 1]

    def test_un_echantillon_de_taille_differente_est_une_autre_famille(self):
        essais = [
            FauxEssai(("ES.v.0",), 2501, "a", 0.01),
            FauxEssai(("ES.v.0",), 2502, "b", 0.02),
        ]
        assert len(familles(essais)) == 2

    def test_l_ordre_des_symboles_compte(self):
        """Un panneau ES+NQ n'est pas le meme echantillon qu'ES seul."""
        essais = [
            FauxEssai(("ES.v.0",), 100, "a", 0.01),
            FauxEssai(("ES.v.0", "NQ.v.0"), 100, "b", 0.02),
        ]
        assert len(familles(essais)) == 2

    def test_les_plus_grosses_familles_viennent_en_premier(self):
        essais = (
            [FauxEssai(("A",), 10, "p", 0.1)]
            + [FauxEssai(("B",), 20, f"g{i}", 0.1) for i in range(4)]
            + [FauxEssai(("C",), 30, f"m{i}", 0.1) for i in range(2)]
        )
        assert [g.taille for g in familles(essais)] == [4, 2, 1]

    def test_l_ecart_type_trahit_une_famille_degeneree(self):
        serree = familles(
            [FauxEssai(("ES.v.0",), 2501, f"s{i}", 0.030 + i * 1e-5) for i in range(20)]
        )[0]
        large = familles(
            [FauxEssai(("ES.v.0",), 2501, f"l{i}", 0.03 * i) for i in range(20)]
        )[0]
        assert serree.ecart_type < large.ecart_type / 100

    def test_une_famille_d_un_seul_essai_a_un_ecart_type_nul(self):
        """Zero par CONVENTION, pas par mesure : une observation n'a pas de
        dispersion. Le rendu doit se lire en le sachant."""
        assert familles([FauxEssai(("ES.v.0",), 10, "seul", 0.4)])[0].ecart_type == 0.0

    def test_aucun_essai_ne_donne_aucune_famille(self):
        assert familles([]) == []

    def test_chaque_essai_appartient_a_exactement_une_famille(self):
        essais = [
            FauxEssai(("ES.v.0",), 2501 + (i % 3), f"e{i}", 0.01 * i) for i in range(30)
        ]
        assert sum(g.taille for g in familles(essais)) == len(essais)


class TestLaCorrelation:
    def test_une_serie_avec_elle_meme_vaut_un(self):
        ts, r = serie(200)
        assert correlation(ts, r, ts, r) == pytest.approx(1.0)

    def test_une_serie_opposee_vaut_moins_un(self):
        ts, r = serie(200)
        assert correlation(ts, r, ts, -r) == pytest.approx(-1.0)

    def test_deux_series_independantes_sont_proches_de_zero(self):
        ts, a = serie(4000, graine=1)
        _, b = serie(4000, graine=2)
        valeur = correlation(ts, a, ts, b)
        assert valeur is not None and abs(valeur) < 0.1

    def test_elle_se_calcule_sur_l_intersection_des_dates(self):
        """Le point ou une erreur d'alignement produirait un chiffre plausible.

        Deux series decalees de 100 jours n'ont que leur chevauchement en
        commun. Si le code recadrait a la meme longueur au lieu d'intersecter,
        il correlerait des jours differents et rendrait du bruit.
        """
        ts_a, a = serie(300, debut=0, graine=7)
        ts_b, b = ts_a[100:], a[100:]
        assert correlation(ts_a, a, ts_b, b) == pytest.approx(1.0)

    def test_deux_series_disjointes_ne_rendent_rien(self):
        ts_a, a = serie(100, debut=0)
        ts_b, b = serie(100, debut=10_000)
        assert correlation(ts_a, a, ts_b, b) is None

    def test_un_chevauchement_trop_court_ne_rend_rien(self):
        """Pas une approximation : du bruit. Une valeur absente se voit."""
        ts_a, a = serie(100, debut=0)
        ts_b, b = serie(100, debut=100 - MINIMUM_COMMUN // 2)
        assert correlation(ts_a, a, ts_b, b) is None

    def test_une_serie_constante_ne_rend_rien(self):
        """Une strategie qui n'a pas negocie n'a pas une correlation de zero :
        elle n'en a pas."""
        ts, a = serie(200)
        assert correlation(ts, a, ts, np.zeros(200)) is None

    def test_elle_est_symetrique(self):
        ts_a, a = serie(500, graine=4)
        ts_b, b = serie(500, graine=5)
        assert correlation(ts_a, a, ts_b, b) == pytest.approx(
            correlation(ts_b, b, ts_a, a)
        )

    def test_un_decalage_d_un_jour_n_est_pas_vu_comme_identique(self):
        """Le test qui attrape une erreur d'alignement d'un cran.

        B porte exactement les MEMES rendements que A, mais sur des dates
        decalees d'un jour. Sur leur intersection, chaque rendement de B doit
        donc tomber en face du rendement PRECEDENT de A. Sur du bruit blanc,
        cela vaut environ zero. Un code qui alignerait par position plutot que
        par date - ou qui indexerait sur `ts[:-1]` d'un cote et `ts[1:]` de
        l'autre - rendrait 1,0, et personne ne verrait la difference sur un
        rapport.
        """
        ts, r = serie(4000, graine=21)
        valeur = correlation(ts, r, ts + JOUR, r)
        assert valeur is not None
        assert abs(valeur) < 0.1, "un decalage d'un jour ne doit pas valoir 1"

    def test_la_meme_serie_aux_memes_dates_vaut_bien_un(self):
        """Le controle du precedent : sans lui, un code qui rendrait toujours
        zero passerait."""
        ts, r = serie(4000, graine=21)
        assert correlation(ts, r, ts, r) == pytest.approx(1.0)


class TestLesCorrelationsDeuxADeux:
    def test_chaque_paire_apparait_une_seule_fois(self):
        series = {nom: serie(300, graine=i) for i, nom in enumerate("abc")}
        paires = correlations(series)
        assert set(paires) == {("a", "b"), ("a", "c"), ("b", "c")}

    def test_une_paire_indefinie_est_absente_et_non_nulle(self):
        series = {
            "a": serie(100, debut=0),
            "loin": serie(100, debut=99_999),
        }
        assert correlations(series) == {}


class TestLArchivageDeLaSerie:
    """Sans elle, deux essais ne se comparent que par leur echantillon."""

    def rapport_bidon(self, cle: str, empreinte: str) -> dict:
        return {
            "name": f"essai-{cle}",
            "result_fingerprint": empreinte,
            "symbols": ["ES.v.0"],
            "manifest": {"config_hash": cle},
            "metrics": {
                "risk": {
                    "sharpe_per_period": 0.03,
                    "n_returns": 200,
                    "returns_skewness": 0.1,
                    "returns_kurtosis": 3.0,
                },
                "sample": {"n_bars": 200, "span_years": 1.0},
            },
        }

    def test_elle_est_ecrite_et_relue_au_bit_pres(self):
        ts, r = serie(200, graine=11)
        with tempfile.TemporaryDirectory() as tmp:
            registre = Registre(pathlib.Path(tmp))
            essai = registre.archiver(
                self.rapport_bidon("a" * 64, "b" * 64),
                serie=DailySeries(ts=ts, returns=r),
            )
            assert essai.serie is not None
            relu = registre.lire_serie(essai)
            assert relu is not None
            assert np.array_equal(relu[0], ts)
            assert np.array_equal(relu[1], r), "un arrondi rendrait les correlations fausses"

    def test_sans_serie_le_champ_vaut_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            registre = Registre(pathlib.Path(tmp))
            essai = registre.archiver(self.rapport_bidon("c" * 64, "d" * 64))
            assert essai.serie is None
            assert registre.lire_serie(essai) is None

    def test_un_essai_de_balayage_n_en_porte_pas(self):
        """Meme arbitrage que pour le rapport : une grille de centaines de
        configurations n'ecrit pas des centaines de fichiers."""
        with tempfile.TemporaryDirectory() as tmp:
            registre = Registre(pathlib.Path(tmp))
            essai = registre.archiver(
                self.rapport_bidon("e" * 64, "f" * 64), artefact="grille.json"
            )
            assert essai.serie is None

    def test_une_serie_declaree_mais_absente_leve(self):
        """Le registre et le disque qui se contredisent doivent se voir."""
        with tempfile.TemporaryDirectory() as tmp:
            registre = Registre(pathlib.Path(tmp))
            essai = registre.archiver(
                self.rapport_bidon("1" * 64, "2" * 64),
                serie=DailySeries(*serie(60)),
            )
            assert essai.serie is not None
            (pathlib.Path(tmp) / essai.serie).unlink()
            with pytest.raises(ConfigurationError, match="se contredisent"):
                registre.lire_serie(essai)


class TestLaCompatibiliteDuRegistre:
    """498 lignes existantes ne portent pas ce champ. Elles doivent se lire."""

    LIGNE_ANCIENNE = (
        '{"config_hash": "ac9b", "date": "2026-09-12", "kurtosis": 13.9, '
        '"label": "ancien", "n_bars": 2652, "n_returns": 2651, "note": "", '
        '"rapport": "rapports/x.json", "result_fingerprint": "e968", '
        '"sharpe_per_period": 0.0376, "skewness": -0.6, "span_years": 10.3, '
        '"symbols": ["ES.v.0"]}'
    )

    def test_une_ligne_sans_serie_se_relit(self):
        essai = Essai.depuis_ligne(self.LIGNE_ANCIENNE)
        assert essai.serie is None
        assert essai.label == "ancien"

    def test_une_ligne_neuve_fait_l_aller_retour(self):
        essai = Essai.depuis_ligne(self.LIGNE_ANCIENNE)
        avec = essai.avec_rapport("rapports/y.json", "series/y.npz")
        assert Essai.depuis_ligne(avec.ligne()).serie == "series/y.npz"


class TestLaSerieQuotidienne:
    def test_elle_exige_une_date_de_plus_que_de_rendements(self):
        """Un rendement relie DEUX dates. Une serie mal formee ferait taire
        l'alignement au lieu de le faire echouer."""
        with pytest.raises(ConfigurationError, match="incoherente"):
            DailySeries(ts=np.arange(5, dtype=np.int64), returns=np.zeros(5))

    def test_la_forme_juste_passe(self):
        assert DailySeries(ts=np.arange(5, dtype=np.int64), returns=np.zeros(4))


class TestCeQueLeRapportPublie:
    def test_le_bloc_dsr_porte_les_deux_facteurs(self):
        from rsl.metrics.statistics import deflated_sharpe_ratio

        resultat = deflated_sharpe_ratio(
            sharpe_per_period=0.04,
            n_observations=2500,
            skewness=-0.5,
            kurtosis=6.0,
            n_trials=498,
            variance_of_trial_sharpes=0.00048,
        )
        publie = resultat.describe()
        assert "dispersion_of_trials" in publie
        assert "count_factor" in publie
        assert publie["dispersion_of_trials"] == pytest.approx(math.sqrt(0.00048))

    def test_le_rendu_ne_montre_plus_le_seul_produit(self):
        from rsl.metrics.statistics import deflated_sharpe_ratio

        rendu = deflated_sharpe_ratio(
            sharpe_per_period=0.04,
            n_observations=2500,
            skewness=0.0,
            kurtosis=3.0,
            n_trials=498,
            variance_of_trial_sharpes=0.00048,
        ).render()
        assert "dispersion" in rendu and "compte" in rendu


class TestLaCommande:
    """`rsl essais --familles`. Un chiffre qui gouverne l'interpretation de
    tous les autres doit pouvoir se consulter sans relire un fichier."""

    def registre_jouet(self, racine: pathlib.Path) -> Registre:
        registre = Registre(racine)
        for i in range(7):
            registre.archiver(
                {
                    "name": f"voisin-{i}",
                    "result_fingerprint": f"{i:064d}",
                    "symbols": ["ES.v.0"],
                    "manifest": {"config_hash": f"{i:064x}"},
                    "metrics": {
                        "risk": {
                            "sharpe_per_period": 0.030 + i * 1e-5,
                            "n_returns": 2501,
                            "returns_skewness": 0.0,
                            "returns_kurtosis": 3.0,
                        },
                        "sample": {"n_bars": 2501, "span_years": 10.0},
                    },
                }
            )
        return registre

    def test_elle_nomme_la_famille_dominante(self, tmp_path, monkeypatch, capsys):
        from rsl.cli import main

        self.registre_jouet(tmp_path / "essais")
        monkeypatch.chdir(tmp_path)
        assert main(["essais", "--familles"]) == 0
        sortie = capsys.readouterr().out
        assert "7 essai(s)" in sortie
        assert "1 famille(s)" in sortie
        assert "dispersion" in sortie and "compte" in sortie

    def test_elle_dit_combien_d_essais_portent_leur_serie(self, tmp_path, monkeypatch, capsys):
        """Zero sur un registre ancien : c'est une information, pas un silence."""
        from rsl.cli import main

        self.registre_jouet(tmp_path / "essais")
        monkeypatch.chdir(tmp_path)
        main(["essais", "--familles"])
        assert "0 essai(s) sur 7 portent leur serie" in capsys.readouterr().out

    def test_sans_le_drapeau_la_sortie_reste_celle_d_avant(self, tmp_path, monkeypatch, capsys):
        from rsl.cli import main

        self.registre_jouet(tmp_path / "essais")
        monkeypatch.chdir(tmp_path)
        main(["essais"])
        sortie = capsys.readouterr().out
        assert "configuration(s) distincte(s)" in sortie
        assert "famille(s)" not in sortie
