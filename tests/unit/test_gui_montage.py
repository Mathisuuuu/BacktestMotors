"""Le MONTAGE : l'actif, l'argent, les couts, choisis dans la fenetre.

Sans tkinter, comme `test_gui_model.py` et pour la meme raison : l'interface
est du dessin, ce qu'elle produit est du calcul. Ce fichier teste le calcul.

Ce qu'il garde
--------------
1. **Les reglages produits sont acceptes par `BacktestSpec`.** Le formulaire
   ne redeclare aucun champ ; s'il en inventait un, `extra="forbid"` le
   refuserait - encore faut-il que quelqu'un le constate.
2. **Une saisie fautive est NOMMEE.** Un capital a zero, un instrument
   inconnu, un glissement negatif : chacun doit dire ce qui ne va pas, pas
   echouer plus loin sous une forme meconnaissable.
3. **La table des dossiers suit la table des instruments.** C'est une dette
   assumee du module ; ce test est ce qui l'empeche de pourrir en silence.
"""

from __future__ import annotations

import pytest

from rsl.data.instruments import known_roots
from rsl.errors import ConfigurationError
from rsl.gui.montage import (
    FRAIS,
    GLISSEMENTS,
    MIN_BARRES_AGREGEES,
    RESAMPLES,
    Montage,
    min_barres_pour,
    racine_initiale,
    seance_proposee,
)


class TestCeQueLeFormulaireProduit:
    def test_les_reglages_sont_acceptes_par_la_specification(self):
        """La verification qui compte : ce que le formulaire produit doit
        composer un run valide, sans qu'aucun champ soit invente."""
        from rsl.composition import StrategyFile, compose

        strategie = StrategyFile.model_validate({
            "format": "rsl-strategy@1", "name": "t",
            "strategy": {"ref": "rules@1", "params": {
                "quantity": 1,
                "rules": {"entry_long": {"type": "constant", "value": 1.0}},
            }},
        })
        montage = Montage(root="ES")
        spec = compose(strategie, montage.reglages(), symbol=montage.symbole)
        assert spec.initial_cash == montage.capital
        assert spec.data[0].root == "ES"

    def test_le_chemin_est_relatif(self):
        """Un chemin absolu ferait diverger le `config_hash` entre deux
        machines - le defaut corrige le 2026-09-10."""
        from pathlib import Path

        chemin = Montage(root="ES").chemin
        assert not Path(chemin).is_absolute()
        assert "\\" not in chemin, "un chemin canonique est en POSIX"

    def test_brut_ne_reechantillonne_pas(self):
        """`brut` est nomme plutot que represente par une chaine vide : un menu
        deroulant ne doit jamais montrer une case dont personne ne sait si elle
        veut dire « rien » ou « pas encore choisi »."""
        donnees = Montage(root="ES", resample="brut").reglages()["data"]
        assert isinstance(donnees, list)
        assert "resample" not in donnees[0]

    def test_une_agregation_pose_un_minimum_de_barres(self):
        """Une seance tronquee produirait sinon une barre quotidienne batie sur
        quelques minutes, qui ressemble a une vraie barre."""
        donnees = Montage(root="ES", resample="day").reglages()["data"]
        assert isinstance(donnees, list)
        assert donnees[0]["resample_min_bars"] > 0

    @pytest.mark.parametrize(("genre", "champ"), [("tick", "ticks"), ("bps", "bps")])
    def test_le_glissement_porte_sa_valeur(self, genre, champ):
        execution = Montage(root="ES", glissement=genre, glissement_valeur=2.0).reglages()
        assert isinstance(execution, dict)
        assert execution["execution"]["slippage"][champ] == 2.0

    def test_un_glissement_nul_n_en_porte_aucune(self):
        """`zero` n'a pas de parametre : lui en donner un serait refuse."""
        execution = Montage(root="ES", glissement="zero").reglages()
        assert isinstance(execution, dict)
        assert execution["execution"]["slippage"] == {"kind": "zero"}


class TestLesSaisiesFautives:
    """Chacune doit dire ce qui ne va pas, et pourquoi c'est un probleme."""

    def test_un_instrument_inconnu_enumere_les_connus(self):
        with pytest.raises(ConfigurationError, match="instrument inconnu"):
            Montage(root="AAPL")

    def test_un_capital_nul_est_refuse(self):
        with pytest.raises(ConfigurationError, match="ne peut rien acheter"):
            Montage(root="ES", capital=0.0)

    def test_zero_contrat_est_refuse(self):
        with pytest.raises(ConfigurationError, match="rien a mesurer"):
            Montage(root="ES", contrats=0)

    def test_un_glissement_negatif_est_refuse(self):
        """Il ferait GAGNER de l'argent a chaque execution - une erreur de
        saisie qui embellirait tous les resultats."""
        with pytest.raises(ConfigurationError, match="gagner de l'argent"):
            Montage(root="ES", glissement="tick", glissement_valeur=-1.0)

    @pytest.mark.parametrize(("champ", "valeur"), [
        ("resample", "quotidien"), ("frais", "gratuit"), ("glissement", "aucun"),
    ])
    def test_une_valeur_hors_liste_est_refusee(self, champ, valeur):
        with pytest.raises(ConfigurationError, match="inconnu"):
            Montage(root="ES", **{champ: valeur})


class TestLesListesProposees:
    def test_chaque_choix_de_frais_est_accepte(self):
        for genre in FRAIS:
            assert Montage(root="ES", frais=genre) is not None

    def test_chaque_choix_de_glissement_est_accepte(self):
        for genre in GLISSEMENTS:
            assert Montage(root="ES", glissement=genre) is not None

    def test_chaque_agregation_est_acceptee_avec_ce_que_le_formulaire_propose(self):
        """La propriete qui compte pour l'utilisateur : tout ce que le menu
        offre doit etre constructible SANS rien retaper.

        Les agregations intra-journalieres exigent une seance ; le formulaire
        la pre-remplit. Si la proposition manquait pour un instrument offert,
        le menu contiendrait un choix menant a une erreur - ce test l'interdit.
        """
        propose = seance_proposee("ES")
        for genre in RESAMPLES:
            assert Montage(root="ES", resample=genre, seance=propose) is not None


class TestUneAgregationIntraJournaliereExigeUneSeance:
    """Le socle ne devine aucune frontiere ; le formulaire non plus."""

    SEANCE = "17:00-16:00@America/Chicago"

    @pytest.mark.parametrize(
        "genre", ["5min", "10min", "15min", "30min", "1h", "2h", "4h"]
    )
    def test_sans_seance_elle_est_refusee(self, genre):
        with pytest.raises(ConfigurationError, match="exige une SEANCE"):
            Montage(root="ES", resample=genre)

    @pytest.mark.parametrize("genre", ["brut", "day", "week", "month"])
    def test_une_agregation_calendaire_n_en_demande_aucune(self, genre):
        assert Montage(root="ES", resample=genre) is not None

    def test_avec_une_seance_elle_passe_et_la_transmet(self):
        reglages = Montage(root="ES", resample="4h", seance=self.SEANCE).reglages()
        source = reglages["data"][0]
        assert source["resample"] == "4h"
        assert source["session"] == {
            "start": "17:00", "end": "16:00", "timezone": "America/Chicago"
        }

    def test_un_format_de_seance_faux_est_refuse_des_la_saisie(self):
        """Et non au chargement des donnees : l'erreur porte sur le
        formulaire, pas sur des centaines de Mo de parquet."""
        with pytest.raises(ConfigurationError, match="format attendu"):
            Montage(root="ES", resample="1h", seance="17h-16h")

    def test_un_fuseau_inconnu_est_refuse_par_le_socle(self):
        """La validation des trois champs reste faite par le socle : ce module
        ne redeclare aucune regle."""
        with pytest.raises(ConfigurationError, match="fuseau inconnu"):
            Montage(root="ES", resample="1h", seance="17:00-16:00@Mars/Olympus")

    def test_une_seance_declaree_sur_une_agregation_calendaire_est_transmise(self):
        """Elle ne sert pas au decoupage - `resample` la refuserait - mais elle
        reste utile aux noeuds `session` et `cumulative`. Le montage la passe
        donc, et c'est `config.py` qui decide de ne pas l'utiliser pour
        agreger."""
        reglages = Montage(root="ES", resample="day", seance=self.SEANCE).reglages()
        assert reglages["data"][0]["session"]["start"] == "17:00"

    def test_le_resume_dit_la_seance_retenue(self):
        """Le bandeau doit montrer ce qui a SERVI : deux seances differentes
        font deux decoupages differents, donc deux runs differents."""
        resume = Montage(root="ES", resample="4h", seance=self.SEANCE).resume()
        assert self.SEANCE in resume


class TestLeSeuilDeRemplissageSuitLaFamille:
    """200 barres sur une tranche de 5 min les ecarterait TOUTES."""

    def test_une_agregation_calendaire_garde_le_seuil_historique(self):
        source = Montage(root="ES", resample="day").reglages()["data"][0]
        assert source["resample_min_bars"] == MIN_BARRES_AGREGEES

    @pytest.mark.parametrize(
        ("genre", "attendu"), [("5min", 2), ("1h", 30), ("4h", 120)]
    )
    def test_une_tranche_exige_la_moitie_de_sa_duree(self, genre, attendu):
        assert min_barres_pour(genre) == attendu

    def test_le_seuil_laisse_passer_la_derniere_tranche_d_une_seance_es(self):
        """Une seance de 23 h decoupee en 4 h finit sur une tranche de 3 h.
        Un seuil qui l'ecarterait supprimerait la cloture de chaque seance -
        la partie la plus liquide."""
        assert min_barres_pour("4h") <= 3 * 60

    def test_brut_n_a_pas_de_seuil_puisqu_il_n_agrege_pas(self):
        source = Montage(root="ES", resample="brut").reglages()["data"][0]
        assert "resample_min_bars" not in source

    def test_chaque_instrument_connu_est_acceptable(self):
        for racine in known_roots():
            assert Montage(root=racine).symbole.startswith(racine)


class TestLeCheminVientDeLaTableDesContrats:
    """La dette est REMBOURSEE depuis le 2026-09-12.

    Ce module portait une copie de l'arborescence (`DOSSIERS`), qu'un
    instrument range ailleurs - ou simplement oublie - aurait fait mentir sans
    prevenir. Le chemin se derive desormais de `InstrumentSpec.data_path`, et
    il n'y a plus qu'une source.
    """

    def test_il_est_celui_que_la_table_des_contrats_annonce(self):
        from rsl.data.instruments import get_instrument

        for racine in known_roots():
            assert Montage(root=racine).chemin == get_instrument(racine).data_path

    def test_le_module_ne_porte_plus_de_copie(self):
        """Une garde contre le retour du probleme : reintroduire une table de
        dossiers ici recreerait la divergence qu'on vient de supprimer."""
        import rsl.gui.montage as module

        assert not hasattr(module, "DOSSIERS")


class TestLeDefautProposeALOuverture:
    def test_c_est_es_et_non_le_premier_par_ordre_alphabetique(self):
        """L'ordre alphabetique donnait `6A`, un contrat sur le dollar
        australien. Un defaut arbitraire n'est pas neutre : il est choisi par
        accident au lieu de l'etre expres."""
        assert racine_initiale() == "ES"

    def test_il_est_toujours_un_instrument_connu(self):
        assert racine_initiale() in known_roots()


class TestLeResume:
    """Ce que le bandeau affiche : ce qui a servi, pas ce qui est possible."""

    def test_il_nomme_l_actif_l_agregation_et_le_capital(self):
        texte = Montage(root="ES", resample="day", capital=250_000.0).resume()
        assert "ES.v.0" in texte
        assert "day" in texte
        assert "250 000" in texte

    def test_brut_s_affiche_en_unite_de_temps(self):
        """« brut » est un mot du formulaire ; ce que l'utilisateur veut lire
        est la granularite reelle."""
        assert "1 min" in Montage(root="ES", resample="brut").resume()

    def test_un_run_sans_cout_le_dit(self):
        texte = Montage(root="ES", frais="zero", glissement="zero").resume()
        assert "sans cout" in texte
