"""`Context` a curseur et iterateurs de barres.

C'est ici que le contrat anti-look-ahead devient du code. Le `Context` detient
une reference au magasin immuable et un entier : rien d'autre. Aucune de ses
methodes ne peut renvoyer une information d'index superieur au curseur, et le
curseur n'est avance qu'en un seul point, par le feed.

Voir `docs/no-lookahead.md` §2 et §3.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Protocol, runtime_checkable

import numpy as np

from rsl.data.schema import (
    ABSENT,
    FLAT,
    Bar,
    BarStore,
    BarWindow,
    Field,
    FloatArray,
    Granularity,
    Panel,
    PositionState,
    ns_to_datetime,
)
from rsl.data.session import SessionField, read_session
from rsl.errors import (
    ConfigurationError,
    InsufficientHistoryError,
    LookAheadError,
    SymbolNotAvailableError,
)


@runtime_checkable
class PeerResolver(Protocol):
    """Ce qui sait donner, a un instant fixe, le contexte d'un AUTRE instrument.

    Seul un panneau le sait : le `MultiContext` l'implemente. Un contexte
    mono-instrument n'a pas de pairs, et le dit plutot que de renvoyer du vide.
    """

    def resolve_peer(self, symbol: str) -> Context: ...

    def peer_symbols(self) -> tuple[str, ...]: ...

    def at_instant(self, ts_close_ns: int) -> PeerResolver:
        """Le meme resolveur, fige a un instant ANTERIEUR ou egal.

        C'est ce qui permet a `shifted` de tenir sa promesse. Sans cela, une
        vue reculee de `lag` barres continuait de voir ses pairs a l'instant
        COURANT : `rolling(zscore, 120, close / peer(NQ, close))` divisait les
        120 clotures d'ES par la MEME cloture de NQ. Le z-score etant
        invariant d'echelle, le terme distant n'avait alors aucun effet -
        mesure le 2026-09-11, ecart maximum 2,08e-14 avec un z-score d'ES seul.

        La ligne visee est cherchee dans le calendrier du panneau, et le pair
        y est resolu par les REGLES DU PANNEAU : un instrument absent le reste,
        un report borne le reste. Remonter directement dans le magasin du pair
        court-circuiterait ces regles et rendrait un « dernier prix connu » que
        `docs/no-lookahead.md` §4.1 refuse.
        """
        ...


@runtime_checkable
class Context(Protocol):
    """Ce qu'une strategie voit du monde a l'instant `t`.

    Rien dans ce protocole ne permet de lire au-dela de `t`, ni de savoir
    combien de barres restent. C'est deliberement pauvre.
    """

    @property
    def symbol(self) -> str: ...

    @property
    def ts(self) -> datetime:
        """`ts_close` de la barre courante : l'instant ou l'info est disponible."""
        ...

    @property
    def bar(self) -> Bar: ...

    @property
    def n_bars_seen(self) -> int: ...

    def value(self, field: Field, lag: int = 0) -> float: ...

    def history(self, n: int) -> BarWindow: ...

    def values(self, field: Field, n: int) -> FloatArray: ...

    def shifted(self, lag: int) -> Context: ...

    @property
    def data_token(self) -> object:
        """Jeton OPAQUE identifiant la serie lue. Comparable, rien d'autre.

        Deux contextes rendent le MEME jeton si et seulement s'ils lisent le
        meme magasin : `shifted` le conserve, `peer` en donne un autre, et deux
        magasins distincts du meme symbole - une serie propre et sa version
        corrompue, par exemple - n'ont jamais le meme.

        A quoi il sert : les noeuds qui reevaluent leur sous-arbre a plusieurs
        decalages (`rolling`, `bars_since`, `cumulative`) memoisent le resultat
        par barre, et doivent pouvoir jeter cette memoire des qu'on leur
        presente une autre serie. Sans jeton, ils n'ont aucun moyen de le
        savoir, et une valeur calculee sur une serie servirait pour une autre.

        Ce qu'il n'est PAS : un acces aux donnees. C'est un `object()` nu,
        sans aucun attribut - le seul usage possible est `token is autre`. Y
        mettre le magasin aurait donne l'historique complet, futur inclus, a
        qui lit la surface publique.
        """
        ...

    @property
    def position(self) -> PositionState:
        """Ce que la strategie sait de SA position. Jamais du marche."""
        ...

    def peer(self, symbol: str) -> Context:
        """Contexte d'un autre instrument, au MEME instant."""
        ...

    def session_value(self, field: SessionField, lag: int = 0) -> float:
        """Grandeur de seance, `lag` seances en arriere.

        Leve si le run n'a declare aucun calendrier : le socle n'invente pas
        de frontiere de seance (voir `rsl.data.session`).
        """
        ...


class BarContext:
    """Vue a curseur sur un `BarStore`, mono-instrument.

    Le curseur demarre a -1 : avant le premier `_advance()`, aucune barre n'est
    close et tout acces leve `InsufficientHistoryError`.

    Note d'honnetete : Python n'offre pas de scellement dur. Un appelant
    determine peut atteindre `_store`. Le contrat est qu'aucune SURFACE
    PUBLIQUE n'expose le magasin ni la longueur de l'echantillon ; le test de
    corruption du futur (`docs/no-lookahead.md` §6) est ce qui verifie qu'aucune
    strategie n'a contourne le contrat.
    """

    __slots__ = ("_i", "_peers", "_position", "_store")

    def __init__(self, store: BarStore) -> None:
        self._store = store
        self._i = -1
        self._position = FLAT
        self._peers: PeerResolver | None = None

    # -- avancee du curseur : reserve au feed -----------------------------

    def _advance(self) -> None:
        self._i += 1

    def _seek(self, index: int) -> None:
        """Positionnement absolu, utilise par le feed multi-instruments."""
        self._i = index

    def _set_peers(self, resolver: PeerResolver | None) -> None:
        """Branche le resolveur de pairs. Reserve au feed multi-instruments."""
        self._peers = resolver

    def _set_position(self, state: PositionState) -> None:
        """Renseigne l'etat de position. Reserve au runner.

        Le runner est le seul a connaitre la verite : il voit les fills. Un
        `Context` construit hors runner reste a plat, ce qui est la seule
        reponse honnete quand personne ne negocie.
        """
        self._position = state

    # -- surface publique -------------------------------------------------

    def peer(self, symbol: str) -> BarContext:
        """Contexte d'un AUTRE instrument, positionne au meme instant.

        C'est ce qui rend exprimable un spread, un ratio ou une couverture :
        `close(ES) - close(NQ)` a besoin des deux au meme moment, pas de l'un
        puis de l'autre.

        Trois refus explicites, plutot qu'un silence :

        - hors panneau, il n'y a pas de pair du tout -> `ConfigurationError`,
          parce qu'une strategie qui lit deux instruments ne peut pas tourner
          sur un seul et que le decouvrir en silence serait pire ;
        - un symbole hors du panneau n'existe pas -> `ConfigurationError`,
          meme raison : c'est une faute de specification, pas un alea ;
        - un symbole qui ne cote pas a cet instant est absent ->
          `SymbolNotAvailableError`, qui est un ETAT legitime d'une coupe
          transversale. Il n'a pas "le prix d'avant"
          (`docs/no-lookahead.md` §4.1).

        Les deux premiers cas doivent faire echouer le run ; le troisieme se
        traduit en « je ne sais pas » cote signal.

        Le pair rendu est un `Context` ordinaire : ses propres gardes
        s'appliquent, et il ne montre que des barres closes.
        """
        if self._peers is None:
            raise ConfigurationError(
                f"'{symbol}' demande depuis un contexte mono-instrument : aucun pair "
                f"n'existe. Une strategie qui lit plusieurs instruments doit tourner "
                f"sur un panneau."
            )
        resolved = self._peers.resolve_peer(symbol)
        assert isinstance(resolved, BarContext)
        return resolved

    @property
    def peers(self) -> tuple[str, ...]:
        """Symboles accessibles a cet instant. Vide hors panneau."""
        return () if self._peers is None else self._peers.peer_symbols()

    @property
    def position(self) -> PositionState:
        """Etat de la position de la strategie sur cet instrument.

        Decrit le passe de la strategie, pas l'avenir du marche : les
        valeurs viennent des fills et des barres deja traversees. Voir
        `PositionState` et `docs/no-lookahead.md` §2.5.
        """
        return self._position

    @property
    def symbol(self) -> str:
        return self._store.symbol

    @property
    def granularity(self) -> Granularity:
        return self._store.granularity

    @property
    def data_token(self) -> object:
        """Le jeton du magasin : un objet NU, qui ne porte aucune donnee.

        Ni le magasin lui-meme - ce serait donner l'historique complet, futur
        inclus, sur la surface publique - ni un entier d'identite, que le
        ramassage reattribue. Voir `BarStore.token`.
        """
        return self._store.token

    @property
    def n_bars_seen(self) -> int:
        """Nombre de barres closes vues jusqu'ici.

        Il n'existe volontairement ni `__len__`, ni `total_bars`, ni
        `end_date` : une strategie qui connait la fin de l'echantillon peut
        s'en servir (`docs/no-lookahead.md` §2.2, regle 4).
        """
        return self._i + 1

    @property
    def ts(self) -> datetime:
        return ns_to_datetime(int(self._store.ts_close[self._require_index(0)]))

    @property
    def ts_event(self) -> datetime:
        return ns_to_datetime(int(self._store.ts_event[self._require_index(0)]))

    @property
    def bar(self) -> Bar:
        return self._store.bar_at(self._require_index(0))

    def bar_at(self, lag: int = 0) -> Bar:
        """Barre a `lag` barres en arriere. `lag = 0` est la barre courante."""
        return self._store.bar_at(self._require_index(lag))

    def value(self, field: Field, lag: int = 0) -> float:
        """Valeur scalaire d'un champ, `lag` barres en arriere.

        Un `lag` negatif viserait une barre non close : `LookAheadError`.
        """
        return float(self._store.column(field)[self._require_index(lag)])

    def values(self, field: Field, n: int) -> FloatArray:
        """Les `n` dernieres valeurs d'un champ, la plus recente en fin.

        Retourne une COPIE en lecture seule : une vue `numpy` exposerait le
        tableau complet via `.base`.
        """
        start = self._require_window(n)
        out = np.array(self._store.column(field)[start : self._i + 1], dtype=np.float64)
        out.setflags(write=False)
        return out

    def session_value(self, field: SessionField, lag: int = 0) -> float:
        """Delegue a `read_session`, qui porte les regles de causalite.

        Le calendrier vient du MAGASIN : `shifted`, `peer` et les deux feeds en
        heritent donc sans plomberie, et une vue reculee voit la meme seance
        que celle qu'elle aurait vue a l'epoque.
        """
        index = self._store.sessions
        if index is None:
            raise ConfigurationError(
                "session : aucun calendrier declare pour "
                f"'{self._store.symbol}'. Ajouter un bloc `session` a son entree "
                "`data` : le socle ne devine pas de frontiere de seance."
            )
        return read_session(index, self._require_index(0), field, lag)

    def shifted(self, lag: int) -> BarContext:
        """Vue du meme magasin, reculee de `lag` barres.

        Permet d'evaluer une expression "telle qu'elle etait il y a `lag`
        barres" - un croisement de moyennes, par exemple - sans jamais sortir
        du passe : la vue rendue est un `BarContext` ordinaire dont le curseur
        est <= celui d'origine, donc soumis aux memes gardes.

        Un `lag` negatif leve `LookAheadError` avant toute construction.
        """
        index = self._require_index(lag)
        sub = BarContext(self._store)
        sub._seek(index)
        # L'etat de position suit la vue. C'est une LIMITE connue, pas un
        # choix : le runner ne conserve que l'etat courant, il n'existe nulle
        # part d'historique de positions a reculer. Consequence a connaitre -
        # `rolling(mean, 20, position("bars_held"))` lit vingt fois la meme
        # valeur. Voir [[reference/vocabulaire-signaux]].
        sub._set_position(self._position)
        # Les pairs, eux, RECULENT : ils le peuvent, puisque le panneau porte
        # tout leur historique. Jusqu'au 2026-09-11 ils restaient a l'instant
        # courant, ce qui rendait le terme distant constant sur toute une
        # fenetre glissante - donc sans effet sur un z-score.
        sub._set_peers(
            None if self._peers is None
            else self._peers.at_instant(int(self._store.ts_close[index]))
        )
        return sub

    def history(self, n: int) -> BarWindow:
        """Les `n` dernieres barres closes, la plus recente en fin."""
        start = self._require_window(n)
        stop = self._i + 1
        store = self._store

        def frozen(source: FloatArray) -> FloatArray:
            out = np.array(source[start:stop], dtype=np.float64)
            out.setflags(write=False)
            return out

        ts = np.array(store.ts_close[start:stop], dtype=np.int64)
        ts.setflags(write=False)
        return BarWindow(
            ts_close=ts,
            open=frozen(store.open),
            high=frozen(store.high),
            low=frozen(store.low),
            close=frozen(store.close),
            volume=frozen(store.volume),
        )

    # -- gardes -----------------------------------------------------------

    def _require_index(self, lag: int) -> int:
        if lag < 0:
            raise LookAheadError(
                f"lag negatif ({lag}) sur {self._store.symbol} : la barre visee n'est pas "
                f"close a {self.n_bars_seen} barre(s) vue(s). Le futur n'est pas lisible."
            )
        index = self._i - lag
        if index < 0:
            raise InsufficientHistoryError(
                f"lag {lag} demande sur {self._store.symbol} mais seulement "
                f"{self.n_bars_seen} barre(s) close(s). Declarez un `warmup_bars` suffisant."
            )
        return index

    def _require_window(self, n: int) -> int:
        if n <= 0:
            raise ValueError(f"taille de fenetre doit etre >= 1, recu {n}")
        if n > self.n_bars_seen:
            raise InsufficientHistoryError(
                f"fenetre de {n} barres demandee sur {self._store.symbol} mais seulement "
                f"{self.n_bars_seen} close(s). Aucun NaN n'est renvoye a la place : un NaN "
                f"se propage en silence et produit 'pas de signal' au lieu d''erreur'."
            )
        return self._i - n + 1


class BarFeed:
    """Iterateur mono-instrument : avance le curseur et cede le `Context`.

    Le meme objet `Context` est cede a chaque tour : c'est une fenetre
    mobile, pas un instantane. Le conserver d'une barre a l'autre ne fige rien
    (mais ne donne pas non plus acces au futur).

    `warmup_bars` : nombre de barres consommees en silence avant le premier
    `yield`. Elles alimentent l'historique sans etre soumises a la strategie ni
    comptees dans les metriques.

    `stop` : index de fin exclusif. C'est ce parametre qui rend le test de
    corruption du futur possible (`docs/no-lookahead.md` §6).
    """

    __slots__ = ("_stop", "_store", "_warmup")

    def __init__(self, store: BarStore, *, warmup_bars: int = 0, stop: int | None = None) -> None:
        if warmup_bars < 0:
            raise ConfigurationError(f"warmup_bars doit etre >= 0, recu {warmup_bars}")
        limit = store.n_bars if stop is None else stop
        if limit < 0 or limit > store.n_bars:
            raise ConfigurationError(f"stop={stop} hors de [0, {store.n_bars}]")
        self._store = store
        self._warmup = warmup_bars
        self._stop = limit

    @property
    def symbol(self) -> str:
        return self._store.symbol

    @property
    def n_tradable_bars(self) -> int:
        """Barres effectivement soumises a la strategie, prechauffage exclu."""
        return max(0, self._stop - self._warmup)

    def __iter__(self) -> Iterator[BarContext]:
        ctx = BarContext(self._store)
        for i in range(self._stop):
            ctx._advance()
            if i >= self._warmup:
                yield ctx


class MultiContext:
    """Coupe transversale a une ligne du panneau.

    Un instrument absent n'a pas "le prix d'avant" : `__getitem__` leve
    `SymbolNotAvailableError`, et `symbols` ne le liste pas
    (`docs/no-lookahead.md` §4.1).
    """

    __slots__ = ("_contexts", "_panel", "_row")

    def __init__(self, panel: Panel) -> None:
        self._panel = panel
        self._row = -1
        self._contexts = {s: BarContext(panel.stores[s]) for s in panel.symbols}

    def _seek_row(self, row: int) -> None:
        self._row = row
        for sym in self._panel.symbols:
            index = int(self._panel.row_index[sym][row])
            if index != ABSENT:
                self._contexts[sym]._seek(index)
                # Chaque sous-contexte peut atteindre les autres, par le
                # panneau : c'est lui qui connait qui cote a cet instant.
                self._contexts[sym]._set_peers(self)

    @property
    def ts(self) -> datetime:
        return ns_to_datetime(int(self._panel.ts_close[self._row]))

    @property
    def symbols(self) -> tuple[str, ...]:
        """Instruments cotant a cet instant, tries. L'ordre ne depend d'aucun `set`."""
        return self._panel.present_symbols(self._row)

    def __contains__(self, symbol: str) -> bool:
        return symbol in self.symbols

    def __getitem__(self, symbol: str) -> BarContext:
        if symbol not in self._panel.stores:
            raise SymbolNotAvailableError(f"{symbol} ne fait pas partie du panneau")
        if int(self._panel.row_index[symbol][self._row]) == ABSENT:
            raise SymbolNotAvailableError(
                f"{symbol} ne cote pas a {self.ts.isoformat()}. Absent ne signifie pas "
                f"'dernier prix connu' : activez explicitement align_policy='ffill' si "
                f"c'est ce que vous voulez."
            )
        return self._contexts[symbol]

    def resolve_peer(self, symbol: str) -> BarContext:
        """Implemente `PeerResolver`.

        Distingue deux refus que `__getitem__` confond a dessein : un symbole
        hors panneau est une faute de specification, un symbole absent a cet
        instant est un etat de marche.
        """
        if symbol not in self._panel.stores:
            raise ConfigurationError(
                f"'{symbol}' ne fait pas partie du panneau. Presents : "
                f"{', '.join(self._panel.symbols)}"
            )
        return self[symbol]

    def peer_symbols(self) -> tuple[str, ...]:
        return self.symbols

    def at_instant(self, ts_close_ns: int) -> PeerResolver:
        """Implemente `PeerResolver.at_instant`.

        Rend un resolveur FIGE, et non ce `MultiContext` recule : celui-ci est
        un curseur unique que le feed avance, et le reculer ici corromprait la
        ligne en cours d'evaluation.
        """
        return FrozenPeers(self._panel, ts_close_ns)

    def is_stale(self, symbol: str) -> bool:
        """True si la barre visible pour cet instrument provient d'un report explicite."""
        return bool(self._panel.is_stale[symbol][self._row])


def _row_at(panel: Panel, ts_close_ns: int) -> int:
    """Derniere ligne du panneau dont la cloture est <= `ts_close_ns`.

    Recherche et non arithmetique : le calendrier est l'UNION des clotures, il
    n'a donc pas de pas regulier. `side="right"` puis `-1` donne bien la
    derniere ligne <= l'instant, y compris quand il tombe exactement dessus.
    """
    ligne = int(np.searchsorted(panel.ts_close, ts_close_ns, side="right")) - 1
    if ligne < 0:
        raise InsufficientHistoryError(
            f"aucune ligne de panneau a {ts_close_ns} ou avant : le calendrier "
            f"commence plus tard. Declarez un `warmup_bars` suffisant."
        )
    return ligne


class FrozenPeers:
    """Resolveur de pairs fige a une ligne du panneau.

    Existe pour `shifted` : une vue reculee doit voir les autres instruments
    tels qu'ils etaient a SON instant, pas a l'instant courant.

    Passe par le panneau et non par les magasins : c'est ce qui fait qu'un
    instrument absent le reste, et qu'un report borne le reste. Lire
    directement le magasin du pair rendrait le dernier prix connu, ce que
    `docs/no-lookahead.md` §4.1 refuse explicitement.
    """

    __slots__ = ("_instant", "_panel", "_row")

    def __init__(self, panel: Panel, ts_close_ns: int) -> None:
        self._panel = panel
        self._instant = ts_close_ns
        self._row = -1  # cherche a la PREMIERE demande, pas ici

    @property
    def row(self) -> int:
        """La ligne visee, cherchee paresseusement.

        `shifted` construit un resolveur a CHAQUE decalage, y compris pour les
        sous-arbres qui ne contiennent aucun `peer` - et ils sont la majorite.
        Chercher la ligne dans le constructeur ferait payer un `searchsorted`
        par decalage a `rolling(mean, 20, close)` sur un panneau, pour rien.
        """
        if self._row < 0:
            self._row = _row_at(self._panel, self._instant)
        return self._row

    def resolve_peer(self, symbol: str) -> BarContext:
        """Memes deux refus que `MultiContext.resolve_peer`, meme distinction.

        Hors panneau : faute de specification. Absent a cet instant : etat de
        marche legitime.
        """
        if symbol not in self._panel.stores:
            raise ConfigurationError(
                f"'{symbol}' ne fait pas partie du panneau. Presents : "
                f"{', '.join(self._panel.symbols)}"
            )
        ligne = self.row
        index = int(self._panel.row_index[symbol][ligne])
        if index == ABSENT:
            raise SymbolNotAvailableError(
                f"{symbol} ne cote pas a "
                f"{ns_to_datetime(int(self._panel.ts_close[ligne])).isoformat()}. "
                f"Absent ne signifie pas 'dernier prix connu'."
            )
        ctx = BarContext(self._panel.stores[symbol])
        ctx._seek(index)
        # Le pair peut lui-meme atteindre les autres, au MEME instant fige :
        # `peer(A, peer(B, ...))` doit rester coherent.
        ctx._set_peers(self)
        return ctx

    def peer_symbols(self) -> tuple[str, ...]:
        return self._panel.present_symbols(self.row)

    def at_instant(self, ts_close_ns: int) -> PeerResolver:
        """Reculer encore depuis une vue deja reculee reste possible."""
        return FrozenPeers(self._panel, ts_close_ns)


class PanelFeed:
    """Iterateur multi-instruments sur le calendrier commun du panneau."""

    __slots__ = ("_panel", "_stop", "_warmup")

    def __init__(self, panel: Panel, *, warmup_rows: int = 0, stop: int | None = None) -> None:
        if warmup_rows < 0:
            raise ConfigurationError(f"warmup_rows doit etre >= 0, recu {warmup_rows}")
        limit = panel.n_rows if stop is None else stop
        if limit < 0 or limit > panel.n_rows:
            raise ConfigurationError(f"stop={stop} hors de [0, {panel.n_rows}]")
        self._panel = panel
        self._warmup = warmup_rows
        self._stop = limit

    def __iter__(self) -> Iterator[MultiContext]:
        ctx = MultiContext(self._panel)
        for row in range(self._stop):
            ctx._seek_row(row)
            if row >= self._warmup:
                yield ctx
