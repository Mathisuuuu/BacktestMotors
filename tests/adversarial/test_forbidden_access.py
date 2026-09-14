"""Test exige n° 2 : acces interdit.

Toute tentative de lire une barre `> t` depuis un `Context` doit lever une
exception. Ce fichier essaie activement de contourner le contrat, y compris par
les chemins detournes que `numpy` offre gratuitement.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fixtures import synthetic
from rsl.data.feed import BarContext, BarFeed
from rsl.data.schema import ALL_FIELDS, BarStore, Field, Granularity
from rsl.data.session import SessionCalendar, build_session_index
from rsl.errors import (
    ConfigurationError,
    InsufficientHistoryError,
    LookAheadError,
)

pytestmark = pytest.mark.adversarial


def advanced(store: BarStore, n: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(n):
        ctx._advance()
    return ctx


SEANCE = SessionCalendar(start="09:00", end="17:00", timezone="UTC")


def _avec_seances(ts: np.ndarray) -> BarStore:
    closes = synthetic.random_walk(ts.size, 100.0, sigma=0.5, seed=11)
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


@pytest.fixture
def session_store() -> BarStore:
    """Six seances d'une minute, de LONGUEURS INEGALES.

    Inegales a dessein : c'est tout le sujet de `lags_de_seance`. Des seances
    egales rendraient les tests verts meme si la fonction comptait des barres
    a pas fixe, c'est-a-dire meme si elle ne faisait rien de ce qu'on lui
    demande.
    """
    import datetime as dt

    ns = 1_000_000_000
    base = int(dt.datetime(2020, 1, 6, 9, 0, tzinfo=dt.UTC).timestamp())
    horodatages: list[int] = []
    for jour, taille in enumerate([120, 90, 120, 60, 120, 120]):
        debut = base + jour * 86400
        horodatages.extend((debut + m * 60) * ns for m in range(taille))
    return _avec_seances(np.asarray(horodatages, dtype=np.int64))


def tronquer(store: BarStore, n: int) -> BarStore:
    """Le meme magasin, coupe apres `n` barres, seances RECALCULEES."""
    return _avec_seances(np.asarray(store.ts_event[:n], dtype=np.int64))


class TestNegativeLagIsLookAhead:
    @pytest.mark.parametrize("lag", [-1, -2, -100])
    @pytest.mark.parametrize("field", list(ALL_FIELDS))
    def test_value_with_negative_lag_raises(self, ramp_store: BarStore, lag, field):
        ctx = advanced(ramp_store, 50)
        with pytest.raises(LookAheadError, match="lag negatif"):
            ctx.value(field, lag=lag)

    def test_bar_at_with_negative_lag_raises(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 50)
        with pytest.raises(LookAheadError):
            ctx.bar_at(-1)

    @pytest.mark.parametrize("lag", [-1, -50])
    def test_shifted_view_cannot_look_forward(self, ramp_store: BarStore, lag):
        ctx = advanced(ramp_store, 50)
        with pytest.raises(LookAheadError):
            ctx.shifted(lag)

    def test_shifted_view_stays_in_the_past(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 50)
        past = ctx.shifted(10)
        assert past.n_bars_seen == ctx.n_bars_seen - 10
        assert past.value(Field.CLOSE) == pytest.approx(ctx.value(Field.CLOSE, lag=10))
        with pytest.raises(InsufficientHistoryError):
            past.history(past.n_bars_seen + 1)

    def test_look_ahead_error_is_not_swallowed_as_value_error(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 10)
        with pytest.raises(LookAheadError):
            ctx.value(Field.CLOSE, lag=-1)

    @given(lag=st.integers(min_value=-10_000, max_value=-1), cursor=st.integers(1, 400))
    @settings(max_examples=200, deadline=None)
    def test_property_every_negative_lag_raises(self, lag, cursor):
        store = synthetic.make_store(synthetic.ramp(500), symbol="P.v.0")
        ctx = advanced(store, cursor)
        with pytest.raises(LookAheadError):
            ctx.value(Field.CLOSE, lag=lag)


class TestMissingHistoryIsNotNaN:
    """Une fenetre trop longue leve, elle ne renvoie pas de `NaN`.

    Un `NaN` traverse une moyenne puis une comparaison, et toute comparaison
    avec `NaN` vaut `False` : le backtest tourne, ne signale rien, et se trompe.
    """

    def test_window_too_long_raises(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 5)
        with pytest.raises(InsufficientHistoryError):
            ctx.history(6)

    def test_lag_beyond_history_raises(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 5)
        with pytest.raises(InsufficientHistoryError):
            ctx.value(Field.CLOSE, lag=5)

    def test_no_nan_is_ever_returned(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 3)
        for n in (1, 2, 3):
            assert np.isfinite(ctx.history(n).close).all()
        with pytest.raises(InsufficientHistoryError):
            ctx.history(4)

    @given(cursor=st.integers(1, 200), extra=st.integers(1, 500))
    @settings(max_examples=200, deadline=None)
    def test_property_window_exceeding_history_always_raises(self, cursor, extra):
        store = synthetic.make_store(synthetic.ramp(500), symbol="P.v.0")
        ctx = advanced(store, cursor)
        with pytest.raises(InsufficientHistoryError):
            ctx.history(cursor + extra)


class TestNoFutureThroughReturnedArrays:
    """`numpy` offre deux portes derobees : `.base` et l'ecriture en place."""

    def test_history_arrays_own_their_data(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 100)
        window = ctx.history(10)
        for array in (window.open, window.high, window.low, window.close, window.volume):
            assert array.base is None, "une vue exposerait le tableau complet via .base"
        assert window.ts_close.base is None

    def test_values_array_owns_its_data(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 100)
        assert ctx.values(Field.CLOSE, 10).base is None

    def test_returned_arrays_are_read_only(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 100)
        window = ctx.history(10)
        with pytest.raises(ValueError, match="read-only"):
            window.close[0] = 0.0
        with pytest.raises(ValueError, match="read-only"):
            ctx.values(Field.CLOSE, 10)[0] = 0.0

    def test_window_cannot_reach_beyond_the_cursor(self, ramp_store: BarStore):
        """Meme en indexant hors bornes, la fenetre ne contient que le passe."""
        ctx = advanced(ramp_store, 100)
        window = ctx.history(10)
        assert float(window.close.max()) <= float(ramp_store.close[99])
        with pytest.raises(IndexError):
            _ = window.close[10]

    def test_mutating_a_window_cannot_corrupt_another_context(self, ramp_store: BarStore):
        a = advanced(ramp_store, 50)
        b = advanced(ramp_store, 50)
        window = a.history(5)
        with pytest.raises(ValueError, match="read-only"):
            window.close[:] = 0.0
        assert b.value(Field.CLOSE) == pytest.approx(float(ramp_store.close[49]))


class TestNoSampleLengthLeak:
    """Regle 4 : une strategie ne doit pas pouvoir deviner la fin de l'echantillon."""

    FORBIDDEN = ("__len__", "total_bars", "n_bars", "end_date", "last_ts", "store", "df", "raw")

    def test_position_state_describes_the_past_not_the_future(self, ramp_store: BarStore):
        """`position` a rejoint la surface publique : elle decrit ce que la
        strategie a FAIT, jamais ce que le marche fera."""
        ctx = advanced(ramp_store, 10)
        assert ctx.position.is_flat
        assert ctx.position.bars_held == 0
        assert ctx.position.entry_price == 0.0

    @pytest.mark.parametrize("attribute", FORBIDDEN)
    def test_context_does_not_expose_the_sample_length(self, ramp_store: BarStore, attribute):
        ctx = advanced(ramp_store, 10)
        assert not hasattr(ctx, attribute), f"'{attribute}' fuite la taille de l'echantillon"

    def test_public_surface_is_the_declared_one(self, ramp_store: BarStore):
        ctx = advanced(ramp_store, 10)
        public = {name for name in dir(ctx) if not name.startswith("_")}
        assert public == {
            # `session_value` a rejoint la surface : il ne lit que des seances
            # CLOSES, et `tests/adversarial/test_session_closure.py` verifie
            # qu'y corrompre le futur ne change aucune lecture passee.
            "bar", "bar_at", "granularity", "history", "n_bars_seen", "peer", "peers",
            "position", "session_value", "shifted", "symbol", "ts", "ts_event",
            "value", "values",
            # `account_value` a rejoint la surface le 2026-09-12 : la gestion
            # du risque pilotee par la PERFORMANCE etait le seul grand absent.
            # METHODE et non propriete, comme `session_value` - elle leve quand
            # aucun compte n'est tenu, et une propriete qui leve rendrait
            # `isinstance(ctx, Context)` impossible.
            "account_value",
            # `data_token` a rejoint la surface le 2026-09-11, pour la
            # memoisation (`rsl/strategies/memoire.py`). Il ne fuite rien :
            # c'est un `object()` NU, sans aucun attribut, dont le seul usage
            # possible est `token is autre_token`. Les trois tests qui suivent
            # l'attaquent explicitement.
            "data_token",
            # `lags_de_seance` a rejoint la surface le 2026-09-13, pour les
            # fenetres comptees en SEANCES (`rolling.across`, `lag.sessions`).
            # Elle ne rend que des DECALAGES vers le passe, jamais de valeur,
            # et son premier argument vaut au moins 1 : la seance EN COURS
            # n'est pas interrogeable, ce qui compte - sa longueur n'est
            # connue qu'une fois finie, donc la lire serait lire le futur.
            # Les deux tests qui suivent l'attaquent sur ces deux points.
            "lags_de_seance",
        }

    def test_session_lags_cannot_reach_the_current_session(self, session_store: BarStore):
        """La longueur de la seance EN COURS est un fait FUTUR.

        Tant qu'elle n'est pas finie, personne ne sait combien de barres elle
        comptera. Si `depart=0` etait accepte, une strategie apprendrait a la
        premiere minute si la journee sera pleine ou ecourtee - c'est-a-dire
        une information que le marche ne donne qu'a la cloture.
        """
        ctx = advanced(session_store, 401)
        with pytest.raises(ConfigurationError, match="au moins 1 seance"):
            ctx.lags_de_seance(0, 5)

    def test_session_lags_only_ever_point_backwards(self, session_store: BarStore):
        """Tout decalage rendu est >= 1, donc `shifted` reste dans le passe."""
        ctx = advanced(session_store, 401)
        # La barre 400 est dans la 5e seance : quatre la precedent.
        for depart in (1, 2, 3, 4):
            for recul in ctx.lags_de_seance(depart, 1):
                assert recul >= 1, f"decalage {recul} : vise le present ou le futur"

    def test_session_lags_do_not_leak_how_much_sample_remains(
        self, session_store: BarStore
    ):
        """Meme reponse sur un magasin TRONQUE apres la barre courante.

        C'est le test de corruption du futur applique a cette surface : si la
        reponse dependait de ce qui suit la barre courante, elle porterait de
        l'information sur l'avenir. Elle n'en porte pas.
        """
        entier = advanced(session_store, 401)
        tronque = advanced(tronquer(session_store, 460), 401)
        assert entier.lags_de_seance(1, 3) == tronque.lags_de_seance(1, 3)

    def test_le_jeton_de_donnees_ne_porte_aucune_donnee(self, ramp_store: BarStore):
        """La garde qui rend `data_token` acceptable sur la surface publique.

        Un jeton qui serait le MAGASIN donnerait l'historique complet, futur
        inclus, a qui sait le caster. Un `object()` nu n'a aucun attribut : il
        n'y a rien a en tirer, meme en trichant.
        """
        jeton = advanced(ramp_store, 10).data_token
        assert type(jeton) is object
        assert [nom for nom in dir(jeton) if not nom.startswith("_")] == []
        for interdit in ("close", "high", "low", "open", "volume", "ts_event", "symbol"):
            assert not hasattr(jeton, interdit), interdit

    def test_le_jeton_ne_distingue_pas_deux_barres(self, ramp_store: BarStore):
        """Il identifie la SERIE, pas l'instant : il ne peut donc pas servir a
        deduire ou l'on se trouve dans l'echantillon."""
        assert advanced(ramp_store, 10).data_token is advanced(ramp_store, 40).data_token

    def test_deux_series_ont_deux_jetons(self, ramp_store: BarStore, walk_store: BarStore):
        """Le seul service qu'il rend, et celui dont la memoisation depend."""
        assert advanced(ramp_store, 10).data_token is not advanced(walk_store, 10).data_token

    def test_n_bars_seen_never_anticipates(self, ramp_store: BarStore):
        for i, ctx in enumerate(BarFeed(ramp_store, stop=40)):
            assert ctx.n_bars_seen == i + 1


class TestFeedCursorMonotonic:
    def test_cursor_only_moves_forward(self, walk_store: BarStore):
        previous = None
        for ctx in BarFeed(walk_store, stop=100):
            current = ctx.ts
            if previous is not None:
                assert current > previous
            previous = current
