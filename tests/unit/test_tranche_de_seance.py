"""Agreger sur une TRANCHE de seance : `cumulative.mask` et `arith %`.

Ce qui est en jeu
------------------
Toute la famille « opening range » demande un agregat sur une PARTIE de la
seance - le plus haut des trente premieres minutes, l'etendue de la premiere
heure, le VWAP de l'ouverture. Avant le 2026-09-14, cela s'ecrivait par une
sentinelle :

    cumulative(max, if_then_else(mfo <= 30, price(high), constant(-1e18)))

Cet artifice fonctionne tant que la tranche contient au moins une barre, et
produit un NOMBRE quand elle est vide. Mesure du 2026-09-14 : une tranche vide
rendait **-1e+18**, et la regle `cours > cette borne` valait vrai a chaque
barre. Le backtest ouvrait des positions partout, sans erreur ni avertissement.
C'est la famille L18 / L25 / L28 - un defaut qui produit un nombre lisible.

Les deux proprietes que ce fichier fixe
----------------------------------------
1. **Equivalence** : la ou la sentinelle est juste, le masque rend EXACTEMENT
   la meme chose. Sans cela, l'ajout serait un changement de comportement
   deguise en correction.
2. **Honnetete** : la ou la sentinelle ment, le masque rend `None`.

Sans la premiere, la seconde ne prouverait rien : on pourrait rendre `None`
partout et passer le test.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, Granularity
from rsl.data.session import SessionCalendar, build_session_index
from rsl.errors import ConfigurationError
from rsl.strategies.signals import build_signal

NS = 1_000_000_000
SEANCE = SessionCalendar(start="09:00", end="16:00", timezone="UTC")
PAR_SEANCE = 120


def magasin(n_seances: int = 6) -> BarStore:
    """Des seances contigues de 120 barres d'une minute, la nuit etant un trou."""
    horodatages: list[int] = []
    base = dt.datetime(2024, 1, 2, 9, 0, tzinfo=dt.UTC)
    for jour in range(n_seances):
        debut = int((base + dt.timedelta(days=jour)).timestamp())
        horodatages.extend((debut + m * 60) * NS for m in range(PAR_SEANCE))
    ts = np.asarray(horodatages, dtype=np.int64)
    closes = synthetic.random_walk(ts.size, 100.0, sigma=0.4, seed=23)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.004)
    store = BarStore.build(
        symbol="TRA.v.0", granularity=Granularity.minutes(1), ts_event=ts,
        open_=o, high=h, low=low, close=c,
        volume=np.full(ts.size, 10.0), source_hash="synthetic",
    )
    return store.with_sessions(
        build_session_index(
            store.ts_close, store.open, store.high, store.low,
            store.close, store.volume, SEANCE,
        )
    )


def au(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    ctx._seek(index)
    return ctx


MFO = {"type": "session", "field": "minutes_from_open", "lag": 0}
HIGH = {"type": "price", "field": "high", "lag": 0}
LOW = {"type": "price", "field": "low", "lag": 0}


def const(v: float) -> dict:
    return {"type": "constant", "value": float(v)}


def avant(minutes: float) -> dict:
    return {"type": "compare", "op": "<=", "left": MFO, "right": const(minutes)}


def par_masque(stat: str, champ: dict, minutes: float) -> dict:
    return {
        "type": "cumulative", "stat": stat, "inner": champ, "mask": avant(minutes),
    }


def par_sentinelle(stat: str, champ: dict, minutes: float) -> dict:
    """L'ecriture d'avant : un `if_then_else` avec une valeur neutre."""
    garde = const(-1e18) if stat == "max" else const(1e18)
    return {
        "type": "cumulative", "stat": stat,
        "inner": {
            "type": "if_then_else", "condition": avant(minutes),
            "then": champ, "otherwise": garde,
        },
    }


def parcourir(spec: dict, store: BarStore, depart: int = 0) -> list[float | None]:
    """Evalue avec UN SEUL noeud, dans l'ordre : c'est ce qui fait vivre le
    tampon de seance. En construire un neuf a chaque barre testerait le chemin
    lent et masquerait toute erreur de cache."""
    signal = build_signal(spec)
    ctx = BarContext(store)
    valeurs: list[float | None] = []
    for i in range(depart, store.n_bars):
        ctx._seek(i)
        valeurs.append(signal(ctx))
    return valeurs


class TestLeMasqueReproduitLArtificeQuandCeluiCiEstJuste:
    """Sans cette equivalence, l'ajout serait un changement de comportement."""

    @pytest.mark.parametrize(("stat", "champ"), [("max", HIGH), ("min", LOW)])
    @pytest.mark.parametrize("minutes", [1, 5, 30, 60, 119])
    def test_meme_resultat_au_bit_pres(self, stat, champ, minutes):
        store = magasin()
        masque = parcourir(par_masque(stat, champ, minutes), store)
        sentinelle = parcourir(par_sentinelle(stat, champ, minutes), store)
        assert masque == sentinelle

    def test_et_ces_valeurs_ne_sont_pas_toutes_none(self):
        """Garde-fou du test precedent : deux listes de `None` seraient egales."""
        valeurs = parcourir(par_masque("max", HIGH, 30), magasin())
        assert sum(v is not None for v in valeurs) > 500

    def test_la_borne_se_fige_apres_la_tranche(self):
        """La propriete qui definit un opening range : une fois les trente
        premieres minutes passees, la borne ne bouge plus de la seance."""
        store = magasin(2)
        valeurs = parcourir(par_masque("max", HIGH, 30), store)
        seance = valeurs[:PAR_SEANCE]
        apres = [v for v in seance[31:] if v is not None]
        assert len(set(apres)) == 1, "la borne a bouge apres la 30e minute"

    def test_elle_repart_a_chaque_seance(self):
        store = magasin(3)
        valeurs = parcourir(par_masque("max", HIGH, 10), store)
        bornes = {valeurs[PAR_SEANCE * j + 50] for j in range(3)}
        assert len(bornes) == 3, f"la borne n'a pas repart : {bornes}"


class TestLeMasqueEstHonneteQuandLArtificeMent:
    """Le cas qui a motive l'ajout."""

    JAMAIS: ClassVar[dict] = {
        "type": "cumulative", "stat": "max", "inner": HIGH,
        # `minutes_from_open` est positif : la condition n'est jamais vraie.
        "mask": {"type": "compare", "op": "<", "left": MFO, "right": const(-1)},
    }

    def test_une_tranche_vide_rend_none(self):
        valeurs = parcourir(self.JAMAIS, magasin(2))
        assert all(v is None for v in valeurs)

    def test_la_sentinelle_rendait_un_nombre_sur_le_meme_cas(self):
        """Ce test ne verifie pas un correctif : il FIGE le defaut qu'on evite.

        S'il devenait vert par accident - parce que quelqu'un a rendu
        `if_then_else` plus prudent - l'argument en faveur du masque aurait
        change et il faudrait le rediscuter, pas le supprimer en silence.
        """
        sentinelle = {
            "type": "cumulative", "stat": "max",
            "inner": {
                "type": "if_then_else",
                "condition": {"type": "compare", "op": "<", "left": MFO, "right": const(-1)},
                "then": HIGH, "otherwise": const(-1e18),
            },
        }
        store = magasin(2)
        valeur = build_signal(sentinelle)(au(store, 200))
        assert valeur == -1e18, "le defaut historique a change de forme"

        regle = {
            "type": "compare", "op": ">",
            "left": {"type": "price", "field": "close", "lag": 0},
            "right": sentinelle,
        }
        assert build_signal(regle)(au(store, 200)) == 1.0, (
            "la regle valait VRAI partout : c'est ce que le masque supprime"
        )

    def test_une_regle_batie_sur_le_masque_ne_declenche_pas(self):
        regle = {
            "type": "compare", "op": ">",
            "left": {"type": "price", "field": "close", "lag": 0},
            "right": self.JAMAIS,
        }
        assert build_signal(regle)(au(magasin(2), 200)) is None


class TestCeQueLeMasqueNeChangePas:
    def test_sans_masque_le_comportement_est_celui_d_avant(self):
        store = magasin(3)
        spec = {"type": "cumulative", "stat": "sum", "inner": const(1.0)}
        valeurs = parcourir(spec, store)
        # Le cumul compte les barres de la seance, et repart a 1.
        assert valeurs[0] == pytest.approx(1.0)
        assert valeurs[PAR_SEANCE - 1] == pytest.approx(float(PAR_SEANCE))
        assert valeurs[PAR_SEANCE] == pytest.approx(1.0)

    def test_le_champ_n_est_pas_publie_quand_il_est_absent(self):
        """Sinon les sept `config_hash` archives changeraient pour un champ qui
        ne dit rien chez eux."""
        sans = build_signal({"type": "cumulative", "stat": "sum", "inner": HIGH})
        assert "mask" not in sans.describe()

    def test_il_est_publie_quand_il_existe(self):
        avec = build_signal(par_masque("max", HIGH, 30))
        assert "mask" in avec.describe()

    def test_le_warmup_tient_compte_du_masque(self):
        """Un masque qui regarde en arriere impose son propre warmup."""
        spec = {
            "type": "cumulative", "stat": "max", "inner": HIGH,
            "mask": {
                "type": "compare", "op": ">",
                "left": {"type": "price", "field": "close", "lag": 40},
                "right": const(0.0),
            },
        }
        assert build_signal(spec).warmup_bars >= 41


class TestLeModulo:
    """`arith %` : les grilles horaires periodiques, en trois noeuds."""

    def test_il_selectionne_une_barre_sur_n(self):
        spec = {
            "type": "compare", "op": "==",
            "left": {"type": "arith", "op": "%", "left": MFO, "right": const(30)},
            "right": const(0.0),
        }
        store = magasin(2)
        valeurs = parcourir(spec, store)
        vrais = [i for i, v in enumerate(valeurs[:PAR_SEANCE]) if v == 1.0]
        # Les indices sont 29, 59, 89, 119 et NON 0, 30, 60, 90 : une barre est
        # horodatee a sa CLOTURE, donc la premiere barre de la seance a deja
        # une minute d'age. `minutes_from_open` parcourt 1..120, jamais 0.
        #
        # C'est le choix causal correct - le point de controle « 30 minutes
        # apres l'ouverture » est la barre qui SE FERME a cette minute, pas
        # celle qui s'ouvre avec elle et dont on ne sait encore rien.
        assert vrais == [29, 59, 89, 119]
        assert [valeurs.index(v) for v in valeurs[:1]] == [0]  # la liste est dense

    def test_il_remplace_douze_comparaisons_par_trois_noeuds(self):
        """Le gain reel : la specification Zarattini portait quatre jeux de
        douze comparaisons pour dire « toutes les trente minutes »."""
        grille = {
            "type": "all_of",
            "operands": [
                {"type": "compare", "op": ">=", "left": MFO, "right": const(30)},
                {"type": "compare", "op": "<=", "left": MFO, "right": const(90)},
                {
                    "type": "compare", "op": "==",
                    "left": {"type": "arith", "op": "%", "left": MFO, "right": const(30)},
                    "right": const(0.0),
                },
            ],
        }
        enumeration = {
            "type": "any_of",
            "operands": [
                {"type": "compare", "op": "==", "left": MFO, "right": const(m)}
                for m in (30, 60, 90)
            ],
        }
        store = magasin(2)
        assert parcourir(grille, store) == parcourir(enumeration, store)

    def test_un_modulo_par_zero_rend_none(self):
        """Comme la division, et pour la meme raison : il n'y a pas de reponse,
        et `nan` en serait une fausse."""
        spec = {"type": "arith", "op": "%", "left": MFO, "right": const(0.0)}
        assert build_signal(spec)(au(magasin(2), 200)) is None

    def test_le_signe_suit_le_diviseur(self):
        """Semantique Python, fixee explicitement : `-10 % 30` vaut 20.

        Sur des grandeurs de seance, qui sont positives, la question ne se pose
        pas. Elle est figee ici pour que le jour ou elle se pose, la reponse ne
        depende pas d'une lecture du code.
        """
        spec = {"type": "arith", "op": "%", "left": const(-10.0), "right": const(30.0)}
        assert build_signal(spec)(au(magasin(2), 200)) == pytest.approx(20.0)

    def test_l_operateur_inconnu_reste_refuse(self):
        with pytest.raises(ConfigurationError, match="operateur invalide"):
            build_signal({"type": "arith", "op": "**", "left": MFO, "right": const(2)})
