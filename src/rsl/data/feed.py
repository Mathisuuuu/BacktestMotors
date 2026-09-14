"""`Context` a curseur et iterateurs de barres.

C'est ici que le contrat anti-look-ahead devient du code. Le `Context` detient
une reference au magasin immuable et un entier : rien d'autre. Aucune de ses
methodes ne peut renvoyer une information d'index superieur au curseur, et le
curseur n'est avance qu'en un seul point, par le feed.

Voir `docs/no-lookahead.md` §2 et §3.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

import numpy as np

from rsl.data.evenements import EventCalendar, EventField
from rsl.data.schema import (
    ABSENT,
    FLAT,
    AccountState,
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
from rsl.data.session import SessionField, lags_meme_rang, read_session
from rsl.errors import (
    ConfigurationError,
    InsufficientHistoryError,
    LookAheadError,
    SymbolNotAvailableError,
)


class PositionHistory:
    """Etat de position PAR BARRE, ecrit par le runner, lu par le contexte.

    Pourquoi il existe
    ------------------
    `shifted(lag)` promet une vue « telle qu'elle etait il y a `lag` barres ».
    Jusqu'au 2026-09-11 elle recopiait l'etat de position COURANT, donc
    `rolling(mean, 20, position("bars_held"))` lisait vingt fois la meme
    valeur - en silence. Meme forme de defaut que celui des pairs, corrige le
    meme jour, et pour la meme raison : une vue reculee doit voir le passe.

    Pourquoi ce n'est pas le « noeud a memoire » ecarte au ledger
    -------------------------------------------------------------
    Cette memoire n'est pas dans un noeud, elle est dans le FEED, et c'est le
    runner qui l'ecrit - exactement l'argument que `PositionState` donne deja
    pour justifier que le runner calcule la position plutot qu'un noeud. Le
    runner repart de zero a chaque run par construction ; rien ne survit.

    Pourquoi elle est BORNEE
    ------------------------
    Un etat par barre sur 3,7 M de barres minute pese des centaines de Mo. La
    borne est le `warmup_bars` declare par la strategie, plus un : c'est le
    budget de lecture en arriere que la strategie a elle-meme annonce, et
    aucun noeud ne peut legitimement demander plus sans l'avoir declare.

    Ce qui est rendu hors de la fenetre retenue
    -------------------------------------------
    - avant la premiere barre enregistree : `FLAT`, et ce n'est PAS une
      supposition. Le runner n'appelle pas la strategie pendant le
      prechauffage, donc aucun ordre n'a pu etre emis, donc la position etait
      plate. C'est une deduction, pas un defaut choisi ;
    - au-dela de la borne : `InsufficientHistoryError`, comme partout ailleurs
      quand on demande plus d'historique qu'il n'en existe.
    """

    __slots__ = ("_etats", "_portee", "_premier")

    DEFAUT: Final[int] = 2
    """Profondeur hors runner. Un `BarContext` construit a la main est a plat :
    il n'a rien a retenir, et `FLAT` repond a tout."""

    def __init__(self) -> None:
        self._portee = PositionHistory.DEFAUT
        self._etats: dict[int, PositionState] = {}
        self._premier = -1

    def set_depth(self, portee: int) -> None:
        """Fixee par le runner, depuis le `warmup_bars` de la strategie."""
        self._portee = max(portee, PositionHistory.DEFAUT)

    def taille(self) -> int:
        """Nombre d'etats retenus. Existe pour les tests de bornage."""
        return len(self._etats)

    def record(self, index: int, state: PositionState) -> None:
        """Enregistre l'etat de la barre `index` et laisse tomber le plus vieux.

        Le retrait est en O(1) : le runner enregistre barre par barre, donc
        une seule cle sort de la fenetre a chaque appel. Une purge qui
        BALAYERAIT le dictionnaire couterait `portee` operations par barre -
        740 millions sur les 3,7 M de barres minute d'ES pour une profondeur
        de 200. La premiere version faisait exactement cela.

        Le balayage reste en secours pour le cas non sequentiel, qui ne se
        produit dans aucun runner mais qui ne doit pas faire enfler la memoire
        s'il se produisait.
        """
        if self._premier < 0:
            self._premier = index
        self._etats[index] = state
        self._etats.pop(index - self._portee - 1, None)
        if len(self._etats) > 2 * (self._portee + 1):
            limite = index - self._portee
            for cle in [k for k in self._etats if k < limite or k > index]:
                del self._etats[cle]

    def at(self, index: int) -> PositionState:
        etat = self._etats.get(index)
        if etat is not None:
            return etat
        if self._premier < 0 or index < self._premier:
            # Aucun runner, ou barre de prechauffage : plat par deduction.
            return FLAT
        raise InsufficientHistoryError(
            f"etat de position demande a la barre {index}, mais seules les "
            f"{self._portee} dernieres sont retenues. Declarez un "
            f"`extra_warmup` suffisant sur la strategie."
        )


class AccountHistory:
    """Etat de COMPTE par barre, ecrit par le runner, lu par le contexte.

    Meme role que `PositionHistory`, avec deux differences qui viennent
    toutes deux du fait qu'un compte est COMMUN a tout le portefeuille.

    1. La cle est un INSTANT, pas un index de barre
    ------------------------------------------------
    Un seul compte pour tous les symboles - deux instruments d'un meme
    portefeuille n'ont pas deux equities. Mais chaque symbole a son propre
    index de barre, et sur un panneau la ligne `r` ne vaut pas l'index `r`
    d'un symbole donne. Indexer par barre aurait donc fait lire a l'un ce qui
    a ete ecrit pour l'autre.

    L'horodatage de cloture est la seule coordonnee que tous partagent : le
    calendrier d'un panneau est l'UNION des clotures, donc la cloture d'une
    barre d'un symbole est toujours une ligne de ce calendrier.

    2. Avant le premier enregistrement, l'etat se DEDUIT
    -----------------------------------------------------
    Le runner n'appelle pas la strategie pendant le prechauffage : aucun ordre
    n'a pu etre emis, donc l'equity vaut le capital de depart et le sommet
    aussi. Meme raisonnement que `FLAT` pour les positions.

    Ce qui ne se deduit pas, c'est l'absence totale de runner : la, une equity
    est INCONNUE et non nulle. Rendre zero ferait d'un `drawdown` une division
    par zero silencieuse. On leve, comme `session` leve sans calendrier
    declare - le socle n'invente pas.
    """

    __slots__ = ("_etats", "_initial", "_ordre", "_portee", "_premiere")

    def __init__(self) -> None:
        self._portee = PositionHistory.DEFAUT
        self._etats: dict[int, AccountState] = {}
        self._ordre: deque[int] = deque()
        self._initial: float | None = None
        self._premiere = -1

    def set_depth(self, portee: int) -> None:
        self._portee = max(portee, PositionHistory.DEFAUT)

    def set_initial(self, cash: float) -> None:
        """Capital de depart, declare par le runner avant la boucle.

        C'est lui qui rend deductible l'etat des barres de prechauffage.
        """
        self._initial = cash

    def taille(self) -> int:
        return len(self._etats)

    def record(self, ts_close_ns: int, state: AccountState) -> None:
        """Enregistre, et laisse tomber le plus ancien au-dela de la portee.

        File d'insertion plutot qu'arithmetique sur les cles : les instants
        ne sont pas consecutifs, donc `cle - portee` ne designe rien.
        """
        if self._premiere < 0:
            self._premiere = ts_close_ns
        if ts_close_ns not in self._etats:
            self._ordre.append(ts_close_ns)
        self._etats[ts_close_ns] = state
        while len(self._ordre) > self._portee + 1:
            self._etats.pop(self._ordre.popleft(), None)

    def at(self, ts_close_ns: int) -> AccountState:
        etat = self._etats.get(ts_close_ns)
        if etat is not None:
            return etat
        if self._initial is None:
            raise ConfigurationError(
                "account : aucun compte n'est tenu. Un `Context` construit hors "
                "runner ne connait pas d'equity, et le socle n'en invente pas - "
                "de meme qu'il n'invente pas de frontiere de seance. Ce noeud "
                "n'a de sens que dans un run."
            )
        if self._premiere < 0 or ts_close_ns < self._premiere:
            # Avant la premiere barre du run : prechauffage. Aucun ordre n'a pu
            # etre emis, donc l'equity vaut le capital de depart. Deduction, pas
            # defaut choisi - meme raisonnement que `FLAT` pour les positions.
            return self._au_depart()
        raise InsufficientHistoryError(
            f"etat de compte demande a {ts_close_ns}, mais seules les "
            f"{self._portee} dernieres barres sont retenues. Declarez un "
            f"`extra_warmup` suffisant sur la strategie."
        )

    def _au_depart(self) -> AccountState:
        assert self._initial is not None
        return AccountState(
            equity=self._initial,
            cash=self._initial,
            peak_equity=self._initial,
            initial_equity=self._initial,
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

    def account_value(self, field: str) -> float:
        """Grandeur de compte : equity, cash, drawdown, total_return...

        METHODE et non propriete, comme `session_value` et pour la meme
        raison : elle LEVE quand aucun compte n'est tenu, et `isinstance` sur
        un `Protocol` evalue les proprietes. Une propriete qui leve rend
        `isinstance(ctx, Context)` impossible - constate le 2026-09-12.
        """
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

    def event_value(self, name: str, field: EventField) -> float | None:
        """Grandeur d'un calendrier d'EVENEMENTS declare.

        Leve si aucun calendrier de ce nom n'est declare : le socle ne
        devine pas de calendrier, pas plus qu'il ne devine une seance.

        Rend `None` quand il n'y a rien a dire - aucun evenement avant, ou
        aucun apres - et jamais une sentinelle : « pas d'annonce en vue »
        et « annonce dans zero minute » ne doivent pas se confondre.
        """
        ...

    def lags_de_seance(self, depart: int, nombre: int) -> tuple[int, ...]:
        """Decalages en BARRES vers le MEME RANG dans les seances precedentes.

        Rend `nombre` decalages, du plus recent au plus ancien, pour les
        seances `depart` a `depart + nombre - 1` en arriere. Un decalage, pas
        une valeur : l'appelant s'en sert avec `shifted`, donc la garde de
        causalite reste celle du socle, et tout decalage rendu est >= 1.

        Existe parce qu'un pas FIXE en barres ne retrouve pas le meme rang des
        que les seances ont des longueurs differentes - ce qui est le cas
        general et non l'exception : sur NQ, la seance du vendredi compte 435
        barres quand les autres en comptent 1 362.

        Leve `InsufficientHistoryError` si une seance visee est trop courte
        pour avoir une barre a ce rang, ou si l'echantillon ne remonte pas
        assez loin.
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

    __slots__ = (
        "_account",
        "_evenements",
        "_i",
        "_peers",
        "_positions",
        "_store",
    )

    def __init__(self, store: BarStore) -> None:
        self._store = store
        self._i = -1
        self._positions = PositionHistory()
        self._account = AccountHistory()
        self._peers: PeerResolver | None = None
        # Les calendriers sont PARTAGES avec les vues reculees et les
        # pairs : ils ne dependent ni de la barre ni de l'instrument.
        self._evenements: Mapping[str, EventCalendar] = {}

    # -- avancee du curseur : reserve au feed -----------------------------

    def _advance(self) -> None:
        self._i += 1

    def _seek(self, index: int) -> None:
        """Positionnement absolu, utilise par le feed multi-instruments."""
        self._i = index

    def _set_events(self, calendriers: Mapping[str, EventCalendar]) -> None:
        """Branche les calendriers declares. Reserve au chargement."""
        self._evenements = calendriers

    def _set_peers(self, resolver: PeerResolver | None) -> None:
        """Branche le resolveur de pairs. Reserve au feed multi-instruments."""
        self._peers = resolver

    def _set_position(self, state: PositionState) -> None:
        """Enregistre l'etat de position DE CETTE BARRE. Reserve au runner.

        Le runner est le seul a connaitre la verite : il voit les fills. Un
        `Context` construit hors runner reste a plat, ce qui est la seule
        reponse honnete quand personne ne negocie.

        Enregistre plutot qu'affecte depuis le 2026-09-11 : une vue reculee
        doit pouvoir lire l'etat de SA barre, pas celui du present.
        """
        self._positions.record(self._i, state)

    def _set_account(self, state: AccountState) -> None:
        """Enregistre l'etat de compte DE CETTE BARRE. Reserve au runner.

        Par l'instant de cloture et non par l'index : le compte est commun a
        tous les symboles, qui n'ont pas le meme index a la meme ligne.
        """
        self._account.record(int(self._store.ts_close[self._i]), state)

    def _share_account(self, history: AccountHistory) -> None:
        """Fait pointer ce contexte vers un compte EXISTANT.

        Un seul compte par run : les vues reculees, les pairs et tous les
        symboles d'un panneau partagent le meme objet.
        """
        self._account = history

    def _set_position_depth(self, warmup_bars: int) -> None:
        """Profondeur de l'historique de positions. Reserve au runner.

        Le `warmup_bars` de la strategie est le budget de lecture en arriere
        qu'elle a elle-meme declare : retenir au-dela serait payer pour ce que
        personne n'a annonce vouloir lire.
        """
        self._positions.set_depth(warmup_bars + 1)
        self._account.set_depth(warmup_bars + 1)

    def _share_positions(self, history: PositionHistory) -> None:
        """Fait pointer ce contexte vers un historique EXISTANT.

        Sert a `shifted` et aux pairs figes : une vue derivee doit lire le
        meme historique que celle dont elle vient, pas un historique vide.
        """
        self._positions = history

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
        """Etat de la position de la strategie sur cet instrument, A CETTE BARRE.

        Decrit le passe de la strategie, pas l'avenir du marche : les valeurs
        viennent des fills et des barres deja traversees. Voir `PositionState`
        et `docs/no-lookahead.md` §2.5.

        Sur une vue reculee, rend l'etat qu'avait la position a la barre visee
        - et non l'etat courant, ce qui etait le cas jusqu'au 2026-09-11.
        """
        return self._positions.at(self._i)

    def account_value(self, field: str) -> float:
        """Grandeur de compte A CETTE BARRE.

        Meme regle que `position` sur une vue reculee : on lit la barre visee,
        pas le present. Leve hors runner - voir `AccountHistory`.
        """
        instant = int(self._store.ts_close[self._require_index(0)])
        return self._account.at(instant).field(field)

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

    def event_value(self, name: str, field: EventField) -> float | None:
        """Lit un calendrier declare, a l'instant de CLOTURE de la barre.

        A la cloture et non a l'ouverture : c'est l'instant que la barre
        represente une fois connue, et le seul dont la strategie dispose
        quand elle decide.
        """
        calendrier = self._evenements.get(name)
        if calendrier is None:
            connus = sorted(self._evenements) or ["aucun"]
            raise ConfigurationError(
                f"event : aucun calendrier '{name}' declare. Declares : "
                f"{', '.join(connus)}. Ajouter une entree a `events` : le socle "
                f"ne devine pas de calendrier."
            )
        return calendrier.valeur(
            int(self._store.ts_close[self._require_index(0)]), field
        )

    def lags_de_seance(self, depart: int, nombre: int) -> tuple[int, ...]:
        """Delegue a `lags_meme_rang`, qui porte les regles.

        Meme dependance au calendrier que `session_value`, et meme refus quand
        il n'est pas declare : sans frontiere de seance declaree, « le meme
        rang la veille » ne veut rien dire.
        """
        index = self._store.sessions
        if index is None:
            raise ConfigurationError(
                "seance : aucun calendrier declare pour "
                f"'{self._store.symbol}'. Une fenetre comptee en SEANCES exige "
                "un bloc `session` dans son entree `data` : le socle ne devine "
                "pas de frontiere de seance."
            )
        return lags_meme_rang(index, self._require_index(0), depart, nombre)

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
        sub._set_events(self._evenements)
        # La vue PARTAGE l'historique de positions, et son propre curseur y
        # designe sa barre : `position` y lit donc l'etat qu'avait la position
        # a ce moment-la. Recopier l'etat courant, comme jusqu'au 2026-09-11,
        # faisait lire vingt fois la meme valeur a
        # `rolling(mean, 20, position("bars_held"))`.
        sub._share_positions(self._positions)
        sub._share_account(self._account)
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

    __slots__ = ("_account", "_contexts", "_multipliers", "_panel", "_row")

    def __init__(self, panel: Panel) -> None:
        self._panel = panel
        self._row = -1
        self._multipliers: dict[str, float] = {}
        self._contexts = {s: BarContext(panel.stores[s]) for s in panel.symbols}
        # UN compte pour tout le panneau : deux instruments d'un meme
        # portefeuille n'ont pas deux equities. Les positions, elles, restent
        # par symbole - c'est la difference entre les deux etats.
        self._account = AccountHistory()
        for contexte in self._contexts.values():
            contexte._share_account(self._account)

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

    def _set_multipliers(self, multipliers: Mapping[str, float]) -> None:
        """Declare la taille des contrats. Reserve au runner, une seule fois.

        Le runner detient deja les `InstrumentSpec` du run ; il les transmet
        plutot que de laisser la couche `strategies` aller les rechercher dans
        la table globale. Deux chemins vers la meme donnee en feraient deux
        sources, dont l'une finirait par mentir.
        """
        self._multipliers = dict(multipliers)

    def contract_value(self, symbol: str) -> float:
        """Valeur d'UN contrat de `symbol`, en devise, a cet instant.

        C'est la seule grandeur dont une allocation ait besoin pour convertir
        de l'argent en contrats, et la seule que l'on expose : une strategie
        n'a pas a connaitre la marge, le tick ni les frais - ce sont des
        affaires du moteur.

        Leve si l'instrument ne cote pas a cet instant (par `__getitem__`), ou
        si aucun multiplicateur n'a ete declare - c'est-a-dire hors runner.
        Rendre une valeur plausible ferait une allocation silencieusement
        fausse, ce qui est pire qu'un refus.
        """
        multiplicateur = self._multipliers.get(symbol)
        if multiplicateur is None:
            raise ConfigurationError(
                f"aucun multiplicateur declare pour {symbol} : `contract_value` "
                f"n'est utilisable que dans un run."
            )
        return self[symbol].bar.close * multiplicateur
    def _set_account(self, state: AccountState) -> None:
        """Enregistre l'etat de compte de la ligne courante. Reserve au runner.

        Une seule fois par ligne, et non par symbole : le compte est commun.
        """
        self._account.record(int(self._panel.ts_close[self._row]), state)

    def _account_history(self) -> AccountHistory:
        """Le compte du panneau. Reserve au runner, pour le declarer."""
        return self._account

    def _context_of(self, symbol: str) -> BarContext:
        """Le contexte d'un symbole, qu'il cote ou non a la ligne courante.

        Reserve au runner, comme `_seek_row` : il doit pouvoir declarer la
        profondeur de l'historique de positions sur CHAQUE instrument, y
        compris ceux qui ne cotent pas encore. `__getitem__` leve dans ce cas,
        et c'est voulu - mais ce n'est pas la question posee ici.
        """
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
        return FrozenPeers(
            self._panel,
            ts_close_ns,
            {s: c._positions for s, c in self._contexts.items()},
            self._account,
        )

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

    __slots__ = ("_compte", "_historiques", "_instant", "_panel", "_row")

    def __init__(
        self,
        panel: Panel,
        ts_close_ns: int,
        historiques: dict[str, PositionHistory] | None = None,
        compte: AccountHistory | None = None,
    ) -> None:
        self._panel = panel
        self._instant = ts_close_ns
        self._row = -1  # cherche a la PREMIERE demande, pas ici
        self._compte = compte
        self._historiques = historiques or {}
        """Historiques de position, par symbole.

        Sans eux, le contexte neuf construit par `resolve_peer` serait a plat,
        et `peer(NQ, position("quantity"))` rendrait zero depuis une vue
        reculee alors qu'il rend la bonne valeur depuis la vue courante. Trou
        introduit avec `FrozenPeers` le 2026-09-11 et referme le meme jour.
        """

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
        historique = self._historiques.get(symbol)
        if historique is not None:
            ctx._share_positions(historique)
        if self._compte is not None:
            ctx._share_account(self._compte)
        # Le pair peut lui-meme atteindre les autres, au MEME instant fige :
        # `peer(A, peer(B, ...))` doit rester coherent.
        ctx._set_peers(self)
        return ctx

    def peer_symbols(self) -> tuple[str, ...]:
        return self._panel.present_symbols(self.row)

    def at_instant(self, ts_close_ns: int) -> PeerResolver:
        """Reculer encore depuis une vue deja reculee reste possible."""
        return FrozenPeers(
            self._panel, ts_close_ns, self._historiques, self._compte
        )


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
