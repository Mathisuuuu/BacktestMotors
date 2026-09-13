"""Le tampon de seance de `cumulative` : rapide, et IDENTIQUE au bit pres.

Ce qui est en jeu
------------------
`cumulative` rassemblait ses valeurs par une boucle Python, une iteration par
barre ecoulee depuis l'ouverture. Sur un VWAP ancre a la seance, mesure le
2026-09-13 : **1249 us par barre**, contre 0,05 us pour l'equivalent vectorise.

Le correctif tient en deux etapes, et la seconde est celle que ce fichier
garde : un tampon numpy par seance, qui n'ajoute qu'UNE valeur par barre
nouvelle. 1249 -> 36,5 us, soit 34 fois.

Le danger de ce genre de correctif
-----------------------------------
Un accumulateur courant - ajouter la valeur nouvelle a un total - aurait ete
plus rapide encore et AURAIT CHANGE LE RESULTAT : `np.sum` somme par paires,
l'addition sequentielle non, et les derniers bits different. Sur dix ans de
barres minute, cette difference se voit.

Le tampon garde donc les VALEURS et laisse numpy reduire. Ce fichier verifie
que les trois chemins du tampon - deja connu, une barre a ajouter,
reconstruction - rendent exactement la meme chose, et que l'ORDRE est preserve
(present en tete), puisque le groupement de la sommation par paires en depend.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, Granularity
from rsl.data.session import SessionCalendar, build_session_index
from rsl.strategies.signals import build_signal

MINUTE = Granularity.minutes(1)
EPOCH = datetime(2020, 1, 6, 9, 0, tzinfo=UTC)
SEANCE = SessionCalendar(start="09:00", end="17:00", timezone="UTC")


def serie(n_seances: int = 3, minutes: int = 120) -> BarStore:
    """Des seances contigues de barres d'une minute, la nuit etant un trou."""
    horodatages: list[int] = []
    for jour in range(n_seances):
        base = int((EPOCH + timedelta(days=jour)).timestamp()) * 1_000_000_000
        horodatages.extend(base + m * 60 * 1_000_000_000 for m in range(minutes))
    ts = np.asarray(horodatages, dtype=np.int64)
    closes = synthetic.random_walk(ts.size, 100.0, sigma=0.5, seed=7)
    opens, highs, lows, closes_ = synthetic.ohlc_from_closes(closes, wick=0.002)
    store = BarStore.build(
        symbol="SES.v.0", granularity=MINUTE, ts_event=ts,
        open_=opens, high=highs, low=lows, close=closes_,
        volume=np.full(ts.size, 10.0), source_hash="synthetic",
    )
    return store.with_sessions(
        build_session_index(
            store.ts_close, store.open, store.high, store.low,
            store.close, store.volume, SEANCE,
        )
    )


VWAP = {
    "type": "arith", "op": "/",
    "left": {
        "type": "cumulative", "stat": "sum",
        "inner": {
            "type": "arith", "op": "*",
            "left": {
                "type": "arith", "op": "/",
                "left": {
                    "type": "arith", "op": "+",
                    "left": {
                        "type": "arith", "op": "+",
                        "left": {"type": "price", "field": "high"},
                        "right": {"type": "price", "field": "low"},
                    },
                    "right": {"type": "price", "field": "close"},
                },
                "right": {"type": "constant", "value": 3.0},
            },
            "right": {"type": "price", "field": "volume"},
        },
    },
    "right": {
        "type": "cumulative", "stat": "sum",
        "inner": {"type": "price", "field": "volume"},
    },
}


def parcourir(spec: dict, store: BarStore, depart: int = 0) -> list[float | None]:
    """Evalue le signal a chaque barre, dans l'ordre, avec UN seul noeud.

    L'ordre compte : c'est lui qui fait vivre le tampon. Construire un noeud
    neuf a chaque barre le viderait et testerait le chemin lent."""
    signal = build_signal(spec)
    ctx = BarContext(store)
    valeurs: list[float | None] = []
    for i in range(depart, store.n_bars):
        ctx._seek(i)
        valeurs.append(signal(ctx))
    return valeurs


def parcourir_sans_tampon(spec: dict, store: BarStore, depart: int = 0):
    """Le TEMOIN : un noeud neuf a chaque barre, donc un tampon toujours vide.

    Force le chemin de reconstruction - celui d'avant le correctif - a chaque
    evaluation. Sans ce temoin, l'egalite testee plus bas ne prouverait rien :
    on comparerait le tampon a lui-meme.
    """
    ctx = BarContext(store)
    valeurs: list[float | None] = []
    for i in range(depart, store.n_bars):
        ctx._seek(i)
        valeurs.append(build_signal(spec)(ctx))
    return valeurs


class TestLeTamponNeChangeRien:
    """L'invariant qui compte : meme resultat, au BIT pres."""

    def test_le_vwap_ancre_est_identique_avec_et_sans_tampon(self):
        store = serie()
        avec = parcourir(VWAP, store)
        sans = parcourir_sans_tampon(VWAP, store)
        assert len(avec) == len(sans) == store.n_bars
        for i, (a, s) in enumerate(zip(avec, sans, strict=True)):
            assert a == s, f"barre {i} : {a!r} avec tampon, {s!r} sans"

    def test_l_egalite_est_binaire_et_non_approchee(self):
        """`==` et non `approx` : le correctif promet l'identite, pas la
        proximite. Une tolerance masquerait exactement ce qu'on craint."""
        store = serie()
        avec = [v for v in parcourir(VWAP, store) if v is not None]
        sans = [v for v in parcourir_sans_tampon(VWAP, store) if v is not None]
        assert avec == sans
        assert any(v != 0.0 for v in avec), "le signal doit produire des valeurs"

    @pytest.mark.parametrize(
        "stat", ["sum", "mean", "min", "max", "first", "last", "count_true"]
    )
    def test_chaque_statistique_est_identique(self, stat):
        """Les sept, et pas seulement `sum` : `first` et `last` lisent par
        INDEX dans la fenetre, donc ils dependent de son ordre."""
        spec = {
            "type": "cumulative", "stat": stat,
            "inner": {"type": "price", "field": "close"},
        }
        store = serie(2, 90)
        assert parcourir(spec, store) == parcourir_sans_tampon(spec, store)


class TestLOrdreDeLaFenetre:
    """Present EN TETE : `np.sum` somme par paires, le groupement en depend."""

    def test_last_rend_la_barre_courante(self):
        """`last` lit `fenetre[0]`. Si l'ordre etait inverse, il rendrait
        l'ouverture de seance - une erreur qui passerait inapercue sur une
        serie plate."""
        store = serie(1, 60)
        spec = {
            "type": "cumulative", "stat": "last",
            "inner": {"type": "price", "field": "close"},
        }
        obtenues = parcourir(spec, store)
        closes = np.asarray(store.close)
        for i, v in enumerate(obtenues):
            assert v == pytest.approx(float(closes[i]))

    def test_first_rend_l_ouverture_de_la_seance(self):
        store = serie(2, 60)
        spec = {
            "type": "cumulative", "stat": "first",
            "inner": {"type": "price", "field": "close"},
        }
        obtenues = parcourir(spec, store)
        closes = np.asarray(store.close)
        # Deux seances de 60 barres : la seconde repart a l'indice 60.
        assert obtenues[59] == pytest.approx(float(closes[0]))
        assert obtenues[60] == pytest.approx(float(closes[60]))

    def test_le_cumul_repart_a_zero_a_chaque_seance(self):
        """La propriete qui definit `cumulative`, et que le tampon pourrait
        casser en gardant les valeurs de la seance precedente."""
        store = serie(3, 40)
        spec = {
            "type": "cumulative", "stat": "sum",
            "inner": {"type": "constant", "value": 1.0},
        }
        obtenues = parcourir(spec, store)
        # A la premiere barre de chaque seance, le cumul vaut exactement 1.
        for debut in (0, 40, 80):
            assert obtenues[debut] == pytest.approx(1.0), f"barre {debut}"
        assert obtenues[39] == pytest.approx(40.0)


class TestLesTroisCheminsDuTampon:
    """Deja connu, une barre a ajouter, reconstruction."""

    def test_une_vue_reculee_ne_corrompt_pas_le_tampon(self):
        """Un `lag` place le contexte en arriere dans la MEME seance. Le tampon
        doit servir une tranche, pas se reconstruire ni se tronquer."""
        spec = {
            "type": "arith", "op": "-",
            "left": {
                "type": "cumulative", "stat": "sum",
                "inner": {"type": "price", "field": "volume"},
            },
            "right": {
                "type": "lag", "bars": 5,
                "inner": {
                    "type": "cumulative", "stat": "sum",
                    "inner": {"type": "price", "field": "volume"},
                },
            },
        }
        store = serie(2, 60)
        # Depart APRES le warmup declare : un `lag` de 5 a la barre 0 est refuse
        # par le socle, et a raison. Ce test porte sur le tampon, pas sur le
        # bornage - le confondre le rendrait vert pour une autre raison.
        depart = build_signal(spec).warmup_bars
        assert parcourir(spec, store, depart) == parcourir_sans_tampon(spec, store, depart)

    def test_un_cumulative_sous_un_rolling_reste_juste(self):
        """Le cas le plus dur : `rolling` remonte le temps a chaque barre, donc
        le tampon est sollicite hors sequence."""
        spec = {
            "type": "rolling", "stat": "mean", "window": 10,
            "inner": {
                "type": "cumulative", "stat": "sum",
                "inner": {"type": "price", "field": "volume"},
            },
        }
        store = serie(2, 60)
        depart = build_signal(spec).warmup_bars
        assert parcourir(spec, store, depart) == parcourir_sans_tampon(spec, store, depart)

    def test_le_tampon_grandit_sans_perdre_de_valeur(self):
        """La croissance geometrique reallouee ne doit rien tronquer : une
        seance de 200 barres depasse la capacite initiale de 64."""
        store = serie(1, 200)
        spec = {
            "type": "cumulative", "stat": "sum",
            "inner": {"type": "constant", "value": 1.0},
        }
        obtenues = parcourir(spec, store)
        assert obtenues[-1] == pytest.approx(200.0)
        assert obtenues[99] == pytest.approx(100.0)
