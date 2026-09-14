"""Calendrier d'ANNONCES declare : FOMC, NFP, publications.

Ce qui est en jeu
------------------
Une entree `data` est un parquet OHLCV. Sur futures intraday, cela laissait hors
d'atteinte toute la famille des strategies qui se positionnent autour d'une
annonce macro - la derniere des quatre familles bloquees par le recensement du
2026-09-14 que le perimetre declare ne rendait pas sans objet.

La question de causalite, et comment elle est tranchee
-------------------------------------------------------
« Combien de minutes avant la prochaine annonce » lit un instant FUTUR. Ce n'est
pas pour autant du look-ahead : un calendrier economique est publie a l'avance,
et savoir que le FOMC parle a 14 h ne dit rien du prix qu'il fera.

Mais cette propriete depend du FICHIER, pas du socle. Un calendrier reconstruit
apres coup ferait entrer du futur sans qu'aucune inspection du code ne le voie.
D'ou la regle que ces tests fixent : `minutes_since` est toujours lisible,
`minutes_until` **exige** que la source declare `known_in_advance`.

Ce n'est pas une garantie. C'est une affirmation signee, qui entre dans le
`config_hash` et engage celui qui l'ecrit.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from fixtures import synthetic
from rsl.data.evenements import (
    EventCalendar,
    EventField,
    charger_calendrier,
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
    """Des barres d'une minute, sans seance declaree : le calendrier n'en a
    pas besoin - il ne depend que de l'horodatage de cloture."""
    ts = np.asarray([instant(m) for m in range(n)], dtype=np.int64)
    closes = synthetic.random_walk(n, 100.0, sigma=0.3, seed=61)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.002)
    return BarStore.build(
        symbol="EVT.v.0", granularity=Granularity.minutes(1), ts_event=ts,
        open_=o, high=h, low=low, close=c,
        volume=np.full(n, 10.0), source_hash="synthetic",
    )


def calendrier(minutes: list[int], *, en_avance: bool = True) -> EventCalendar:
    return EventCalendar(
        name="fomc",
        instants=np.asarray([instant(m) for m in minutes], dtype=np.int64),
        known_in_advance=en_avance,
        source_hash="test",
    )


def au(store: BarStore, i: int, cal: EventCalendar) -> BarContext:
    ctx = BarContext(store)
    ctx._seek(i)
    ctx._set_events({cal.name: cal})
    return ctx


class TestLesTroisChamps:
    CAL = None

    def test_minutes_since_compte_depuis_la_derniere(self):
        store, cal = magasin(), calendrier([30, 90])
        ctx = au(store, 100, cal)
        # Barre 100 : cloture a la minute 101 (horodatage de cloture).
        assert ctx.event_value("fomc", EventField.MINUTES_SINCE) == pytest.approx(11.0)

    def test_minutes_until_compte_jusqu_a_la_prochaine(self):
        store, cal = magasin(), calendrier([30, 90])
        ctx = au(store, 50, cal)
        assert ctx.event_value("fomc", EventField.MINUTES_UNTIL) == pytest.approx(39.0)

    def test_is_now_ne_vaut_1_que_sur_la_barre_de_l_annonce(self):
        store, cal = magasin(), calendrier([30])
        vrais = [
            i for i in range(60)
            if au(store, i, cal).event_value("fomc", EventField.IS_NOW) == 1.0
        ]
        assert vrais == [29], "une seule barre, celle qui CLOTURE a la minute 30"

    def test_avant_la_premiere_annonce_minutes_since_rend_none(self):
        """Et non zero : « aucune annonce passee » n'est pas « annonce a
        l'instant »."""
        store, cal = magasin(), calendrier([200])
        assert au(store, 10, cal).event_value("fomc", EventField.MINUTES_SINCE) is None

    def test_apres_la_derniere_minutes_until_rend_none(self):
        store, cal = magasin(), calendrier([30])
        assert au(store, 100, cal).event_value("fomc", EventField.MINUTES_UNTIL) is None


class TestLaCausalite:
    """La regle qui empeche un calendrier reconstruit de faire fuiter du futur."""

    def test_minutes_until_est_refuse_sans_declaration(self):
        store, cal = magasin(), calendrier([90], en_avance=False)
        with pytest.raises(ConfigurationError, match="known_in_advance"):
            au(store, 10, cal).event_value("fomc", EventField.MINUTES_UNTIL)

    def test_minutes_since_reste_lisible_sans_declaration(self):
        """Il ne regarde que le passe : aucune affirmation n'est necessaire."""
        store, cal = magasin(), calendrier([30], en_avance=False)
        assert au(store, 100, cal).event_value(
            "fomc", EventField.MINUTES_SINCE
        ) == pytest.approx(71.0)

    def test_is_now_reste_lisible_sans_declaration(self):
        store, cal = magasin(), calendrier([30], en_avance=False)
        assert au(store, 29, cal).event_value("fomc", EventField.IS_NOW) == 1.0

    def test_une_annonce_sur_la_barre_appartient_a_son_passe(self):
        """La barre est close, son prix est connu, l'annonce a eu lieu pendant
        qu'elle se formait. `minutes_since` vaut donc zero, pas `minutes_until`."""
        store, cal = magasin(), calendrier([30])
        ctx = au(store, 29, cal)
        assert ctx.event_value("fomc", EventField.MINUTES_SINCE) == pytest.approx(0.0)
        assert ctx.event_value("fomc", EventField.MINUTES_UNTIL) is None


class TestCeQueLeSocleRefuse:
    def test_un_calendrier_non_declare_leve(self):
        """Le socle ne devine pas plus un calendrier d'annonces qu'une seance."""
        store = magasin()
        ctx = BarContext(store)
        ctx._seek(10)
        with pytest.raises(ConfigurationError, match="aucun calendrier"):
            ctx.event_value("fomc", EventField.MINUTES_SINCE)

    def test_le_message_nomme_les_calendriers_declares(self):
        store, cal = magasin(), calendrier([30])
        with pytest.raises(ConfigurationError, match="fomc"):
            au(store, 10, cal).event_value("nfp", EventField.MINUTES_SINCE)

    def test_un_calendrier_vide_est_refuse(self):
        """Il rendrait `None` partout, ce qui se lit comme « la strategie n'a
        pas declenche » plutot que comme « le fichier est vide »."""
        with pytest.raises(ConfigurationError, match="aucun evenement"):
            EventCalendar(name="vide", instants=np.zeros(0, dtype=np.int64),
                          known_in_advance=True, source_hash="test")

    def test_des_instants_non_tries_sont_refuses(self):
        """Le loader ne trie pas : un fichier desordonne est une source
        douteuse, pas une source a reparer."""
        with pytest.raises(DataValidationError, match="non tries"):
            EventCalendar(
                name="desordre",
                instants=np.asarray([instant(90), instant(30)], dtype=np.int64),
                known_in_advance=True, source_hash="test",
            )


class TestLeNoeud:
    def test_il_lit_le_calendrier(self):
        store, cal = magasin(), calendrier([30])
        spec = {"type": "event", "name": "fomc", "field": "minutes_since"}
        assert build_signal(spec)(au(store, 100, cal)) == pytest.approx(71.0)

    def test_le_defaut_est_minutes_since(self):
        """Le seul champ toujours causal : c'est le bon defaut."""
        signal = build_signal({"type": "event", "name": "fomc"})
        assert signal.describe()["field"] == EventField.MINUTES_SINCE.value

    def test_un_nom_vide_est_refuse(self):
        with pytest.raises(ConfigurationError, match="name"):
            build_signal({"type": "event", "name": ""})

    def test_un_champ_inconnu_est_refuse(self):
        with pytest.raises(ConfigurationError, match="champ invalide"):
            build_signal({"type": "event", "name": "fomc", "field": "demain"})

    def test_il_se_compose_comme_tout_le_reste(self):
        """« Ne pas negocier dans les trente minutes qui suivent une annonce »."""
        store, cal = magasin(), calendrier([30])
        spec = {
            "type": "compare", "op": ">",
            "left": {"type": "event", "name": "fomc", "field": "minutes_since"},
            "right": {"type": "constant", "value": 30.0},
        }
        signal = build_signal(spec)
        assert signal(au(store, 40, cal)) == 0.0, "onze minutes apres"
        assert signal(au(store, 70, cal)) == 1.0, "quarante et une minutes apres"

    def test_une_vue_reculee_voit_le_meme_calendrier(self):
        """`shifted` doit propager les calendriers : sans cela, `lag` sur un
        `event` leverait, et le defaut serait silencieux dans un `rolling`."""
        store, cal = magasin(), calendrier([30])
        spec = {"type": "lag", "bars": 10,
                "inner": {"type": "event", "name": "fomc", "field": "minutes_since"}}
        assert build_signal(spec)(au(store, 100, cal)) == pytest.approx(61.0)


class TestLeChargement:
    def fichier(self, tmp_path, minutes: list[int]):
        chemin = tmp_path / "fomc.parquet"
        pl.DataFrame({"ts_event": [instant(m) for m in minutes]}).write_parquet(chemin)
        return chemin

    def test_il_lit_la_colonne_ts_event(self, tmp_path):
        cal = charger_calendrier(
            self.fichier(tmp_path, [30, 90]), name="fomc", known_in_advance=True
        )
        assert cal.instants.tolist() == [instant(30), instant(90)]
        assert cal.known_in_advance is True

    def test_il_hache_la_source(self, tmp_path):
        """Le calendrier entre au manifeste comme les cotations : deux runs sur
        des calendriers differents ne peuvent pas se confondre."""
        cal = charger_calendrier(
            self.fichier(tmp_path, [30]), name="fomc", known_in_advance=False
        )
        assert len(cal.source_hash) == 64

    def test_un_fichier_absent_leve(self, tmp_path):
        with pytest.raises(ConfigurationError, match="introuvable"):
            charger_calendrier(tmp_path / "absent.parquet", name="x",
                               known_in_advance=True)

    def test_une_colonne_manquante_leve_en_la_nommant(self, tmp_path):
        chemin = tmp_path / "mauvais.parquet"
        pl.DataFrame({"date": [1, 2]}).write_parquet(chemin)
        with pytest.raises(ConfigurationError, match="ts_event"):
            charger_calendrier(chemin, name="x", known_in_advance=True)
