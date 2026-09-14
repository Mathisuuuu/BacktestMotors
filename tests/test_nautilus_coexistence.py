"""Deux moteurs qui COEXISTENT : ce qu'ils partagent, et ce qu'on ne compare pas.

La decision du 2026-09-13
--------------------------
Les deux moteurs sont gardes. Le notre pour la recherche reproductible - les
sept empreintes, le registre des essais, la PBO ; Nautilus pour la validation
croisee et le futur passage en live, ou backtest et production partagent le
meme `NautilusKernel`.

Ce fichier ne cherche donc PAS a prouver qu'ils donnent le meme chiffre. Ils
n'en donnent pas, et c'est etabli.

Pourquoi le fichier precedent etait dangereux
----------------------------------------------
`test_nautilus_concordance.py` tolerait 0,5 % d'ecart sur l'equity finale, et
il PASSAIT - parce que `sma_es_daily` est a -0,47 %. Or les strategies actives
divergent de 17 a 24 % :

    _moule                        152 692  ->  189 099   +23,84 %
    rsi_survendu_hors_lundi       607 025  ->  712 877   +17,44 %
    retour_moyenne_dans_tendance  471 685  ->  467 319    -0,93 %
    sma_es_daily                  627 312  ->  624 360    -0,47 %

Un test vert sur le seul exemple tranquille pendant que les autres derivent de
vingt pour cent est pire que pas de test : il rassure. Meme famille de piege
que [[lessons]] L18 - une mesure juste pour une mauvaise raison.

Ce que ce fichier garde
------------------------
1. **Aucune fuite.** Le seul invariant EXACT, et celui qui compte. Sans
   differe, Nautilus remplit au marche a la cloture de la barre qui a
   DECLENCHE la decision. Le test neutralise le differe pour prouver qu'il
   porte quelque chose.
2. **Chaque strategie JSON tourne sur les deux moteurs.** Le vocabulaire est la
   chose partagee ; s'il cessait de s'executer d'un cote, la coexistence
   n'aurait plus d'objet.
3. **L'ecart est NOMME, pas tolere** - pour que personne ne rederive la
   conclusion dans six mois, ni ne se rejouisse d'une convergence accidentelle.
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

CONVENTION_RSL = "fill a open[t+1]"
CONVENTION_NAUTILUS = "fill a close[t+1]"
"""Les deux conventions de remplissage, ecrites pour ne plus etre redecouvertes.

Ni l'une ni l'autre ne regarde le futur : les deux servent APRES la decision.
Elles ne mesurent simplement pas la meme chose, et sur du quotidien l'ecart
vaut une journee entiere. Il se compose a chaque trade - d'ou 24 % sur une
strategie qui negocie dix-huit fois et 0,5 % sur une qui en fait dix."""

EXEMPLES = (
    "_moule.json",
    "rsi_survendu_hors_lundi.json",
    "retour_moyenne_dans_tendance.json",
    "sma_es_daily.json",
)


def _sans_differe(base: Any) -> Any:
    """Une sous-classe TEMOIN qui soumet pendant la barre qui vient de decider.

    Une premiere version remplacait `_en_attente` par une fausse liste. Elle ne
    neutralisait rien : `on_bar` REASSIGNE `self._en_attente` a une liste
    ordinaire des la premiere barre, et l'espion disparaissait. Le test passait
    en comparant deux executions identiques - exactement le genre de temoin qui
    rassure sans rien prouver. Constate le 2026-09-13, corrige par heritage.
    """

    class SansDiffere(base):  # type: ignore[valid-type, misc]
        def on_bar(self, bar: Any) -> None:
            ctx = self._avancer(bar)
            if ctx.n_bars_seen <= self._regles.warmup_bars:
                return
            for ordre in self._regles.on_bar(ctx):
                self._soumettre(ordre)

    return SansDiffere


def executer_nautilus(nom: str, *, differe: bool = True) -> dict[str, Any]:
    """Execute un exemple sur Nautilus et rend de quoi l'examiner."""
    import sys

    sys.path.insert(0, "tests")
    import numpy as np
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.identifiers import InstrumentId, Symbol

    from fixtures.exemples import specification
    from rsl.config import load_stores
    from rsl.nautilus.moteur import Montage, monter
    from rsl.nautilus.pont import VENUE, type_de_barre
    from rsl.nautilus.vocabulaire import VocabulaireConfig, VocabulaireNautilus

    spec = specification(nom)
    stores, _, _ = load_stores(spec)
    store = stores["ES.v.0"]
    moteur = monter(
        store, Montage(root="ES", agregation="1-DAY-LAST", capital=spec.initial_cash)
    )
    classe = VocabulaireNautilus if differe else _sans_differe(VocabulaireNautilus)
    strategie = classe(
        VocabulaireConfig(
            instrument_id=InstrumentId(Symbol("ES.v.0"), VENUE),
            bar_type=type_de_barre("ES", "1-DAY-LAST"),
            strategie=spec.strategy.as_dict(),
        )
    )
    strategie.attacher(store)
    moteur.add_strategy(strategie)
    moteur.run()

    fills = sorted(
        (
            ev
            for o in moteur.cache.orders()
            for ev in o.events
            if type(ev).__name__ == "OrderFilled"
        ),
        key=lambda e: e.ts_event,
    )
    return {
        "equity": float(moteur.portfolio.account(VENUE).balance_total(USD).as_double()),
        "n_positions": len(moteur.trader.generate_positions_report()),
        "prix_fills": [float(f.last_px) for f in fills],
        "ts_fills": [int(f.ts_event) for f in fills],
        "ts_close": np.asarray(store.ts_close),
        "closes": np.asarray(store.close),
    }


def _fills_colles_a_la_cloture(resultat: dict[str, Any]) -> int:
    """Combien de fills tombent EXACTEMENT sur la cloture de leur barre."""
    import numpy as np

    ts_close, closes = resultat["ts_close"], resultat["closes"]
    colles = 0
    for prix, instant in zip(resultat["prix_fills"], resultat["ts_fills"], strict=True):
        i = int(np.searchsorted(ts_close, instant))
        if i < len(closes) and abs(prix - float(closes[i])) < 1e-9:
            colles += 1
    return colles


@pytest.fixture(scope="module")
def avec_differe() -> dict[str, Any]:
    return executer_nautilus("_moule.json")


@pytest.fixture(scope="module")
def sans_differe() -> dict[str, Any]:
    """Le TEMOIN : la meme execution, sans le decalage."""
    return executer_nautilus("_moule.json", differe=False)


class TestAucuneFuiteDansLePont:
    """L'invariant EXACT, et le seul qui compte vraiment.

    Nautilus remplit un ordre au marche a la cloture de la barre que son moteur
    de correspondance traite. Soumettre pendant `on_bar(t)` donne donc un fill
    a `close[t]` : le prix meme que la strategie vient de lire pour decider.
    """

    NOM = "_moule.json"

    def test_le_temoin_reproduit_bien_la_fuite(self, sans_differe):
        """Sans ce temoin, le test suivant serait vert sans rien garder.

        Mesure du 2026-09-13 : les fills au marche tombaient exactement sur
        `close[t]`, et l'equity depassait la notre de 19,43 %.
        """
        assert _fills_colles_a_la_cloture(sans_differe) > 0, (
            "le temoin ne reproduit plus la fuite : soit Nautilus a change de "
            "convention, soit le contournement ne contourne plus rien. Dans les "
            "deux cas ce fichier ne garde plus rien."
        )

    def test_le_differe_change_le_resultat(self, avec_differe, sans_differe):
        """S'ils donnaient le meme chiffre, le differe serait decoratif."""
        assert float(avec_differe["equity"]) != pytest.approx(
            float(sans_differe["equity"]), rel=1e-9
        )

    def test_la_file_est_videe_a_l_arret(self):
        """Les ordres decides a la DERNIERE barre ne sont jamais soumis : il n'y
        a pas de lendemain pour les executer. Les passer reviendrait a negocier
        sur une information qui n'a pas eu de suite."""
        import inspect

        from rsl.nautilus.vocabulaire import VocabulaireNautilus

        source = inspect.getsource(VocabulaireNautilus.on_stop)
        assert "_en_attente.clear()" in source


@pytest.mark.parametrize("nom", EXEMPLES)
class TestChaqueStrategieJsonTourneSurLesDeuxMoteurs:
    """Le vocabulaire est la chose PARTAGEE.

    Un JSON qui cesserait de s'executer d'un cote ferait tomber la raison d'etre
    de la coexistence : valider une meme description par deux implementations
    independantes.
    """

    def test_nautilus_l_execute_et_negocie(self, nom):
        resultat = executer_nautilus(nom)
        assert int(resultat["n_positions"]) > 0, (
            f"{nom} ne prend aucune position sur Nautilus : le vocabulaire est "
            f"execute mais ses signaux ne declenchent jamais."
        )

    def test_il_produit_des_remplissages(self, nom):
        assert len(executer_nautilus(nom)["prix_fills"]) > 0


class TestLesDeuxMoteursNeSontPasComparables:
    """La conclusion du 2026-09-13, ecrite pour ne plus etre rederivee.

    Ce n'est pas un defaut de la traduction : c'est une difference de
    CONVENTION. Nous servons a l'ouverture suivante, Nautilus a la cloture de
    la barre traitee. Sur du quotidien, une journee entiere d'ecart, qui se
    compose a chaque trade.
    """

    def test_la_convention_de_chaque_moteur_est_nommee(self):
        """Un test sur deux constantes, et il a sa raison d'etre : la conclusion
        doit vivre dans le code, pas seulement dans un message de commit."""
        assert CONVENTION_RSL == "fill a open[t+1]"
        assert CONVENTION_NAUTILUS == "fill a close[t+1]"

    def test_une_strategie_active_diverge_franchement(self):
        """`_moule` negocie 18 fois ; l'ecart mesure vaut 23,84 %.

        On borne INFERIEUREMENT, ce qui est inhabituel et voulu : le jour ou cet
        ecart tomberait sous 5 %, un des deux moteurs aurait change de
        convention. Se rejouir d'une convergence qu'on n'a pas provoquee serait
        exactement la mauvaise reaction.
        """
        import sys

        sys.path.insert(0, "tests")
        from fixtures.exemples import specification
        from rsl.report import run_backtest

        notre = float(
            run_backtest(specification("_moule.json")).to_dict()["metrics"]["return"][
                "final_equity"
            ]
        )
        ecart = abs(float(executer_nautilus("_moule.json")["equity"]) - notre) / notre
        assert ecart > 0.05, (
            f"l'ecart est tombe a {ecart * 100:.2f} % : les deux moteurs se sont "
            f"rapproches. Verifier lequel a change de convention avant de s'en "
            f"rejouir - la comparabilite ne doit pas arriver par accident."
        )
