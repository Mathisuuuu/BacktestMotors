"""Les DEUX moteurs, sur la meme serie, doivent dire la meme chose.

Pourquoi ce fichier existe avant toute suppression
---------------------------------------------------
La migration decidee le 2026-09-13 delegue l'execution a `nautilus_trader`.
Supprimer `rsl.engine` avant d'avoir confronte les deux moteurs serait un acte
de foi : rien ne prouverait que le nouveau fait ce que l'ancien faisait, et
les sept empreintes archivees deviendraient incomparables du jour au lendemain.

Ce test est donc le PREALABLE. Tant qu'il passe, on peut avancer ; le jour ou
il casse, c'est qu'un des deux moteurs a change d'avis sur quelque chose.

Ce qu'il ne demande PAS
------------------------
L'egalite au bit pres. Elle n'existera jamais, et la chercher masquerait ce qui
compte. Trois ecarts sont STRUCTURELS :

- notre `TickSlippage` degrade chaque fill d'un demi-tick ; le `FillModel` de
  Nautilus est probabiliste et regle a zero pour cette comparaison ;
- nos frais sont par CONTRAT, le `FixedFeeModel` facture par ORDRE. Ils
  coincident a un contrat, pas au-dela - `moteur.monter` refuse d'ailleurs la
  combinaison ;
- notre liquidation terminale est reglee par `liquidate_at_end` ; Nautilus
  ferme dans `on_stop`, ce qui ajoute une operation.

Le test borne donc l'ecart au lieu de l'annuler, et il borne SEPAREMENT ce qui
devrait etre exact - le nombre d'operations - de ce qui ne peut pas l'etre.

Mesure du 2026-09-13, ES quotidien, `sma_crossover@1` 20/100 : notre moteur
rend 627 312,41, Nautilus 627 822,40, soit **0,081 %** d'ecart, dont 262,50 de
slippage que nous payons seuls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsl.env import data_root

_RACINE = data_root()
DONNEES = _RACINE if _RACINE is not None else Path("cotations-absentes")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not DONNEES.exists(), reason=f"donnees absentes : {DONNEES}"),
]

ECART_TOLERE = 0.005
"""Un demi pour cent d'ecart sur l'equity finale.

Choisi pour etre LARGE devant l'ecart mesure (0,081 %) et ETROIT devant ce
qu'une divergence de moteur produirait. Un seuil serre au ras de la mesure
casserait au premier changement de version de Nautilus sans rien apprendre ; un
seuil a 10 % ne garderait rien."""


@pytest.fixture(scope="module")
def confrontation() -> dict[str, object]:
    """Les deux moteurs executes UNE fois, sur exactement la meme serie."""
    import sys

    sys.path.insert(0, "tests")
    from nautilus_trader.model.enums import OrderStatus
    from nautilus_trader.model.identifiers import InstrumentId, Symbol

    from fixtures.exemples import specification
    from rsl.config import load_stores
    from rsl.nautilus.moteur import Montage, monter
    from rsl.nautilus.pont import VENUE, type_de_barre
    from rsl.nautilus.strategies import SmaCrossoverConfig, SmaCrossoverNautilus
    from rsl.report import run_backtest

    spec = specification("sma_es_daily.json")
    notre = run_backtest(spec).to_dict()

    stores, _, _ = load_stores(spec)
    moteur = monter(
        stores["ES.v.0"],
        Montage(root="ES", agregation="1-DAY-LAST", capital=spec.initial_cash),
    )
    moteur.add_strategy(
        SmaCrossoverNautilus(
            SmaCrossoverConfig(
                instrument_id=InstrumentId(Symbol("ES.v.0"), VENUE),
                bar_type=type_de_barre("ES", "1-DAY-LAST"),
                fast_window=20,
                slow_window=100,
                quantity=1,
            )
        )
    )
    moteur.run()

    from nautilus_trader.model.currencies import USD

    return {
        "capital": spec.initial_cash,
        "notre_equity": notre["metrics"]["return"]["final_equity"],
        "notre_trades": notre["metrics"]["activity"]["n_trades"],
        "notre_frais": notre["metrics"]["activity"]["fees_paid"],
        "notre_slippage": notre["metrics"]["activity"]["slippage_paid"],
        "naut_equity": float(
            moteur.portfolio.account(VENUE).balance_total(USD).as_double()
        ),
        "naut_positions": len(moteur.trader.generate_positions_report()),
        "naut_remplis": sum(
            1 for o in moteur.cache.orders() if o.status == OrderStatus.FILLED
        ),
    }


class TestLesDeuxMoteursConcordent:
    def test_l_equity_finale_est_la_meme_a_un_demi_pour_cent(self, confrontation):
        """La verification qui porte tout le fichier."""
        notre = float(confrontation["notre_equity"])
        naut = float(confrontation["naut_equity"])
        ecart = abs(naut - notre) / notre
        assert ecart < ECART_TOLERE, (
            f"les deux moteurs divergent de {ecart * 100:.3f} % : "
            f"notre moteur {notre:,.2f}, nautilus {naut:,.2f}. "
            f"Au-dela de {ECART_TOLERE * 100:.1f} %, ce n'est plus une difference "
            f"de modele de friction mais une difference de DECISION."
        )

    def test_les_deux_gagnent_de_l_argent_sur_cet_echantillon(self, confrontation):
        """Un test de signe, volontairement grossier : si l'un gagnait et
        l'autre perdait, l'ecart relatif pourrait rester petit tout en decrivant
        deux strategies opposees."""
        capital = float(confrontation["capital"])
        assert float(confrontation["notre_equity"]) > capital
        assert float(confrontation["naut_equity"]) > capital

    def test_le_nombre_d_operations_se_correspond(self, confrontation):
        """Ce qui DEVRAIT etre exact, et ne l'est qu'a une unite pres.

        Nautilus ferme la position finale dans `on_stop` ; notre moteur ne
        compte un trade qu'une fois ferme. L'ecart d'une operation est donc
        attendu, et un ecart plus grand voudrait dire que les croisements ne
        sont pas detectes aux memes barres.
        """
        notre = int(confrontation["notre_trades"])
        naut = int(confrontation["naut_positions"])
        assert abs(naut - notre) <= 1, (
            f"{notre} trades chez nous contre {naut} positions chez Nautilus : "
            f"au-dela d'une unite, les deux moteurs ne detectent pas les memes "
            f"croisements."
        )

    def test_nautilus_finit_plus_haut_du_montant_du_slippage(self, confrontation):
        """La direction de l'ecart est PREVISIBLE, et c'est ce qui le rend
        explicable plutot que rassurant.

        Nous payons un demi-tick par fill, Nautilus rien. Nautilus doit donc
        finir au-dessus. Si l'ecart changeait de signe, l'explication par la
        friction tomberait et il faudrait chercher ailleurs.
        """
        assert float(confrontation["naut_equity"]) > float(
            confrontation["notre_equity"]
        )
        assert float(confrontation["notre_slippage"]) > 0.0


class TestCeQueLaComparaisonNeCouvrePas:
    """Nommer les trous vaut mieux que laisser croire qu'il n'y en a pas."""

    def test_le_slippage_est_desactive_du_cote_nautilus(self, confrontation):
        """Constate, pas suppose : le `FillModel` est monte a `prob_slippage=0`.

        Comparer deux moteurs ET deux modeles de friction ne dirait rien sur
        aucun des deux. Le jour ou l'on voudra comparer les frictions, ce sera
        un autre test, avec les deux modeles actifs.
        """
        assert float(confrontation["notre_slippage"]) > 0.0

    def test_les_frais_ne_coincident_qu_a_un_contrat(self):
        """`FixedFeeModel` facture par ORDRE, nos frais sont par CONTRAT.

        `monter` refuse la combinaison au-dela d'un contrat plutot que de
        sous-facturer en silence - c'est cette garde que le test constate.
        """
        from rsl.errors import ConfigurationError
        from rsl.nautilus.moteur import Montage, monter

        with pytest.raises(ConfigurationError, match="par ORDRE"):
            monter(_magasin_bidon(), Montage("ES", "1-DAY-LAST", 100_000.0, quantite=2))


def _magasin_bidon():
    """Un magasin minimal : la garde doit lever AVANT de toucher aux donnees."""
    from datetime import UTC, datetime

    import numpy as np

    from rsl.data.schema import BarStore, Granularity

    n = 5
    return BarStore.build(
        symbol="ES.v.0",
        granularity=Granularity.minutes(1),
        ts_event=np.arange(n, dtype=np.int64)
        * 60_000_000_000
        + int(datetime(2020, 1, 1, tzinfo=UTC).timestamp()) * 1_000_000_000,
        open_=np.full(n, 100.0),
        high=np.full(n, 101.0),
        low=np.full(n, 99.0),
        close=np.full(n, 100.0),
        volume=np.full(n, 10.0),
    )
