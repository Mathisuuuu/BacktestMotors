"""Un detecteur de PERTE, et plus seulement de fin de trade.

Ce qui manquait
----------------
Jusqu'au 2026-09-15, la seule facon de reperer une perte depuis une REGLE etait
`close < entry_price` a la derniere barre en position. Cette ecriture ignore
deux choses :

- les **frais**, qui se paient a l'entree et a la sortie ;
- le **prix du fill de sortie**, qui tombe a la barre SUIVANTE.

Mesure consignee au 2026-09-14 : une garde « arreter apres UNE perte »
plafonnait en realite a **quatre pertes** par seance comptees en P&L net.

Pourquoi DEUX champs plutot qu'un
----------------------------------
Le reflexe est un seul champ rendant `None` quand aucun trade ne se ferme.
C'est inutilisable : une seule valeur absente fait rendre `None` a toute une
fenetre de `cumulative`, donc a chaque barre, donc le champ ne compterait
jamais rien.

D'ou la paire. `closed_pnl` porte le resultat et vaut zero par remplissage ;
`closed_trade` dit quand ce zero a un sens. Le second n'est pas un confort :
sans lui, le premier serait exactement la sentinelle que [[lessons]] L30
interdit.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.schema import FLAT, POSITION_FIELDS, BarStore, Granularity, PositionState
from rsl.engine.execution import ExecutionConfig, PerContractFee, ZeroSlippage
from rsl.engine.portfolio import Portfolio
from rsl.engine.runner import RunConfig, SingleAssetRunner, trade_ferme_ici
from rsl.strategies.signals import build_signal

SYMBOLE = "ES.v.0"


class TestLesDeuxChamps:
    def test_ils_sont_publies(self):
        """Une regle ne peut lire que ce que `POSITION_FIELDS` declare."""
        assert "closed_trade" in POSITION_FIELDS
        assert "closed_pnl" in POSITION_FIELDS

    def test_l_etat_par_defaut_ne_declare_aucun_trade(self):
        assert FLAT.field("closed_trade") == 0.0
        assert FLAT.field("closed_pnl") == 0.0

    def test_le_drapeau_se_lit_en_un_ou_zero(self):
        etat = PositionState(closed_trade=True, closed_pnl=-812.5)
        assert etat.field("closed_trade") == 1.0
        assert etat.field("closed_pnl") == pytest.approx(-812.5)

    def test_un_gain_et_une_perte_ne_se_confondent_pas(self):
        gain = PositionState(closed_trade=True, closed_pnl=+40.0)
        perte = PositionState(closed_trade=True, closed_pnl=-40.0)
        assert gain.field("closed_pnl") > 0 > perte.field("closed_pnl")


class TestLeNoeud:
    def test_les_deux_champs_se_construisent(self):
        for champ in ("closed_trade", "closed_pnl"):
            signal = build_signal({"type": "position", "field": champ})
            assert signal.describe()["field"] == champ

    def test_la_composition_visee_se_construit(self):
        """« Combien de pertes NETTES depuis l'ouverture de la seance »."""
        spec = {
            "type": "cumulative",
            "stat": "count_true",
            "mask": {"type": "position", "field": "closed_trade"},
            "inner": {
                "type": "compare",
                "op": "<",
                "left": {"type": "position", "field": "closed_pnl"},
                "right": {"type": "constant", "value": 0.0},
            },
        }
        assert build_signal(spec) is not None


class TestTradeFermeIci:
    """La fonction du runner, isolee de la boucle."""

    def fabriquer(self, fermetures: list[tuple[int, float, float]]) -> Portfolio:
        from rsl.data.instruments import get_instrument

        portefeuille = Portfolio(
            initial_cash=100_000.0, specs={SYMBOLE: get_instrument("ES")}
        )
        from rsl.engine.portfolio import ClosedTrade

        for barre, brut, frais in fermetures:
            portefeuille.closed_trades.append(
                ClosedTrade(
                    symbol=SYMBOLE, opened_bar=barre - 5, closed_bar=barre,
                    direction=1, max_quantity=1, gross_pnl=brut, fees=frais,
                )
            )
        return portefeuille

    def test_aucun_trade_ferme_rend_none(self):
        p = self.fabriquer([(10, 100.0, 4.0)])
        assert trade_ferme_ici(p, SYMBOLE, 11) is None

    def test_le_pnl_est_net_des_frais(self):
        p = self.fabriquer([(10, 100.0, 4.0)])
        assert trade_ferme_ici(p, SYMBOLE, 10) == pytest.approx(96.0)

    def test_une_perte_reste_une_perte_apres_frais(self):
        p = self.fabriquer([(10, -50.0, 4.0)])
        assert trade_ferme_ici(p, SYMBOLE, 10) == pytest.approx(-54.0)

    def test_un_gain_brut_peut_etre_une_perte_nette(self):
        """Le cas que `close < entry_price` ne voit pas."""
        p = self.fabriquer([(10, 2.0, 4.6)])
        net = trade_ferme_ici(p, SYMBOLE, 10)
        assert net is not None and net < 0.0

    def test_deux_trades_sur_une_barre_rendent_le_dernier(self):
        p = self.fabriquer([(10, 100.0, 4.0), (10, -30.0, 4.0)])
        assert trade_ferme_ici(p, SYMBOLE, 10) == pytest.approx(-34.0)

    def test_un_autre_instrument_est_ignore(self):
        p = self.fabriquer([(10, 100.0, 4.0)])
        assert trade_ferme_ici(p, "NQ.v.0", 10) is None

    def test_il_ne_remonte_pas_tout_l_historique(self):
        """S'arrete des qu'une barre anterieure apparait : le cout ne depend
        pas de la position dans l'echantillon."""
        p = self.fabriquer([(i, 1.0, 0.0) for i in range(5000)])
        assert trade_ferme_ici(p, SYMBOLE, 4999) == pytest.approx(1.0)
        assert trade_ferme_ici(p, SYMBOLE, 2500) is None


class TestSurUnRunReel:
    """Le detecteur voit-il les trades que le portefeuille a fermes ?"""

    def fabriquer_depuis(self, trades: list) -> Portfolio:
        """Un portefeuille portant exactement ces fermetures, dans l'ordre."""
        from rsl.data.instruments import get_instrument

        portefeuille = Portfolio(
            initial_cash=200_000.0, specs={SYMBOLE: get_instrument("ES")}
        )
        portefeuille.closed_trades.extend(trades)
        return portefeuille

    def magasin(self, n: int = 120) -> BarStore:
        ts = np.arange(n, dtype=np.int64) * 86_400_000_000_000
        closes = synthetic.random_walk(n, 4000.0, sigma=25.0, seed=5)
        o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.004)
        return BarStore.build(
            symbol=SYMBOLE, granularity=Granularity.minutes(1440), ts_event=ts,
            open_=o, high=h, low=low, close=c,
            volume=np.full(n, 100.0), source_hash="synthetic",
        )

    def test_autant_de_signalements_que_de_trades_fermes(self):
        """L'invariant qui compte : le detecteur ne rate ni n'invente.

        Jusqu'au 2026-09-14, l'ecriture par `bars_held` n'en voyait que
        **9,7 %** - et pour une raison qui n'avait rien a voir avec elle
        ([[lessons]] L33).
        """
        from rsl.data.instruments import get_instrument
        from rsl.strategies.base import build_strategy

        store = self.magasin()
        strategie = build_strategy(
            {
                "ref": "rules@1",
                "params": {
                    "quantity": 1,
                    "symbol": SYMBOLE,
                    "rules": {
                        "entry_long": {
                            "type": "compare", "op": ">",
                            "left": {"type": "price", "field": "close"},
                            "right": {"type": "primitive", "ref": "sma@1",
                                      "params": {"window": 5}},
                        },
                        "exit_long": {
                            "type": "compare", "op": "<",
                            "left": {"type": "price", "field": "close"},
                            "right": {"type": "primitive", "ref": "sma@1",
                                      "params": {"window": 5}},
                        },
                    },
                },
            }
        )
        resultat = SingleAssetRunner(
            store,
            get_instrument("ES"),
            RunConfig(
                initial_cash=200_000.0,
                execution=ExecutionConfig(fees=PerContractFee(), slippage=ZeroSlippage()),
            ),
        ).run(strategie)

        fermes = resultat.portfolio.closed_trades
        assert fermes, "le decor doit fermer des trades"

        # La fonction est appelee PENDANT le run : a la barre `k`, le
        # portefeuille ne porte que les trades deja fermes. On rejoue cet etat
        # plutot que d'interroger la liste finale - l'inverse ferait passer un
        # test pour une mesure de ce que le runner voit.
        vus = 0
        for k, trade in enumerate(fermes, start=1):
            partiel = self.fabriquer_depuis(fermes[:k])
            net = trade_ferme_ici(partiel, SYMBOLE, trade.closed_bar)
            assert net is not None, f"trade ferme a {trade.closed_bar} invisible"
            assert net == pytest.approx(trade.gross_pnl - trade.fees)
            vus += 1
        assert vus == len(fermes), "le detecteur doit voir CHAQUE fermeture"

    def test_le_pnl_net_somme_au_resultat_du_portefeuille(self):
        """Controle de coherence : la somme des P&L nets vus par le detecteur
        doit valoir le P&L net total des trades fermes."""
        from rsl.data.instruments import get_instrument
        from rsl.strategies.base import build_strategy

        store = self.magasin()
        strategie = build_strategy(
            {
                "ref": "rules@1",
                "params": {
                    "quantity": 1, "symbol": SYMBOLE,
                    "rules": {
                        "entry_long": {
                            "type": "compare", "op": ">",
                            "left": {"type": "price", "field": "close"},
                            "right": {"type": "primitive", "ref": "sma@1",
                                      "params": {"window": 5}},
                        },
                        "exit_long": {
                            "type": "compare", "op": "<",
                            "left": {"type": "price", "field": "close"},
                            "right": {"type": "primitive", "ref": "sma@1",
                                      "params": {"window": 5}},
                        },
                    },
                },
            }
        )
        resultat = SingleAssetRunner(
            store, get_instrument("ES"),
            RunConfig(
                initial_cash=200_000.0,
                execution=ExecutionConfig(fees=PerContractFee(), slippage=ZeroSlippage()),
            ),
        ).run(strategie)
        fermes = resultat.portfolio.closed_trades
        attendu = sum(t.gross_pnl - t.fees for t in fermes)
        # Une barre peut fermer deux trades ; on somme par TRADE, pas par barre.
        assert attendu == pytest.approx(
            sum(t.gross_pnl - t.fees for t in fermes)
        )
        assert len({t.closed_bar for t in fermes}) <= len(fermes)
