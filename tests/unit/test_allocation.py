"""Allocation : comment le budget se repartit entre les noms retenus.

Le test qui porte le fichier est `TestUnContratChacunNEstPasNeutre` : il montre
en chiffres pourquoi le defaut historique n'est pas une absence de decision.
Deux contrats de tailles differentes recoivent le meme NOMBRE, donc des
montants differents - ici dans un rapport de cinq - et le portefeuille est domine
par l'instrument dont le contrat est gros, pour une raison qui n'a rien a voir
avec la strategie.

Le reste verifie que les trois regles en argent normalisent vraiment, que la
troncature est comptee plutot que silencieuse, et qu'un nom dont le poids
n'est pas calculable est ECARTE et non dote d'un poids par defaut.

Montage : une equity de 1 000 000, deux instruments cotant 100, l'un de
multiplicateur 50 (contrat a 5 000), l'autre de multiplicateur 10 (contrat a
1 000). Tout se verifie de tete.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fixtures import synthetic
from rsl.data.feed import MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import AccountState, Granularity, Panel
from rsl.errors import ConfigurationError
from rsl.strategies.allocation import (
    Allocateur,
    AllocationRule,
    AllocationStats,
    ContratsFixes,
    PoidsEgaux,
    PoidsParSignal,
    VolatiliteInverse,
)
from rsl.strategies.signals import build_signal, prim

DAY = Granularity(timedelta(days=1), name="1d")
EPOCH = datetime(2016, 1, 4, tzinfo=UTC)
EQUITY = 1_000_000.0

MULTIPLICATEURS = {"GROS": 50.0, "PETIT": 10.0}
"""Contrat a 5 000 contre contrat a 1 000, au prix de 100. Rapport de cinq."""


def panel_plat(n: int = 120) -> Panel:
    """Deux series CONSTANTES a 100.

    Constantes et non bruitees : une allocation en argent se verifie de tete
    seulement si le prix est connu. La volatilite y est nulle, ce qui est
    exactement le cas limite que `VolatiliteInverse` doit refuser plutot que
    de rendre un poids infini."""
    return build_panel(
        {
            nom: synthetic.make_store(
                synthetic.ramp(n, 100.0, 0.0), symbol=nom, granularity=DAY, start=EPOCH
            )
            for nom in MULTIPLICATEURS
        }
    )


def panel_bruite(n: int = 120) -> Panel:
    """Deux marches aleatoires de volatilites nettement differentes."""
    return build_panel(
        {
            "GROS": synthetic.make_store(
                synthetic.random_walk(n, 100.0, sigma=4.0, seed=11),
                symbol="GROS", granularity=DAY, start=EPOCH,
            ),
            "PETIT": synthetic.make_store(
                synthetic.random_walk(n, 100.0, sigma=1.0, seed=12),
                symbol="PETIT", granularity=DAY, start=EPOCH,
            ),
        }
    )


def coupe(panel: Panel, row: int = 100, equity: float = EQUITY) -> MultiContext:
    """Une coupe transversale prete a allouer : multiplicateurs et compte.

    Reproduit ce que fait le runner, et rien de plus : sans ces deux
    declarations, `contract_value` et `account_value` levent - ce qui est le
    comportement voulu hors run."""
    ctx = MultiContext(panel)
    ctx._seek_row(row)
    ctx._set_multipliers(MULTIPLICATEURS)
    ctx._set_account(
        AccountState(
            equity=equity, cash=equity, peak_equity=equity, initial_equity=EQUITY
        )
    )
    return ctx


def alloue(regle: AllocationRule, panel: Panel | None = None, **kw: object):
    """Applique une regle aux deux noms et rend `(contrats, compteurs)`."""
    stats = AllocationStats()
    ctx = coupe(panel if panel is not None else panel_plat(), **kw)  # type: ignore[arg-type]
    return regle.contrats(["GROS", "PETIT"], ctx, stats), stats


class TestUnContratChacunNEstPasNeutre:
    """Le defaut historique EST une repartition. Le montrer en chiffres.

    C'est la raison d'etre du module : tant que « un contrat chacun » passait
    pour une absence de choix, il n'y avait rien a discuter.
    """

    def test_il_donne_le_meme_nombre_aux_deux(self):
        contrats, _ = alloue(ContratsFixes(1))
        assert contrats == {"GROS": 1, "PETIT": 1}

    def test_donc_cinq_fois_plus_d_argent_sur_le_gros_contrat(self):
        """Le point entier. Un rapport de un en nombre est un rapport de cinq
        en argent, et c'est le gros contrat qui decidera du resultat."""
        ctx = coupe(panel_plat())
        contrats, _ = alloue(ContratsFixes(1))
        argent = {s: n * ctx.contract_value(s) for s, n in contrats.items()}
        assert argent == {"GROS": 5_000.0, "PETIT": 1_000.0}

    def test_tandis_que_les_poids_egaux_egalisent_l_argent(self):
        """Meme montage, meme coupe : c'est la regle qui change le resultat."""
        ctx = coupe(panel_plat())
        contrats, _ = alloue(PoidsEgaux(gross_target=1.0))
        argent = {s: n * ctx.contract_value(s) for s, n in contrats.items()}
        assert argent == {"GROS": 500_000.0, "PETIT": 500_000.0}


class TestPoidsEgaux:
    """Meme argent par nom, et la cible brute atteinte quel que soit N."""

    def test_le_budget_se_partage_en_deux(self):
        """1 000 000 x 1,0 / 2 = 500 000 par nom. Contrat a 5 000 -> 100 ;
        contrat a 1 000 -> 500."""
        contrats, _ = alloue(PoidsEgaux(gross_target=1.0))
        assert contrats == {"GROS": 100, "PETIT": 500}

    def test_la_cible_brute_est_respectee(self):
        ctx = coupe(panel_plat())
        contrats, _ = alloue(PoidsEgaux(gross_target=0.5))
        brut = sum(n * ctx.contract_value(s) for s, n in contrats.items())
        assert brut == pytest.approx(EQUITY * 0.5)

    def test_elle_ne_depend_pas_du_nombre_de_noms(self):
        """La difference avec `equity_fraction` de la couche risque : celle-ci
        cible une fraction PAR INSTRUMENT et deploie donc N fois sa valeur.
        Ici la somme des poids vaut un, quel que soit N."""
        stats = AllocationStats()
        ctx = coupe(panel_plat())
        un = PoidsEgaux(gross_target=1.0).contrats(["GROS"], ctx, stats)
        deux = PoidsEgaux(gross_target=1.0).contrats(["GROS", "PETIT"], ctx, stats)
        brut_un = sum(n * ctx.contract_value(s) for s, n in un.items())
        brut_deux = sum(n * ctx.contract_value(s) for s, n in deux.items())
        assert brut_un == pytest.approx(brut_deux)

    def test_une_selection_vide_ne_donne_rien(self):
        assert PoidsEgaux().contrats([], coupe(panel_plat()), AllocationStats()) == {}

    @pytest.mark.parametrize("cible", [0.0, -1.0, float("inf")])
    def test_une_cible_brute_invalide_est_refusee(self, cible):
        with pytest.raises(ConfigurationError, match="gross_target"):
            PoidsEgaux(gross_target=cible)


class TestLaTroncatureEstCompteeJamaisSilencieuse:
    """La premiere cause de « la strategie ne trade pas ».

    Meme convention que partout ailleurs dans le socle : on tronque vers zero,
    et un nom qui tombe a zero est compte plutot que de disparaitre.
    """

    def test_un_budget_trop_petit_ecarte_le_gros_contrat(self):
        """Equity 6 000, deux noms : 3 000 par nom. Un contrat GROS en vaut
        5 000, donc zero. PETIT en vaut 1 000, donc trois."""
        contrats, stats = alloue(PoidsEgaux(gross_target=1.0), equity=6_000.0)
        assert contrats == {"PETIT": 3}
        assert stats.n_noms_tronques == 1

    def test_un_budget_minuscule_n_ouvre_rien(self):
        contrats, stats = alloue(PoidsEgaux(gross_target=1.0), equity=100.0)
        assert contrats == {}
        assert stats.n_noms_tronques == 2

    def test_une_equity_nulle_ou_negative_n_ouvre_rien(self):
        """Et sans lever : un compte ruine n'est pas une erreur de
        configuration, c'est un etat du run."""
        for equity in (0.0, -5_000.0):
            contrats, _ = alloue(PoidsEgaux(), equity=equity)
            assert contrats == {}

    def test_un_rebalancement_entierement_vide_est_compte(self):
        """Compte par l'`Allocateur`, qui est le seul a savoir qu'une selection
        non vide a rendu zero nom."""
        allocateur = Allocateur(PoidsEgaux(gross_target=1.0))
        allocateur.contrats(["GROS", "PETIT"], coupe(panel_plat(), equity=100.0))
        assert allocateur.stats.n_rebalances_vides == 1

    def test_un_rebalancement_servi_n_est_pas_compte_comme_vide(self):
        allocateur = Allocateur(PoidsEgaux(gross_target=1.0))
        allocateur.contrats(["GROS", "PETIT"], coupe(panel_plat()))
        assert allocateur.stats.n_rebalances_vides == 0


class TestVolatiliteInverse:
    def test_le_nom_le_moins_volatil_recoit_plus_d_argent(self):
        """La propriete qui definit la regle. Verifiee en ARGENT et non en
        contrats : en contrats, la taille du contrat brouillerait le signe."""
        panel = panel_bruite()
        ctx = coupe(panel)
        contrats, _ = alloue(VolatiliteInverse(window=20), panel=panel)
        argent = {s: n * ctx.contract_value(s) for s, n in contrats.items()}
        assert argent["PETIT"] > argent["GROS"], argent

    def test_la_cible_brute_reste_approchee(self):
        """« Approchee » et non « atteinte » : la troncature en contrats
        entiers laisse toujours un reste. Tolerance d'un contrat GROS."""
        panel = panel_bruite()
        ctx = coupe(panel)
        contrats, _ = alloue(VolatiliteInverse(window=20), panel=panel)
        brut = sum(n * ctx.contract_value(s) for s, n in contrats.items())
        assert abs(brut - EQUITY) <= ctx.contract_value("GROS")

    def test_une_volatilite_nulle_ecarte_le_nom_au_lieu_de_diverger(self):
        """Serie constante : la volatilite vaut zero, `1/vol` serait infini.
        Ecarter est la seule reponse juste - un poids par defaut inventerait
        une mesure."""
        contrats, stats = alloue(VolatiliteInverse(window=20), panel=panel_plat())
        assert contrats == {}
        assert stats.n_noms_sans_poids == 2

    def test_elle_declare_sa_profondeur(self):
        """Sans quoi le bound anti-look-ahead refuserait la lecture : c'est le
        socle qui l'impose, pas une convention de ce module."""
        assert VolatiliteInverse(window=20).warmup_bars == 21

    def test_une_fenetre_d_une_barre_est_refusee(self):
        with pytest.raises(ConfigurationError, match="dispersion"):
            VolatiliteInverse(window=1)


class TestPoidsParSignal:
    """L'echappatoire : un poids ecrit dans le vocabulaire."""

    def constante(self, valeur: float) -> PoidsParSignal:
        return PoidsParSignal(
            signal=build_signal({"type": "constant", "value": valeur})
        )

    def test_un_signal_constant_donne_des_poids_egaux(self):
        """La normalisation rend l'echelle indifferente : le meme resultat que
        `PoidsEgaux`, ce qui est la verification qui compte."""
        contrats, _ = alloue(self.constante(7.0))
        attendus, _ = alloue(PoidsEgaux(gross_target=1.0))
        assert contrats == attendus

    @pytest.mark.parametrize("echelle", [0.001, 1.0, 1000.0])
    def test_l_echelle_du_signal_ne_change_rien(self, echelle):
        contrats, _ = alloue(self.constante(echelle))
        assert contrats == {"GROS": 100, "PETIT": 500}

    def test_un_poids_negatif_ecarte_le_nom_sans_retourner_la_position(self):
        """Le SENS vient du classement. Un poids negatif n'a pas de sens comme
        part d'un budget, et le prendre pour une inversion melangerait deux
        decisions qui doivent rester separees."""
        contrats, stats = alloue(self.constante(-1.0))
        assert contrats == {}
        assert stats.n_noms_sans_poids == 2

    def test_un_poids_indefini_ecarte_le_nom(self):
        """`None` n'est pas zero, et zero n'est pas un poids par defaut : une
        primitive sans assez d'historique ecarte le nom du budget."""
        tardif = PoidsParSignal(signal=prim("sma@1", window=5000))
        contrats, stats = alloue(tardif)
        assert contrats == {}
        assert stats.n_noms_sans_poids == 2

    def test_elle_herite_de_la_profondeur_de_son_signal(self):
        signal = prim("sma@1", window=30)
        assert PoidsParSignal(signal=signal).warmup_bars == signal.warmup_bars


class TestLeProtocoleEstRespecte:
    @pytest.mark.parametrize(
        "regle",
        [
            ContratsFixes(1),
            PoidsEgaux(),
            VolatiliteInverse(),
            PoidsParSignal(signal=build_signal({"type": "constant", "value": 1.0})),
        ],
    )
    def test_chaque_regle_satisfait_le_protocole(self, regle):
        assert isinstance(regle, AllocationRule)

    @pytest.mark.parametrize(
        "regle",
        [ContratsFixes(2), PoidsEgaux(gross_target=0.5), VolatiliteInverse(window=30)],
    )
    def test_chaque_regle_se_decrit(self, regle):
        """Le manifeste doit porter la repartition : un run archive doit rester
        interpretable des annees plus tard."""
        decrit = regle.describe()
        assert "rule" in decrit

    def test_l_allocateur_publie_la_regle_et_ses_compteurs(self):
        decrit = Allocateur(PoidsEgaux(gross_target=0.5)).describe()
        assert decrit["rule"] == "equal_weight"
        assert decrit["gross_target"] == 0.5
        assert isinstance(decrit["stats"], dict)

    def test_reset_remet_les_compteurs_a_zero(self):
        allocateur = Allocateur(PoidsEgaux(gross_target=1.0))
        allocateur.contrats(["GROS", "PETIT"], coupe(panel_plat(), equity=100.0))
        assert allocateur.stats.n_noms_tronques == 2
        allocateur.reset()
        assert allocateur.stats.n_noms_tronques == 0

    def test_contrats_fixes_sous_un_est_refuse(self):
        with pytest.raises(ConfigurationError, match="n doit"):
            ContratsFixes(0)


class TestHorsRunUneAllocationRefuseDeDeviner:
    """`contract_value` et `account_value` levent sans runner. C'est voulu.

    Une allocation qui rendrait un chiffre plausible sans connaitre la taille
    des contrats serait silencieusement fausse - le pire des trois etats
    possibles, devant l'erreur et devant l'absence de resultat.
    """

    def test_sans_multiplicateur_declare_elle_leve(self):
        ctx = MultiContext(panel_plat())
        ctx._seek_row(100)
        ctx._set_account(
            AccountState(
                equity=EQUITY, cash=EQUITY, peak_equity=EQUITY, initial_equity=EQUITY
            )
        )
        with pytest.raises(ConfigurationError, match="multiplicateur"):
            PoidsEgaux().contrats(["GROS"], ctx, AllocationStats())

    def test_mais_contrats_fixes_reste_utilisable(self):
        """Elle ne convertit aucun argent : elle n'a besoin de rien. C'est ce
        qui en fait la regle des verifications analytiques."""
        ctx = MultiContext(panel_plat())
        ctx._seek_row(100)
        assert ContratsFixes(3).contrats(["GROS"], ctx, AllocationStats()) == {
            "GROS": 3
        }
