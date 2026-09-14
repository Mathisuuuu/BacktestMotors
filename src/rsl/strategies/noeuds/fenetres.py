"""Noeuds qui regardent PLUSIEURS barres : fenetres glissantes et recherche.

Leur point commun est mecanique : ils reevaluent leur sous-arbre sur
`ctx.shifted(k)` pour plusieurs `k`. C'est ce qui les rend puissants - une
statistique glissante s'applique a n'importe quelle expression, pas seulement
a un champ de prix - et c'est ce qui les rend chers.

La memoisation de `rsl/strategies/memoire.py` supprime la redondance ENTRE
barres pour les sous-arbres qui le permettent. Elle est branchee ici, et
nulle part ailleurs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

import numpy as np
import numpy.typing as npt

from rsl.data.feed import Context
from rsl.data.session import SessionField
from rsl.errors import ConfigurationError, InsufficientHistoryError
from rsl.strategies.memoire import (
    Leve,
    Memoire,
    memoire_pour,
    valeur_a,
    valeurs_de_fenetre,
)
from rsl.strategies.noeuds.contrat import (
    FALSE,
    Builder,
    FieldKind,
    NodeField,
    Signal,
    SpecDict,
    _child,
    signal_node,
)

FloatArray = npt.NDArray[np.float64]


class RollingStat(StrEnum):
    """Statistique appliquee a la fenetre.

    `ema` est la plus consequente des six ajoutees en second temps : elle leve
    la seule limite structurelle du vocabulaire. Avant elle, un lissage
    exponentiel n'existait que comme primitive sur un CHAMP de prix, donc
    impossible a appliquer a une expression - la ligne de signal d'un MACD,
    par exemple, etait inexprimable.
    """

    MEAN = "mean"
    STDEV = "stdev"
    MIN = "min"
    MAX = "max"
    SUM = "sum"
    ZSCORE = "zscore"
    EMA = "ema"
    MEDIAN = "median"
    VAR = "var"
    SLOPE = "slope"
    RANK = "rank"
    COUNT_TRUE = "count_true"


DISPERSION_STATS = (RollingStat.STDEV, RollingStat.ZSCORE, RollingStat.VAR, RollingStat.SLOPE)
"""Statistiques exigeant au moins deux observations."""


class RollingAcross(StrEnum):
    """Ce que compte `window` : des barres, ou des seances.

    `bars` est le comportement historique et reste le defaut, si bien
    qu'aucune specification ecrite avant cet ajout ne change de sens - ni de
    `config_hash`, le champ n'etant publie que lorsqu'il s'ecarte du defaut.
    """

    BARS = "bars"
    SESSIONS = "sessions"


@signal_node(
    "rolling",
    summary="Statistique glissante d'un sous-signal QUELCONQUE, pas d'un champ de prix.",
    fields=(
        NodeField(
            "stat",
            FieldKind.STRING,
            choices=tuple(s.value for s in RollingStat),
        ),
        NodeField("window", FieldKind.INTEGER, minimum=1),
        NodeField("stride", FieldKind.INTEGER, required=False, default=1, minimum=1),
        NodeField(
            "across",
            FieldKind.STRING,
            required=False,
            default=RollingAcross.BARS.value,
            choices=tuple(a.value for a in RollingAcross),
            description=(
                "`bars` : `window` barres espacees de `stride`. "
                "`sessions` : la barre courante, puis celles de MEME RANG "
                "dans les seances precedentes. Exige `data[].session`."
            ),
        ),
        NodeField("inner", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class Rolling:
    """Eleve n'importe quel signal scalaire en statistique glissante.

    Les primitives comme `sma` ou `zscore` ne travaillent que sur un CHAMP de
    prix. Ce noeud leve cette limite : il applique la meme mecanique a une
    expression arbitraire. C'est lui qui rend un spread negociable - un ecart
    de prix brut ne se trade pas, son z-score si :

        rolling(zscore, 100, arith(close, "-", peer("NQ.v.0", close)))

    Le pas d'echantillonnage (`stride`)
    -----------------------------------
    Par defaut `stride = 1` : la fenetre prend les `window` dernieres barres,
    consecutives. Avec `stride = n`, elle prend une barre sur `n` - lags 0, n,
    2n, ... Toute specification ecrite avant l'ajout de ce champ garde donc
    exactement le meme sens.

    A quoi cela sert : comparer une barre a celles qui occupent le MEME RANG
    dans les periodes precedentes. Sur des barres de 5 minutes et un `stride`
    de 78, la 12e barre du jour se compare aux 12es barres des jours passes.
    Le pas est DECLARE par l'utilisateur, jamais devine : le socle ne connait
    pas de notion de seance, et l'inferer d'un trou serait une supposition
    (voir le ledger).

    Compter en SEANCES plutot qu'en barres (`across`)
    -------------------------------------------------
    `stride` ne retrouve le meme rang que si toutes les periodes ont la MEME
    longueur. Mesure du 2026-09-13 sur NQ : la seance du vendredi compte 435
    barres et les autres 1 362 - celle ouverte le vendredi a 9 h 30 se ferme
    avant le week-end. Un `stride` de 390 n'echantillonne alors pas « le meme
    rang la veille » mais une heure arbitraire, differente chaque jour.

    `across: "sessions"` fait compter `window` en SEANCES : la barre
    courante, puis les barres de MEME RANG dans les seances precedentes,
    retrouvees par le calendrier DECLARE. Rien n'est devine - sans
    `data[].session`, le noeud leve.

    Cette forme avait ete ecartee le 2026-09-11 (`rolling.across:
    sessions_same_offset`, ledger) faute de frontiere de seance. Le
    calendrier declare l'ayant fournie le jour meme, la condition de reprise
    inscrite alors est remplie.

    Ce qu'elle refuse, et pourquoi
    ------------------------------
    Une seance ECOURTEE n'a pas de barre au rang demande. Le noeud rend alors
    `None` pour toute la fenetre, plutot que de substituer la derniere barre
    disponible - ce qui comparerait 15 h 59 d'un jour plein a 13 h 00 d'un
    demi-jour, c'est-a-dire le desalignement silencieux que `across` existe
    pour supprimer.

    Consequence MESUREE, a connaitre avant de s'en servir : sur NQ avec
    `window` 60, seules 33 % des barres ont une fenetre complete - les
    vendredis courts privent de rang toutes les barres de nuit. Aux douze
    points de controle semi-horaires de la strategie Zarattini, qui vivent
    tous dans les six premieres heures, la proportion est de **88 %**.

    Attention a une statistique : `slope` rend une pente par ECHANTILLON, donc
    par `stride` barres des que le pas depasse 1. Sur une rampe de +1 par barre
    et un `stride` de 2, elle vaut 2, pas 1. Diviser par `stride` pour revenir
    a des unites par barre.

    Comment la fenetre est constituee
    ---------------------------------
    Le sous-signal est reevalue sur `ctx.shifted(k)` pour k de 0 a window-1 -
    donc uniquement sur des barres closes, et par la meme mecanique que le
    reste du socle. Aucune memoire, aucun accumulateur : la valeur ne depend
    que du contexte recu, et deux evaluations du meme instant donnent le meme
    resultat.

    Le cout, et ce qui en reste
    ---------------------------
    En principe `window` evaluations du sous-arbre par barre : sur une fenetre
    de 120 et un `arith` de deux primitives, 1 381 us par barre - soit 1,6 h
    pour UN signal sur les 3,7 M de barres minute d'ES.

    Depuis le 2026-09-11, une MEMOISATION supprime la redondance ENTRE barres
    (`rsl/strategies/memoire.py`) : la valeur du sous-arbre a la barre j etait
    recalculee `window` fois, elle l'est une. Mesure sur le meme cas :
    **1 381 -> 116 us**, et de bout en bout sur ES quotidien 5 427 -> 2 299 ms,
    a empreinte IDENTIQUE.

    Deux limites a connaitre, et elles ne sont pas des details :

    - un sous-arbre contenant `peer` ou `position` n'est PAS memoise, parce que
      `shifted` recopie le resolveur de pairs et l'etat de position : sa valeur
      ne depend alors pas seulement de la serie et de la barre. Le cas
      emblematique - le z-score d'un ratio ES/NQ - garde donc son cout entier ;
    - la memoisation ne change pas la COMPLEXITE. Elle retire un facteur
      `window` constant ; une primitive dediee reste preferable quand elle
      existe.

    Une seule valeur indefinie dans la fenetre rend le tout indefini : une
    moyenne sur une fenetre trouee ne serait pas la moyenne demandee.
    """

    NODE_TYPE: ClassVar[str] = "rolling"
    NODE_VERSION: ClassVar[int] = 1

    stat: RollingStat
    window: int
    inner: Signal
    stride: int = 1
    across: RollingAcross = RollingAcross.BARS
    _memoire: Memoire | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.across is RollingAcross.SESSIONS and self.stride != 1:
            raise ConfigurationError(
                f"'rolling' : `across: sessions` et `stride: {self.stride}` "
                f"disent la meme chose de deux facons, et elles se "
                f"contredisent. La fenetre par seance prend UNE barre par "
                f"seance, au meme rang ; retirer `stride`."
            )
        if self.stride < 1:
            raise ConfigurationError(f"stride doit etre >= 1, recu {self.stride}")
        if self.window < 1:
            raise ConfigurationError(f"window doit etre >= 1, recu {self.window}")
        if self.stat in DISPERSION_STATS and self.window < 2:
            raise ConfigurationError(
                f"'{self.stat.value}' exige window >= 2 : une seule observation n'a "
                f"ni dispersion ni pente"
            )
        # Le noeud reste gele ; seule la memoire qu'il detient est mutable.
        object.__setattr__(
            self,
            "_memoire",
            memoire_pour(self.window * self.stride, self.inner),
        )

    @property
    def warmup_bars(self) -> int:
        """En BARRES - et c'est pourquoi `across: sessions` ne peut pas le dire.

        Combien de barres font soixante seances depend des DONNEES, pas de la
        specification : environ 81 700 sur NQ a la minute, 60 sur du
        quotidien. Le socle refusant d'inventer, le noeud ne declare que le
        warmup de son sous-arbre, et l'insuffisance reelle est signalee a
        l'evaluation : `lags_de_seance` leve, le noeud rend `None`, et une
        regle qui vaut `None` ne declenche pas. Le comportement est donc SUR -
        jamais une valeur fausse, seulement une absence de valeur.

        Ce qu'il faut en faire : declarer `min_warmup_bars` au niveau du run
        quand on veut que le runner saute vraiment ces barres.
        """
        if self.across is RollingAcross.SESSIONS:
            return self.inner.warmup_bars
        return self.inner.warmup_bars + (self.window - 1) * self.stride

    def _decalages(self, ctx: Context) -> Sequence[int] | None:
        """Les lags en barres composant la fenetre, le PRESENT en tete.

        En mode seance le present est inclus EXPLICITEMENT : `zscore`, `rank`
        et `slope` lisent tous `values[0]` comme la valeur courante.
        Demarrer a la seance precedente les ferait porter sur la veille sans
        le dire.
        """
        if self.across is RollingAcross.BARS:
            return range(0, self.window * self.stride, self.stride)
        if self.window == 1:
            return (0,)
        try:
            return (0, *ctx.lags_de_seance(1, self.window - 1))
        except InsufficientHistoryError:
            # Rang absent d'une seance ecourtee, ou echantillon trop court :
            # la fenetre n'existe pas. Meme reponse que pour une valeur
            # manquante, et pour la meme raison.
            return None

    def __call__(self, ctx: Context) -> float | None:
        decalages = self._decalages(ctx)
        if decalages is None:
            return None
        values = valeurs_de_fenetre(self._memoire, self.inner, ctx, decalages)
        if values is None:
            return None

        window = np.array(values, dtype=np.float64)
        match self.stat:
            case RollingStat.MEAN:
                return float(np.mean(window))
            case RollingStat.SUM:
                return float(np.sum(window))
            case RollingStat.MIN:
                return float(np.min(window))
            case RollingStat.MAX:
                return float(np.max(window))
            case RollingStat.STDEV:
                return float(np.std(window, ddof=1))
            case RollingStat.ZSCORE:
                deviation = float(np.std(window, ddof=1))
                if deviation <= 0.0:
                    return None
                # `values[0]` est la valeur COURANTE : `shifted(0)` est le
                # present, et les lags croissants remontent le temps.
                return (values[0] - float(np.mean(window))) / deviation
            case RollingStat.VAR:
                return float(np.var(window, ddof=1))
            case RollingStat.MEDIAN:
                return float(np.median(window))
            case RollingStat.EMA:
                # Amorcee sur la valeur la PLUS ANCIENNE de la fenetre, puis
                # parcourue vers le present. Contrairement a `ema@1`, il n'y a
                # pas d'historique tronque plus long : la fenetre EST tout ce
                # que le noeud voit. Le poids residuel de l'amorce vaut
                # `(1 - alpha)^(window-1)` ; a window=9 il pese encore 13 %,
                # ce qui est assume et documente plutot que masque.
                alpha = 2.0 / (self.window + 1.0)
                courant = values[-1]
                for valeur in reversed(values[:-1]):
                    courant = alpha * valeur + (1.0 - alpha) * courant
                return courant
            case RollingStat.SLOPE:
                # En unites par barre, du passe vers le present : `values` est
                # ordonne du present vers le passe, on le retourne.
                abscisses = np.arange(self.window, dtype=np.float64)
                ordonnees = window[::-1]
                pente = np.polyfit(abscisses, ordonnees, 1)[0]
                return float(pente)
            case RollingStat.RANK:
                # Rang de la valeur COURANTE dans sa fenetre, dans [0, 1].
                # 1.0 = plus haute des `window` dernieres, 0.0 = plus basse.
                return float(np.mean(window <= values[0]))
            case RollingStat.COUNT_TRUE:
                # Les booleens du vocabulaire valent 1.0 ou 0.0 : compter les
                # valeurs strictement positives compte donc les "vrai".
                return float(np.count_nonzero(window > 0.0))

    def describe(self) -> SpecDict:
        decrit: SpecDict = {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "stat": self.stat.value,
            "window": self.window,
            "stride": self.stride,
            "inner": self.inner.describe(),
        }
        # Publie SEULEMENT quand il s'ecarte du defaut : l'emettre toujours
        # changerait le `config_hash` des sept exemples archives pour un champ
        # qui ne dit rien de nouveau chez eux.
        if self.across is not RollingAcross.BARS:
            decrit["across"] = self.across.value
        return decrit

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        raw = spec.get("stat")
        if not isinstance(raw, str) or raw not in set(RollingStat):
            raise ConfigurationError(
                f"'rolling' : statistique invalide {raw!r}. "
                f"Attendu l'un de {', '.join(s.value for s in RollingStat)}"
            )
        window = spec.get("window")
        if not isinstance(window, int) or isinstance(window, bool):
            raise ConfigurationError(f"'rolling' exige un `window` entier, recu {window!r}")
        stride = spec.get("stride", 1)
        if not isinstance(stride, int) or isinstance(stride, bool):
            raise ConfigurationError(f"'rolling' exige un `stride` entier, recu {stride!r}")
        across = spec.get("across", RollingAcross.BARS.value)
        if not isinstance(across, str) or across not in set(RollingAcross):
            raise ConfigurationError(
                f"'rolling' : `across` invalide {across!r}. Attendu "
                f"{' ou '.join(a.value for a in RollingAcross)}"
            )
        return cls(
            RollingStat(raw),
            window,
            _child(spec, "inner", build),
            stride,
            RollingAcross(across),
        )


def rolling(stat: str, window: int, inner: Signal, stride: int = 1) -> Rolling:
    """Raccourci : `rolling("zscore", 100, spread)`."""
    return Rolling(RollingStat(stat), window, inner, stride)


@signal_node(
    "lag",
    summary="Evalue un sous-signal tel qu'il etait il y a `bars` barres.",
    fields=(
        NodeField("bars", FieldKind.INTEGER, minimum=1, description="Toujours vers le passe."),
        NodeField("inner", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class Lag:
    """Decalage temporel d'une expression, toujours vers le passe.

    Repose sur `Context.shifted`, dont le curseur reste <= celui d'origine : un
    decalage negatif est impossible a exprimer.

    Compte des BARRES, et rien d'autre. Reculer d'une SEANCE est une autre
    operation - elle exige un calendrier declare, son warmup ne se connait
    pas en barres, et elle peut ne rien rendre sur une seance ecourtee.
    C'est `session_lag` qui la porte, plus bas. Les fondre en un seul noeud a
    deux champs exclusifs aurait cache ces trois differences.
    """

    NODE_TYPE: ClassVar[str] = "lag"
    NODE_VERSION: ClassVar[int] = 1

    inner: Signal
    bars: int

    def __post_init__(self) -> None:
        if self.bars < 1:
            raise ConfigurationError(f"lag doit etre >= 1 barre, recu {self.bars}")

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars + self.bars

    def __call__(self, ctx: Context) -> float | None:
        return self.inner(ctx.shifted(self.bars))

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "bars": self.bars,
            "inner": self.inner.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        bars = spec.get("bars")
        if not isinstance(bars, int) or isinstance(bars, bool):
            raise ConfigurationError(f"'lag' exige un champ 'bars' entier, recu {bars!r}")
        return cls(_child(spec, "inner", build), bars)


@signal_node(
    "session_lag",
    summary="Evalue un sous-signal au MEME RANG, N seances en arriere.",
    fields=(
        NodeField(
            "sessions",
            FieldKind.INTEGER,
            minimum=1,
            description="Nombre de seances a reculer. Toujours vers le passe.",
        ),
        NodeField("inner", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class SessionLag:
    """La 30e minute d'hier, pas « il y a 390 barres ».

    Pourquoi ce n'est pas un reglage de `lag`
    ------------------------------------------
    Un recul en barres et un recul en seances se ressemblent et ne se
    comportent pas pareil :

    - celui-ci exige un calendrier DECLARE (`data[].session`), et leve sans ;
    - son `warmup_bars` ne se connait pas : combien de barres fait une
      seance depend des donnees, pas de la specification ;
    - il peut ne rien rendre - une seance ECOURTEE n'a pas de barre au rang
      demande - la ou `lag` rend toujours une valeur passe le warmup.

    Les fondre en un noeud a deux champs exclusifs aurait cache ces trois
    differences derriere un nom commun.

    A quoi il sert
    ---------------
    A exclure la seance en cours d'une fenetre `rolling(across="sessions")`,
    ce que le papier de Zarattini demande pour son `sigma[tau]` : la moyenne
    sur soixante seances PRECEDENTES du rendement depuis l'ouverture au meme
    rang. La composition s'ecrit alors sans rien supposer de la longueur
    d'une seance :

        rolling(mean, 60, across="sessions",
                inner=session_lag(1, abs(close / session_open - 1)))

    Ce que rendait l'ecriture precedente
    -------------------------------------
    `lag(bars=390)` supposait 390 barres par seance. Mesure du 2026-09-13 :
    les cotations NQ en portent 1 362 les jours pleins et 435 le vendredi.
    Le decalage ne tombait donc jamais sur le rang voulu.
    """

    NODE_TYPE: ClassVar[str] = "session_lag"
    NODE_VERSION: ClassVar[int] = 1

    inner: Signal
    sessions: int

    def __post_init__(self) -> None:
        if self.sessions < 1:
            raise ConfigurationError(
                f"session_lag doit etre >= 1 seance, recu {self.sessions}. "
                f"Zero designerait la seance en cours, dont la longueur "
                f"n'est connue qu'une fois close."
            )

    @property
    def warmup_bars(self) -> int:
        """Celui du sous-arbre, et rien de plus.

        Le socle refuse d'inventer : nul ne sait combien de barres font N
        seances avant d'avoir lu les donnees. L'insuffisance reelle se
        signale a l'evaluation, ou elle rend `None` - jamais une valeur
        prise au mauvais rang.
        """
        return self.inner.warmup_bars

    def __call__(self, ctx: Context) -> float | None:
        try:
            (recul,) = ctx.lags_de_seance(self.sessions, 1)
        except InsufficientHistoryError:
            # Seance trop courte pour porter ce rang, ou echantillon qui ne
            # remonte pas assez loin. Pas de valeur plutot qu'une valeur
            # prise a un autre rang.
            return None
        return self.inner(ctx.shifted(recul))

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "sessions": self.sessions,
            "inner": self.inner.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        sessions = spec.get("sessions")
        if not isinstance(sessions, int) or isinstance(sessions, bool):
            raise ConfigurationError(
                f"'session_lag' exige un champ 'sessions' entier, recu {sessions!r}"
            )
        return cls(_child(spec, "inner", build), sessions)


@signal_node(
    "bars_since",
    summary="Nombre de barres depuis la derniere fois qu'une condition etait vraie.",
    fields=(
        NodeField("lookback", FieldKind.INTEGER, minimum=1),
        NodeField("inner", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class BarsSince:
    """Distance en barres au dernier "vrai", bornee par `lookback`.

    Rend `0.0` si la condition est vraie maintenant, `None` si elle n'a pas ete
    vraie dans les `lookback` dernieres barres. `None` plutot qu'une sentinelle
    comme `lookback + 1` : une sentinelle se compare sans lever et ferait
    passer "jamais vu" pour "vu il y a longtemps".

    La borne est obligatoire. Sans elle le noeud devrait remonter tout
    l'historique depuis l'origine, ce qui rendrait son cout dependant de la
    position dans l'echantillon et son warmup indefinissable.
    """

    NODE_TYPE: ClassVar[str] = "bars_since"
    NODE_VERSION: ClassVar[int] = 1

    lookback: int
    inner: Signal
    _memoire: Memoire | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.lookback < 1:
            raise ConfigurationError(f"lookback doit etre >= 1, recu {self.lookback}")
        object.__setattr__(self, "_memoire", memoire_pour(self.lookback, self.inner))

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars + self.lookback - 1

    def __call__(self, ctx: Context) -> float | None:
        # Valeur par valeur et non par fenetre entiere : ce noeud s'arrete des qu'il
        # trouve, et construire toute la fenetre annulerait cet arret.
        for lag in range(self.lookback):
            valeur = valeur_a(self._memoire, self.inner, ctx, lag)
            if valeur is None or isinstance(valeur, Leve):
                return None
            if valeur != FALSE:
                return float(lag)
        return None

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "lookback": self.lookback,
            "inner": self.inner.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        lookback = spec.get("lookback")
        if not isinstance(lookback, int) or isinstance(lookback, bool):
            raise ConfigurationError(
                f"'bars_since' exige un `lookback` entier, recu {lookback!r}"
            )
        return cls(lookback, _child(spec, "inner", build))


def bars_since(lookback: int, inner: Signal) -> BarsSince:
    """Raccourci : `bars_since(50, condition)`."""
    return BarsSince(lookback, inner)


class CumulativeStat(StrEnum):
    """Statistique cumulee depuis l'ouverture de la seance."""

    SUM = "sum"
    MEAN = "mean"
    MIN = "min"
    MAX = "max"
    FIRST = "first"
    LAST = "last"
    COUNT_TRUE = "count_true"


class _TamponDeSeance:
    """Les valeurs de `inner` depuis l'ouverture, gardees en NUMPY.

    Pourquoi ce tampon existe
    --------------------------
    `Cumulative` demandait a `valeurs_de_fenetre` de rassembler `rang + 1`
    valeurs a chaque barre, par une boucle PYTHON. Meme une fois la memoire
    consultee avant la vue reculee - correctif du 2026-09-13 qui a deja divise
    le cout par trois - il restait quatre operations Python par lag : lecture du
    jeton, recherche dans un dictionnaire, test de type, ajout a une liste.

    Sur une seance de 400 barres, cela fait 1 600 operations par barre et par
    noeud. Un VWAP ancre en compte deux : 428 us/barre mesures, contre 0,05 us
    pour l'equivalent vectorise.

    Le tampon garde la serie CHRONOLOGIQUE dans un tableau numpy qui grandit, et
    n'y ajoute qu'UNE valeur par barre nouvelle. La fenetre devient une vue, pas
    une reconstruction.

    L'ordre est preserve, et ce n'est pas un detail
    -----------------------------------------------
    `valeurs_de_fenetre` rend le PRESENT EN TETE. `np.sum` somme par paires, et
    le groupement depend de l'ordre : sommer a l'endroit ou a l'envers ne donne
    pas les memes bits. Le tampon rend donc une vue RENVERSEE
    (`tableau[:n][::-1]`), qui presente exactement la meme sequence que la liste
    d'avant. Les sept empreintes archivees le verifient.

    Ce qu'il ne fait pas
    ---------------------
    Il ne cumule rien lui-meme. Un accumulateur courant - ajouter la nouvelle
    valeur a un total - serait plus rapide encore, et donnerait d'AUTRES bits
    que `np.sum` : l'addition sequentielle n'est pas la sommation par paires.
    Le tampon garde donc les valeurs et laisse numpy reduire, ce qui preserve le
    resultat au bit pres.
    """

    __slots__ = ("_ancre", "_debut", "_n", "_valeurs")

    CAPACITE_INITIALE: ClassVar[int] = 64

    def __init__(self) -> None:
        self._ancre: object = None
        self._debut: int = -1
        self._n: int = 0
        self._valeurs: FloatArray = np.empty(self.CAPACITE_INITIALE, dtype=np.float64)

    def _reinitialiser(self, jeton: object, debut: int) -> None:
        self._ancre = jeton
        self._debut = debut
        self._n = 0

    def _ajouter(self, valeur: float) -> None:
        if self._n == self._valeurs.shape[0]:
            # Croissance geometrique : une reallocation par doublement, pas une
            # par barre.
            self._valeurs = np.resize(self._valeurs, self._n * 2)
        self._valeurs[self._n] = valeur
        self._n += 1

    def fenetre(self, jeton: object, debut: int, rang: int) -> FloatArray | None:
        """La fenetre PRESENT EN TETE, ou `None` s'il faut la reconstruire.

        Rend `None` dans les trois cas ou le tampon ne sait pas repondre : une
        autre serie, une autre seance, ou un rang qu'il n'a pas encore atteint.
        L'appelant retombe alors sur le chemin general, qui est juste et lent.
        """
        if jeton is not self._ancre or debut != self._debut:
            return None
        if rang + 1 > self._n:
            return None
        return self._valeurs[: rang + 1][::-1]


@signal_node(
    "cumulative",
    summary="Cumul d'un sous-signal DEPUIS l'ouverture de la seance courante.",
    fields=(
        NodeField(
            "stat",
            FieldKind.STRING,
            choices=tuple(s.value for s in CumulativeStat),
        ),
        NodeField("inner", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class Cumulative:
    """Fenetre a longueur VARIABLE : celle qui va de l'ouverture a maintenant.

    C'est la difference avec `rolling`, dont la fenetre est fixe. Ici elle
    s'allonge barre apres barre et repart a zero a chaque seance. Exige donc un
    calendrier declare, comme le noeud `session`.

    Ce que cela debloque, sans aucune primitive nouvelle - le VWAP ANCRE sur la
    seance, qui n'etait pas exprimable :

        arith(/,
          cumulative(sum, arith(*, prix_typique, price(volume))),
          cumulative(sum, price(volume)))

    Et aussi le plus haut depuis l'ouverture, le volume cumule, le nombre de
    barres depuis l'ouverture ou le compte de conditions remplies dans la
    seance.

    Cout, assume et a connaitre : le sous-arbre est reevalue une fois par barre
    ecoulee depuis l'ouverture. Sur une seance de 1 380 barres d'une minute, la
    derniere barre l'evalue 1 380 fois. C'est le meme arbitrage que `rolling`,
    la correction avant la vitesse, et une primitive dediee reste possible le
    jour ou un cas precis devient trop lent.

    Pas de `reset: never` : un cumul depuis l'origine remonterait tout
    l'historique, son cout dependrait de la position dans l'echantillon et son
    warmup serait indefinissable. C'est la raison pour laquelle `bars_since@1`
    est borne, et elle vaut ici aussi.
    """

    NODE_TYPE: ClassVar[str] = "cumulative"
    NODE_VERSION: ClassVar[int] = 1

    stat: CumulativeStat
    inner: Signal
    _memoire: Memoire | None = field(default=None, compare=False, repr=False)
    _tampon: _TamponDeSeance = field(
        default_factory=_TamponDeSeance, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        # Portee : une seance de barres d'une minute en compte ~1 380. Le
        # chiffre n'a pas besoin d'etre exact - il borne la memoire, il ne
        # gouverne rien. Trop petit, on perd des reprises ; trop grand, on
        # retient des barres inutiles. C'est le seul parametre approximatif du
        # mecanisme, et il ne peut pas changer un resultat.
        object.__setattr__(self, "_memoire", memoire_pour(1_500, self.inner))

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars

    def __call__(self, ctx: Context) -> float | None:
        rang = int(ctx.session_value(SessionField.BAR_INDEX, 0))
        fenetre = self._fenetre(ctx, rang)
        if fenetre is None:
            return None
        match self.stat:
            case CumulativeStat.SUM:
                return float(np.sum(fenetre))
            case CumulativeStat.MEAN:
                return float(np.mean(fenetre))
            case CumulativeStat.MIN:
                return float(np.min(fenetre))
            case CumulativeStat.MAX:
                return float(np.max(fenetre))
            case CumulativeStat.FIRST:
                # La fenetre est PRESENT EN TETE : la premiere barre de la
                # seance est donc en queue.
                return float(fenetre[-1])
            case CumulativeStat.LAST:
                return float(fenetre[0])
            case CumulativeStat.COUNT_TRUE:
                return float(np.count_nonzero(fenetre > 0.0))

    def _fenetre(self, ctx: Context, rang: int) -> FloatArray | None:
        """La fenetre depuis l'ouverture, PRESENT EN TETE.

        Trois chemins, du moins cher au plus cher :

        1. le tampon la connait deja - une vue, rien a calculer ;
        2. il lui manque exactement la barre courante - une evaluation ;
        3. il ne sait pas repondre - reconstruction par le chemin general.

        Le troisieme arrive a chaque nouvelle seance, et sur toute vue reculee
        qui saute en arriere. Il est juste et lent ; les deux premiers sont
        justes et rapides.
        """
        jeton = ctx.data_token
        debut = ctx.n_bars_seen - 1 - rang

        connue = self._tampon.fenetre(jeton, debut, rang)
        if connue is not None:
            return connue

        # Cas 2 : la seance est la bonne et il ne manque que le present.
        if (
            jeton is self._tampon._ancre
            and debut == self._tampon._debut
            and rang == self._tampon._n
        ):
            valeur = valeur_a(self._memoire, self.inner, ctx, 0)
            if valeur is None or isinstance(valeur, Leve):
                return None
            self._tampon._ajouter(float(valeur))
            return self._tampon.fenetre(jeton, debut, rang)

        # Cas 3 : tout reconstruire, et repartir le tampon de la.
        values = valeurs_de_fenetre(
            self._memoire, self.inner, ctx, range(rang + 1)
        )
        if values is None:
            return None
        self._tampon._reinitialiser(jeton, debut)
        # `values[0]` est le PRESENT : le tampon garde l'ordre CHRONOLOGIQUE.
        for valeur in reversed(values):
            self._tampon._ajouter(valeur)
        return self._tampon.fenetre(jeton, debut, rang)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "stat": self.stat.value,
            "inner": self.inner.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        brut = spec.get("stat")
        if not isinstance(brut, str) or brut not in set(CumulativeStat):
            raise ConfigurationError(
                f"'cumulative' : statistique invalide {brut!r}. "
                f"Attendu l'un de {', '.join(s.value for s in CumulativeStat)}"
            )
        return cls(CumulativeStat(brut), _child(spec, "inner", build))


def cumulative(stat: str, inner: Signal) -> Cumulative:
    """Raccourci : `cumulative("sum", price("volume"))`."""
    return Cumulative(CumulativeStat(stat), inner)
