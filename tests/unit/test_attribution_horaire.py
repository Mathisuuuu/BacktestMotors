"""Attribution des trades par heure de seance.

Ce qui est en jeu
------------------
« Ca marche a 10 h et pas a 14 h » est le premier diagnostic d'une strategie
intraday, et il etait inaccessible : le rapport agregeait tout l'echantillon.
Une strategie qui gagne a l'ouverture et perd le reste de la journee rend un
chiffre global mediocre, indistinguable d'une strategie mediocre partout - alors
que les deux appellent des decisions opposees.

Ce que ces tests protegent surtout : **la somme**. Un tableau par heure dont les
lignes ne totalisent pas les trades fermes serait pire qu'absent, parce qu'il
aurait l'air complet.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.schema import BarStore, Granularity
from rsl.data.session import SessionCalendar, build_session_index
from rsl.engine.portfolio import ClosedTrade
from rsl.errors import ConfigurationError
from rsl.metrics.intraday import (
    MINUTES_PAR_TRANCHE,
    attribution_horaire,
    verifier_coherence,
)

NS = 1_000_000_000
PAR_SEANCE = 300  # cinq heures de barres d'une minute
SEANCE = SessionCalendar(start="09:00", end="16:00", timezone="UTC")


def magasin(symbole: str = "ATT.v.0", *, avec_seance: bool = True) -> BarStore:
    horodatages: list[int] = []
    base = dt.datetime(2024, 1, 2, 9, 0, tzinfo=dt.UTC)
    for jour in range(4):
        debut = int((base + dt.timedelta(days=jour)).timestamp())
        horodatages.extend((debut + m * 60) * NS for m in range(PAR_SEANCE))
    ts = np.asarray(horodatages, dtype=np.int64)
    closes = synthetic.random_walk(ts.size, 100.0, sigma=0.3, seed=31)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.002)
    store = BarStore.build(
        symbol=symbole, granularity=Granularity.minutes(1), ts_event=ts,
        open_=o, high=h, low=low, close=c,
        volume=np.full(ts.size, 10.0), source_hash="synthetic",
    )
    if not avec_seance:
        return store
    return store.with_sessions(
        build_session_index(
            store.ts_close, store.open, store.high, store.low,
            store.close, store.volume, SEANCE,
        )
    )


def trade(barre: int, pnl: float, *, symbole: str = "ATT.v.0") -> ClosedTrade:
    return ClosedTrade(
        symbol=symbole, opened_bar=barre, closed_bar=barre + 5,
        direction=1, max_quantity=1, gross_pnl=pnl, fees=0.0,
    )


class TestLaRepartition:
    def test_un_trade_tombe_dans_la_tranche_de_son_ouverture(self):
        """A l'ouverture et non a la cloture : c'est a l'entree que la decision
        est prise, et c'est elle qu'on cherche a qualifier."""
        store = magasin()
        # Barre 90 : rang 90 dans la premiere seance, donc minute 91 (une barre
        # est horodatee a sa cloture) -> deuxieme heure.
        a = attribution_horaire([trade(90, 100.0)], {"ATT.v.0": store})
        assert a is not None
        assert [t.debut_minute for t in a.tranches] == [MINUTES_PAR_TRANCHE]

    def test_plusieurs_tranches_sont_rendues_triees(self):
        store = magasin()
        trades = [trade(10, 1.0), trade(200, 2.0), trade(130, 3.0)]
        a = attribution_horaire(trades, {"ATT.v.0": store})
        assert a is not None
        debuts = [t.debut_minute for t in a.tranches]
        assert debuts == sorted(debuts)
        assert debuts == [0, 120, 180]

    def test_le_pnl_est_net_des_frais(self):
        store = magasin()
        t = ClosedTrade(symbol="ATT.v.0", opened_bar=10, closed_bar=15,
                        direction=1, max_quantity=1, gross_pnl=100.0, fees=30.0)
        a = attribution_horaire([t], {"ATT.v.0": store})
        assert a is not None
        assert a.tranches[0].pnl_net == pytest.approx(70.0)

    def test_le_hit_rate_compte_les_trades_nets_positifs(self):
        store = magasin()
        trades = [trade(10, 5.0), trade(11, -5.0), trade(12, 5.0), trade(13, 0.0)]
        a = attribution_horaire(trades, {"ATT.v.0": store})
        assert a is not None
        assert a.tranches[0].n_trades == 4
        assert a.tranches[0].n_gagnants == 2
        assert a.tranches[0].hit_rate == pytest.approx(0.5)

    def test_une_tranche_sans_trade_n_apparait_pas(self):
        """Une strategie qui ne decide qu'a l'ouverture n'a pas besoin de vingt
        lignes a zero. Leur ABSENCE est elle-meme l'information."""
        store = magasin()
        a = attribution_horaire([trade(10, 1.0)], {"ATT.v.0": store})
        assert a is not None
        assert len(a.tranches) == 1


class TestLaSommeTient:
    """La propriete qui rend le tableau lisible sans le verifier a la main."""

    def test_les_lignes_totalisent_les_trades(self):
        store = magasin()
        trades = [trade(b, float(b)) for b in (5, 70, 130, 200, 280, 305, 400)]
        a = attribution_horaire(trades, {"ATT.v.0": store})
        assert a is not None
        assert sum(t.n_trades for t in a.tranches) == a.n_trades_classes
        assert a.n_trades_classes + a.n_trades_hors_seance == len(trades)
        verifier_coherence(a, len(trades))

    def test_le_pnl_total_est_celui_des_trades(self):
        store = magasin()
        trades = [trade(b, float(b)) for b in (5, 70, 130, 200)]
        a = attribution_horaire(trades, {"ATT.v.0": store})
        assert a is not None
        assert a.total_pnl == pytest.approx(sum(float(b) for b in (5, 70, 130, 200)))

    def test_un_total_qui_ne_tombe_pas_juste_est_refuse(self):
        """Le garde-fou lui-meme. Un tableau incomplet se lirait comme complet."""
        store = magasin()
        a = attribution_horaire([trade(10, 1.0)], {"ATT.v.0": store})
        assert a is not None
        with pytest.raises(ConfigurationError, match="se lirait comme complet"):
            verifier_coherence(a, 7)

    def test_un_trade_sur_un_symbole_sans_calendrier_est_compte_a_part(self):
        """Range silencieusement dans une tranche, il ferait croire a une
        couverture complete."""
        stores = {"ATT.v.0": magasin(), "NU.v.0": magasin("NU.v.0", avec_seance=False)}
        trades = [trade(10, 1.0), trade(10, 2.0, symbole="NU.v.0")]
        a = attribution_horaire(trades, stores)
        assert a is not None
        assert a.n_trades_classes == 1
        assert a.n_trades_hors_seance == 1
        verifier_coherence(a, 2)


class TestSansCalendrier:
    def test_aucune_attribution_sans_seance_declaree(self):
        """« L'heure de la seance » n'a pas de sens sans seance, et le socle ne
        devine pas de frontiere."""
        stores = {"NU.v.0": magasin("NU.v.0", avec_seance=False)}
        assert attribution_horaire([trade(10, 1.0, symbole="NU.v.0")], stores) is None

    def test_aucun_trade_rend_une_attribution_vide_et_non_none(self):
        """Vide et `None` ne disent pas la meme chose : l'un dit « la strategie
        n'a pas negocie », l'autre « la question ne se pose pas »."""
        a = attribution_horaire([], {"ATT.v.0": magasin()})
        assert a is not None
        assert a.tranches == ()
        assert a.render() == []


class TestLeRendu:
    def test_il_nomme_les_heures_depuis_l_ouverture(self):
        store = magasin()
        a = attribution_horaire([trade(10, 1.0), trade(200, -2.0)], {"ATT.v.0": store})
        assert a is not None
        texte = "\n".join(a.render())
        assert "depuis l'ouverture declaree" in texte
        assert "+ 0 h a + 1 h" in texte
        assert "+ 3 h a + 4 h" in texte

    def test_les_trades_hors_seance_sont_dits(self):
        stores = {"ATT.v.0": magasin(), "NU.v.0": magasin("NU.v.0", avec_seance=False)}
        a = attribution_horaire(
            [trade(10, 1.0), trade(10, 2.0, symbole="NU.v.0")], stores
        )
        assert a is not None
        assert "hors de toute seance declaree" in "\n".join(a.render())
