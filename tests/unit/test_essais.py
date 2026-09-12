"""Le registre des essais : la memoire du compteur, entre les sessions.

Pourquoi ce registre existe
----------------------------
`TrialLog` compte les essais d'un PROCESSUS. Chaque `rsl run` en creait un
neuf, donc chaque run se declarait « 1 essai » et son Deflated Sharpe se
confondait avec son PSR. Le seul chiffre qui corrige la selection ne corrigeait
jamais rien.

Ce que ce fichier garde, par ordre d'importance
------------------------------------------------
1. **Rejouer n'est pas essayer.** Deux runs de la meme specification ne
   comptent qu'une fois. Punir la reproductibilite serait exactement contraire
   au but du socle.
2. **Un essai perdu est pire qu'un essai en trop.** Sous-compter gonfle le DSR
   de tous les autres, sans que rien ne le signale. Le registre refuse donc les
   rapports dont il ne peut pas tirer un Sharpe, plutot que d'en inventer un.
3. **Deux verites ne portent pas le meme nom.** Une specification qui rend un
   autre resultat qu'avant signale un changement de MOTEUR ; le registre le
   garde et le dit, au lieu de choisir laquelle croire.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rsl.errors import ConfigurationError
from rsl.essais import EssaiDejaArchiveError, Registre


def rapport(
    *,
    config: str = "c0ffee" * 10,
    empreinte: str = "beef" * 16,
    sharpe: float | None = 0.05,
    nom: str = "essai-de-test",
) -> dict[str, object]:
    """Un rapport minimal, de la forme que produit `BacktestReport.to_dict`."""
    risque: dict[str, object] = {
        "n_returns": 2500,
        "returns_skewness": -0.5,
        "returns_kurtosis": 8.0,
    }
    if sharpe is not None:
        risque["sharpe_per_period"] = sharpe
    return {
        "name": nom,
        "symbols": ["ES.v.0"],
        "result_fingerprint": empreinte,
        "manifest": {"config_hash": config},
        "metrics": {
            "risk": risque,
            "sample": {"n_bars": 2600, "span_years": 10.2},
        },
    }


@pytest.fixture
def registre(tmp_path: Path) -> Registre:
    return Registre(racine=tmp_path / "essais")


class TestUnRegistreVide:
    """Un depot neuf n'a pas d'essais, et ce n'est pas une erreur."""

    def test_il_ne_leve_pas(self, registre):
        assert registre.essais() == []

    def test_son_journal_ne_compte_rien(self, registre):
        assert registre.journal().n_trials == 0

    def test_sa_variance_est_nulle(self, registre):
        """Sans selection, il n'y a rien a corriger - la regle de `TrialLog`."""
        assert registre.journal().variance_of_sharpes == 0.0


class TestArchiverUnEssai:
    def test_la_ligne_est_ecrite(self, registre):
        registre.archiver(rapport())
        assert len(registre.essais()) == 1

    def test_le_rapport_complet_est_ecrit_a_cote(self, registre):
        """Une ligne de registre suffit au DSR ; elle ne suffit pas a VERIFIER
        un chiffre publie. Le rapport archive est ce qui rend l'essai
        rejouable."""
        essai = registre.archiver(rapport())
        assert essai.rapport is not None
        assert (registre.racine / essai.rapport).exists()

    def test_le_nom_du_rapport_porte_les_deux_cles(self, registre):
        """Configuration ET resultat : une meme specification peut avoir
        plusieurs rapports si le moteur a change, et ils ne doivent pas
        s'ecraser."""
        essai = registre.archiver(rapport())
        assert essai.config_hash[:12] in str(essai.rapport)
        assert essai.result_fingerprint[:12] in str(essai.rapport)

    def test_le_journal_le_compte(self, registre):
        registre.archiver(rapport())
        assert registre.journal().n_trials == 1

    def test_la_note_est_conservee(self, registre):
        """Le « pourquoi » d'un essai ne se retrouve nulle part ailleurs : ni
        la specification ni le resultat ne disent ce qu'on cherchait."""
        essai = registre.archiver(rapport(), note="pour voir")
        assert essai.note == "pour voir"
        assert registre.essais()[0].note == "pour voir"

    def test_le_fichier_est_du_jsonl(self, registre):
        """Une ligne par essai : deux sessions qui archivent en parallele font
        deux lignes, pas un conflit sur un tableau reindente."""
        registre.archiver(rapport(config="a" * 64))
        registre.archiver(rapport(config="b" * 64, empreinte="c" * 64))
        lignes = registre.fichier.read_text(encoding="utf-8").strip().split("\n")
        assert len(lignes) == 2
        assert all(isinstance(json.loads(ligne), dict) for ligne in lignes)


class TestRejouerNEstPasEssayer:
    """La regle qui protege la reproductibilite."""

    def test_le_meme_essai_deux_fois_est_refuse(self, registre):
        registre.archiver(rapport())
        with pytest.raises(EssaiDejaArchiveError, match="Rejouer n'est pas essayer"):
            registre.archiver(rapport())

    def test_et_le_compteur_ne_bouge_pas(self, registre):
        registre.archiver(rapport())
        with pytest.raises(EssaiDejaArchiveError):
            registre.archiver(rapport())
        assert registre.journal().n_trials == 1

    def test_aucun_drapeau_ne_permet_de_passer_outre(self, registre):
        """Une echappatoire finirait par transformer « j'ai relance pour
        verifier » en un essai de plus, par inadvertance."""
        registre.archiver(rapport())
        with pytest.raises(TypeError):
            registre.archiver(rapport(), forcer=True)  # type: ignore[call-arg]

    def test_deux_configurations_distinctes_comptent_deux_fois(self, registre):
        registre.archiver(rapport(config="a" * 64, empreinte="1" * 64))
        registre.archiver(rapport(config="b" * 64, empreinte="2" * 64))
        assert registre.journal().n_trials == 2


class TestUneEmpreinteQuiChangeEstUnEvenement:
    """Meme specification, autre resultat : le moteur a change."""

    def deux_resultats(self, registre: Registre) -> None:
        registre.archiver(rapport(config="a" * 64, empreinte="1" * 64))
        registre.archiver(rapport(config="a" * 64, empreinte="2" * 64))

    def test_le_second_n_est_pas_refuse(self, registre):
        """Ce n'est pas un doublon : c'est une information qu'on perdrait."""
        self.deux_resultats(registre)
        assert len(registre.essais()) == 2

    def test_mais_il_ne_compte_pas_pour_un_essai_de_plus(self, registre):
        """Une seule configuration a ete essayee ; on en a deux mesures.
        Gonfler le compteur ferait baisser le DSR pour une raison qui n'a rien
        a voir avec la selection."""
        self.deux_resultats(registre)
        assert registre.journal().n_trials == 1

    def test_et_la_divergence_est_signalee(self, registre):
        self.deux_resultats(registre)
        divergences = registre.divergences()
        assert list(divergences) == ["a" * 64]
        assert len(divergences["a" * 64]) == 2

    def test_sans_divergence_rien_n_est_signale(self, registre):
        registre.archiver(rapport(config="a" * 64, empreinte="1" * 64))
        registre.archiver(rapport(config="b" * 64, empreinte="2" * 64))
        assert registre.divergences() == {}


class TestUnMemeResultatSousDeuxNoms:
    """Le miroir, et le plus insidieux des deux.

    Deux ecritures de la meme strategie ont deux `config_hash` et une seule
    empreinte. Le compteur les voit comme deux essais alors qu'une seule idee a
    ete essayee - et l'effet sur le DSR n'est pas lisible a l'oeil : le nombre
    d'essais monte, la variance des Sharpe baisse.
    """

    def test_il_est_signale(self, registre):
        registre.archiver(rapport(config="a" * 64, empreinte="1" * 64, nom="ecriture-A"))
        registre.archiver(rapport(config="b" * 64, empreinte="1" * 64, nom="ecriture-B"))
        doublons = registre.doublons()
        assert list(doublons) == ["1" * 64]
        assert {e.label for e in doublons["1" * 64]} == {"ecriture-A", "ecriture-B"}

    def test_mais_il_n_est_pas_corrige_d_office(self, registre):
        """Decider que deux specifications sont « la meme idee » est un
        jugement. Le registre signale ; il ne tranche pas."""
        registre.archiver(rapport(config="a" * 64, empreinte="1" * 64))
        registre.archiver(rapport(config="b" * 64, empreinte="1" * 64))
        assert registre.journal().n_trials == 2

    def test_le_signal_est_suffisant_jamais_necessaire(self, registre):
        """Deux ecritures economiquement equivalentes dont les fills portent
        d'autres etiquettes ont deux empreintes, et passent inapercues -
        constate le 2026-09-12 entre `cross_sectional_momentum@1` et
        `ranking@1`, meme Sharpe et deux empreintes."""
        registre.archiver(rapport(config="a" * 64, empreinte="1" * 64, sharpe=0.2638))
        registre.archiver(rapport(config="b" * 64, empreinte="2" * 64, sharpe=0.2638))
        assert registre.doublons() == {}


class TestUnEssaiSansSharpeEstRefuse:
    """Plutot que d'en inventer un.

    Un zero ferait baisser la variance des Sharpe essayes, donc monter le DSR
    de tous les autres essais. Une mesure inventee ne se contente pas d'etre
    fausse : elle fausse le chiffre des voisins.
    """

    def test_il_leve(self, registre):
        with pytest.raises(ConfigurationError, match="sharpe_per_period"):
            registre.archiver(rapport(sharpe=None))

    def test_le_message_dit_pourquoi(self, registre):
        with pytest.raises(ConfigurationError, match="ferait monter le DSR"):
            registre.archiver(rapport(sharpe=None))

    def test_et_rien_n_est_ecrit(self, registre):
        with pytest.raises(ConfigurationError):
            registre.archiver(rapport(sharpe=None))
        assert registre.essais() == []

    @pytest.mark.parametrize("bloc", ["metrics", "manifest"])
    def test_un_rapport_tronque_est_nomme(self, registre, bloc):
        charge = rapport()
        del charge[bloc]
        with pytest.raises(ConfigurationError, match=bloc):
            registre.archiver(charge)


class TestLaLectureDuRegistre:
    def test_une_ligne_fautive_est_nommee_avec_son_numero(self, registre):
        """Un registre append-only se repare a la main : sans le numero de
        ligne, « quelque chose ne va pas » n'est pas actionnable."""
        registre.archiver(rapport())
        with registre.fichier.open("a", encoding="utf-8") as flux:
            flux.write("ceci n'est pas du JSON\n")
        with pytest.raises(ConfigurationError, match=":2 :"):
            registre.essais()

    def test_les_lignes_vides_sont_ignorees(self, registre):
        registre.archiver(rapport())
        with registre.fichier.open("a", encoding="utf-8") as flux:
            flux.write("\n\n")
        assert len(registre.essais()) == 1

    def test_une_ligne_fait_l_aller_retour(self, registre):
        """Ce qui est ecrit doit se relire identique, sinon le registre perd de
        l'information a chaque session."""
        ecrit = registre.archiver(rapport(), note="aller-retour")
        relu = registre.essais()[0]
        assert relu == ecrit

    def test_les_cles_sont_triees_dans_le_fichier(self, registre):
        """Deux archivages du meme essai donnent le meme texte, et un
        `git diff` reste lisible."""
        registre.archiver(rapport())
        cles = list(json.loads(registre.fichier.read_text(encoding="utf-8").strip()))
        assert cles == sorted(cles)


class TestCeQueLeJournalDonneAuDeflatedSharpe:
    """Le registre doit suffire a recalculer un DSR, sans relire les rapports."""

    def test_la_variance_des_sharpe_est_celle_des_essais(self, registre):
        for i, sharpe in enumerate((0.01, 0.05, 0.09)):
            registre.archiver(
                rapport(config=f"{i}" * 64, empreinte=f"{i}e" * 32, sharpe=sharpe)
            )
        journal = registre.journal()
        assert journal.n_trials == 3
        assert journal.variance_of_sharpes == pytest.approx(0.0016)

    def test_les_moments_sont_recopies_dans_la_ligne(self, registre):
        """Asymetrie et kurtosis entrent dans le DSR. Les laisser dans le seul
        rapport obligerait a relire quatorze fichiers pour un chiffre."""
        essai = registre.archiver(rapport())
        assert essai.skewness == -0.5
        assert essai.kurtosis == 8.0
        assert essai.n_returns == 2500

    def test_describe_resume_l_etat(self, registre):
        registre.archiver(rapport())
        resume = registre.describe()
        assert resume["n_lignes"] == 1
        assert resume["n_trials"] == 1
        assert resume["n_divergences"] == 0
        assert resume["n_doublons"] == 0


class TestLeRegistreDuDepot:
    """Le vrai, celui qui est versionne."""

    def test_il_existe_et_se_lit(self):
        from rsl.essais import registre_par_defaut

        essais = registre_par_defaut().essais()
        assert essais, "le registre du depot est vide : les essais faits sont perdus"

    def test_chaque_essai_pointe_vers_un_rapport_qui_existe(self):
        """Une ligne sans rapport serait un chiffre inverifiable - exactement
        ce que l'archivage doit empecher."""
        from rsl.essais import registre_par_defaut

        registre = registre_par_defaut()
        for essai in registre.essais():
            assert essai.rapport is not None, essai.label
            assert (registre.racine / essai.rapport).exists(), essai.rapport

    def test_aucune_divergence_non_expliquee(self):
        """Une divergence est legitime apres un changement de moteur, mais elle
        doit etre VUE. Ce test la fait remonter plutot que de la laisser dormir
        dans un fichier que personne n'ouvre."""
        from rsl.essais import registre_par_defaut

        divergences = registre_par_defaut().divergences()
        assert not divergences, (
            f"{len(divergences)} specification(s) rendent plusieurs resultats : "
            f"{sorted(k[:12] for k in divergences)}. Le moteur a change ; les "
            f"chiffres d'avant et d'apres ne se comparent pas."
        )


class TestUnWalkForwardEstUnSeulEssai:
    """La decision que `rsl walkforward --archive` encode.

    Un essai est une CONFIGURATION differente sur les memes donnees ; un pli
    est la MEME configuration sur d'autres donnees. Verser neuf plis au
    compteur du Deflated Sharpe le rendrait pessimiste pour une raison qui n'a
    rien a voir avec la selection - c'est la regle que `walkforward.py` posait
    deja en commentaire depuis sa premiere version.
    """

    def rapport(self, tmp_path: Path):
        from datetime import UTC, datetime, timedelta

        from fixtures import synthetic
        from rsl.config import BacktestSpec
        from rsl.data.schema import Granularity
        from rsl.metrics.statistics import RollingWalkForward
        from rsl.walkforward import run_walk_forward

        jour = Granularity(timedelta(days=1), name="1d")
        chemin = tmp_path / "ES_v0_1m.parquet"
        synthetic.make_frame(
            synthetic.sine(900, 2000.0, 200.0, 90),
            granularity=jour,
            start=datetime(2016, 1, 4, tzinfo=UTC),
        ).write_parquet(chemin)
        spec = BacktestSpec.model_validate({
            "name": "wf", "initial_cash": 500_000.0,
            "data": [{"root": "ES", "path": str(chemin)}],
            "execution": {"fees": {"kind": "zero"}, "slippage": {"kind": "zero"}},
            "risk": {"sizing": {"kind": "fixed", "contracts": 1}},
            "strategy": {
                "ref": "sma_crossover@1",
                "params": {"symbol": "ES.v.0", "fast_window": 5, "slow_window": 20},
            },
        })
        return run_walk_forward(
            spec, RollingWalkForward(train_bars=300, test_bars=150)
        )

    def test_plusieurs_plis_font_un_seul_essai(self, registre, tmp_path):
        from rsl.cli import _essai_de_walkforward

        rapport = self.rapport(tmp_path)
        assert rapport.n_folds > 2, "il faut plusieurs plis pour que le test morde"
        registre.archiver(_essai_de_walkforward(rapport))
        assert registre.journal().n_trials == 1

    def test_le_sharpe_enregistre_est_celui_de_la_serie_groupee(
        self, registre, tmp_path
    ):
        """Et non la moyenne des Sharpe par pli, ou un pli court peserait
        autant qu'un pli long."""
        from rsl.cli import _essai_de_walkforward

        rapport = self.rapport(tmp_path)
        essai = registre.archiver(_essai_de_walkforward(rapport))
        assert essai.sharpe_per_period == rapport.pooled_sharpe_per_period

    def test_le_nom_dit_que_c_est_un_walk_forward(self, registre, tmp_path):
        """Le registre melange des runs simples et des walk-forwards : lire
        « 0,04 » sans savoir lequel serait trompeur."""
        from rsl.cli import _essai_de_walkforward

        essai = registre.archiver(_essai_de_walkforward(self.rapport(tmp_path)))
        assert "walk-forward" in essai.label

    def test_l_empreinte_couvre_tous_les_plis(self, registre, tmp_path):
        """Deux walk-forwards qui produisent les memes plis dans le meme ordre
        sont le meme resultat ; un pli qui change doit changer l'empreinte."""
        from rsl.cli import _essai_de_walkforward
        from rsl.manifest import canonical_hash

        rapport = self.rapport(tmp_path)
        charge = _essai_de_walkforward(rapport)
        attendu = canonical_hash([f.fingerprint for f in rapport.folds])
        assert charge["result_fingerprint"] == attendu
        assert attendu != canonical_hash([f.fingerprint for f in rapport.folds[:-1]])

    def test_le_rapport_complet_des_plis_est_conserve(self, registre, tmp_path):
        """Le detail par pli est ce qui distingue une performance repartie
        d'une performance concentree. Le perdre laisserait un Sharpe sans son
        avertissement."""
        from rsl.cli import _essai_de_walkforward

        essai = registre.archiver(_essai_de_walkforward(self.rapport(tmp_path)))
        assert essai.rapport is not None
        archive = json.loads(
            (registre.racine / essai.rapport).read_text(encoding="utf-8")
        )
        assert archive["walkforward"]["folds"]


class TestArchiverUnBalayage:
    """Une grille de centaines de configurations est des centaines d'essais.

    Le compteur du Deflated Sharpe en a besoin - sous-compter gonfle le DSR de
    tous les autres. Mais ecrire un rapport complet par configuration ajouterait
    des centaines de fichiers au depot pour une information que le fichier de
    grille contient deja.
    """

    ARTEFACT = "grilles/abc123.json"

    def test_les_lignes_pointent_vers_l_artefact_partage(self, registre):
        for i in range(3):
            registre.archiver(
                rapport(config=f"{i}" * 64, empreinte=f"{i}e" * 32),
                artefact=self.ARTEFACT,
            )
        assert {e.rapport for e in registre.essais()} == {self.ARTEFACT}

    def test_et_aucun_rapport_individuel_n_est_ecrit(self):
        """C'est tout l'interet : trois cents essais, un fichier."""
        import tempfile
        from pathlib import Path

        from rsl.essais import Registre

        with tempfile.TemporaryDirectory() as dossier:
            reg = Registre(racine=Path(dossier) / "essais")
            reg.archiver(rapport(), artefact=self.ARTEFACT)
            assert not reg.rapports.exists()

    def test_mais_ils_comptent_tous_au_compteur(self, registre):
        for i in range(5):
            registre.archiver(
                rapport(config=f"{i}" * 64, empreinte=f"{i}e" * 32, sharpe=0.01 * i),
                artefact=self.ARTEFACT,
            )
        assert registre.journal().n_trials == 5

    def test_un_essai_de_balayage_deja_connu_reste_refuse(self, registre):
        """Relancer une grille est une VERIFICATION : elle ne doit pas monter
        le compteur une seconde fois."""
        registre.archiver(rapport(), artefact=self.ARTEFACT)
        with pytest.raises(EssaiDejaArchiveError):
            registre.archiver(rapport(), artefact=self.ARTEFACT)

    def test_sans_artefact_le_rapport_individuel_revient(self, registre):
        """Le defaut n'a pas change : un essai qu'on publie garde son rapport
        complet, seul un balayage y renonce."""
        essai = registre.archiver(rapport())
        assert essai.rapport is not None
        assert essai.rapport.startswith("rapports/")
