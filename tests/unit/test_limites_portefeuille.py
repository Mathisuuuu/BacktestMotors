"""Les plafonds de portefeuille : ce qu'ils bornent, et ce qu'ils ne piegent pas.

Deux familles de tests, et la seconde compte plus que la premiere.

1. **Le plafond mord.** Un ordre qui ferait franchir la limite est refuse, avec
   le bon motif. C'est ce qu'on attend, et c'est le facile.
2. **Le plafond ne piege jamais.** Un ordre qui REDUIT la mesure plafonnee
   passe, meme quand le portefeuille est deja au-dessus. Sans cette regle, une
   baisse d'equity - qui franchit le plafond sans qu'aucun ordre soit passe -
   enfermerait le portefeuille dans un etat dont il ne pourrait plus sortir :
   le plafond ne serait plus une contrainte mais une panne.

Les chiffres sont choisis pour etre verifiables de tete : multiplicateur 50,
marque 100, donc 5 000 le contrat ; equity 10 000, donc un contrat = 0,5.
"""

from __future__ import annotations

import pytest

from rsl.data.schema import AssetClass, InstrumentSpec
from rsl.engine.limites import (
    AUCUN,
    MOTIFS,
    SANS_CLASSE,
    Expositions,
    PortfolioLimits,
    classe_de,
    mesurer,
    notionnel,
    projeter,
)
from rsl.errors import ConfigurationError

EQUITY = 10_000.0
MARQUE = 100.0
MULTIPLICATEUR = 50.0
CONTRAT = MARQUE * MULTIPLICATEUR  # 5 000, soit 0,5 d'equity


def instrument(symbole: str, classe: AssetClass | None = AssetClass.INDICES) -> InstrumentSpec:
    return InstrumentSpec(
        symbol=symbole, root=symbole.split(".")[0], name=symbole,
        exchange="CME", currency="USD",
        multiplier=MULTIPLICATEUR, tick_size=0.25,
        commission_per_contract=0.0, exchange_fee_per_contract=0.0,
        initial_margin=500.0, maintenance_margin=400.0,
        category=classe,
    )


def univers(*symboles: str) -> dict[str, InstrumentSpec]:
    return {s: instrument(s) for s in symboles}


def marques(*symboles: str) -> dict[str, float]:
    return dict.fromkeys(symboles, MARQUE)


class TestMesure:
    """Ce qu'une photographie de portefeuille dit, et dans quelle unite."""

    def test_un_contrat_vaut_multiplicateur_fois_marque(self):
        assert notionnel(instrument("A"), 1, MARQUE) == CONTRAT

    def test_le_notionnel_est_signe(self):
        """Le signe est ce qui distingue le net du brut ; le perdre les
        confondrait."""
        assert notionnel(instrument("A"), -3, MARQUE) == -3 * CONTRAT

    def test_le_brut_additionne_les_valeurs_absolues(self):
        vue = mesurer({"A": 2, "B": -2}, univers("A", "B"), marques("A", "B"))
        assert vue.gross == 4 * CONTRAT

    def test_le_net_se_compense(self):
        """Long 2 / court 2 : aucune exposition directionnelle, tout le risque
        de base. C'est precisement le cas qu'un plafond brut seul manquerait."""
        vue = mesurer({"A": 2, "B": -2}, univers("A", "B"), marques("A", "B"))
        assert vue.net == 0.0

    def test_une_position_plate_n_est_pas_une_position(self):
        """Le portefeuille cree une `Position` pour CHAQUE instrument declare,
        des le depart. Les compter toutes ferait depasser `max_positions` avant
        le premier ordre."""
        vue = mesurer({"A": 0, "B": 3}, univers("A", "B"), marques("A", "B"))
        assert vue.n_positions == 1

    def test_les_classes_sont_comptees_separement(self):
        specs = {
            "A": instrument("A", AssetClass.INDICES),
            "B": instrument("B", AssetClass.INDICES),
            "C": instrument("C", AssetClass.ENERGIE),
        }
        vue = mesurer({"A": 1, "B": 1, "C": 1}, specs, marques("A", "B", "C"))
        assert vue.par_categorie == {"indices": 2, "energie": 1}

    def test_un_instrument_sans_classe_est_compte_a_part_jamais_exempte(self):
        """Omettre un champ facultatif ne doit pas contourner un plafond."""
        specs = {"A": instrument("A", None), "B": instrument("B", None)}
        vue = mesurer({"A": 1, "B": 1}, specs, marques("A", "B"))
        assert vue.par_categorie == {SANS_CLASSE: 2}

    def test_classe_de_lit_la_classe_declaree(self):
        assert classe_de(instrument("A", AssetClass.METAUX)) == "metaux"
        assert classe_de(instrument("A", None)) == SANS_CLASSE


class TestUnInstrumentSansMarque:
    """« Detenu » et « valorisable » ne sont pas la meme chose."""

    def test_il_compte_dans_les_positions(self):
        vue = mesurer({"A": 1, "B": 1}, univers("A", "B"), marques("A"))
        assert vue.n_positions == 2

    def test_mais_pas_dans_le_notionnel(self):
        """Lui inventer une valeur serait la seule facon de se tromper en
        silence : le brut serait faux sans qu'aucun compteur ne le dise."""
        vue = mesurer({"A": 1, "B": 1}, univers("A", "B"), marques("A"))
        assert vue.gross == CONTRAT


class TestRapporteesALEquity:
    def test_un_contrat_vaut_un_demi_d_equity(self):
        vue = mesurer({"A": 1}, univers("A"), marques("A"))
        assert vue.rapportees(EQUITY) == (0.5, 0.5)

    def test_le_net_est_rendu_en_valeur_absolue(self):
        """Un plafond compare a un nombre positif : un net de -2 doit mordre
        comme un net de +2, sans quoi seuls les longs seraient bornes."""
        vue = mesurer({"A": -2}, univers("A"), marques("A"))
        assert vue.rapportees(EQUITY) == (1.0, 1.0)

    @pytest.mark.parametrize("equity", [0.0, -1.0, -50_000.0])
    def test_une_equity_nulle_ou_negative_rend_l_infini(self, equity):
        """Plutot que de lever, ou pire, de diviser par zero.

        Ce que `inf` fait ENSUITE surprend, et c'est teste plus bas : combine
        a la non-aggravation, il rend les plafonds inertes sous zero."""
        vue = mesurer({"A": 1}, univers("A"), marques("A"))
        assert vue.rapportees(equity) == (float("inf"), float("inf"))


class TestProjection:
    """Le plafond porte sur le portefeuille d'APRES."""

    def test_un_achat_ajoute(self):
        assert projeter({"A": 2}, "A", 3) == {"A": 5}

    def test_une_vente_retranche(self):
        assert projeter({"A": 2}, "A", -3) == {"A": -1}

    def test_un_symbole_absent_part_de_zero(self):
        assert projeter({"A": 2}, "B", 1) == {"A": 2, "B": 1}

    def test_l_original_n_est_pas_modifie(self):
        """Le `RiskManager` mesure AVANT et APRES sur le meme dictionnaire :
        une mutation en place ferait coincider les deux, et la regle de
        non-aggravation laisserait tout passer."""
        avant = {"A": 2}
        projeter(avant, "A", 3)
        assert avant == {"A": 2}


class TestDeclaration:
    @pytest.mark.parametrize("champ", ["max_gross_exposure", "max_net_exposure"])
    @pytest.mark.parametrize("valeur", [0.0, -1.0])
    def test_un_plafond_d_exposition_nul_ou_negatif_est_refuse(self, champ, valeur):
        with pytest.raises(ConfigurationError, match=champ):
            PortfolioLimits(**{champ: valeur})

    @pytest.mark.parametrize("champ", ["max_positions", "max_per_category"])
    def test_un_plafond_de_comptage_sous_un_est_refuse(self, champ):
        with pytest.raises(ConfigurationError, match=champ):
            PortfolioLimits(**{champ: 0})

    def test_sans_plafond_declare_rien_n_est_verifie(self):
        """Le defaut doit etre inerte : sinon toute specification anterieure
        changerait de resultat sans que personne ne l'ait demande."""
        assert PortfolioLimits().actives is False

    @pytest.mark.parametrize(
        ("champ", "valeur"),
        [
            ("max_gross_exposure", 2.0),
            ("max_net_exposure", 1.0),
            ("max_positions", 3),
            ("max_per_category", 1),
        ],
    )
    def test_un_seul_plafond_suffit_a_activer_le_controle(self, champ, valeur):
        assert PortfolioLimits(**{champ: valeur}).actives is True

    def test_describe_publie_les_quatre_champs(self):
        """Le manifeste doit porter la contrainte : un run refuse des ordres
        pour une raison qui doit rester lisible des annees plus tard."""
        assert set(PortfolioLimits().describe()) == {
            "max_gross_exposure",
            "max_net_exposure",
            "max_positions",
            "max_per_category",
        }


def vue(quantites: dict[str, int], specs: dict[str, InstrumentSpec] | None = None) -> Expositions:
    specs = specs if specs is not None else univers(*quantites)
    return mesurer(quantites, specs, marques(*quantites))


class TestLePlafondMord:
    """Un ordre qui ferait franchir la limite est refuse, avec son motif."""

    def test_le_brut_refuse_au_dela(self):
        limites = PortfolioLimits(max_gross_exposure=1.0)  # 2 contrats
        motif = limites.refus(vue({"A": 2}), vue({"A": 3}), EQUITY, "indices")
        assert motif == "gross_exposure"

    def test_le_brut_laisse_passer_l_egalite(self):
        """`>` et non `>=` : un plafond de 1,0 autorise exactement 1,0. Un
        plafond qui refuse sa propre valeur est un plafond mal nomme."""
        limites = PortfolioLimits(max_gross_exposure=1.0)
        assert limites.refus(vue({"A": 1}), vue({"A": 2}), EQUITY, "indices") == AUCUN

    def test_le_net_ignore_ce_que_le_brut_voit(self):
        """Long 2 / court 2 : brut 2,0, net 0,0. Un plafond net de 0,5 laisse
        passer ce qu'un plafond brut de 0,5 refuserait - et c'est le but."""
        specs = univers("A", "B")
        limites = PortfolioLimits(max_net_exposure=0.5)
        motif = limites.refus(
            vue({"A": 2, "B": -1}, specs), vue({"A": 2, "B": -2}, specs),
            EQUITY, "indices",
        )
        assert motif == AUCUN

    def test_et_le_brut_voit_ce_que_le_net_ignore(self):
        specs = univers("A", "B")
        limites = PortfolioLimits(max_gross_exposure=1.5)
        motif = limites.refus(
            vue({"A": 2, "B": -1}, specs), vue({"A": 2, "B": -2}, specs),
            EQUITY, "indices",
        )
        assert motif == "gross_exposure"

    def test_un_net_vendeur_mord_comme_un_net_acheteur(self):
        limites = PortfolioLimits(max_net_exposure=1.0)
        motif = limites.refus(vue({"A": -2}), vue({"A": -3}), EQUITY, "indices")
        assert motif == "net_exposure"

    def test_le_nombre_de_positions_refuse_le_troisieme_instrument(self):
        specs = univers("A", "B", "C")
        limites = PortfolioLimits(max_positions=2)
        motif = limites.refus(
            vue({"A": 1, "B": 1}, specs), vue({"A": 1, "B": 1, "C": 1}, specs),
            EQUITY, "indices",
        )
        assert motif == "positions"

    def test_renforcer_une_position_existante_n_en_cree_pas_une_nouvelle(self):
        specs = univers("A", "B")
        limites = PortfolioLimits(max_positions=2)
        motif = limites.refus(
            vue({"A": 1, "B": 1}, specs), vue({"A": 5, "B": 1}, specs),
            EQUITY, "indices",
        )
        assert motif == AUCUN

    def test_la_classe_d_actif_refuse_le_second_de_sa_famille(self):
        specs = {
            "A": instrument("A", AssetClass.INDICES),
            "B": instrument("B", AssetClass.INDICES),
        }
        limites = PortfolioLimits(max_per_category=1)
        motif = limites.refus(
            vue({"A": 1}, specs), vue({"A": 1, "B": 1}, specs), EQUITY, "indices"
        )
        assert motif == "per_category"

    def test_une_autre_classe_passe(self):
        """C'est tout l'interet du plafond par classe : il borne la
        concentration, pas le nombre total."""
        specs = {
            "A": instrument("A", AssetClass.INDICES),
            "C": instrument("C", AssetClass.ENERGIE),
        }
        limites = PortfolioLimits(max_per_category=1)
        motif = limites.refus(
            vue({"A": 1}, specs), vue({"A": 1, "C": 1}, specs), EQUITY, "energie"
        )
        assert motif == AUCUN

    def test_le_motif_rendu_est_un_motif_connu(self):
        """Le compteur du rapport est indexe dessus : un motif hors liste
        creerait un compteur fantome."""
        limites = PortfolioLimits(max_gross_exposure=0.1)
        motif = limites.refus(vue({"A": 1}), vue({"A": 2}), EQUITY, "indices")
        assert motif in MOTIFS


class TestLePlafondNePiegeJamais:
    """La propriete de surete : on peut toujours revenir vers la conformite.

    Le cas concret : l'equity tombe de 10 000 a 2 000 sans qu'aucun ordre soit
    passe. Une position de 2 contrats passe de 1,0 a 5,0 d'exposition brute,
    au-dessus d'un plafond de 2,0. Si le controle regardait le NIVEAU, plus
    aucun ordre ne passerait - y compris celui qui reduit la position.
    """

    RUINE = 2_000.0

    def test_reduire_passe_meme_au_dessus_du_plafond(self):
        limites = PortfolioLimits(max_gross_exposure=2.0)
        motif = limites.refus(vue({"A": 2}), vue({"A": 1}), self.RUINE, "indices")
        assert motif == AUCUN, "un plafond qui empeche de se reduire est une panne"

    def test_aggraver_reste_refuse(self):
        """La contrepartie : au-dessus du plafond, on ne peut qu'aller vers
        lui, jamais s'en eloigner."""
        limites = PortfolioLimits(max_gross_exposure=2.0)
        motif = limites.refus(vue({"A": 2}), vue({"A": 3}), self.RUINE, "indices")
        assert motif == "gross_exposure"

    def test_retourner_une_position_en_la_reduisant_passe(self):
        """Long 3 -> court 1 : le brut baisse de 1,5 a 0,5. Le sens change,
        l'exposition diminue, l'ordre doit passer."""
        limites = PortfolioLimits(max_gross_exposure=1.0)
        motif = limites.refus(vue({"A": 3}), vue({"A": -1}), EQUITY, "indices")
        assert motif == AUCUN

    def test_mais_retourner_en_aggravant_est_refuse(self):
        """Long 2 -> court 3 : le brut monte de 1,0 a 1,5. Le sens change
        aussi, mais l'exposition augmente."""
        limites = PortfolioLimits(max_gross_exposure=1.0)
        motif = limites.refus(vue({"A": 2}), vue({"A": -3}), EQUITY, "indices")
        assert motif == "gross_exposure"

    def test_fermer_une_position_de_trop_passe(self):
        """`max_positions` deja depasse - par exemple parce qu'il a ete
        resserre entre deux runs : fermer doit rester possible."""
        specs = univers("A", "B", "C")
        limites = PortfolioLimits(max_positions=1)
        motif = limites.refus(
            vue({"A": 1, "B": 1, "C": 1}, specs), vue({"A": 1, "B": 1}, specs),
            EQUITY, "indices",
        )
        assert motif == AUCUN

    def test_une_equity_effondree_ne_bloque_pas_la_liquidation(self):
        """Equity nulle : toutes les mesures valent l'infini. `inf > inf` est
        faux, donc la non-aggravation laisse passer - c'est exactement ce
        qu'il faut, sans quoi un compte ruine ne pourrait pas se solder."""
        limites = PortfolioLimits(max_gross_exposure=1.0)
        motif = limites.refus(vue({"A": 2}), vue({"A": 1}), 0.0, "indices")
        assert motif == AUCUN

    def test_sous_zero_les_plafonds_sont_inertes_dans_les_deux_sens(self):
        """La contrepartie, notee parce qu'elle surprend : `inf > inf` etant
        faux, un ordre qui AUGMENTE l'exposition passe lui aussi sous zero.

        Ce n'est pas un trou laisse ouvert - sous la politique `reject`, la
        marge refuse deja tout ordre qui ajoute du risque quand l'equity ne
        couvre plus rien. Le test l'ecrit pour que le comportement soit
        constate plutot que suppose."""
        limites = PortfolioLimits(max_gross_exposure=1.0)
        motif = limites.refus(vue({"A": 1}), vue({"A": 9}), 0.0, "indices")
        assert motif == AUCUN

    def test_ne_rien_changer_passe(self):
        """Un ordre de quantite nulle ne peut rien aggraver."""
        limites = PortfolioLimits(max_gross_exposure=0.1, max_positions=1)
        photo = vue({"A": 5})
        assert limites.refus(photo, photo, EQUITY, "indices") == AUCUN


class TestCeQuiEntreDansLeConfigHash:
    """Un plafond non declare n'est pas une instruction.

    Le `config_hash` repond a « ces deux runs ont-ils recu les memes
    instructions ». Ajouter un champ facultatif a la specification lui donne
    une valeur par defaut dans `model_dump`, donc un hachage different - et
    rend d'un coup incomparable tout run archive avant l'existence du champ.

    Mesure le 2026-09-12 : sans le retrait, les SEPT exemples changeaient de
    `config_hash` sans qu'aucune decision de strategie n'ait bouge. C'est la
    meme regle que pour `note`, et la meme raison.
    """

    def base(self) -> dict[str, object]:
        return {
            "name": "plafonds",
            "initial_cash": 100_000.0,
            "data": [{"root": "ES", "path": "indices/ES_v0_1m.parquet"}],
            "execution": {
                "fees": {"kind": "zero"},
                "slippage": {"kind": "zero"},
            },
            "strategy": {"ref": "sma_crossover@1", "params": {}},
        }

    def hash_de(self, **risque: object) -> str:
        from rsl.config import BacktestSpec
        from rsl.manifest import canonical_hash

        charge = self.base()
        if risque:
            charge["risk"] = risque
        return canonical_hash(BacktestSpec.model_validate(charge).canonical())

    def test_omettre_limits_et_le_declarer_vide_donnent_le_meme_hash(self):
        assert self.hash_de() == self.hash_de(limits={})

    def test_declarer_un_plafond_nul_explicitement_ne_change_rien_non_plus(self):
        """Ecrire `"max_positions": null` dit exactement ce que dit l'absence
        du champ. Deux facons de ne rien demander ne sont pas deux runs."""
        assert self.hash_de() == self.hash_de(
            limits={"max_positions": None, "max_gross_exposure": None}
        )

    def test_mais_un_plafond_reel_change_le_hash(self):
        """La contrepartie, et c'est elle qui rend le retrait sur : un plafond
        declare est une instruction, il doit etre hache. Sans quoi deux runs
        aux contraintes differentes se confondraient."""
        assert self.hash_de() != self.hash_de(limits={"max_positions": 3})

    def test_deux_plafonds_differents_donnent_deux_hash_differents(self):
        assert self.hash_de(limits={"max_positions": 3}) != self.hash_de(
            limits={"max_positions": 4}
        )

    def test_le_bloc_limits_disparait_de_la_forme_canonique_quand_il_est_muet(self):
        from rsl.config import BacktestSpec

        canonique = BacktestSpec.model_validate(self.base()).canonical()
        risque = canonique["risk"]
        assert isinstance(risque, dict)
        assert "limits" not in risque

    def test_et_y_figure_des_qu_un_plafond_est_declare(self):
        from rsl.config import BacktestSpec

        charge = self.base()
        charge["risk"] = {"limits": {"max_gross_exposure": 2.0}}
        risque = BacktestSpec.model_validate(charge).canonical()["risk"]
        assert isinstance(risque, dict)
        assert risque["limits"]["max_gross_exposure"] == 2.0


class TestLeRapportLisibleDitCeQuIlAEmpeche:
    """Un plafond qui refuse en silence rend le rapport trompeur.

    Le rapport lisible est ce qu'un humain lit en premier. S'il montre « 46
    trades » sans dire que 283 ordres ont ete refuses, il decrit la strategie
    comme si elle avait choisi de ne pas trader.
    """

    def rapport(self, **limites: object):
        from rsl.config import BacktestSpec
        from rsl.report import BacktestReport

        base = TestCeQuiEntreDansLeConfigHash().base()
        if limites:
            base["risk"] = {"limits": limites}
        spec = BacktestSpec.model_validate(base)
        return BacktestReport(
            spec=spec,
            manifest=None,  # type: ignore[arg-type]
            metrics=None,  # type: ignore[arg-type]
            run={"risk_stats": {f"n_rejected_{m}": 0 for m in MOTIFS} | {
                "n_rejected_positions": 7
            }},
            result_fingerprint="",
            deflated_sharpe=None,
            symbols=("ES.v.0",),
            cross_sectional=False,
        )

    def test_sans_plafond_declare_aucune_ligne_n_est_ajoutee(self):
        """Le rendu de toute specification anterieure doit rester identique au
        caractere pres."""
        assert self.rapport()._lignes_de_plafonds() == []

    def test_les_plafonds_declares_sont_montres(self):
        lignes = self.rapport(max_positions=3)._lignes_de_plafonds()
        assert "max_positions 3" in lignes[0]

    def test_les_refus_sont_nommes_et_chiffres(self):
        lignes = self.rapport(max_positions=3)._lignes_de_plafonds()
        assert "positions 7" in lignes[1]

    def test_zero_refus_se_dit_plutot_que_de_disparaitre(self):
        """« Aucun » est une information - le plafond etait peut-etre trop
        large pour mordre. Une ligne absente ne se distingue pas d'une
        fonctionnalite oubliee."""
        rapport = self.rapport(max_net_exposure=99.0)
        rapport.run["risk_stats"] = dict.fromkeys(
            (f"n_rejected_{m}" for m in MOTIFS), 0
        )
        assert rapport._lignes_de_plafonds()[1].endswith("aucun")
