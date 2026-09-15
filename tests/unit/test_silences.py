"""Les trois mesures que le rapport ne faisait pas.

Pourquoi elles existent
------------------------
Le 2026-09-15, la replication de Zarattini a demande trois heures de mesure
pour expliquer un ecart de Sharpe. Cinq causes ont ete trouvees ; les deux qui
etaient DEJA IMPRIMEES - `dropped_sizing`, `reduce_only_dropped` - ont pris
quelques minutes, les trois silencieuses ont pris le reste.

Ces tests fixent ce que chacune doit dire, et surtout QUAND elle doit se
taire : une mesure qui parle toujours n'alerte plus.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.schema import BarStore, Granularity
from rsl.data.session import SessionCalendar, build_session_index
from rsl.metrics.silences import (
    franchissements_de_nuit,
    mesurer_les_silences,
    seances_sans_cloture,
)
from rsl.orders import Fill, Side

NS = 1_000_000_000


def magasin(n: int = 60, *, avec_seance: bool = False) -> BarStore:
    """`n` barres d'une minute a partir de 09:31 New York."""
    depart = dt.datetime(2024, 3, 4, 14, 31, tzinfo=dt.UTC)  # 09:31 NY
    ts = np.asarray(
        [int((depart + dt.timedelta(minutes=m)).timestamp()) * NS for m in range(n)],
        dtype=np.int64,
    )
    closes = synthetic.random_walk(n, 100.0, sigma=0.2, seed=13)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.002)
    store = BarStore.build(
        symbol="X.v.0", granularity=Granularity.minutes(1), ts_event=ts,
        open_=o, high=h, low=low, close=c,
        volume=np.full(n, 10.0), source_hash="synthetic",
    )
    if not avec_seance:
        return store
    calendrier = SessionCalendar(
        start="09:30", end="16:00", timezone="America/New_York"
    )
    return store.with_sessions(
        build_session_index(
            store.ts_close, store.open, store.high, store.low,
            store.close, store.volume, calendrier,
        )
    )


def fill(bar_index: int, symbol: str = "X.v.0") -> Fill:
    return Fill(
        order_id=bar_index, symbol=symbol, bar_index=bar_index, side=Side.BUY,
        quantity=1, price=100.0, fee=0.0, slippage_cost=0.0,
        was_clamped=False, tag=None, ts_ns=bar_index,
    )


class TestSansSeanceDeclaree:
    """Rien a dire : sans calendrier, il n'y a ni nuit ni cloture."""

    def test_les_deux_mesures_rendent_none(self):
        store = magasin()
        stores = {store.symbol: store}
        assert seances_sans_cloture(stores) is None
        assert franchissements_de_nuit(stores, [fill(10)], 1) is None

    def test_le_bloc_entier_est_vide(self):
        store = magasin()
        silences = mesurer_les_silences({store.symbol: store}, [fill(10)], 1)
        assert silences.est_vide
        assert silences.describe() == {}
        assert silences.render() == []


class TestSeancesSansCloture:
    def test_une_seance_complete_n_a_pas_de_trou(self):
        """Les barres vont jusqu'a la fermeture declaree : `is_last` tombe."""
        store = magasin(n=400, avec_seance=True)
        mesure = seances_sans_cloture({store.symbol: store})
        assert mesure is not None
        assert mesure.n_sans_cloture == 0
        assert mesure.part == 0.0

    def test_une_seance_ecourtee_est_comptee(self):
        """Soixante barres depuis 09:31 s'arretent a 10:30, bien avant 16:00 :
        aucune barre ne porte `is_last`. C'est exactement le cas des 90
        demi-journees de NQ."""
        store = magasin(n=60, avec_seance=True)
        mesure = seances_sans_cloture({store.symbol: store})
        assert mesure is not None
        assert mesure.n_seances == 1
        assert mesure.n_sans_cloture == 1
        assert mesure.part == pytest.approx(1.0)

    def test_elle_se_rend_dans_le_texte(self):
        store = magasin(n=60, avec_seance=True)
        lignes = mesurer_les_silences({store.symbol: store}, [], 1).render()
        assert any("AUCUNE" in ligne for ligne in lignes)
        assert any("is_last" in ligne for ligne in lignes)

    def test_elle_se_tait_quand_il_n_y_a_rien(self):
        """Une mesure qui parle toujours n'alerte plus."""
        store = magasin(n=400, avec_seance=True)
        lignes = mesurer_les_silences({store.symbol: store}, [], 1).render()
        assert not any("is_last" in ligne for ligne in lignes)


class TestFranchissementsDeNuit:
    def test_un_fill_dans_la_meme_seance_n_est_pas_compte(self):
        store = magasin(n=400, avec_seance=True)
        mesure = franchissements_de_nuit({store.symbol: store}, [fill(50)], 1)
        assert mesure is not None
        assert mesure.n_franchissements == 0
        assert mesure.n_fills == 1

    def test_un_fill_dans_une_autre_seance_est_compte(self):
        """On fabrique la situation : deux seances, et un fill sur la premiere
        barre de la seconde dont la decision tombait sur la derniere de la
        premiere."""
        depart = dt.datetime(2024, 3, 4, 19, 59, tzinfo=dt.UTC)  # 14:59 NY
        # Deux barres de la seance du 4, puis deux du 5.
        instants = [
            depart,
            depart + dt.timedelta(minutes=1),
            depart + dt.timedelta(days=1, minutes=-300),
            depart + dt.timedelta(days=1, minutes=-299),
        ]
        ts = np.asarray([int(t.timestamp()) * NS for t in instants], dtype=np.int64)
        # OHLC pose a la main : `ohlc_from_closes` derive l'ouverture de la
        # cloture precedente, ce qui rend tout gap NUL par construction - et
        # c'est precisement le gap qu'on veut mesurer.
        o = np.asarray([100.0, 101.0, 140.0, 141.0])
        c = np.asarray([101.0, 101.0, 141.0, 141.0])
        h = np.maximum(o, c)
        low = np.minimum(o, c)
        store = BarStore.build(
            symbol="X.v.0", granularity=Granularity.minutes(1), ts_event=ts,
            open_=o, high=h, low=low, close=c,
            volume=np.full(4, 10.0), source_hash="synthetic",
        )
        calendrier = SessionCalendar(
            start="09:30", end="16:00", timezone="America/New_York"
        )
        store = store.with_sessions(
            build_session_index(
                store.ts_close, store.open, store.high, store.low,
                store.close, store.volume, calendrier,
            )
        )
        numeros = np.asarray(store.sessions.session_number)
        assert numeros[1] != numeros[2], "le decor exige DEUX seances"

        mesure = franchissements_de_nuit({store.symbol: store}, [fill(2)], 1)
        assert mesure is not None
        assert mesure.n_franchissements == 1
        # Gap = |open(barre 2) - close(barre 1)|, et il est large.
        assert mesure.gap_moyen == pytest.approx(39.0), (
            "|open(barre 2) - close(barre 1)| = |140 - 101|"
        )

    def test_sans_fill_la_mesure_rend_none(self):
        store = magasin(n=400, avec_seance=True)
        assert franchissements_de_nuit({store.symbol: store}, [], 1) is None

    def test_un_fill_trop_tot_pour_avoir_une_decision_est_ignore(self):
        """`bar_index - lag` negatif : il n'y a pas de barre de decision."""
        store = magasin(n=400, avec_seance=True)
        mesure = franchissements_de_nuit({store.symbol: store}, [fill(0)], 2)
        assert mesure is not None
        assert mesure.n_franchissements == 0

    def test_elle_se_tait_quand_rien_ne_franchit(self):
        store = magasin(n=400, avec_seance=True)
        lignes = mesurer_les_silences(
            {store.symbol: store}, [fill(50)], 1
        ).render()
        assert not any("Nuit" in ligne for ligne in lignes)


class TestLaPerteParTroncature:
    """Mesuree dans `RiskStats`, hors `result_fingerprint`."""

    def test_aucune_taille_mesuree_rend_none(self):
        """Et non zero : « aucune regle ne divise » n'est pas « rien perdu »."""
        from rsl.engine.risk import RiskStats

        assert RiskStats().perte_par_troncature is None

    def test_elle_vaut_la_part_supprimee(self):
        from rsl.engine.risk import RiskStats

        stats = RiskStats()
        # Trois demandes de 1,5 contrat, trois executions a 1.
        stats.taille_brute_cumulee = 4.5
        stats.taille_entiere_cumulee = 3.0
        stats.n_tailles_mesurees = 3
        assert stats.perte_par_troncature == pytest.approx(1.0 / 3.0)

    def test_une_taille_deja_entiere_ne_perd_rien(self):
        from rsl.engine.risk import RiskStats

        stats = RiskStats()
        stats.taille_brute_cumulee = 6.0
        stats.taille_entiere_cumulee = 6.0
        stats.n_tailles_mesurees = 3
        assert stats.perte_par_troncature == pytest.approx(0.0)

    def test_elle_n_est_publiee_que_lorsqu_elle_existe(self):
        from rsl.engine.risk import RiskStats

        assert "perte_par_troncature" not in RiskStats().describe()
        stats = RiskStats()
        stats.taille_brute_cumulee = 2.0
        stats.taille_entiere_cumulee = 1.0
        stats.n_tailles_mesurees = 1
        decrit = stats.describe()
        assert decrit["perte_par_troncature"] == pytest.approx(0.5)
        assert decrit["n_tailles_mesurees"] == 1


class TestLesRegleQuiTronquentSaventleDire:
    """Chaque regle qui DIVISE expose sa taille avant troncature ; celle qui ne
    divise pas ne l'expose pas, et ne verse donc aucun zero dans la moyenne."""

    def test_fixed_contracts_ne_l_expose_pas(self):
        from rsl.engine.risk import FixedContracts

        assert not hasattr(FixedContracts(3), "taille_brute")

    @pytest.mark.parametrize(
        "fabrique",
        [
            lambda: __import__(
                "rsl.engine.risk", fromlist=["EquityFraction"]
            ).EquityFraction(0.5),
            lambda: __import__(
                "rsl.engine.risk", fromlist=["RiskFraction"]
            ).RiskFraction(0.01),
            lambda: __import__(
                "rsl.engine.risk", fromlist=["VolatilityTarget"]
            ).VolatilityTarget(0.02),
        ],
    )
    def test_les_autres_l_exposent(self, fabrique):
        assert callable(getattr(fabrique(), "taille_brute", None))
