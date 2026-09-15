"""Serie EXOGENE declaree : COT, open interest, sentiment.

Ce qui est en jeu
------------------
Une entree `data` est un parquet OHLCV ; `events` y a ajoute des INSTANTS.
Restait le dernier canal ferme du recensement : une grandeur CHIFFREE qui ne
vienne pas du prix. `evenements.py` nommait lui-meme ce manque - « ce module ne
sait rien dire d'un libelle ou d'une surprise chiffree ».

Le piege, et il n'est PAS celui des evenements
------------------------------------------------
Lire « la derniere valeur connue » ne regarde jamais l'avenir : c'est un
`searchsorted` vers la gauche, aussi causal qu'un `lag`. Le danger est ailleurs,
et il est pire parce qu'il est invisible dans le code.

Une donnee fondamentale porte DEUX dates : celle de ce qu'elle mesure, et celle
ou elle a ete publiee. Le rapport COT du mardi parait le vendredi. Un fichier
horodate a la date de MESURE fait entrer trois jours de futur ; le tableau est
trie, les valeurs sont justes, la lecture est causale, et le backtest est faux.

D'ou la regle que ces tests fixent : une source declare
`horodatee_a_la_publication: true` - une affirmation signee, comme
`known_in_advance` - OU un `publication_lag_minutes` strictement positif. Il
n'y a pas de troisieme possibilite, et le defaut ne passe pas.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from fixtures import synthetic
from rsl.data.exogene import (
    ChampExogene,
    SerieExogene,
    charger_serie_exogene,
)
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, Granularity
from rsl.errors import ConfigurationError, DataValidationError
from rsl.strategies.signals import build_signal

NS = 1_000_000_000
DEBUT = dt.datetime(2024, 3, 4, 9, 0, tzinfo=dt.UTC)


def instant(minutes: int) -> int:
    return int((DEBUT + dt.timedelta(minutes=minutes)).timestamp()) * NS


def magasin(n: int = 240) -> BarStore:
    ts = np.asarray([instant(m) for m in range(n)], dtype=np.int64)
    closes = synthetic.random_walk(n, 100.0, sigma=0.3, seed=71)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.002)
    return BarStore.build(
        symbol="EXO.v.0", granularity=Granularity.minutes(1), ts_event=ts,
        open_=o, high=h, low=low, close=c,
        volume=np.full(n, 10.0), source_hash="synthetic",
    )


def serie(
    points: list[tuple[int, float]],
    *,
    publiee: bool = True,
    decalage: int = 0,
) -> SerieExogene:
    return SerieExogene(
        name="cot_net",
        instants=np.asarray([instant(m) for m, _ in points], dtype=np.int64),
        valeurs=np.asarray([v for _, v in points], dtype=np.float64),
        horodatee_a_la_publication=publiee,
        publication_lag_minutes=decalage,
        source_hash="test",
    )


def au(store: BarStore, i: int, s: SerieExogene) -> BarContext:
    ctx = BarContext(store)
    ctx._seek(i)
    ctx._set_exogenes({s.name: s})
    return ctx


class TestLesDeuxChamps:
    def test_value_rend_la_derniere_valeur_publiee(self):
        store = magasin()
        s = serie([(30, 1_500.0), (90, -2_000.0)])
        # Barre 100 : cloture a la minute 101. La derniere publication est
        # celle de la minute 90.
        assert au(store, 100, s).exogenous_value("cot_net", ChampExogene.VALUE) == -2_000.0

    def test_elle_ne_change_pas_entre_deux_publications(self):
        store = magasin()
        s = serie([(30, 7.0), (90, 9.0)])
        valeurs = {
            au(store, i, s).exogenous_value("cot_net", ChampExogene.VALUE)
            for i in range(40, 80)
        }
        assert valeurs == {7.0}, "une serie exogene est en ESCALIER, pas interpolee"

    def test_age_minutes_compte_depuis_la_publication(self):
        store = magasin()
        s = serie([(30, 1.0)])
        assert au(store, 100, s).exogenous_value(
            "cot_net", ChampExogene.AGE_MINUTES
        ) == pytest.approx(71.0)

    def test_avant_la_premiere_publication_tout_rend_none(self):
        """Et non zero : « rien publie » n'est pas « valeur nulle »."""
        store = magasin()
        s = serie([(200, 5.0)])
        ctx = au(store, 10, s)
        assert ctx.exogenous_value("cot_net", ChampExogene.VALUE) is None
        assert ctx.exogenous_value("cot_net", ChampExogene.AGE_MINUTES) is None

    def test_une_publication_sur_la_barre_appartient_a_son_passe(self):
        """La barre est close, son prix est connu, la publication a eu lieu
        pendant qu'elle se formait. Meme convention que `evenements.py`."""
        store = magasin()
        s = serie([(30, 42.0)])
        ctx = au(store, 29, s)
        assert ctx.exogenous_value("cot_net", ChampExogene.VALUE) == 42.0
        assert ctx.exogenous_value(
            "cot_net", ChampExogene.AGE_MINUTES
        ) == pytest.approx(0.0)


class TestLeDecalageDePublication:
    """Le coeur du module : une donnee est connue APRES ce qu'elle mesure."""

    def test_le_decalage_retarde_la_valeur(self):
        store = magasin()
        s = serie([(30, 5.0)], publiee=False, decalage=60)
        # Mesuree a la minute 30, connaissable a la minute 90.
        assert au(store, 50, s).exogenous_value("cot_net", ChampExogene.VALUE) is None
        assert au(store, 100, s).exogenous_value("cot_net", ChampExogene.VALUE) == 5.0

    def test_l_age_se_compte_depuis_la_publication_pas_la_mesure(self):
        store = magasin()
        s = serie([(30, 5.0)], publiee=False, decalage=60)
        # Barre 100 -> cloture minute 101 ; connaissable depuis la minute 90.
        assert au(store, 100, s).exogenous_value(
            "cot_net", ChampExogene.AGE_MINUTES
        ) == pytest.approx(11.0)

    def test_sans_affirmation_ni_decalage_la_serie_est_refusee(self):
        """Il n'y a pas de troisieme possibilite, et le defaut ne passe pas."""
        with pytest.raises(ConfigurationError, match="publication_lag_minutes"):
            serie([(30, 1.0)], publiee=False, decalage=0)

    def test_affirmer_et_decaler_est_refuse(self):
        """Les deux ensemble se contredisent : `ts_event` ne peut pas etre a la
        fois l'instant de publication et en avoir besoin d'un decalage."""
        with pytest.raises(ConfigurationError, match="contredirait"):
            serie([(30, 1.0)], publiee=True, decalage=60)


class TestCeQueLeSocleRefuse:
    def test_une_serie_non_declaree_leve(self):
        store = magasin()
        ctx = BarContext(store)
        ctx._seek(10)
        with pytest.raises(ConfigurationError, match="aucune serie"):
            ctx.exogenous_value("cot_net", ChampExogene.VALUE)

    def test_le_message_nomme_les_series_declarees(self):
        store = magasin()
        with pytest.raises(ConfigurationError, match="cot_net"):
            au(store, 10, serie([(30, 1.0)])).exogenous_value(
                "open_interest", ChampExogene.VALUE
            )

    def test_une_serie_vide_est_refusee(self):
        with pytest.raises(ConfigurationError, match="aucune valeur"):
            SerieExogene(
                name="vide", instants=np.zeros(0, dtype=np.int64),
                valeurs=np.zeros(0, dtype=np.float64),
                horodatee_a_la_publication=True, publication_lag_minutes=0,
                source_hash="test",
            )

    def test_des_instants_non_tries_sont_refuses(self):
        with pytest.raises(DataValidationError, match="non tries"):
            serie([(90, 1.0), (30, 2.0)])

    def test_un_desaccord_de_longueur_est_refuse(self):
        with pytest.raises(DataValidationError, match="instants pour"):
            SerieExogene(
                name="bancale",
                instants=np.asarray([instant(30), instant(60)], dtype=np.int64),
                valeurs=np.asarray([1.0], dtype=np.float64),
                horodatee_a_la_publication=True, publication_lag_minutes=0,
                source_hash="test",
            )

    def test_une_valeur_non_finie_rend_none(self):
        """Un `nan` dans le fichier ne doit pas devenir un nombre."""
        store = magasin()
        s = serie([(30, float("nan"))])
        assert au(store, 100, s).exogenous_value("cot_net", ChampExogene.VALUE) is None


class TestLeNoeud:
    def test_il_lit_la_serie(self):
        store = magasin()
        spec = {"type": "exogenous", "name": "cot_net", "field": "value"}
        assert build_signal(spec)(au(store, 100, serie([(30, 3.5)]))) == 3.5

    def test_le_defaut_est_value(self):
        signal = build_signal({"type": "exogenous", "name": "cot_net"})
        assert signal.describe()["field"] == ChampExogene.VALUE.value

    def test_un_nom_vide_est_refuse(self):
        with pytest.raises(ConfigurationError, match="name"):
            build_signal({"type": "exogenous", "name": ""})

    def test_un_champ_inconnu_est_refuse(self):
        with pytest.raises(ConfigurationError, match="champ invalide"):
            build_signal({"type": "exogenous", "name": "x", "field": "demain"})

    def test_refuser_une_donnee_perimee_s_ecrit(self):
        """L'usage qui justifie `age_minutes` : une serie qui cesse d'etre
        alimentee rendrait sa derniere valeur indefiniment."""
        store = magasin()
        s = serie([(30, 1_000.0)])
        spec = {
            "type": "all_of",
            "operands": [
                {"type": "compare", "op": "<",
                 "left": {"type": "exogenous", "name": "cot_net",
                          "field": "age_minutes"},
                 "right": {"type": "constant", "value": 60.0}},
                {"type": "compare", "op": ">",
                 "left": {"type": "exogenous", "name": "cot_net"},
                 "right": {"type": "constant", "value": 0.0}},
            ],
        }
        signal = build_signal(spec)
        assert signal(au(store, 50, s)) == 1.0, "vingt et une minutes : fraiche"
        assert signal(au(store, 200, s)) == 0.0, "cent soixante et onze : perimee"

    def test_une_vue_reculee_voit_la_meme_serie(self):
        """`shifted` doit propager les series : sans cela, un `lag` sur un
        `exogenous` leverait, et le defaut serait silencieux dans un `rolling`."""
        store = magasin()
        s = serie([(30, 4.0), (90, 8.0)])
        spec = {"type": "lag", "bars": 20,
                "inner": {"type": "exogenous", "name": "cot_net"}}
        # Barre 100 reculee de 20 -> barre 80, cloture minute 81 : avant la
        # publication de la minute 90.
        assert build_signal(spec)(au(store, 100, s)) == 4.0


class TestLeChargement:
    def fichier(self, tmp_path, points: list[tuple[int, float]]):
        chemin = tmp_path / "cot.parquet"
        pl.DataFrame(
            {
                "ts_event": [instant(m) for m, _ in points],
                "value": [v for _, v in points],
            }
        ).write_parquet(chemin)
        return chemin

    def test_il_lit_les_deux_colonnes(self, tmp_path):
        s = charger_serie_exogene(
            self.fichier(tmp_path, [(30, 1.5), (90, -2.5)]),
            name="cot_net", horodatee_a_la_publication=True,
        )
        assert s.instants.tolist() == [instant(30), instant(90)]
        assert s.valeurs.tolist() == [1.5, -2.5]

    def test_il_hache_la_source(self, tmp_path):
        """La serie entre au manifeste comme les cotations : deux runs sur des
        series differentes ne peuvent pas se confondre."""
        s = charger_serie_exogene(
            self.fichier(tmp_path, [(30, 1.0)]),
            name="cot_net", horodatee_a_la_publication=True,
        )
        assert len(s.source_hash) == 64

    def test_un_fichier_absent_leve(self, tmp_path):
        with pytest.raises(ConfigurationError, match="introuvable"):
            charger_serie_exogene(
                tmp_path / "absent.parquet", name="x",
                horodatee_a_la_publication=True,
            )

    def test_une_colonne_manquante_leve_en_la_nommant(self, tmp_path):
        chemin = tmp_path / "mauvais.parquet"
        pl.DataFrame({"ts_event": [instant(1)]}).write_parquet(chemin)
        with pytest.raises(ConfigurationError, match="value"):
            charger_serie_exogene(
                chemin, name="x", horodatee_a_la_publication=True
            )
