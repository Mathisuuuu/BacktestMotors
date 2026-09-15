"""`rsl check` : les pieges du vocabulaire, dits AVANT le run.

Ce que ces tests fixent
------------------------
Chaque controle correspond a une trace datee du 2026-09-15, ou le defaut a
coute une enquete. Ils verifient les deux sens :

1. le controle MORD quand la situation est reunie ;
2. il se TAIT quand elle ne l'est pas.

Le second compte autant. Un controle qui parle toujours n'alerte plus - c'est
la meme regle que pour les compteurs de `metrics/silences.py`.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from fixtures import synthetic
from rsl.config import BacktestSpec
from rsl.controles import (
    Gravite,
    controler,
    noeuds,
    render,
)
from rsl.data.schema import BarStore, Granularity
from rsl.data.session import SessionCalendar, build_session_index

NS = 1_000_000_000


def magasin(n: int, *, minutes: int = 1, avec_seance: bool = True) -> BarStore:
    """`n` barres a partir de 09:31 New York. A 60 barres la seance s'arrete
    a 10:30, bien avant la fermeture declaree de 16:00 : aucune `is_last`."""
    depart = dt.datetime(2024, 3, 4, 14, 31, tzinfo=dt.UTC)
    ts = np.asarray(
        [int((depart + dt.timedelta(minutes=minutes * k)).timestamp()) * NS
         for k in range(n)],
        dtype=np.int64,
    )
    closes = synthetic.random_walk(n, 100.0, sigma=0.2, seed=29)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.002)
    store = BarStore.build(
        symbol="NQ.v.0", granularity=Granularity.minutes(minutes), ts_event=ts,
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


def vrai() -> dict:
    return {"type": "compare", "op": ">",
            "left": {"type": "price", "field": "close"},
            "right": {"type": "constant", "value": 0.0}}


def sortie_is_last() -> dict:
    return {"type": "compare", "op": "==",
            "left": {"type": "session", "field": "is_last", "lag": 0},
            "right": {"type": "constant", "value": 1.0}}


def specification(
    *,
    regles: dict | None = None,
    sizing: dict | None = None,
    session_only: bool = True,
    lag_bars: int = 1,
    max_fill_gap_seconds: int | None = None,
) -> BacktestSpec:
    execution: dict = {
        "fees": {"kind": "per_contract"},
        "slippage": {"kind": "zero"},
        "lag_bars": lag_bars,
    }
    if max_fill_gap_seconds is not None:
        execution["max_fill_gap_seconds"] = max_fill_gap_seconds
    brut: dict = {
        "name": "controle",
        "initial_cash": 500000.0,
        "execution": execution,
        "data": [
            {
                "root": "NQ",
                "path": "indices/NQ_v0_1m.parquet",
                "granularity_minutes": 1,
                "close_stamp": "period_end",
                "session": {"start": "09:30", "end": "16:00",
                            "timezone": "America/New_York"},
                "session_only": session_only,
            }
        ],
        "strategy": {
            "ref": "rules@1",
            "params": {
                "quantity": 1,
                "symbol": "NQ.v.0",
                "rules": regles or {"entry_long": vrai(), "exit_long": vrai()},
            },
        },
    }
    if sizing is not None:
        brut["risk"] = {"sizing": sizing}
    return BacktestSpec.model_validate(brut)


def codes(spec: BacktestSpec, store: BarStore) -> dict[str, Gravite]:
    return {c.code: c.gravite for c in controler(spec, {store.symbol: store})}


class TestLeParcoursDeLArbre:
    def test_il_trouve_les_noeuds_imbriques(self):
        arbre = {"type": "all_of", "operands": [
            {"type": "compare", "left": {"type": "price"}},
            {"type": "constant", "value": 1.0},
        ]}
        assert [n["type"] for n in noeuds(arbre)] == [
            "all_of", "compare", "price", "constant"
        ]

    def test_il_ignore_ce_qui_n_est_pas_un_noeud(self):
        assert list(noeuds({"note": ["texte"], "window": 60})) == []


class TestIsLastAbsent:
    """90 seances de NQ sur 2 748 n'ont aucune barre `is_last`."""

    def test_il_mord_sur_une_seance_ecourtee(self):
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()}
        )
        # 60 barres : la seance s'arrete a 10:30, jamais 16:00.
        resultat = codes(spec, magasin(60))
        assert resultat["is_last-absent"] is Gravite.ERREUR

    def test_il_se_tait_quand_toutes_les_seances_cloturent(self):
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()}
        )
        assert "is_last-absent" not in codes(spec, magasin(400))

    def test_il_se_tait_si_la_strategie_ne_cite_pas_is_last(self):
        assert "is_last-absent" not in codes(specification(), magasin(60))

    def test_le_message_nomme_la_regle_fautive(self):
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()}
        )
        constats = controler(spec, {"NQ.v.0": magasin(60)})
        faute = next(c for c in constats if c.code == "is_last-absent")
        assert "exit_long" in faute.message
        assert "PREMIERE barre" in faute.remede


class TestFillDeNuit:
    def test_il_mord_sur_une_sortie_a_la_derniere_barre(self):
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()}
        )
        assert codes(spec, magasin(400))["fill-de-nuit"] is Gravite.AVERTISSEMENT

    def test_une_garde_declaree_le_fait_taire(self):
        """`max_fill_gap_seconds` est la reponse ; l'avoir posee suffit."""
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()},
            max_fill_gap_seconds=300,
        )
        assert "fill-de-nuit" not in codes(spec, magasin(400))

    def test_il_ignore_une_entree_qui_cite_is_last(self):
        """Seule une SORTIE laisse une position traverser la nuit."""
        spec = specification(
            regles={"entry_long": sortie_is_last(), "exit_long": vrai()}
        )
        assert "fill-de-nuit" not in codes(spec, magasin(400))


class TestMinutesJamaisNulles:
    """`minutes_from_open` parcourt 1..N. Comparer a zero ne declenche jamais."""

    def test_il_mord_sur_une_egalite_a_zero(self):
        regle = {"type": "compare", "op": "==",
                 "left": {"type": "session", "field": "minutes_from_open",
                          "lag": 0},
                 "right": {"type": "constant", "value": 0.0}}
        spec = specification(regles={"entry_long": regle, "exit_long": vrai()})
        assert codes(spec, magasin(400))["minutes-jamais-nulles"] is Gravite.ERREUR

    def test_il_mord_sur_un_strictement_inferieur_a_zero(self):
        regle = {"type": "compare", "op": "<",
                 "left": {"type": "session", "field": "minutes_from_open",
                          "lag": 0},
                 "right": {"type": "constant", "value": 0.0}}
        spec = specification(regles={"entry_long": regle, "exit_long": vrai()})
        assert "minutes-jamais-nulles" in codes(spec, magasin(400))

    def test_il_se_tait_sur_une_comparaison_saine(self):
        regle = {"type": "compare", "op": ">=",
                 "left": {"type": "session", "field": "minutes_from_open",
                          "lag": 0},
                 "right": {"type": "constant", "value": 30.0}}
        spec = specification(regles={"entry_long": regle, "exit_long": vrai()})
        assert "minutes-jamais-nulles" not in codes(spec, magasin(400))


class TestVolTargetEnBarres:
    def test_il_mord_sur_des_barres_intra_journalieres(self):
        spec = specification(
            sizing={"kind": "vol_target", "vol_target": 0.02, "vol_window": 60}
        )
        resultat = codes(spec, magasin(400, minutes=1))
        assert resultat["vol-target-en-barres"] is Gravite.AVERTISSEMENT

    def test_il_se_tait_sur_un_autre_dimensionnement(self):
        spec = specification(sizing={"kind": "fixed", "contracts": 1})
        assert "vol-target-en-barres" not in codes(spec, magasin(400))


class TestSeanceElectronique:
    """Sans `session_only`, NQ rendait 3 314 seances dont 548 de DIMANCHE."""

    def test_il_mord_quand_le_filtre_manque(self):
        spec = specification(session_only=False)
        resultat = codes(spec, magasin(400))
        assert resultat["seance-electronique"] is Gravite.AVERTISSEMENT

    def test_il_se_tait_quand_le_filtre_est_pose(self):
        assert "seance-electronique" not in codes(
            specification(session_only=True), magasin(400)
        )


class TestRollingRank:
    def test_il_signale_que_le_rang_est_temporel(self):
        regle = {"type": "compare", "op": ">",
                 "left": {"type": "rolling", "stat": "rank", "window": 20,
                          "inner": {"type": "price", "field": "close"}},
                 "right": {"type": "constant", "value": 0.8}}
        spec = specification(regles={"entry_long": regle, "exit_long": vrai()})
        assert codes(spec, magasin(400))["rank-temporel"] is Gravite.INFO


class TestLeRendu:
    def test_le_silence_se_dit(self):
        """Une sortie vide se lit comme « la commande n'a rien fait »."""
        assert "Aucun constat" in render([])

    def test_chaque_constat_porte_un_remede(self):
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()},
            session_only=False,
        )
        constats = controler(spec, {"NQ.v.0": magasin(60)})
        assert constats, "le decor doit faire mordre au moins un controle"
        for constat in constats:
            assert constat.remede.strip(), constat.code

    def test_les_erreurs_viennent_en_tete(self):
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()},
            session_only=False,
        )
        constats = controler(spec, {"NQ.v.0": magasin(60)})
        gravites = [c.gravite for c in constats]
        assert gravites[0] is Gravite.ERREUR

    def test_le_total_est_imprime(self):
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()}
        )
        sortie = render(controler(spec, {"NQ.v.0": magasin(60)}))
        assert "erreur(s)" in sortie


class TestSansSeanceDeclaree:
    """Sans calendrier, les controles de seance n'ont pas d'objet."""

    def test_aucun_controle_de_seance_ne_mord(self):
        spec = specification(
            regles={"entry_long": vrai(), "exit_long": sortie_is_last()}
        )
        resultat = codes(spec, magasin(60, avec_seance=False))
        assert "is_last-absent" not in resultat


@pytest.mark.parametrize("n_barres", [60, 400])
def test_la_specification_saine_ne_produit_aucune_erreur(n_barres: int):
    """Le cas nominal : rien a dire, et la commande le dit."""
    constats = controler(specification(), {"NQ.v.0": magasin(n_barres)})
    assert not [c for c in constats if c.gravite is Gravite.ERREUR]
