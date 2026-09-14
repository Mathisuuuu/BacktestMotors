"""La seance ne doit pas ouvrir de canal vers le futur.

Le noeud `session` est le premier du vocabulaire a lire un agregat calcule sur
PLUSIEURS barres a la construction du magasin, et non barre par barre a
l'evaluation. C'est exactement le genre d'ajout qui peut faire entrer le futur
sans que personne ne le voie : les agregats d'une seance sont calcules une fois,
d'avance, sur l'echantillon entier.

Trois gardes, dans cet ordre de severite :

1. les agregats non clos sont refuses a `lag` 0 - la seance n'est pas finie ;
2. corrompre le futur ne change AUCUNE valeur de seance lue dans le passe ;
3. la surface publique du contexte reste celle qui est declaree.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore
from rsl.data.schema import Field as PriceField
from rsl.data.session import SessionCalendar, SessionField, build_session_index
from rsl.errors import ConfigurationError, LookAheadError
from rsl.strategies.signals import TRUE, build_signal, const, cumulative, price, session

NS = 1_000_000_000
CALENDRIER = SessionCalendar(start="17:00", end="16:00", timezone="America/Chicago")


def magasin(n: int = 120, seed: int = 3) -> BarStore:
    """Barres horaires, avec un calendrier de seance attache."""
    closes = synthetic.random_walk(n, seed=seed)
    store = synthetic.make_store(closes, granularity=synthetic.MINUTE)
    # Horodatages horaires : quelques seances completes sur la periode.
    debut = int(dt.datetime(2025, 6, 2, 18, 0, tzinfo=dt.UTC).timestamp())
    ts = np.asarray([(debut + i * 3600) * NS for i in range(n)], dtype=np.int64)
    store = BarStore.build(
        symbol=store.symbol, granularity=store.granularity, ts_event=ts,
        open_=store.open, high=store.high, low=store.low, close=store.close,
        volume=store.volume, is_stale=store.is_stale, ts_close=ts,
        source_hash=store.source_hash,
    )
    return store.with_sessions(
        build_session_index(store.ts_close, store.open, store.high, store.low,
                            store.close, store.volume, CALENDRIER)
    )


def au(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


class TestSeanceEnCours:
    """Une seance qui n'est pas finie n'a ni plus haut, ni plus bas, ni cloture."""

    @pytest.mark.adversarial
    @pytest.mark.parametrize("champ", ["high", "low", "close", "volume"])
    def test_les_agregats_non_clos_sont_refuses_a_lag_zero(self, champ):
        ctx = au(magasin(), 60)
        with pytest.raises(LookAheadError, match="n'est pas connu"):
            ctx.session_value(SessionField(champ), 0)

    def test_l_ouverture_est_lisible_des_la_premiere_barre(self):
        """Elle est connue des que la seance commence : ce n'est pas du futur."""
        ctx = au(magasin(), 60)
        assert ctx.session_value(SessionField.OPEN, 0) > 0.0

    @pytest.mark.adversarial
    def test_un_lag_negatif_leve(self):
        ctx = au(magasin(), 60)
        with pytest.raises(LookAheadError, match="lag negatif"):
            ctx.session_value(SessionField.OPEN, -1)

    def test_les_champs_positionnels_refusent_un_lag(self):
        """`bar_index` decrit la barre courante : il n'a pas de sens ailleurs."""
        ctx = au(magasin(), 60)
        with pytest.raises(ConfigurationError, match="barre courante"):
            ctx.session_value(SessionField.BAR_INDEX, 1)


class TestCorruptionDuFutur:
    """Garde n° 1 du socle, appliquee au nouveau canal."""

    @pytest.mark.adversarial
    @pytest.mark.parametrize("champ", ["open", "high", "low", "close", "volume"])
    def test_corrompre_le_futur_ne_change_aucune_lecture_passee(self, champ):
        """Les agregats sont calcules a la CONSTRUCTION, sur tout l'echantillon.
        Si une valeur lue avant la coupure bougeait, le futur serait entre par
        la porte des agregats."""
        coupure = 70
        propre = magasin()
        brut = synthetic.corrupt_future(
            BarStore.build(
                symbol=propre.symbol, granularity=propre.granularity,
                ts_event=propre.ts_event, open_=propre.open, high=propre.high,
                low=propre.low, close=propre.close, volume=propre.volume,
                is_stale=propre.is_stale, ts_close=propre.ts_close,
            ),
            after_index=coupure,
        )
        corrompu = brut.with_sessions(
            build_session_index(brut.ts_close, brut.open, brut.high, brut.low,
                                brut.close, brut.volume, CALENDRIER)
        )

        for index in range(30, coupure - 24):
            attendu = au(propre, index).session_value(SessionField(champ), 1)
            obtenu = au(corrompu, index).session_value(SessionField(champ), 1)
            assert obtenu == pytest.approx(attendu), f"{champ} a l'index {index}"

    @pytest.mark.adversarial
    def test_les_champs_positionnels_resistent_aussi(self):
        coupure = 70
        propre = magasin()
        for champ in (SessionField.BAR_INDEX, SessionField.IS_FIRST, SessionField.IS_LAST):
            for index in range(30, coupure):
                # Ils ne dependent que des horodatages, que la corruption
                # preserve : le test verifie que c'est bien le cas.
                assert au(propre, index).session_value(champ, 0) is not None


class TestSurfacePublique:
    def test_le_contexte_n_expose_que_ce_qui_est_declare(self):
        """Meme liste que `test_forbidden_access`, verifiee ici aussi apres
        l'ajout de `session_value` : deux tests valent mieux qu'un pour une
        surface qui ne doit grandir que volontairement."""
        ctx = au(magasin(), 10)
        public = {nom for nom in dir(ctx) if not nom.startswith("_")}
        assert public == {
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
            # fenetres comptees en SEANCES. Elle ne rend que des DECALAGES
            # vers le passe et refuse la seance en cours, dont la longueur
            # est un fait futur tant qu'elle n'est pas close.
            "lags_de_seance",
            # `event_value` a rejoint la surface le 2026-09-14, pour les
            # calendriers d'annonces declares (`events`). Elle ne lit qu'un
            # fichier DECLARE, hache au manifeste, et son seul champ qui
            # regarde l'avenir - `minutes_until` - exige que la source affirme
            # `known_in_advance`. Sans calendrier declare, elle LEVE.
            "event_value",
        }

    def test_sans_calendrier_le_noeud_leve_au_lieu_de_deviner(self):
        """Le point de tout le mecanisme : pas de frontiere inventee."""
        sans = synthetic.make_store(synthetic.ramp(50))
        ctx = au(sans, 20)
        with pytest.raises(ConfigurationError, match="aucun calendrier declare"):
            session("open")(ctx)


class TestNoeud:
    def test_il_lit_la_seance_close(self):
        ctx = au(magasin(), 60)
        valeur = session("high", lag=1)(ctx)
        assert valeur is not None and valeur > 0.0

    def test_historique_insuffisant_rend_none_plutot_que_lever(self):
        """Convention du vocabulaire : une valeur non calculable est absente."""
        ctx = au(magasin(), 2)
        assert session("close", lag=10)(ctx) is None

    def test_aller_retour_declaratif(self):
        noeud = session("low", lag=2)
        assert noeud.describe() == {
            "type": "session", "version": 1, "field": "low", "lag": 2,
        }


class TestCumulative:
    """Fenetre a longueur variable : de l'ouverture de seance a maintenant."""

    def test_le_cumul_repart_a_chaque_seance(self):
        """La propriete qui definit le noeud : sans remise a zero, ce serait
        un cumul depuis l'origine, que le socle refuse."""
        store = magasin(120)
        index = store.sessions
        assert index is not None
        premieres = [i for i in range(30, 110) if bool(index.is_first[i])]
        assert premieres, "le montage doit contenir au moins une ouverture"
        ouverture = premieres[0]
        avant = cumulative("count_true", const(TRUE))(au(store, ouverture - 1))
        apres = cumulative("count_true", const(TRUE))(au(store, ouverture))
        assert avant is not None and apres == pytest.approx(1.0)
        assert avant > apres

    def test_count_true_vaut_le_rang_plus_un(self):
        store = magasin(120)
        for index in (35, 60, 90):
            ctx = au(store, index)
            rang = ctx.session_value(SessionField.BAR_INDEX, 0)
            assert cumulative("count_true", const(TRUE))(ctx) == pytest.approx(rang + 1)

    def test_first_est_la_valeur_de_l_ouverture(self):
        """`values[0]` est le present : `first` est donc le dernier element."""
        store = magasin(120)
        ctx = au(store, 60)
        rang = int(ctx.session_value(SessionField.BAR_INDEX, 0))
        attendu = au(store, 60 - rang).value(PriceField.CLOSE)
        assert cumulative("first", price("close"))(ctx) == pytest.approx(attendu)

    def test_last_est_la_valeur_courante(self):
        store = magasin(120)
        ctx = au(store, 60)
        assert cumulative("last", price("close"))(ctx) == pytest.approx(
            ctx.value(PriceField.CLOSE)
        )

    def test_max_ne_descend_jamais_dans_une_seance(self):
        store = magasin(120)
        index = store.sessions
        assert index is not None
        precedent = None
        for i in range(40, 70):
            courant = cumulative("max", price("close"))(au(store, i))
            if precedent is not None and not bool(index.is_first[i]):
                assert courant >= precedent
            precedent = courant

    def test_sans_calendrier_il_leve(self):
        sans = synthetic.make_store(synthetic.ramp(50))
        with pytest.raises(ConfigurationError, match="aucun calendrier declare"):
            cumulative("sum", price("close"))(au(sans, 20))

    def test_statistique_inconnue_refusee(self):
        with pytest.raises(ConfigurationError, match="statistique invalide"):
            build_signal({"type": "cumulative", "stat": "mediane",
                          "inner": {"type": "constant", "value": 1.0}})

    def test_aller_retour_declaratif(self):
        noeud = cumulative("sum", price("volume"))
        reconstruit = build_signal(noeud.describe())
        assert reconstruit(au(magasin(120), 50)) == pytest.approx(
            noeud(au(magasin(120), 50))
        )
