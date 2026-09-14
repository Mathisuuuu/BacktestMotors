"""La frontiere entre deux trades, vue par la strategie.

Ce qui est en jeu
------------------
Jusqu'au 2026-09-14, le suivi de position ne repartait que lorsque la quantite
passait par ZERO. Quand une strategie ressort et re-entre sur la MEME barre,
elle n'y passe jamais : `bars_held` continuait de compter depuis l'entree
d'ORIGINE et `high_since_entry` gardait les extremes de l'ancien trade, pendant
que `entry_price` - lu sur le portefeuille - prenait le prix du trade NEUF.

**Deux champs decrivaient deux trades differents.**

Ce n'etait pas un cas de bord. Mesure sur un momentum ES 30 minutes : 30 119
barres sur 37 615 portaient deux fills, et la position n'etait observee a plat
que 3 748 fois pour 33 867 trades fermes.

Ce que cela coutait, mesure sur `paire_es_nq`
---------------------------------------------
Sa sortie de secours est `bars_held >= 40`. Une fois ce seuil franchi,
`bars_held` ne redescendait plus : la sortie se declenchait a CHAQUE barre, la
condition d'entree etant encore vraie la strategie re-entrait aussitot, et la
boucle tournait en payant frais et slippage a chaque tour.

| | trades | dont 1 barre | duree mediane |
|---|---|---|---|
| avant | 149 | **121** | 1 |
| apres | 33 | 0 | 41 |

**121 trades sur 149 etaient des artefacts du defaut.**
"""

from __future__ import annotations

import pytest

from rsl.data.instruments import get_instrument
from rsl.data.schema import Bar
from rsl.engine.portfolio import Portfolio
from rsl.engine.runner import position_state, track_positions
from rsl.errors import InsufficientHistoryError
from rsl.orders import Fill, Side

SPEC = get_instrument("ES")


def portefeuille() -> Portfolio:
    return Portfolio(1_000_000.0, {SPEC.symbol: SPEC})


def barre(prix: float) -> Bar:
    return Bar(ts_event=0, ts_close=0, open=prix, high=prix + 2.0,
               low=prix - 2.0, close=prix, volume=100.0)


def remplir(pf: Portfolio, index: int, side: Side, prix: float, qty: int = 1) -> None:
    pf.begin_bar()
    pf.apply_fill(Fill(order_id=index, symbol=SPEC.symbol, bar_index=index, ts_ns=index,
                       side=side, quantity=qty, price=prix, fee=0.0,
                       slippage_cost=0.0, was_clamped=False, tag=""))


def avancer(pf: Portfolio, suivi: dict, index: int, prix: float):
    track_positions(suivi, pf, {SPEC.symbol: barre(prix)}, index)
    return position_state(suivi, pf, SPEC.symbol, index)


class TestSortieEtReentreeSurLaMemeBarre:
    """Le cas qui a motive le correctif : la quantite ne passe pas par zero."""

    def scenario(self):
        pf, suivi = portefeuille(), {}
        remplir(pf, 0, Side.BUY, 4000.0)
        etats = [avancer(pf, suivi, 0, 4000.0)]
        for i in (1, 2):
            etats.append(avancer(pf, suivi, i, 4000.0 + 10 * i))
        # Barre 3 : vente PUIS achat, les deux fills sur la meme barre.
        remplir(pf, 3, Side.SELL, 4050.0)
        remplir(pf, 3, Side.BUY, 4050.0)
        etats.append(avancer(pf, suivi, 3, 4050.0))
        return pf, etats

    def test_la_quantite_ne_passe_jamais_par_zero(self):
        """L'hypothese du test. Si elle tombait, il ne prouverait plus rien."""
        _pf, etats = self.scenario()
        assert all(e.quantity != 0 for e in etats)

    def test_le_portefeuille_compte_bien_deux_trades(self):
        """C'est lui qui fait autorite : il voit les fills."""
        pf, _etats = self.scenario()
        assert len(pf.closed_trades) == 1  # un ferme
        assert pf.opened_bar_of(SPEC.symbol) == 3  # un ouvert, a la barre 3

    def test_bars_held_repart_de_zero(self):
        _pf, etats = self.scenario()
        assert [e.bars_held for e in etats] == [0, 1, 2, 0]

    def test_entry_price_et_bars_held_decrivent_le_meme_trade(self):
        """L'invariant que le defaut violait."""
        _pf, etats = self.scenario()
        dernier = etats[-1]
        assert dernier.entry_price == pytest.approx(4050.0)
        assert dernier.bars_held == 0, (
            "prix d'entree du trade neuf mais duree du trade ancien"
        )

    def test_les_extremes_repartent_aussi(self):
        """`high_since_entry` gardait les extremes de l'ancien trade, donc un
        stop suiveur se declenchait sur un plus haut que la position courante
        n'avait jamais vu."""
        _pf, etats = self.scenario()
        # Barres 0-2 montent jusqu'a 4022 ; la barre 3 plafonne a 4052.
        assert etats[2].high_since_entry == pytest.approx(4022.0)
        assert etats[-1].high_since_entry == pytest.approx(4052.0)
        assert etats[-1].low_since_entry == pytest.approx(4048.0)


class TestRetournementDirect:
    """Long vers short en UN fill : meme defaut, meme correctif."""

    def test_le_suivi_repart_au_retournement(self):
        pf, suivi = portefeuille(), {}
        remplir(pf, 0, Side.BUY, 4000.0)
        avancer(pf, suivi, 0, 4000.0)
        avancer(pf, suivi, 1, 4010.0)
        etat = avancer(pf, suivi, 2, 4020.0)
        assert etat.bars_held == 2 and etat.direction == 1

        remplir(pf, 3, Side.SELL, 4030.0, qty=2)  # +1 -> -1
        etat = avancer(pf, suivi, 3, 4030.0)
        assert etat.direction == -1
        assert etat.bars_held == 0, "le short herite de la duree du long"
        assert etat.entry_price == pytest.approx(4030.0)


class TestCeQuiNeChangePas:
    """Un aller-retour ORDINAIRE doit se comporter comme avant."""

    def test_une_position_tenue_compte_ses_barres(self):
        pf, suivi = portefeuille(), {}
        remplir(pf, 0, Side.BUY, 4000.0)
        etats = [avancer(pf, suivi, i, 4000.0 + i) for i in range(5)]
        assert [e.bars_held for e in etats] == [0, 1, 2, 3, 4]
        assert all(e.entry_price == pytest.approx(4000.0) for e in etats)

    def test_un_passage_a_plat_efface_le_suivi(self):
        pf, suivi = portefeuille(), {}
        remplir(pf, 0, Side.BUY, 4000.0)
        avancer(pf, suivi, 0, 4000.0)
        avancer(pf, suivi, 1, 4010.0)
        remplir(pf, 2, Side.SELL, 4020.0)
        etat = avancer(pf, suivi, 2, 4020.0)
        assert etat.quantity == 0
        assert etat.bars_held == 0 and etat.entry_price == 0.0
        assert SPEC.symbol not in suivi

    def test_une_position_absente_ne_declare_aucune_ouverture(self):
        pf = portefeuille()
        assert pf.opened_bar_of(SPEC.symbol) is None


class TestDetecterLaFinDUnTrade:
    """Ce que le correctif DEBLOQUE, et pourquoi il avait l'air de ne rien faire.

    Une garde intraday courante - « arreter apres N pertes dans la seance » -
    demande de reperer la fin d'un trade depuis une regle. Le vocabulaire n'a
    pas d'acces aux trades fermes ; la seule voie est de voir `bars_held`
    RECULER :

        compare("<", position(bars_held), lag(1, position(bars_held)))

    Pourquoi cette detection etait aveugle
    ---------------------------------------
    Elle suppose que `bars_held` monte pendant un trade. Tant que `is_last`
    marquait 72 % des barres ([[lessons]] L31), la strategie sortait et
    re-entrait a chaque barre : chaque trade durait UNE barre, `bars_held`
    valait 0 en permanence, et `0 < 0` est faux.

    Mesure du 2026-09-14, meme strategie, meme echantillon :

    | | ancien `is_last` | apres correctif |
    |---|---|---|
    | trades fermes | 41 110 | 12 585 |
    | `bars_held = 0` | **111 137 (88 %)** | 77 243 (61 %) |
    | fin de trade DETECTEE | **3 995** | 12 497 |

    Le detecteur voyait **9,7 %** des fins de trade. Le defaut cachait
    exactement les trades qu'il creait.
    """

    def suite(self, durees: list[int]) -> list[float | None]:
        """Evalue `bars_held < lag(1, bars_held)` sur une suite de trades.

        `durees` donne le nombre de barres de chaque trade, dos a dos, sans
        jamais passer a plat - le cas que le correctif a debloque.
        """
        import numpy as np

        from rsl.data.feed import BarContext
        from rsl.data.schema import BarStore, Granularity, PositionState
        from rsl.strategies.signals import build_signal

        n = sum(durees)
        ts = np.arange(n, dtype=np.int64) * 60 * 10**9
        prix = np.full(n, 100.0)
        store = BarStore.build(
            symbol="DET.v.0", granularity=Granularity.minutes(1), ts_event=ts,
            open_=prix, high=prix, low=prix, close=prix,
            volume=np.full(n, 1.0), source_hash="synthetic",
        )
        etats: list[PositionState] = []
        for duree in durees:
            etats.extend(
                PositionState(quantity=1, bars_held=k, entry_price=100.0,
                              high_since_entry=100.0, low_since_entry=100.0)
                for k in range(duree)
            )
        signal = build_signal({
            "type": "compare", "op": "<",
            "left": {"type": "position", "field": "bars_held"},
            "right": {"type": "lag", "bars": 1,
                      "inner": {"type": "position", "field": "bars_held"}},
        })
        ctx = BarContext(store)
        ctx._set_position_depth(10)
        sortie: list[float | None] = []
        for i in range(n):
            ctx._seek(i)
            ctx._set_position(etats[i])
            try:
                sortie.append(signal(ctx))
            except InsufficientHistoryError:
                # La barre 0 n'a pas de precedente. Dans un vrai run le runner
                # ne fait pas decider la strategie pendant le prechauffage ;
                # ici on garde l'alignement des indices.
                sortie.append(None)
        return sortie

    def test_elle_repere_chaque_nouveau_trade(self):
        """Trois trades de 4, 3 et 5 barres, dos a dos."""
        sortie = self.suite([4, 3, 5])
        # La premiere barre n'a pas de precedente ; les deux frontieres sont
        # aux indices 4 et 7.
        assert [i for i, v in enumerate(sortie) if v == 1.0] == [4, 7]

    def test_elle_est_aveugle_aux_trades_d_une_seule_barre(self):
        """Le regime que le defaut `is_last` produisait.

        Huit trades d'une barre : `bars_held` vaut 0 partout, `0 < 0` est faux,
        et la frontiere entre trades est INVISIBLE a la regle - alors qu'elle
        existe bel et bien du point de vue du portefeuille.
        """
        sortie = self.suite([1] * 8)
        assert all(v != 1.0 for v in sortie if v is not None), (
            "un trade d'une barre ne peut pas etre repere ainsi"
        )

    def test_le_melange_ne_repere_que_les_trades_assez_longs(self):
        """Consequence pratique : une garde batie dessus SOUS-COMPTE, et le
        sous-comptage est invisible - elle mord moins, sans rien signaler.

        Quatre trades de 3, 1, 1 et 3 barres : `bars_held` parcourt
        `0,1,2 | 0 | 0 | 0,1,2`. Il y a TROIS frontieres - aux indices 3, 4 et
        5 - et une seule est vue, celle qui suit un trade assez long pour avoir
        fait monter le compteur.
        """
        sortie = self.suite([3, 1, 1, 3])
        assert [i for i, v in enumerate(sortie) if v == 1.0] == [3]
