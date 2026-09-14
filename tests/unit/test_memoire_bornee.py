"""Retenir quelque chose du passe, sans noeud a etat.

Ce qui est en jeu
------------------
Le recensement du 2026-09-14 laissait quatre familles de strategie intraday
bloquees. Deux tenaient a la meme incapacite : **le vocabulaire ne savait rien
retenir**.

- `bars_since` disait QUAND une condition avait ete vraie, jamais CE QUI valait
  alors. Et `lag.bars` etant une CONSTANTE, on ne pouvait pas reculer d'un
  nombre de barres calcule. Donc « ne pas rejouer le meme niveau » etait
  inexprimable, et la perte NETTE d'un trade aussi.
- `cumulative` remettait a zero a chaque seance. Donc « reduire apres une serie
  de mauvais JOURS » etait inexprimable.

Deux ajouts y repondent, et aucun n'est un noeud a etat
--------------------------------------------------------
`value_when` et `cumulative.sessions` ne RETIENNENT rien : ils RECALCULENT, a
chaque barre, sur une fenetre BORNEE et declaree. Deux evaluations du meme
instant donnent le meme resultat, et rien ne survit a un run - c'est ce qui les
distingue du « noeud a memoire interne » que le ledger ecarte depuis le
2026-09-10.

Pour `cumulative.sessions`, le ledger est meme explicite : `reset: never` est
ecarte « **sauf borne par une fenetre explicite** ». `sessions: N` EST cette
fenetre.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, Granularity
from rsl.data.session import SessionCalendar, build_session_index
from rsl.errors import ConfigurationError
from rsl.strategies.signals import build_signal

NS = 1_000_000_000
PAR_SEANCE = 20
SEANCE = SessionCalendar(start="09:00", end="16:00", timezone="UTC")


def magasin(n_seances: int = 6) -> BarStore:
    """Des seances courtes, pour que les fenetres multi-seances tiennent."""
    ts: list[int] = []
    base = dt.datetime(2024, 1, 2, 9, 0, tzinfo=dt.UTC)
    for j in range(n_seances):
        debut = int((base + dt.timedelta(days=j)).timestamp())
        ts.extend((debut + m * 600) * NS for m in range(PAR_SEANCE))
    tab = np.asarray(ts, dtype=np.int64)
    closes = synthetic.random_walk(tab.size, 100.0, sigma=0.5, seed=53)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.002)
    store = BarStore.build(
        symbol="MEM.v.0", granularity=Granularity.minutes(10), ts_event=tab,
        open_=o, high=h, low=low, close=c,
        volume=np.full(tab.size, 10.0), source_hash="synthetic",
    )
    return store.with_sessions(
        build_session_index(store.ts_close, store.open, store.high, store.low,
                            store.close, store.volume, SEANCE)
    )


def au(store: BarStore, i: int) -> BarContext:
    ctx = BarContext(store)
    ctx._seek(i)
    return ctx


def const(v: float) -> dict:
    return {"type": "constant", "value": float(v)}


CLOSE = {"type": "price", "field": "close", "lag": 0}
MFO = {"type": "session", "field": "minutes_from_open", "lag": 0}


def parcourir(spec: dict, store: BarStore) -> list[float | None]:
    """UN seul noeud, dans l'ordre : c'est ce qui fait vivre les tampons."""
    signal = build_signal(spec)
    ctx = BarContext(store)
    valeurs: list[float | None] = []
    for i in range(store.n_bars):
        ctx._seek(i)
        valeurs.append(signal(ctx))
    return valeurs


class TestValueWhen:
    """La valeur d'une expression a la derniere barre ou une condition tenait."""

    def cible(self, lookback: int = 30, minute: float = 60.0) -> dict:
        return {
            "type": "value_when", "lookback": lookback,
            "when": {"type": "compare", "op": "==", "left": MFO, "right": const(minute)},
            "inner": CLOSE,
        }

    def test_elle_rend_la_valeur_de_la_barre_trouvee(self):
        store = magasin(2)
        closes = np.asarray(store.close)
        obtenues = parcourir(self.cible(), store)
        # Barres de 10 min : la minute 60 depuis l'ouverture est le rang 5.
        assert obtenues[10] == pytest.approx(float(closes[5]))
        assert obtenues[19] == pytest.approx(float(closes[5]))

    def test_elle_suit_la_derniere_occurrence(self):
        """Et non la premiere : c'est ce qui en fait un ancrage utilisable."""
        store = magasin(3)
        closes = np.asarray(store.close)
        obtenues = parcourir(self.cible(lookback=60), store)
        assert obtenues[10] == pytest.approx(float(closes[5]))
        assert obtenues[30] == pytest.approx(float(closes[25])), "seance suivante"

    def test_la_barre_courante_compte(self):
        """Meme convention que `bars_since`, qui rend zero quand c'est vrai
        maintenant."""
        store = magasin(1)
        closes = np.asarray(store.close)
        assert parcourir(self.cible(), store)[5] == pytest.approx(float(closes[5]))

    def test_jamais_vu_rend_none_et_non_une_sentinelle(self):
        """Une sentinelle se comparerait sans lever, et ferait declencher des
        regles sur un evenement qui n'a pas eu lieu ([[lessons]] L30)."""
        spec = {
            "type": "value_when", "lookback": 5,
            "when": {"type": "compare", "op": "<", "left": MFO, "right": const(-1.0)},
            "inner": CLOSE,
        }
        assert all(v is None for v in parcourir(spec, magasin(2)))

    def test_hors_de_la_fenetre_rend_none(self):
        """La borne mord : un `lookback` de 3 ne voit pas une condition vraie
        il y a dix barres."""
        store = magasin(2)
        obtenues = parcourir(self.cible(lookback=3), store)
        assert obtenues[5] is not None, "vrai a la barre meme"
        assert obtenues[15] is None, "la minute 60 est hors de portee"

    def test_ce_que_lag_ne_pouvait_pas_faire(self):
        """La comparaison qui justifie le noeud.

        `lag` recule d'un nombre CONSTANT de barres. Ici la distance au dernier
        evenement change a chaque barre, donc aucune constante ne peut la
        suivre : aux barres 6 et 9, la meme valeur est rendue alors que le recul
        vaut respectivement 1 et 4.
        """
        store = magasin(1)
        obtenues = parcourir(self.cible(), store)
        assert obtenues[6] == obtenues[9]
        # `lag` est evalue a partir de son warmup : un lag de 1 a la barre 0
        # est refuse par le socle, et a raison.
        lag1 = build_signal({"type": "lag", "bars": 1, "inner": CLOSE})
        assert obtenues[9] != pytest.approx(lag1(au(store, 9)))

    def test_un_lookback_nul_est_refuse(self):
        with pytest.raises(ConfigurationError, match="lookback"):
            build_signal(self.cible(lookback=0))

    def test_le_warmup_couvre_la_fenetre(self):
        assert build_signal(self.cible(lookback=30)).warmup_bars >= 29

    def test_deux_evaluations_du_meme_instant_sont_egales(self):
        """La propriete qui le distingue d'un noeud a ETAT : il ne retient
        rien, il recalcule."""
        store = magasin(2)
        signal = build_signal(self.cible())
        assert signal(au(store, 25)) == signal(au(store, 25))


class TestCumulativeSurPlusieursSeances:
    def compte(self, sessions: int) -> dict:
        return {"type": "cumulative", "stat": "sum",
                "inner": const(1.0), "sessions": sessions}

    def test_une_seance_reste_le_defaut(self):
        """Aucune specification ecrite avant cet ajout ne change de sens."""
        store = magasin(3)
        sans = parcourir({"type": "cumulative", "stat": "sum", "inner": const(1.0)}, store)
        avec = parcourir(self.compte(1), store)
        assert sans == avec
        assert "sessions" not in build_signal(self.compte(1)).describe()

    def test_deux_seances_franchissent_la_nuit(self):
        store = magasin(3)
        obtenues = parcourir(self.compte(2), store)
        # Derniere barre de la 2e seance : 20 barres de la seance 0 + 20 de la 1.
        assert obtenues[2 * PAR_SEANCE - 1] == pytest.approx(2.0 * PAR_SEANCE)

    def test_la_fenetre_reste_bornee(self):
        """Le point qui la distingue de `reset: never`, ecarte au ledger : le
        cumul ne croit pas indefiniment avec la position dans l'echantillon."""
        store = magasin(6)
        obtenues = parcourir(self.compte(2), store)
        fins = [obtenues[(j + 1) * PAR_SEANCE - 1] for j in range(1, 6)]
        assert all(v == pytest.approx(2.0 * PAR_SEANCE) for v in fins), fins

    def test_elle_rend_none_tant_que_l_historique_manque(self):
        """Jamais une valeur calculee sur une fenetre tronquee."""
        store = magasin(3)
        obtenues = parcourir(self.compte(3), store)
        assert obtenues[0] is None, "aucune seance close derriere"
        assert obtenues[2 * PAR_SEANCE] is not None, "deux seances closes"

    def test_le_champ_est_publie_seulement_s_il_s_ecarte_du_defaut(self):
        assert build_signal(self.compte(3)).describe()["sessions"] == 3

    def test_zero_seance_est_refuse(self):
        with pytest.raises(ConfigurationError, match="au moins 1"):
            build_signal(self.compte(0))

    def test_il_se_compose_avec_le_masque(self):
        """La combinaison qui debloque « les pertes des N derniers jours » :
        compter, sur plusieurs seances, les seules barres qui remplissent une
        condition."""
        spec = {
            "type": "cumulative", "stat": "sum", "inner": const(1.0), "sessions": 2,
            "mask": {"type": "compare", "op": "<=", "left": MFO, "right": const(30.0)},
        }
        store = magasin(3)
        obtenues = parcourir(spec, store)
        # Barres de 10 min : les minutes <= 30 sont les rangs 0, 1, 2 -> trois
        # par seance, donc six sur deux seances.
        assert obtenues[2 * PAR_SEANCE - 1] == pytest.approx(6.0)
