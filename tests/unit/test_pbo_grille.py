"""Construire la matrice de la CSCV a partir de vraies specifications.

Deux decouvertes du 2026-09-12, faites en lancant la premiere grille reelle, et
que ce fichier verrouille.

1. **Une grille ne partage pas son echantillon naturellement.** Une fenetre
   lente de 200 barres commence 200 barres plus tard qu'une de 50 : la grille
   4x4 des fenetres usuelles donnait QUATRE longueurs differentes sur ES
   quotidien. Les comparer telles quelles compare des epoques, pas des
   strategies.
2. **Une configuration peut ne rien faire pendant un huitieme de
   l'echantillon.** Son Sharpe n'y est alors pas defini. Lui donner zero la
   classerait au-dessus de toutes les perdantes ; le defaut est donc de
   refuser, et le retrait doit etre DEMANDE et nomme.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fixtures import synthetic
from rsl.config import BacktestSpec
from rsl.data.schema import Granularity
from rsl.errors import ConfigurationError
from rsl.pbo import aligner_sur_un_echantillon_commun, construire_grille, warmup_naturel

JOUR = Granularity(timedelta(days=1), name="1d")
EPOCH = datetime(2016, 1, 4, tzinfo=UTC)


@pytest.fixture(scope="module")
def serie(tmp_path_factory) -> Path:
    """Une sinusoide assez longue et assez bruitee pour que les croisements
    negocient sur toutes les sous-periodes."""
    chemin = tmp_path_factory.mktemp("pbo") / "ES_v0_1m.parquet"
    synthetic.make_frame(
        synthetic.sine(1200, 2000.0, 200.0, 60), granularity=JOUR, start=EPOCH
    ).write_parquet(chemin)
    return chemin


@pytest.fixture(scope="module")
def lente(tmp_path_factory) -> Path:
    """Une sinusoide de periode 700 : une fenetre de 300 barres y croise
    rarement, ce qui rend une configuration inactive sur une sous-periode sans
    tirer le warmup de toute la grille."""
    chemin = tmp_path_factory.mktemp("pbo-lente") / "ES_v0_1m.parquet"
    synthetic.make_frame(
        synthetic.sine(1400, 2000.0, 200.0, 700), granularity=JOUR, start=EPOCH
    ).write_parquet(chemin)
    return chemin


@pytest.fixture(scope="module")
def monotone(tmp_path_factory) -> Path:
    """Une rampe : aucun croisement apres le premier, donc plus personne ne
    negocie."""
    chemin = tmp_path_factory.mktemp("pbo-rampe") / "ES_v0_1m.parquet"
    synthetic.make_frame(
        synthetic.ramp(1400, 2000.0, 1.0), granularity=JOUR, start=EPOCH
    ).write_parquet(chemin)
    return chemin


def config(chemin: Path, rapide: int, lent: int) -> BacktestSpec:
    return BacktestSpec.model_validate({
        "name": f"sma-{rapide}-{lent}",
        "initial_cash": 500_000.0,
        "data": [{"root": "ES", "path": str(chemin)}],
        "execution": {"fees": {"kind": "zero"}, "slippage": {"kind": "zero"}},
        "risk": {"sizing": {"kind": "fixed", "contracts": 1}},
        "strategy": {
            "ref": "sma_crossover@1",
            "params": {
                "symbol": "ES.v.0", "fast_window": rapide, "slow_window": lent
            },
        },
    })


def grille_de(chemin: Path) -> list[BacktestSpec]:
    return [config(chemin, f, s) for f, s in ((5, 20), (10, 40), (5, 60), (15, 80))]


class TestLAlignementSurUnEchantillonCommun:
    def test_les_fenetres_inegales_donnent_des_warmups_inegaux(self, serie):
        """Le fait de depart, constate plutot que suppose."""
        naturels = {warmup_naturel(spec) for spec in grille_de(serie)}
        assert len(naturels) > 1, naturels

    def test_l_alignement_les_porte_tous_au_maximum(self, serie):
        specs = grille_de(serie)
        attendu = max(warmup_naturel(s) for s in specs)
        alignees, plancher = aligner_sur_un_echantillon_commun(specs)
        assert plancher == attendu
        assert {warmup_naturel(s) for s in alignees} == {attendu}

    def test_il_ne_modifie_pas_les_specifications_d_origine(self, serie):
        """Une grille qui muterait ce qu'on lui passe rendrait le second appel
        different du premier."""
        specs = grille_de(serie)
        avant = [s.min_warmup_bars for s in specs]
        aligner_sur_un_echantillon_commun(specs)
        assert [s.min_warmup_bars for s in specs] == avant

    def test_sans_alignement_les_longueurs_inegales_sont_refusees(self, serie):
        """Le refus est ce qui a revele le probleme. Le garder accessible
        permet de le CONSTATER plutot que de le contourner sans le voir."""
        with pytest.raises(ConfigurationError, match="epoques differentes"):
            construire_grille(grille_de(serie), 4, aligner=False)

    def test_avec_alignement_la_grille_se_construit(self, serie):
        grille = construire_grille(grille_de(serie), 4)
        assert grille.matrice.shape == (4, 4)

    def test_et_le_cout_de_l_alignement_est_rapporte(self, serie):
        """Des barres sont perdues au debut : c'est le prix de la
        comparabilite, et il doit se lire."""
        grille = construire_grille(grille_de(serie), 4)
        assert any("warmup porte a" in a for a in grille.warnings)


class TestUneConfigurationInactive:
    """Sharpe indefini sur un bloc : refuser par defaut, retirer sur demande."""

    def inactive(self, lente: Path) -> list[BacktestSpec]:
        """Sur une sinusoide LENTE, une fenetre de 300 barres croise rarement :
        `sma-5-300` ne prend aucune position sur la premiere sous-periode,
        tandis que les deux autres negocient partout.

        Une fenetre encore plus longue ne conviendrait pas : elle tirerait le
        warmup de TOUTE la grille par l'alignement, et rendrait tout le monde
        inactif - constate en ecrivant ce test."""
        return [config(lente, 5, 20), config(lente, 10, 40), config(lente, 5, 300)]

    def test_elle_est_refusee_par_defaut(self, lente):
        with pytest.raises(ConfigurationError, match="flatte l'inactivite"):
            construire_grille(self.inactive(lente), 4)

    def test_le_message_nomme_la_configuration_et_le_bloc(self, lente):
        with pytest.raises(ConfigurationError, match="sma-5-300"):
            construire_grille(self.inactive(lente), 4)

    def test_le_retrait_doit_etre_demande(self, lente):
        grille = construire_grille(self.inactive(lente), 4, ignorer_inactives=True)
        assert len(grille.labels) == 2
        assert "sma-5-300" not in grille.labels

    def test_et_il_est_nomme_dans_les_avertissements(self, lente):
        """Les retirees ne sont pas neutres : la PBO porte sur les restantes,
        et le lecteur doit savoir laquelle a disparu."""
        grille = construire_grille(self.inactive(lente), 4, ignorer_inactives=True)
        assert any("sma-5-300" in a for a in grille.warnings)

    def test_une_grille_reduite_a_moins_de_deux_est_refusee(self, monotone):
        """Sur une rampe, aucun croisement apres le premier : plus personne ne
        negocie, et une PBO sur zero configuration n'existe pas."""
        specs = [config(monotone, 5, 20), config(monotone, 10, 40)]
        with pytest.raises(ConfigurationError, match="ne mesure pas une"):
            construire_grille(specs, 4, ignorer_inactives=True)


class TestLeDecoupage:
    def test_les_blocs_sont_de_meme_taille(self, serie):
        grille = construire_grille(grille_de(serie), 4)
        assert grille.barres_par_bloc > 0
        assert grille.matrice.shape[1] == 4

    def test_le_reste_est_ecarte_a_la_fin_et_rapporte(self, serie):
        """Le retirer au debut ferait disparaitre du warmup ; le repartir
        donnerait des blocs de tailles differentes, donc des Sharpe non
        comparables."""
        grille = construire_grille(grille_de(serie), 6)
        assert grille.barres_ecartees < 6

    def test_un_s_impair_est_refuse(self, serie):
        with pytest.raises(ConfigurationError, match="PAIR"):
            construire_grille(grille_de(serie), 3)

    def test_une_seule_configuration_est_refusee(self, serie):
        with pytest.raises(ConfigurationError, match="SELECTION"):
            construire_grille([config(serie, 5, 20)], 4)

    def test_un_s_trop_grand_pour_l_echantillon_est_refuse(self, serie):
        with pytest.raises(ConfigurationError, match="au moins deux observations"):
            construire_grille(grille_de(serie), 2000)


class TestDeLaGrilleAuChiffre:
    def test_evaluer_rend_une_pbo(self, serie):
        resultat = construire_grille(grille_de(serie), 4).evaluer()
        assert 0.0 <= resultat.pbo <= 1.0
        assert resultat.n_configurations == 4

    def test_la_grille_se_serialise(self, serie):
        import json

        decrit = construire_grille(grille_de(serie), 4).describe()
        assert json.loads(json.dumps(decrit)) == decrit

    def test_elle_porte_de_quoi_se_relire(self, serie):
        """Une matrice anonyme ne se relit pas : « la configuration 2 gagne »
        n'est utilisable que si l'on sait laquelle c'est."""
        grille = construire_grille(grille_de(serie), 4)
        assert len(grille.labels) == len(grille.config_hashes) == 4
        assert all(len(h) == 64 for h in grille.config_hashes)

    def test_le_rendu_montre_la_matrice(self, serie):
        rendu = construire_grille(grille_de(serie), 4).render()
        assert "sma-5-20" in rendu
