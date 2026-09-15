"""Format canonique interne : types, specification d'instrument, magasin de barres.

Le magasin (`BarStore`) est immuable et partage. Il est le seul detenteur des
donnees ; le `Context` n'en detient qu'une reference et un entier. Voir
`docs/no-lookahead.md` §2.

Convention d'horodatage (`docs/execution-model.md` §1.1) : `ts_event` est
l'OUVERTURE de la barre, `ts_close = ts_event + granularite` est l'instant ou
l'information devient disponible. Le moteur raisonne sur `ts_close`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic import Field as PydField

from rsl.data.session import SessionIndex
from rsl.errors import ConfigurationError

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

NS_PER_SECOND: Final[int] = 1_000_000_000


class Field(StrEnum):
    """Colonnes du format canonique."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"


PRICE_FIELDS: Final[tuple[Field, ...]] = (Field.OPEN, Field.HIGH, Field.LOW, Field.CLOSE)
ALL_FIELDS: Final[tuple[Field, ...]] = (*PRICE_FIELDS, Field.VOLUME)
TIMESTAMP_COLUMN: Final[str] = "ts_event"


@dataclass(frozen=True, slots=True)
class Granularity:
    """Duree nominale d'une barre.

    Nominale, et non effective, pour deux raisons distinctes :

    - les donnees comportent des trous (coupures de maintenance, week-ends,
      feries), donc deux barres consecutives ne sont pas separees de `delta` ;
    - une barre reechantillonnee sur un calendrier (mois, trimestre) n'a pas de
      duree fixe du tout. Dans ce cas `name` porte le libelle exact et
      `ts_close` est fourni explicitement au magasin.

    Voir `docs/execution-model.md` §5.
    """

    delta: timedelta
    name: str = ""

    @staticmethod
    def minutes(n: int) -> Granularity:
        if n <= 0:
            raise ValueError(f"granularite en minutes doit etre > 0, recu {n}")
        return Granularity(timedelta(minutes=n))

    @property
    def nanoseconds(self) -> int:
        return int(self.delta.total_seconds() * NS_PER_SECOND)

    def __str__(self) -> str:
        if self.name:
            return self.name
        total = int(self.delta.total_seconds())
        if total % 86_400 == 0:
            return f"{total // 86_400}d"
        if total % 3_600 == 0:
            return f"{total // 3_600}h"
        if total % 60 == 0:
            return f"{total // 60}m"
        return f"{total}s"


class AssetClass(StrEnum):
    """Classe d'actif d'un contrat.

    Propriete du CONTRAT, pas du disque : ES est un future d'indice, que ses
    donnees soient rangees ici ou ailleurs. Le fait que l'arborescence de
    `RSL_DATA_DIR` la reproduise est une commodite, et c'est `data_path` qui
    porte cette hypothese - une seule fois, nommee.
    """

    INDICES = "indices"
    METAUX = "metaux"
    ENERGIE = "energie"
    FOREX = "forex"


class InstrumentSpec(BaseModel):
    """Specification economique d'un contrat future.

    `multiplier` et `tick_size` conditionnent le P&L et le slippage ; ils n'ont
    pas de valeur par defaut plausible et sont donc obligatoires.

    Les marges sont statiques et donc anachroniques sur un echantillon de dix
    ans (`docs/execution-model.md` §6.1). Le manifeste de run le signale.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = PydField(min_length=1, description="Symbole continu, ex. 'ES.v.0'")
    root: str = PydField(min_length=1, description="Racine du contrat, ex. 'ES'")
    name: str = PydField(min_length=1, description="Libelle lisible, ex. 'S&P 500'")
    exchange: str = PydField(min_length=1)
    currency: str = PydField(min_length=3, max_length=3)
    multiplier: float = PydField(gt=0.0, description="Valeur d'un point de prix, en devise")
    tick_size: float = PydField(gt=0.0, description="Increment minimal de prix")
    commission_per_contract: float = PydField(ge=0.0, description="Par contrat et par cote")
    exchange_fee_per_contract: float = PydField(ge=0.0, description="Par contrat et par cote")
    initial_margin: float = PydField(gt=0.0)
    maintenance_margin: float = PydField(gt=0.0)

    category: AssetClass | None = PydField(
        default=None,
        description="Classe d'actif. Absente sur un instrument synthetique.",
    )
    """`None` par defaut, et ce n'est pas un oubli : les instruments construits
    dans les tests n'existent sur aucun disque, et leur en inventer une classe
    laisserait croire qu'ils ont un fichier.

    Les dix contrats de la table, eux, en ont tous une - un test le verifie,
    pour qu'un instrument ajoute demain ne puisse pas l'omettre."""

    @property
    def data_path(self) -> str:
        """Chemin RELATIF a la racine des donnees, ex. `indices/ES_v0_1m.parquet`.

        Une seule convention, ecrite une seule fois : la classe d'actif donne
        le dossier, et le nom de fichier suit `{root}_v0_1m` - `v0` pour la
        serie continue non ajustee, `1m` pour la granularite native.

        Elle vivait en double jusqu'au 2026-09-12 : une table `DOSSIERS`
        recopiee dans `gui/montage.py`, qu'un instrument ajoute ailleurs
        aurait fait mentir sans prevenir.

        Relatif et jamais absolu : un chemin absolu ferait diverger le
        `config_hash` entre deux machines.

        Leve si l'instrument n'a pas de classe : il n'existe alors sur aucun
        disque, et rendre un chemin plausible serait pire que refuser.
        """
        if self.category is None:
            raise ConfigurationError(
                f"'{self.symbol}' n'a pas de classe d'actif : c'est un "
                f"instrument synthetique, il n'a de fichier nulle part. Un "
                f"chemin plausible serait pire qu'un refus."
            )
        return f"{self.category.value}/{self.root}_v0_1m.parquet"

    @field_validator("maintenance_margin")
    @classmethod
    def _maintenance_below_initial(cls, v: float, info: object) -> float:
        # La marge de maintien est par construction <= marge initiale.
        data = getattr(info, "data", {})
        initial = data.get("initial_margin")
        if isinstance(initial, float) and v > initial:
            raise ValueError(
                f"maintenance_margin ({v}) ne peut pas exceder initial_margin ({initial})"
            )
        return v

    @property
    def fee_per_contract_per_side(self) -> float:
        return self.commission_per_contract + self.exchange_fee_per_contract


@dataclass(frozen=True, slots=True)
class Bar:
    """Une barre close, valeur scalaire immuable.

    `is_stale` vaut True si la barre a ete produite par un forward-fill
    explicite (`docs/no-lookahead.md` §4.1), jamais implicitement.
    """

    ts_event: datetime
    ts_close: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_stale: bool = False

    def field(self, field: Field) -> float:
        match field:
            case Field.OPEN:
                return self.open
            case Field.HIGH:
                return self.high
            case Field.LOW:
                return self.low
            case Field.CLOSE:
                return self.close
            case Field.VOLUME:
                return self.volume


@dataclass(frozen=True, slots=True)
class BarWindow:
    """Fenetre de `n` barres closes, la plus recente en derniere position.

    Les tableaux sont des COPIES en lecture seule, pas des vues. Une vue
    `numpy` expose son tableau parent via `.base`, ce qui redonnerait acces a
    l'echantillon complet - donc au futur. Le cout d'une copie de quelques
    centaines de flottants est le prix de la garantie
    (`docs/no-lookahead.md` §2.2, regle 5).
    """

    ts_close: IntArray
    open: FloatArray
    high: FloatArray
    low: FloatArray
    close: FloatArray
    volume: FloatArray

    def __len__(self) -> int:
        return int(self.close.shape[0])

    def field(self, field: Field) -> FloatArray:
        match field:
            case Field.OPEN:
                return self.open
            case Field.HIGH:
                return self.high
            case Field.LOW:
                return self.low
            case Field.CLOSE:
                return self.close
            case Field.VOLUME:
                return self.volume


def _freeze(array: npt.NDArray[np.generic]) -> npt.NDArray[np.generic]:
    """Rend un tableau non modifiable, apres copie contigue si necessaire."""
    frozen = np.ascontiguousarray(array)
    if frozen is array:
        frozen = array.copy()
    frozen.setflags(write=False)
    return frozen


@dataclass(frozen=True, slots=True)
class BarStore:
    """Magasin de barres immuable pour un instrument.

    Construit une seule fois par le loader, jamais mute ensuite. Les tableaux
    portent `writeable = False` : aucune strategie, aucun run, aucune primitive
    ne peut alterer l'historique d'un autre.

    Les horodatages sont des entiers de nanosecondes UTC depuis l'epoque, pour
    que la comparaison et le hachage soient exacts et deterministes.
    """

    symbol: str
    granularity: Granularity
    ts_event: IntArray
    ts_close: IntArray
    open: FloatArray
    high: FloatArray
    low: FloatArray
    close: FloatArray
    volume: FloatArray
    is_stale: npt.NDArray[np.bool_]
    source_hash: str = ""
    sessions: SessionIndex | None = None
    """Index de seance, present UNIQUEMENT si le run en a declare un.

    Optionnel par construction : sans declaration, le socle n'a pas de notion
    de seance et le dit en levant, plutot que d'en inventer une. Porte par le
    magasin plutot que par le contexte pour que `shifted`, `peer` et les deux
    feeds en heritent sans plomberie supplementaire."""

    token: object = field(default_factory=object, compare=False, repr=False)
    """Jeton d'identite : un objet nu, unique a ce magasin, qui ne PORTE RIEN.

    Il existe pour que la memoisation des noeuds
    (`rsl/strategies/memoire.py`) sache reconnaitre un changement de serie.
    Deux magasins n'ont jamais le meme jeton ; `shifted` et les vues derivees
    gardent celui de leur magasin.

    Pourquoi un objet nu plutot que le magasin lui-meme : `Context.data_token`
    est une surface PUBLIQUE. Y exposer le magasin donnerait a un appelant
    determine l'historique complet, futur inclus - exactement ce que
    `tests/adversarial/test_forbidden_access.py` interdit. Un `object()` n'a
    aucun attribut : il ne se compare qu'a lui-meme.

    Pourquoi pas un entier d'identite non plus : `id()` est reattribue apres
    ramassage, et deux series differentes finiraient par se confondre en
    silence. Un objet detenu par qui s'en sert ne peut pas etre reattribue.

    `compare=False` : deux magasins de contenu identique restent egaux.
    """

    @staticmethod
    def build(
        *,
        symbol: str,
        granularity: Granularity,
        ts_event: IntArray,
        open_: FloatArray,
        high: FloatArray,
        low: FloatArray,
        close: FloatArray,
        volume: FloatArray,
        is_stale: npt.NDArray[np.bool_] | None = None,
        ts_close: IntArray | None = None,
        source_hash: str = "",
    ) -> BarStore:
        """Gele un magasin.

        `ts_close` n'est a fournir que pour les barres agregees sur un
        calendrier : un mois n'a pas de duree fixe, donc
        `ts_event + granularite` y serait faux. Pour une granularite reguliere,
        il est calcule.
        """
        n = ts_event.shape[0]
        for label, arr in (
            ("open", open_),
            ("high", high),
            ("low", low),
            ("close", close),
            ("volume", volume),
        ):
            if arr.shape[0] != n:
                raise ValueError(f"colonne '{label}' de longueur {arr.shape[0]}, attendu {n}")
        stale = np.zeros(n, dtype=np.bool_) if is_stale is None else is_stale
        if stale.shape[0] != n:
            raise ValueError(f"is_stale de longueur {stale.shape[0]}, attendu {n}")

        ts_event_i = np.ascontiguousarray(ts_event, dtype=np.int64)
        if ts_close is None:
            ts_close_i = ts_event_i + granularity.nanoseconds
        else:
            ts_close_i = np.ascontiguousarray(ts_close, dtype=np.int64)
            if ts_close_i.shape[0] != n:
                raise ValueError(f"ts_close de longueur {ts_close_i.shape[0]}, attendu {n}")
            if bool(np.any(ts_close_i < ts_event_i)):
                raise ValueError("ts_close ne peut pas preceder ts_event")
        return BarStore(
            symbol=symbol,
            granularity=granularity,
            ts_event=_freeze(ts_event_i),  # type: ignore[arg-type]
            ts_close=_freeze(ts_close_i),  # type: ignore[arg-type]
            open=_freeze(np.ascontiguousarray(open_, dtype=np.float64)),  # type: ignore[arg-type]
            high=_freeze(np.ascontiguousarray(high, dtype=np.float64)),  # type: ignore[arg-type]
            low=_freeze(np.ascontiguousarray(low, dtype=np.float64)),  # type: ignore[arg-type]
            close=_freeze(np.ascontiguousarray(close, dtype=np.float64)),  # type: ignore[arg-type]
            volume=_freeze(np.ascontiguousarray(volume, dtype=np.float64)),  # type: ignore[arg-type]
            is_stale=_freeze(np.ascontiguousarray(stale, dtype=np.bool_)),  # type: ignore[arg-type]
            source_hash=source_hash,
        )

    @property
    def n_bars(self) -> int:
        """Nombre total de barres.

        ATTENTION : cette propriete est destinee au loader, au runner et aux
        tests. Elle n'est PAS exposee au travers du `Context` - une strategie
        qui connait la longueur de l'echantillon peut s'en servir
        (`docs/no-lookahead.md` §2.2, regle 4).
        """
        return int(self.ts_event.shape[0])

    def column(self, field: Field) -> FloatArray:
        match field:
            case Field.OPEN:
                return self.open
            case Field.HIGH:
                return self.high
            case Field.LOW:
                return self.low
            case Field.CLOSE:
                return self.close
            case Field.VOLUME:
                return self.volume

    def bar_at(self, index: int) -> Bar:
        """Barre a un index absolu. Reserve au moteur ; jamais expose tel quel."""
        return Bar(
            ts_event=ns_to_datetime(int(self.ts_event[index])),
            ts_close=ns_to_datetime(int(self.ts_close[index])),
            open=float(self.open[index]),
            high=float(self.high[index]),
            low=float(self.low[index]),
            close=float(self.close[index]),
            volume=float(self.volume[index]),
            is_stale=bool(self.is_stale[index]),
        )

    def slice(self, start: int, stop: int) -> BarStore:
        """Sous-magasin `[start, stop)`, utilise par les tests de corruption."""
        return BarStore.build(
            symbol=self.symbol,
            granularity=self.granularity,
            ts_event=self.ts_event[start:stop],
            open_=self.open[start:stop],
            high=self.high[start:stop],
            low=self.low[start:stop],
            close=self.close[start:stop],
            volume=self.volume[start:stop],
            is_stale=self.is_stale[start:stop],
            ts_close=self.ts_close[start:stop],
            source_hash=self.source_hash,
        ).with_sessions(
            None if self.sessions is None else self.sessions.slice(start, stop)
        )

    def filtrer(self, garde: npt.NDArray[np.bool_]) -> BarStore:
        """Sous-magasin ne gardant que les barres marquees.

        Rend un magasin SANS index de seance : l'index decrit des positions,
        et un filtrage les renumerote. Le reconstruire est a la charge de
        l'appelant, qui seul sait sur quel calendrier.
        """
        if garde.shape != self.ts_event.shape:
            raise ConfigurationError(
                f"filtrer : masque de {garde.shape} pour {self.ts_event.shape} barres"
            )
        if not bool(garde.any()):
            raise ConfigurationError(
                f"filtrer : aucune barre retenue sur {self.symbol}. Un magasin vide "
                f"ne produirait aucune erreur au run, seulement un resultat vide."
            )
        return BarStore.build(
            symbol=self.symbol,
            granularity=self.granularity,
            ts_event=self.ts_event[garde],
            open_=self.open[garde],
            high=self.high[garde],
            low=self.low[garde],
            close=self.close[garde],
            volume=self.volume[garde],
            is_stale=self.is_stale[garde],
            ts_close=self.ts_close[garde],
            source_hash=self.source_hash,
        )

    def with_sessions(self, index: SessionIndex | None) -> BarStore:
        """Copie portant un index de seance. Le magasin reste immuable."""
        if index is None:
            return self
        return replace(self, sessions=index)


def ns_to_datetime(ns: int) -> datetime:
    """Nanosecondes UTC depuis l'epoque -> `datetime` conscient du fuseau."""
    return datetime.fromtimestamp(ns / NS_PER_SECOND, tz=UTC)


def datetime_to_ns(dt: datetime) -> int:
    """`datetime` conscient du fuseau -> nanosecondes UTC depuis l'epoque."""
    if dt.tzinfo is None:
        raise ValueError("datetime naif refuse : le socle ne travaille qu'en UTC explicite")
    return int(dt.timestamp() * NS_PER_SECOND)


@dataclass(frozen=True, slots=True)
class PositionState:
    """Ce qu'une strategie sait de SA propre position, a la barre courante.

    Pourquoi cela ne rompt pas le contrat anti-look-ahead
    ------------------------------------------------------
    Ces valeurs decrivent le PASSE de la strategie, pas l'avenir du marche.
    Elles sont calculees par le runner a partir des fills - qui viennent de
    barres deja closes - et des extremes des barres traversees depuis
    l'entree. Aucune n'existe avant que la position n'existe.

    Pourquoi c'est le runner qui les calcule, et non un noeud a memoire
    -------------------------------------------------------------------
    Un noeud de signal qui memoriserait son etat survivrait d'un run a
    l'autre : deux backtests identiques donneraient des resultats differents
    selon ce qui a tourne avant, et le test de corruption du futur perdrait son
    sens. Le runner, lui, repart de zero a chaque run par construction.

    `bars_held` compte les barres depuis l'ENTREE, l'entree valant zero.
    """

    quantity: int = 0
    """Signee : positive en position longue, negative en courte, nulle a plat."""

    bars_held: int = 0
    entry_price: float = 0.0
    high_since_entry: float = 0.0
    low_since_entry: float = 0.0

    closed_trade: bool = False
    """Un aller-retour s'est-il FERME sur cette barre ?

    Le compagnon obligatoire de `closed_pnl`, et la raison pour laquelle
    les deux existent plutot qu'un seul champ rendant `None`. Une seule
    valeur absente empoisonne toute une fenetre de `cumulative`, qui rend
    alors `None` sur chaque barre - le champ serait inutilisable pour ce a
    quoi il sert.

    Il se lit comme masque : `cumulative(count_true,
    mask=position("closed_trade"), inner=position("closed_pnl") < 0)`
    compte les pertes NETTES de la seance.
    """

    closed_pnl: float = 0.0
    """P&L NET - frais deduits - du trade ferme sur cette barre. Zero sinon.

    Zero est ici une valeur de REMPLISSAGE, pas une mesure, et c'est
    exactement ce que [[lessons]] L30 interdit de laisser seul. D'ou
    `closed_trade` : la valeur ne doit JAMAIS etre lue sans lui.

    Ce qu'il repare
    ----------------
    Jusqu'au 2026-09-15, la seule facon de reperer une perte depuis une
    regle etait `close < entry_price` a la derniere barre en position. Cette
    ecriture ignore les FRAIS et le prix du fill de SORTIE, qui tombe a la
    barre suivante. Mesure : une garde « une seule perte » plafonnait en
    realite a QUATRE pertes par seance comptees en P&L net.

    Ce qu'il ne dit pas : si DEUX trades se ferment sur la meme barre, seul
    le DERNIER est visible. C'est la meme limite de granularite que partout
    ailleurs, et elle est reelle - 30 119 barres sur 37 615 portaient deux
    fills sur un momentum ES 30 minutes ([[lessons]] L32).
    """

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    @property
    def direction(self) -> int:
        if self.quantity > 0:
            return 1
        return -1 if self.quantity < 0 else 0

    def field(self, name: str) -> float:
        match name:
            case "quantity":
                return float(self.quantity)
            case "bars_held":
                return float(self.bars_held)
            case "entry_price":
                return self.entry_price
            case "high_since_entry":
                return self.high_since_entry
            case "low_since_entry":
                return self.low_since_entry
            case "direction":
                return float(self.direction)
            case "closed_trade":
                return 1.0 if self.closed_trade else 0.0
            case "closed_pnl":
                return self.closed_pnl
        raise ValueError(f"champ de position inconnu : '{name}'")


FLAT: Final[PositionState] = PositionState()
"""Etat par defaut. Un `Context` non pilote par un runner est toujours a plat :
il ne peut pas inventer une position qui n'existe pas."""


@dataclass(frozen=True, slots=True)
class AccountState:
    """Ce qu'une strategie sait de SON compte, a la barre courante.

    Le pendant de `PositionState` au niveau du PORTEFEUILLE : la position dit
    ce qu'on detient, le compte dit ce que ca a donne.

    Pourquoi cela ne rompt pas le contrat anti-look-ahead
    ------------------------------------------------------
    Exactement le meme argument qu'en `PositionState`, et il n'est pas affaibli
    par le changement d'echelle. L'equity a la barre `t` est calculee par le
    runner a partir des fills - qui viennent de barres deja closes - et des
    marques de la barre `t`, deja close elle aussi. Aucune valeur n'est
    posterieure a l'instant ou la strategie la lit.

    Une strategie qui la lit n'apprend rien qu'elle n'ait elle-meme provoque :
    l'equity est la consequence de ses propres decisions passees. La boucle de
    retroaction est dans le TEMPS, jamais a l'interieur d'une barre.

    Ce que cela rend exprimable, et qui ne l'etait pas
    --------------------------------------------------
    Couper apres un repli donne, alleger quand le drawdown se creuse, cesser
    d'ajouter au-dela d'un gain - toute la gestion du risque pilotee par la
    PERFORMANCE. Jusqu'au 2026-09-12, la couche risque voyait l'equity
    (`RiskManager.contracts` la recoit) mais la DECISION non : le
    dimensionnement pouvait composer avec le capital, aucune regle ne pouvait
    y reagir.

    Pourquoi il n'existe pas d'etat par defaut
    -------------------------------------------
    `PositionState` en a un - `FLAT` - et c'est une DEDUCTION : hors runner,
    personne n'a pris de position. Il n'y a pas d'equivalent ici. Hors runner,
    une equity n'est pas nulle, elle est INCONNUE, et repondre zero ferait
    d'un `drawdown` une division par zero silencieuse. Le noeud `account`
    leve donc, comme `session` leve sans calendrier declare : le socle
    n'invente pas.
    """

    equity: float
    """Valeur totale, marquee au marche."""

    cash: float
    peak_equity: float
    """Plus haut atteint depuis le DEBUT DU RUN, prechauffage compris."""

    initial_equity: float

    @property
    def drawdown(self) -> float:
        """Repli depuis le sommet, en fraction. Negatif ou nul.

        Sans unite, donc utilisable comme seuil sans dependre du capital de
        depart - contrairement a `equity - peak_equity`.
        """
        if self.peak_equity <= 0.0:
            return 0.0
        return (self.equity - self.peak_equity) / self.peak_equity

    @property
    def total_return(self) -> float:
        """Rendement depuis le debut du run, en fraction."""
        if self.initial_equity <= 0.0:
            return 0.0
        return (self.equity / self.initial_equity) - 1.0

    def field(self, name: str) -> float:
        match name:
            case "equity":
                return self.equity
            case "cash":
                return self.cash
            case "peak_equity":
                return self.peak_equity
            case "initial_equity":
                return self.initial_equity
            case "drawdown":
                return self.drawdown
            case "total_return":
                return self.total_return
        raise ValueError(f"champ de compte inconnu : '{name}'")


ACCOUNT_FIELDS: Final[tuple[str, ...]] = (
    "equity",
    "cash",
    "peak_equity",
    "initial_equity",
    "drawdown",
    "total_return",
)
"""Champs lisibles par le noeud `account`. Publie dans le schema engendre."""


TIME_FIELDS: Final[tuple[str, ...]] = (
    "weekday",
    "hour",
    "minute",
    "day",
    "month",
    "day_of_year",
    "year",
)
"""Champs calendaires lisibles depuis un `Context`.

Le calendrier n'est pas de l'information de marche : la date de la barre
courante est connue de tous, y compris a l'avance. L'exposer n'ouvre aucune
fuite - contrairement au PRIX de la barre suivante, qui lui n'existe pas
encore.

`weekday` suit la convention Python : lundi vaut 0, dimanche 6.
"""


def time_field(moment: datetime, name: str) -> float:
    """Extrait un champ calendaire d'un instant UTC."""
    match name:
        case "weekday":
            return float(moment.weekday())
        case "hour":
            return float(moment.hour)
        case "minute":
            return float(moment.minute)
        case "day":
            return float(moment.day)
        case "month":
            return float(moment.month)
        case "day_of_year":
            return float(moment.timetuple().tm_yday)
        case "year":
            return float(moment.year)
    raise ValueError(f"champ calendaire inconnu : '{name}'")


POSITION_FIELDS: Final[tuple[str, ...]] = (
    "quantity",
    "direction",
    "bars_held",
    "entry_price",
    "high_since_entry",
    "low_since_entry",
    "closed_trade",
    "closed_pnl",
)


class AlignPolicy(StrEnum):
    """Politique d'alignement multi-instruments (`docs/no-lookahead.md` §4.1)."""

    DROP = "drop"
    """Un instrument sans barre a `t` est absent de la coupe. Defaut."""

    FFILL = "ffill"
    """Report explicite de la derniere barre close, borne et compte."""

    ERROR = "error"
    """Toute absence fait echouer la construction du panneau."""


ABSENT: Final[int] = -1


@dataclass(frozen=True, slots=True)
class Panel:
    """Plusieurs `BarStore` alignes sur un calendrier commun.

    Le calendrier est l'UNION des horodatages de cloture, pas leur
    intersection : une intersection sur dix futures de places differentes
    ampute l'echantillon et introduit un biais de selection
    (`docs/execution-model.md` §7.2).

    `row_index[symbole][k]` donne l'index de barre de `symbole` a la ligne `k`
    du panneau, ou `ABSENT` (-1). Absent ne veut pas dire "dernier prix connu" :
    sans forward-fill explicite, l'instrument ne figure tout simplement pas
    dans la coupe transversale.
    """

    granularity: Granularity
    ts_close: IntArray
    symbols: tuple[str, ...]
    stores: dict[str, BarStore]
    row_index: dict[str, IntArray]
    is_stale: dict[str, npt.NDArray[np.bool_]]
    align_policy: AlignPolicy

    @property
    def n_rows(self) -> int:
        return int(self.ts_close.shape[0])

    def present_symbols(self, row: int) -> tuple[str, ...]:
        """Instruments cotant a cette ligne, dans l'ordre trie (deterministe)."""
        return tuple(s for s in self.symbols if self.row_index[s][row] != ABSENT)

    def n_stale(self, symbol: str) -> int:
        return int(np.count_nonzero(self.is_stale[symbol]))
