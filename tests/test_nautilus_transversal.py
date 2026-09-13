"""Le vocabulaire TRANSVERSAL sur Nautilus : ce qui a failli passer inapercu.

Le porter a demande de reconstituer une COUPE - tous les instruments a un
instant - a partir de barres livrees une par une. Deux pieges s'y cachaient, et
aucun des deux ne produisait d'erreur : tous deux rendaient un backtest plat.

Piege 1 : declencher trop tot
------------------------------
Une premiere version decidait a l'arrivee de la premiere barre d'un nouvel
instant. La ligne precedente etait bien finie - mais le simulateur n'avait
traite qu'UNE barre du nouvel instant, et les neuf autres instruments n'avaient
pas de prix. Nautilus rejetait chaque ordre : `no market for NQ.v.0.SIM`.

**684 ordres emis, 684 rejetes, zero position, capital intact.** Aucune
exception, aucun avertissement. Le correctif compte les barres attendues
(`present_symbols`) et ne traite la ligne qu'a la derniere.

Piege 2 : une etiquette que le simulateur n'execute pas
--------------------------------------------------------
Meme symptome, autre cause. Nautilus ne remplit AUCUN ordre sur des barres
etiquetees `MONTH` - mesure a la ligne pres : `1-DAY-LAST` donne 14 fills,
`1-MONTH-LAST` 14 rejets, tout le reste etant identique.

`etiquette_executable` reetiquette donc le mensuel en `DAY`. Les barres restent
mensuelles - leurs horodatages le disent - et Nautilus ne les reagrege jamais,
puisqu'elles arrivent deja agregees.

Ce que ces deux pieges ont en commun, et pourquoi ce fichier existe : **un
backtest qui ne negocie pas ressemble a un backtest qui perd**. Les deux tests
qui suivent auraient echoue dans les deux cas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rsl.env import data_root

_RACINE = data_root()
DONNEES = _RACINE if _RACINE is not None else Path("cotations-absentes")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not DONNEES.exists(), reason=f"donnees absentes : {DONNEES}"),
]


def executer_transversal(nom: str, agregation: str) -> dict[str, Any]:
    """Un exemple transversal, execute sur Nautilus."""
    import sys

    sys.path.insert(0, "tests")
    from collections import Counter

    from nautilus_trader.model.currencies import USD

    from fixtures.exemples import specification
    from rsl.config import build_panel_from, load_stores
    from rsl.nautilus.moteur import monter_transversal
    from rsl.nautilus.pont import VENUE
    from rsl.nautilus.transversal import TransversalConfig, TransversalNautilus

    spec = specification(nom)
    stores, instruments, _ = load_stores(spec)
    panel = build_panel_from(spec, stores)
    # Le pont ne porte pas le `RiskManager` : on neutralise le dimensionnement
    # plutot que de le laisser etre ignore en silence.
    sans = spec.risk.model_copy(
        update={"sizing": spec.risk.sizing.model_copy(update={"kind": "none"})}
    )
    moteur = monter_transversal(
        stores,
        instruments,
        capital=spec.initial_cash,
        agregation=agregation,
        risque=sans,
    )
    strategie = TransversalNautilus(
        TransversalConfig(
            strategie=spec.strategy.as_dict(),
            venue=str(VENUE),
            agregation=agregation,
        )
    )
    strategie.attacher(
        panel,
        {cle: spec_.multiplier for cle, spec_ in instruments.items()},
        capital=spec.initial_cash,
        schedule=spec.rebalance.build(),
    )
    moteur.add_strategy(strategie)
    moteur.run()

    statuts = Counter(str(o.status) for o in moteur.cache.orders())
    return {
        "equity": float(moteur.portfolio.account(VENUE).balance_total(USD).as_double()),
        "capital": spec.initial_cash,
        "n_positions": len(moteur.trader.generate_positions_report()),
        "n_ordres": len(moteur.cache.orders()),
        "n_remplis": statuts.get("14", 0),
        "n_rejetes": statuts.get("7", 0),
        "n_symboles": len(panel.symbols),
    }


@pytest.fixture(scope="module")
def momentum() -> dict[str, Any]:
    return executer_transversal("momentum_12_1_mensuel.json", "1-MONTH-LAST")


class TestLeTransversalNegocieVraiment:
    """Les deux assertions qui auraient attrape les deux pieges."""

    def test_des_positions_sont_prises(self, momentum):
        assert int(momentum["n_positions"]) > 0, (
            "aucune position : le vocabulaire transversal s'execute mais rien "
            "n'aboutit. Verifier que la ligne est traitee a sa DERNIERE barre, "
            "et que l'agregation est executable par le simulateur."
        )

    def test_et_la_plupart_des_ordres_sont_remplis(self, momentum):
        """Le piege des 684 rejets avait des ordres, pas des fills. Compter les
        ordres ne suffit donc pas - il faut compter ce qui aboutit."""
        assert int(momentum["n_remplis"]) > int(momentum["n_rejetes"]), (
            f"{momentum['n_rejetes']} rejets pour {momentum['n_remplis']} fills : "
            f"le simulateur refuse la majorite des ordres."
        )

    def test_le_capital_a_bouge(self, momentum):
        """Un capital intact est la signature d'un backtest qui n'a rien fait -
        et il ressemble a un backtest qui n'a rien gagne."""
        assert float(momentum["equity"]) != pytest.approx(
            float(momentum["capital"]), rel=1e-9
        )

    def test_les_dix_instruments_sont_dans_le_panneau(self, momentum):
        assert int(momentum["n_symboles"]) == 10


class TestLAgregationMensuelleEstReetiquetee:
    """`MONTH` n'est pas executable ; le pont le sait et le corrige."""

    def test_month_n_est_pas_dans_la_liste_executable(self):
        from rsl.nautilus.pont import AGREGATIONS_EXECUTABLES

        assert "MONTH" not in AGREGATIONS_EXECUTABLES
        assert "DAY" in AGREGATIONS_EXECUTABLES

    def test_le_mensuel_devient_du_quotidien(self):
        from rsl.nautilus.pont import etiquette_executable

        assert etiquette_executable("1-MONTH-LAST") == "1-DAY-LAST"

    def test_les_agregations_executables_passent_intactes(self):
        from rsl.nautilus.pont import etiquette_executable

        for agregation in ("1-MINUTE-LAST", "1-HOUR-LAST", "1-DAY-LAST", "1-WEEK-LAST"):
            assert etiquette_executable(agregation) == agregation

    def test_une_unite_inconnue_est_refusee(self):
        """Plutot que reetiquetee au hasard : une unite qu'on ne connait pas est
        une unite dont on ignore si le simulateur l'execute."""
        from rsl.errors import ConfigurationError
        from rsl.nautilus.pont import etiquette_executable

        with pytest.raises(ConfigurationError, match="inconnue"):
            etiquette_executable("1-FORTNIGHT-LAST")

    def test_le_type_de_barre_porte_l_etiquette_corrigee(self):
        from rsl.nautilus.pont import type_de_barre

        assert "DAY" in str(type_de_barre("ES", "1-MONTH-LAST"))


class TestCeQueLePontTransversalRefuse:
    """Il ne porte pas le `RiskManager`, et il le dit plutot que de l'ignorer."""

    def _stores_minimaux(self):
        import sys

        sys.path.insert(0, "tests")
        from fixtures.exemples import specification
        from rsl.config import load_stores

        spec = specification("momentum_12_1_mensuel.json")
        stores, instruments, _ = load_stores(spec)
        return spec, stores, instruments

    def test_un_dimensionnement_declare_est_refuse(self):
        """Il serait IGNORE : les tailles seraient celles emises par la
        strategie, pas celles que le dimensionnement calcule."""
        from rsl.errors import ConfigurationError
        from rsl.nautilus.moteur import monter_transversal

        spec, stores, instruments = self._stores_minimaux()
        assert spec.risk.sizing.kind != "none", "l'exemple doit declarer un sizing"
        with pytest.raises(ConfigurationError, match="ne porte pas le RiskManager"):
            monter_transversal(
                stores,
                instruments,
                capital=spec.initial_cash,
                agregation="1-MONTH-LAST",
                risque=spec.risk,
            )

    def test_des_plafonds_de_portefeuille_declares_sont_refuses(self):
        from rsl.config import PortfolioLimitsSpec
        from rsl.errors import ConfigurationError
        from rsl.nautilus.moteur import monter_transversal

        spec, stores, instruments = self._stores_minimaux()
        risque = spec.risk.model_copy(
            update={
                "sizing": spec.risk.sizing.model_copy(update={"kind": "none"}),
                "limits": PortfolioLimitsSpec(max_positions=3),
            }
        )
        with pytest.raises(ConfigurationError, match="plafonds de portefeuille"):
            monter_transversal(
                stores,
                instruments,
                capital=spec.initial_cash,
                agregation="1-MONTH-LAST",
                risque=risque,
            )

    def test_une_strategie_mono_instrument_est_refusee(self):
        """Elle passe par `rsl.nautilus.vocabulaire`, et le message le dit."""
        from rsl.errors import ConfigurationError
        from rsl.nautilus.pont import VENUE
        from rsl.nautilus.transversal import TransversalConfig, TransversalNautilus

        with pytest.raises(ConfigurationError, match="pas une strategie"):
            TransversalNautilus(
                TransversalConfig(
                    strategie={
                        "ref": "sma_crossover@1",
                        "params": {"symbol": "ES.v.0"},
                    },
                    venue=str(VENUE),
                )
            )
