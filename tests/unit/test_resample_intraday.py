"""Tranches intra-journalieres, ancrees sur la seance DECLAREE.

Ce que ce fichier garde, dans l'ordre d'importance
---------------------------------------------------
1. **Aucune fuite.** Une barre agregee n'est jamais reputee disponible avant la
   cloture d'une des barres qui la composent. C'est la seule propriete dont une
   violation invaliderait un backtest plutot que de le rendre imprecis, et elle
   n'est pas theorique : sur les vraies donnees ES, le garde-fou qui l'assure
   mord 74 fois sur 16 417 tranches de 4 h.
2. **L'ancrage est la seance, pas l'epoque.** Une tranche de 4 h commence a
   l'ouverture declaree, pas a 00:00 UTC. C'est toute la difference entre le
   decoupage demande et celui qu'on aurait eu gratuitement.
3. **Rien n'est devine.** Une periode intra-journaliere sans `session` est
   refusee, et une `session` sur une periode calendaire aussi - l'accepter
   laisserait croire qu'elle change quelque chose.

Montage : une seance de 8 h, 09:00 -> 17:00 UTC, decoupee en tranches de 2 h.
Quatre tranches pleines par seance, tout se verifie de tete.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.resample import (
    CloseStamp,
    Period,
    bucket_ids,
    granularity_of,
    period_end_ns,
    resample,
    tranches_de_seance,
)
from rsl.data.schema import BarStore, Granularity, ns_to_datetime
from rsl.data.session import SessionCalendar
from rsl.errors import ConfigurationError

MINUTE = Granularity.minutes(1)
SEANCE = SessionCalendar(start="09:00", end="17:00", timezone="UTC")
"""Huit heures pleines, en UTC : ni passage de minuit, ni heure d'ete. Les cas
difficiles ont leurs propres tests ; celui-ci doit rester lisible."""

OUVERTURE = datetime(2020, 1, 6, 9, 0, tzinfo=UTC)  # un lundi


def serie_de_seances(n_seances: int = 3, minutes: int = 480) -> BarStore:
    """`n_seances` seances de `minutes` barres d'une minute, 09:00 -> 17:00.

    Les barres d'une seance sont contigues ; la nuit est un TROU, comme dans
    les vraies series. Une serie continue ne testerait pas l'ancrage, puisque
    tout y serait a l'heure.
    """
    horodatages: list[int] = []
    for jour in range(n_seances):
        debut = OUVERTURE + timedelta(days=jour)
        base = int(debut.timestamp()) * 1_000_000_000
        horodatages.extend(base + m * 60 * 1_000_000_000 for m in range(minutes))
    ts = np.asarray(horodatages, dtype=np.int64)
    n = ts.size
    closes = synthetic.ramp(n, 100.0, 0.1)
    opens, highs, lows, closes_ = synthetic.ohlc_from_closes(closes, wick=0.001)
    return BarStore.build(
        symbol="SES.v.0", granularity=MINUTE, ts_event=ts,
        open_=opens, high=highs, low=lows, close=closes_,
        volume=np.full(n, 10.0), source_hash="synthetic",
    )


def heures(store: BarStore, champ: str = "ts_event") -> list[str]:
    return [
        ns_to_datetime(int(t)).strftime("%d %H:%M") for t in getattr(store, champ)
    ]


class TestLAncrageEstLaSeance:
    """La propriete demandee : une tranche commence a l'OUVERTURE."""

    def test_les_tranches_commencent_a_l_ouverture_declaree(self):
        """09:00, 11:00, 13:00, 15:00 - et non 00:00, 02:00, 04:00... qu'un
        ancrage sur l'epoque UTC aurait donnes."""
        agg, _ = resample(serie_de_seances(1), Period.H2, calendar=SEANCE)
        assert heures(agg) == ["06 09:00", "06 11:00", "06 13:00", "06 15:00"]

    def test_une_seance_de_huit_heures_donne_quatre_tranches_de_deux(self):
        agg, rapport = resample(serie_de_seances(3), Period.H2, calendar=SEANCE)
        assert agg.n_bars == 12
        assert rapport.min_bars_in_a_period == 120
        assert rapport.max_bars_in_a_period == 120

    def test_une_seance_decalee_decale_les_tranches(self):
        """La verification qui prouve que c'est bien la DECLARATION qui ancre :
        meme serie, autre seance declaree, autres frontieres."""
        decalee = SessionCalendar(start="10:00", end="17:00", timezone="UTC")
        agg, _ = resample(serie_de_seances(1), Period.H2, calendar=decalee)
        assert heures(agg)[:2] == ["06 09:00", "06 10:00"]

    def test_les_tranches_ne_traversent_jamais_une_nuit(self):
        """C'est ce qu'un ancrage sur l'epoque aurait fait : une tranche de 4 h
        a cheval sur la fermeture aurait melange deux seances."""
        agg, _ = resample(serie_de_seances(3), Period.H4, calendar=SEANCE)
        jours = {ns_to_datetime(int(t)).day for t in agg.ts_event}
        assert len(agg.ts_event) == 6, heures(agg)
        assert jours == {6, 7, 8}

    def test_la_cle_de_tranche_est_l_instant_ou_elle_commence(self):
        """Pas un numero arbitraire : un entier qui a un sens, et dont la fin
        nominale se deduit par addition."""
        store = serie_de_seances(1)
        debuts, _ = tranches_de_seance(store.ts_event, SEANCE, Period.H2)
        assert ns_to_datetime(int(debuts[0])) == OUVERTURE
        assert ns_to_datetime(int(debuts[-1])) == OUVERTURE + timedelta(hours=6)

    def test_les_cles_sont_strictement_croissantes_entre_seances(self):
        """Sans quoi le regroupement par `diff` fusionnerait deux tranches
        distinctes de deux seances differentes."""
        store = serie_de_seances(3)
        debuts, _ = tranches_de_seance(store.ts_event, SEANCE, Period.H2)
        assert bool(np.all(np.diff(np.unique(debuts)) > 0))


class TestLaDerniereTrancheEstPlusCourte:
    """Quand la seance n'est pas un multiple de la periode.

    Cas reel et non theorique : la seance ES dure 23 h, donc 4 h y donne cinq
    tranches pleines et une de 3 h. Le socle la GARDE plutot que de l'ecarter -
    c'est la cloture, la partie la plus liquide de la seance.
    """

    def test_une_seance_de_sept_heures_en_tranches_de_deux(self):
        """2 + 2 + 2 + 1 : quatre tranches, la derniere amputee et CONSERVEE."""
        cal = SessionCalendar(start="09:00", end="16:00", timezone="UTC")
        agg, rapport = resample(
            serie_de_seances(1, minutes=420), Period.H2, calendar=cal
        )
        assert agg.n_bars == 4
        assert rapport.max_bars_in_a_period == 120
        assert rapport.min_bars_in_a_period == 60

    def test_une_seance_qui_tombe_juste_n_a_aucune_tranche_courte(self):
        """Huit heures en tranches de deux : quatre tranches pleines."""
        _, rapport = resample(serie_de_seances(1), Period.H2, calendar=SEANCE)
        assert rapport.min_bars_in_a_period == rapport.max_bars_in_a_period == 120

    def test_la_tranche_courte_est_datee_a_la_fermeture(self):
        """Et non a sa fin nominale : la dater plus tard retarderait le signal
        de cloture sans rien y gagner."""
        cal = SessionCalendar(start="09:00", end="16:00", timezone="UTC")
        store = serie_de_seances(1, minutes=420)  # 7 h
        agg, _ = resample(store, Period.H2, calendar=cal)
        fin = ns_to_datetime(int(agg.ts_close[-1]))
        assert fin == datetime(2020, 1, 6, 16, 0, tzinfo=UTC)

    def test_une_tranche_pleine_est_datee_a_sa_fin_nominale(self):
        agg, _ = resample(serie_de_seances(1), Period.H2, calendar=SEANCE)
        assert ns_to_datetime(int(agg.ts_close[0])) == OUVERTURE + timedelta(hours=2)


class TestAucuneFuite:
    """La propriete de surete. Une violation invaliderait le backtest."""

    def _bornes(self, store: BarStore, periode: Period, cal: SessionCalendar):
        debuts, _ = tranches_de_seance(store.ts_event, cal, periode)
        starts = np.concatenate(([0], np.flatnonzero(np.diff(debuts)) + 1))
        ends = np.append(starts[1:] - 1, store.n_bars - 1)
        return store.ts_close[ends]

    @pytest.mark.parametrize(
        "periode", [Period.MIN5, Period.MIN15, Period.MIN30, Period.H1, Period.H4]
    )
    def test_une_barre_agregee_n_est_jamais_disponible_avant_ses_composantes(
        self, periode
    ):
        store = serie_de_seances(3)
        agg, _ = resample(store, periode, calendar=SEANCE)
        dernieres = self._bornes(store, periode, SEANCE)
        assert bool(np.all(agg.ts_close >= dernieres))

    def test_une_barre_qui_traine_apres_la_fermeture_repousse_la_disponibilite(self):
        """Le garde-fou, sur le cas qui le justifie.

        Une seance declaree fermee a 16:00 mais dont la derniere barre d'une
        minute est horodatee 16:00 - donc close a 16:01. Borner a la fermeture
        declaree donnerait une disponibilite ANTERIEURE a cette barre : une
        fuite. Sur les vraies series ES, ce cas se presente 74 fois.
        """
        cal = SessionCalendar(start="09:00", end="16:00", timezone="UTC")
        store = serie_de_seances(1, minutes=421)  # une minute de trop
        agg, _ = resample(store, Period.H2, calendar=cal)
        derniere_barre = ns_to_datetime(int(store.ts_close[-1]))
        assert derniere_barre == datetime(2020, 1, 6, 16, 1, tzinfo=UTC)
        assert ns_to_datetime(int(agg.ts_close[-1])) == derniere_barre

    @pytest.mark.parametrize("periode", [Period.MIN15, Period.H1, Period.H4])
    def test_les_horodatages_de_disponibilite_sont_strictement_croissants(
        self, periode
    ):
        agg, _ = resample(serie_de_seances(3), periode, calendar=SEANCE)
        assert bool(np.all(np.diff(agg.ts_close) > 0))

    @pytest.mark.parametrize("periode", [Period.MIN15, Period.H1, Period.H4])
    def test_une_barre_est_toujours_disponible_apres_son_ouverture(self, periode):
        agg, _ = resample(serie_de_seances(3), periode, calendar=SEANCE)
        assert bool(np.all(agg.ts_close > agg.ts_event))


class TestLAgregationResteJuste:
    """Le decoupage change ; l'agregation, elle, doit rester celle d'avant."""

    def test_open_high_low_close_et_volume(self):
        store = serie_de_seances(1)
        agg, _ = resample(store, Period.H2, calendar=SEANCE)
        assert agg.open[0] == store.open[0]
        assert agg.close[0] == store.close[119]
        assert agg.high[0] == pytest.approx(store.high[:120].max())
        assert agg.low[0] == pytest.approx(store.low[:120].min())
        assert agg.volume[0] == pytest.approx(store.volume[:120].sum())

    def test_min_bars_ecarte_une_tranche_trop_creuse(self):
        """Meme garde-fou que pour les periodes calendaires : une tranche batie
        sur trois minutes ressemble a une vraie tranche et n'en est pas une."""
        store = serie_de_seances(1, minutes=370)  # 6 h 10 : derniere tranche de 10 min
        complet, _ = resample(store, Period.H2, calendar=SEANCE)
        filtre, rapport = resample(store, Period.H2, calendar=SEANCE, min_bars=60)
        assert filtre.n_bars == complet.n_bars - 1
        assert rapport.n_dropped_incomplete == 1

    def test_le_calendrier_entre_dans_l_empreinte_de_source(self):
        """Deux decoupages sur des seances differentes ne doivent pas se
        presenter sous la meme empreinte : le manifeste mentirait."""
        autre = SessionCalendar(start="10:00", end="17:00", timezone="UTC")
        un, _ = resample(serie_de_seances(1), Period.H2, calendar=SEANCE)
        deux, _ = resample(serie_de_seances(1), Period.H2, calendar=autre)
        assert un.source_hash != deux.source_hash

    def test_close_stamp_last_bar_reste_disponible(self):
        """Il ignore la seance : c'est la cloture reelle de la derniere barre.
        Toujours sur, par construction."""
        agg, _ = resample(
            serie_de_seances(1), Period.H2, calendar=SEANCE,
            close_stamp=CloseStamp.LAST_BAR,
        )
        assert ns_to_datetime(int(agg.ts_close[0])) == OUVERTURE + timedelta(hours=2)

    def test_la_granularite_annoncee_est_la_duree_nominale(self):
        granularite = granularity_of(Period.H4)
        assert granularite.delta == timedelta(hours=4)
        assert str(granularite) == "4h"


class TestRienNEstDevine:
    """Le socle refuse d'ancrer une tranche sans declaration."""

    def test_une_periode_intraday_sans_seance_est_refusee(self):
        with pytest.raises(ConfigurationError, match="exige un calendrier de seance"):
            resample(serie_de_seances(1), Period.H4)

    def test_le_message_dit_quoi_ajouter(self):
        with pytest.raises(ConfigurationError, match="start, end, timezone"):
            resample(serie_de_seances(1), Period.MIN5)

    def test_une_seance_sur_une_periode_calendaire_est_refusee(self):
        """Elle n'y changerait rien. L'accepter laisserait croire le contraire -
        et quelqu'un finirait par declarer une seance en croyant deplacer la
        frontiere de ses barres quotidiennes."""
        with pytest.raises(ConfigurationError, match="est calendaire"):
            resample(serie_de_seances(3), Period.DAY, calendar=SEANCE)

    def test_bucket_ids_refuse_une_periode_intraday(self):
        """Le decoupage calendaire n'a pas d'ancrage pour elle."""
        with pytest.raises(ConfigurationError, match="intra-journaliere"):
            bucket_ids(serie_de_seances(1).ts_event, Period.H1)

    def test_period_end_ns_aussi(self):
        with pytest.raises(ConfigurationError, match="intra-journaliere"):
            period_end_ns(np.zeros(3, dtype=np.int64), Period.H1)

    def test_une_periode_calendaire_n_a_pas_de_duree_en_minutes(self):
        with pytest.raises(ConfigurationError, match="periode calendaire"):
            _ = Period.MONTH.minutes


class TestLaTablePeriodeEstLaDefinition:
    """`intra_journaliere` se lit dans une seule table.

    Une liste enumeree a deux endroits est fausse des le deuxieme ([[lessons]]
    L15) : ce test constate que la classification vient bien de `_MINUTES`.
    """

    INTRADAY = (
        Period.MIN5, Period.MIN10, Period.MIN15, Period.MIN30,
        Period.H1, Period.H2, Period.H4,
    )
    CALENDAIRES = (Period.DAY, Period.WEEK, Period.MONTH, Period.QUARTER, Period.YEAR)

    def test_chaque_periode_est_dans_exactement_une_famille(self):
        assert set(self.INTRADAY) | set(self.CALENDAIRES) == set(Period)
        assert not set(self.INTRADAY) & set(self.CALENDAIRES)

    @pytest.mark.parametrize("periode", INTRADAY)
    def test_une_intraday_a_une_duree_positive(self, periode):
        assert periode.intra_journaliere
        assert periode.minutes > 0

    @pytest.mark.parametrize("periode", CALENDAIRES)
    def test_une_calendaire_n_en_a_pas(self, periode):
        assert not periode.intra_journaliere

    def test_les_durees_sont_ordonnees_comme_les_noms(self):
        """Une table mal saisie - `1h` a 30 minutes - ne se verrait pas
        autrement."""
        durees = [p.minutes for p in self.INTRADAY]
        assert durees == sorted(durees)
        assert durees == [5, 10, 15, 30, 60, 120, 240]


class TestUnPanneauIntradayExigeUneSeanceCommune:
    """Deux seances differentes n'ont aucune frontiere de tranche commune.

    Ce n'est pas une precaution : mesure le 2026-09-12 sur ES (CME) + FDAX
    (Eurex) en tranches de 4 h, **18 653 lignes de panneau sur 18 654 ne
    portaient qu'un seul instrument**, soit 100 %. Une strategie transversale
    n'y aurait jamais rien a comparer - et n'aurait leve aucune erreur : elle
    aurait saute tous ses rebalancements en silence.

    `allow_mixed_granularity` ne voit pas ce cas : les deux series sont bien en
    `4h`. C'est leur ANCRAGE qui differe, pas leur granularite.
    """

    CME: ClassVar[dict[str, str]] = {
        "start": "17:00", "end": "16:00", "timezone": "America/Chicago"
    }
    EUREX: ClassVar[dict[str, str]] = {
        "start": "01:10", "end": "22:00", "timezone": "Europe/Berlin"
    }

    def spec(self, *entrees: dict[str, object]):
        from rsl.config import BacktestSpec

        return BacktestSpec.model_validate({
            "name": "panneau", "initial_cash": 1e6,
            "data": list(entrees),
            "execution": {"fees": {"kind": "zero"}, "slippage": {"kind": "zero"}},
            "strategy": {
                "ref": "ranking@1",
                "params": {"score": {"type": "constant", "value": 1.0}},
            },
        })

    def entree(self, root: str, resample: str, session: dict[str, str] | None):
        entree: dict[str, object] = {"root": root, "path": f"{root}.parquet"}
        entree["resample"] = resample
        if session is not None:
            entree["session"] = session
        return entree

    def test_deux_seances_differentes_sont_refusees(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="aucune frontiere de tranche"):
            self.spec(
                self.entree("ES", "4h", self.CME),
                self.entree("FDAX", "4h", self.EUREX),
            )

    def test_le_message_nomme_les_seances_en_conflit(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="17:00-16:00@America/Chicago"):
            self.spec(
                self.entree("ES", "4h", self.CME),
                self.entree("FDAX", "4h", self.EUREX),
            )

    def test_la_meme_seance_pour_tous_est_acceptee(self):
        assert self.spec(
            self.entree("ES", "4h", self.CME), self.entree("NQ", "4h", self.CME)
        ) is not None

    def test_un_seul_instrument_est_l_usage_prevu(self):
        assert self.spec(self.entree("ES", "4h", self.CME)) is not None

    def test_des_periodes_calendaires_alignent_et_restent_libres(self):
        """La frontiere de mois est la meme pour tous : le probleme n'existe
        pas, et l'interdire aurait casse des specifications valides."""
        assert self.spec(
            self.entree("ES", "day", self.CME), self.entree("FDAX", "day", self.EUREX)
        ) is not None

    def test_une_entree_intraday_sans_seance_est_deja_refusee_en_amont(self):
        """Par le validateur de `DataSpec`, avant meme d'arriver ici."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="exige une `session`"):
            self.spec(self.entree("ES", "1h", None))
