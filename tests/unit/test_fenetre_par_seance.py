"""Fenetres comptees en SEANCES : `rolling.across` et `session_lag`.

Ce qui est en jeu
------------------
`rolling.stride` comptait des BARRES. Il ne retrouve « le meme rang la veille »
que si toutes les seances ont la meme longueur - hypothese que les donnees
reelles ne verifient pas. Mesure du 2026-09-13 sur les cotations NQ a la
minute : **1 362 barres les jours pleins, 435 le vendredi**, la seance ouverte
le vendredi a 9 h 30 se fermant avant le week-end. La specification Zarattini
supposait 390 barres par seance ; son `stride` tombait donc a une heure
arbitraire, differente chaque jour.

Ces deux formes le remplacent en s'appuyant sur le calendrier DECLARE.

Comment ce fichier evite de se tromper lui-meme
------------------------------------------------
Toutes les seances y sont de longueurs INEGALES. Avec des seances egales, un
`stride` fixe et un comptage par seance donneraient le meme resultat : les
tests seraient verts meme si le code ne faisait rien de ce qu'on lui demande.
`test_le_pas_fixe_ne_donne_pas_la_meme_chose` fige cet ecart explicitement.
"""

from __future__ import annotations

import datetime as dt
import itertools

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, Granularity
from rsl.data.session import SessionCalendar, build_session_index, lags_meme_rang
from rsl.errors import ConfigurationError, InsufficientHistoryError
from rsl.strategies.signals import build_signal

NS = 1_000_000_000
EPOCH = dt.datetime(2020, 1, 6, 9, 0, tzinfo=dt.UTC)
SEANCE = SessionCalendar(start="09:00", end="17:00", timezone="UTC")

# Longueurs INEGALES, et la plus courte au milieu : c'est elle qui doit faire
# tomber une fenetre qui l'enjambe a un rang qu'elle ne porte pas.
LONGUEURS = (100, 60, 100, 40, 100, 100, 100)


def magasin(longueurs: tuple[int, ...] = LONGUEURS) -> BarStore:
    """Des seances d'une minute, une par jour, de longueurs donnees."""
    horodatages: list[int] = []
    for jour, taille in enumerate(longueurs):
        debut = int((EPOCH + dt.timedelta(days=jour)).timestamp())
        horodatages.extend((debut + m * 60) * NS for m in range(taille))
    ts = np.asarray(horodatages, dtype=np.int64)
    closes = synthetic.random_walk(ts.size, 100.0, sigma=0.5, seed=3)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.002)
    store = BarStore.build(
        symbol="SES.v.0", granularity=Granularity.minutes(1), ts_event=ts,
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


CLOSE = {"type": "price", "field": "close"}


class TestLaBriqueDeBase:
    """`lags_meme_rang` : la seule chose qui calcule vraiment quelque chose."""

    def test_elle_retrouve_le_rang_et_non_le_nombre_de_barres(self):
        store = magasin()
        idx = store.sessions
        assert idx is not None
        # Seances : 0=[0,100) 1=[100,160) 2=[160,260) 3=[260,300) 4=[300,400)
        barre = 310  # seance 4, rang 10
        assert int(idx.bar_in_session[barre]) == 10
        obtenus = lags_meme_rang(idx, barre, 1, 4)
        # Rang 10 des seances 3, 2, 1, 0 -> barres 270, 170, 110, 10.
        assert obtenus == (310 - 270, 310 - 170, 310 - 110, 310 - 10)

    def test_les_decalages_ne_sont_pas_regulierement_espaces(self):
        """La propriete qui distingue cette fonction d'un `stride`.

        Si les ecarts entre decalages successifs etaient constants, un pas fixe
        ferait le meme travail et cette fonction n'aurait pas lieu d'etre.
        """
        store = magasin()
        assert store.sessions is not None
        decalages = lags_meme_rang(store.sessions, 310, 1, 4)
        ecarts = {b - a for a, b in itertools.pairwise(decalages)}
        assert len(ecarts) > 1, f"ecarts constants {ecarts} : un stride suffirait"

    def test_un_rang_absent_d_une_seance_courte_leve(self):
        store = magasin()
        assert store.sessions is not None
        # Barre 350 : seance 4, rang 50. La seance 3 n'a que 40 barres.
        assert int(store.sessions.bar_in_session[350]) == 50
        with pytest.raises(InsufficientHistoryError, match="n'existe pas dans la seance"):
            lags_meme_rang(store.sessions, 350, 1, 1)

    def test_la_seance_en_cours_est_refusee(self):
        """Sa longueur est un fait FUTUR tant qu'elle n'est pas close."""
        store = magasin()
        assert store.sessions is not None
        with pytest.raises(ConfigurationError, match="au moins 1 seance"):
            lags_meme_rang(store.sessions, 310, 0, 3)

    def test_sans_calendrier_le_contexte_refuse(self):
        store = magasin()
        nu = BarStore.build(
            symbol="NU.v.0", granularity=store.granularity,
            ts_event=np.asarray(store.ts_event, dtype=np.int64),
            open_=np.asarray(store.open), high=np.asarray(store.high),
            low=np.asarray(store.low), close=np.asarray(store.close),
            volume=np.asarray(store.volume), source_hash="synthetic",
        )
        with pytest.raises(ConfigurationError, match="aucun calendrier declare"):
            au(nu, 310).lags_de_seance(1, 3)


class TestRollingAcrossSessions:
    def test_la_fenetre_prend_une_barre_par_seance_au_meme_rang(self):
        spec = {
            "type": "rolling", "stat": "sum", "window": 4,
            "across": "sessions", "inner": CLOSE,
        }
        store = magasin()
        closes = np.asarray(store.close)
        obtenu = build_signal(spec)(au(store, 310))
        # Present (310) + rang 10 des seances 3, 2, 1 -> 270, 170, 110.
        attendu = float(closes[[310, 270, 170, 110]].sum())
        assert obtenu == pytest.approx(attendu)

    def test_le_pas_fixe_ne_donne_pas_la_meme_chose(self):
        """Le test qui justifie tout le reste.

        Si les deux formes coincidaient sur des seances inegales, `across`
        n'apporterait rien. Le `stride` de 100 - la longueur de la seance la
        plus frequente - est l'erreur exacte que la specification Zarattini
        faisait avec 390.
        """
        commun = {"type": "rolling", "stat": "sum", "window": 4, "inner": CLOSE}
        store = magasin()
        par_seance = build_signal({**commun, "across": "sessions"})(au(store, 310))
        par_pas = build_signal({**commun, "stride": 100})(au(store, 310))
        assert par_seance is not None and par_pas is not None
        assert par_seance != pytest.approx(par_pas)

    def test_le_present_est_en_tete(self):
        """`zscore`, `rank` et `slope` lisent `values[0]` comme le PRESENT."""
        spec = {
            "type": "rolling", "stat": "max", "window": 4,
            "across": "sessions", "inner": CLOSE,
        }
        store = magasin()
        # `rank` vaut 1.0 quand la valeur courante est la plus haute de sa
        # fenetre : c'est le moyen le plus direct de constater la position.
        rang = build_signal({**spec, "stat": "rank"})(au(store, 310))
        valeurs = np.asarray(store.close)[[310, 270, 170, 110]]
        assert rang == pytest.approx(float(np.mean(valeurs <= valeurs[0])))

    def test_une_seance_trop_courte_rend_none_et_non_une_valeur_voisine(self):
        """Le coeur de l'affaire : ne PAS substituer la derniere barre.

        Substituer comparerait la 50e minute d'un jour plein a la 39e d'un
        jour ecourte - le desalignement silencieux que `across` supprime.
        """
        spec = {
            "type": "rolling", "stat": "mean", "window": 2,
            "across": "sessions", "inner": CLOSE,
        }
        store = magasin()
        signal = build_signal(spec)
        assert int(store.sessions.bar_in_session[350]) == 50  # type: ignore[union-attr]
        assert signal(au(store, 350)) is None, "la seance 3 n'a que 40 barres"
        # Au rang 10, la meme fenetre existe : l'absence est LOCALE, pas globale.
        assert signal(au(store, 310)) is not None

    def test_le_defaut_reste_le_comptage_en_barres(self):
        """Aucune specification ecrite avant cet ajout ne change de sens."""
        sans = build_signal({"type": "rolling", "stat": "sum", "window": 3, "inner": CLOSE})
        avec = build_signal(
            {"type": "rolling", "stat": "sum", "window": 3, "across": "bars", "inner": CLOSE}
        )
        store = magasin()
        assert sans(au(store, 310)) == avec(au(store, 310))
        assert "across" not in sans.describe(), "le defaut ne doit pas etre publie"

    def test_across_et_stride_ensemble_sont_refuses(self):
        with pytest.raises(ConfigurationError, match="disent la meme chose"):
            build_signal({
                "type": "rolling", "stat": "sum", "window": 3,
                "across": "sessions", "stride": 5, "inner": CLOSE,
            })

    def test_across_inconnu_est_refuse(self):
        with pytest.raises(ConfigurationError, match="`across` invalide"):
            build_signal({
                "type": "rolling", "stat": "sum", "window": 3,
                "across": "jours", "inner": CLOSE,
            })


class TestSessionLag:
    def test_il_recule_d_une_seance_au_meme_rang(self):
        spec = {"type": "session_lag", "sessions": 1, "inner": CLOSE}
        store = magasin()
        obtenu = build_signal(spec)(au(store, 310))
        assert obtenu == pytest.approx(float(np.asarray(store.close)[270]))

    def test_il_n_est_pas_un_lag_en_barres(self):
        """Sur des seances inegales, les deux ne designent pas la meme barre."""
        store = magasin()
        par_seance = build_signal({"type": "session_lag", "sessions": 1, "inner": CLOSE})
        # 100 est la longueur MODALE - ce qu'un utilisateur ecrirait pour dire
        # « une seance », exactement comme la specification Zarattini ecrivait
        # 390. La seance qui precede la barre 310 n'en compte que 40, donc le
        # pas fixe rate le rang.
        #
        # A noter : `session_lag(1)` vaut TOUJOURS `lag(longueur de la seance
        # precedente)` pour une barre donnee - c'est une identite, pas une
        # coincidence. Ce qui les separe est que ce nombre CHANGE d'une barre a
        # l'autre, et qu'aucune constante ne peut le suivre.
        par_barres = build_signal({"type": "lag", "bars": 100, "inner": CLOSE})
        assert par_seance(au(store, 310)) != pytest.approx(par_barres(au(store, 310)))

    def test_zero_seance_est_refuse(self):
        with pytest.raises(ConfigurationError, match=r"au moins 1 seance|>= 1 seance"):
            build_signal({"type": "session_lag", "sessions": 0, "inner": CLOSE})

    def test_il_rend_none_quand_la_seance_visee_est_trop_courte(self):
        store = magasin()
        signal = build_signal({"type": "session_lag", "sessions": 1, "inner": CLOSE})
        assert signal(au(store, 350)) is None  # rang 50, seance precedente a 40
        assert signal(au(store, 310)) is not None

    def test_il_rend_none_au_debut_de_l_echantillon(self):
        """Son `warmup_bars` ne peut pas le dire : il ne connait pas les
        donnees. L'absence est donc signalee a l'evaluation, et elle est SURE -
        `None`, jamais une valeur prise au mauvais rang."""
        store = magasin()
        signal = build_signal({"type": "session_lag", "sessions": 3, "inner": CLOSE})
        # Le warmup declare est celui du SOUS-ARBRE seul : `session_lag`
        # n'en ajoute aucun, ne sachant pas combien de barres font trois
        # seances.
        assert signal.warmup_bars == build_signal(CLOSE).warmup_bars
        assert signal(au(store, 50)) is None, "une seule seance derriere soi"
        assert signal(au(store, 310)) is not None


class TestLaCompositionDuPapier:
    """`sigma[tau]` de Zarattini, ecrit sans supposer la longueur d'une seance."""

    def test_la_moyenne_porte_sur_les_seances_precedentes(self):
        spec = {
            "type": "rolling", "stat": "mean", "window": 3, "across": "sessions",
            "inner": {"type": "session_lag", "sessions": 1, "inner": CLOSE},
        }
        store = magasin()
        closes = np.asarray(store.close)
        # Seances : 0=[0,100) 1=[100,160) 2=[160,260) 3=[260,300)
        #           4=[300,400) 5=[400,500) 6=[500,600)
        obtenu = build_signal(spec)(au(store, 510))  # seance 6, rang 10
        # `rolling` visite les seances 6, 5, 4 au rang 10 ; `session_lag` recule
        # chacune d'une seance -> 5, 4, 3, soit les barres 410, 310, 270.
        assert obtenu == pytest.approx(float(closes[[410, 310, 270]].mean()))

    def test_la_seance_en_cours_n_entre_jamais_dans_la_moyenne(self):
        """Ce que `session_lag` garantit, et qui est le point du papier."""
        spec = {
            "type": "rolling", "stat": "max", "window": 3, "across": "sessions",
            "inner": {"type": "session_lag", "sessions": 1, "inner": CLOSE},
        }
        store = magasin()
        closes = np.asarray(store.close)
        obtenu = build_signal(spec)(au(store, 510))
        assert obtenu != pytest.approx(float(closes[510])), "la barre courante a fuite"
