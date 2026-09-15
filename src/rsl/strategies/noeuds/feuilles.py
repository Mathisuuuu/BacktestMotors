"""Feuilles : les noeuds qui lisent le monde au lieu de composer.

Une feuille n'a pas de sous-signal. Elle lit une barre (`price`), une
primitive (`primitive`), l'etat de la strategie (`position`), le calendrier
(`time`), une seance declaree (`session`), un autre instrument (`peer`), ou
rien du tout (`constant`).

C'est par elles que TOUT ce que voit une strategie entre dans le vocabulaire -
donc c'est ici que se joue la garantie anti-look-ahead : chacune passe par le
`Context`, qui ne montre que des barres closes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from rsl.data.evenements import EventField
from rsl.data.exogene import ChampExogene
from rsl.data.feed import Context
from rsl.data.schema import (
    ACCOUNT_FIELDS,
    POSITION_FIELDS,
    TIME_FIELDS,
    time_field,
)
from rsl.data.session import SessionField
from rsl.errors import (
    ConfigurationError,
    InsufficientHistoryError,
    LookAheadError,
    SymbolNotAvailableError,
)
from rsl.primitives.base import BoundPrimitive
from rsl.primitives.registry import get_primitive
from rsl.strategies.noeuds.contrat import (
    Builder,
    FieldKind,
    NodeField,
    Piege,
    Signal,
    SpecDict,
    _child,
    signal_node,
)


@signal_node(
    "constant",
    summary="Valeur litterale, independante du contexte.",
    fields=(
        NodeField("value", FieldKind.NUMBER, description="La valeur rendue, telle quelle."),
    ),
)
@dataclass(frozen=True, slots=True)
class Constant:
    """Constante. Sert de seuil dans les comparaisons."""

    NODE_TYPE: ClassVar[str] = "constant"
    NODE_VERSION: ClassVar[int] = 1

    value: float

    @property
    def warmup_bars(self) -> int:
        return 0

    def __call__(self, ctx: Context) -> float | None:
        return self.value

    def describe(self) -> SpecDict:
        return {"type": self.NODE_TYPE, "version": self.NODE_VERSION, "value": self.value}

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        raw = spec.get("value")
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            raise ConfigurationError(f"'constant' exige un champ 'value' numerique, recu {raw!r}")
        return cls(float(raw))


@signal_node(
    "primitive",
    summary="Feuille : une primitive du registre, parametres figes.",
    fields=(
        NodeField(
            "ref",
            FieldKind.STRING,
            description=(
                "Reference versionnee, ex. 'sma@1'. Sans version, la plus recente est "
                "prise - a n'utiliser qu'en exploration."
            ),
        ),
        NodeField(
            "params",
            FieldKind.OBJECT,
            required=False,
            description=(
                "Parametres de la primitive. Leur schema depend de `ref` et ne peut "
                "donc pas etre fige ici : il est publie par le catalogue des "
                "primitives, une entree par reference."
            ),
        ),
    ),
)
@dataclass(frozen=True, slots=True)
class PrimitiveSignal:
    """Primitive liee a ses parametres."""

    NODE_TYPE: ClassVar[str] = "primitive"
    NODE_VERSION: ClassVar[int] = 1

    bound: BoundPrimitive

    @staticmethod
    def of(ref: str, **params: object) -> PrimitiveSignal:
        return PrimitiveSignal(get_primitive(ref).bind(**params))

    @property
    def warmup_bars(self) -> int:
        return self.bound.warmup_bars

    def __call__(self, ctx: Context) -> float | None:
        return self.bound(ctx)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            # La reference est epinglee a l'ecriture : une specification
            # archivee ne doit pas dependre de ce qui a ete enregistre depuis.
            "ref": str(self.bound.primitive.ref),
            "params": self.bound.params.model_dump(mode="json"),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        ref = spec.get("ref")
        if not isinstance(ref, str):
            raise ConfigurationError(f"'primitive' exige un champ 'ref' textuel, recu {ref!r}")
        params = spec.get("params") or {}
        if not isinstance(params, dict):
            raise ConfigurationError(f"'primitive' : 'params' doit etre un objet, recu {params!r}")
        return cls(get_primitive(ref).bind(**params))


@signal_node(
    "price",
    summary="Feuille : un champ OHLCV de la barre courante ou passee.",
    fields=(
        NodeField(
            "field",
            FieldKind.STRING,
            required=False,
            default="close",
            choices=("open", "high", "low", "close", "volume"),
        ),
        NodeField(
            "lag",
            FieldKind.INTEGER,
            required=False,
            default=0,
            minimum=0,
            description="Barres en arriere. Un lag negatif viserait une barre non close.",
        ),
    ),
)
@dataclass(frozen=True, slots=True)
class Price:
    """Champ OHLCV lu directement, sans passer par une primitive."""

    NODE_TYPE: ClassVar[str] = "price"
    NODE_VERSION: ClassVar[int] = 1

    field: str = "close"
    lag: int = 0

    def __post_init__(self) -> None:
        if self.lag < 0:
            raise ConfigurationError(f"lag doit etre >= 0, recu {self.lag}")

    @property
    def warmup_bars(self) -> int:
        return self.lag + 1

    def __call__(self, ctx: Context) -> float | None:
        from rsl.data.schema import Field

        return ctx.value(Field(self.field), lag=self.lag)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "field": self.field,
            "lag": self.lag,
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        from rsl.data.schema import Field

        field = spec.get("field", "close")
        lag = spec.get("lag", 0)
        if not isinstance(field, str) or field not in {f.value for f in Field}:
            raise ConfigurationError(f"'price' : champ inconnu {field!r}")
        if not isinstance(lag, int) or isinstance(lag, bool):
            raise ConfigurationError(f"'price' : 'lag' doit etre un entier, recu {lag!r}")
        return cls(field, lag)


@signal_node(
    "position",
    summary="Feuille : ce que la strategie sait de SA propre position.",
    fields=(
        NodeField(
            "field",
            FieldKind.STRING,
            required=False,
            default="quantity",
            choices=POSITION_FIELDS,
            description=(
                "quantity (signee), direction (-1/0/+1), bars_held (0 a l'entree), "
                "entry_price, high_since_entry, low_since_entry."
            ),
        ),
    ),
)
@dataclass(frozen=True, slots=True)
class Position:
    """Etat de la position, lu depuis le `Context`.

    C'est ce noeud qui rend exprimables les regles dependant du temps passe en
    position - « sortir apres dix barres » - et les sorties calees sur un
    extreme atteint depuis l'entree, dont le stop suiveur evalue a la cloture :

        exit_long = close < high_since_entry - 2 * ATR(14)

    Nuance a ne pas gommer : c'est un stop suiveur evalue A LA CLOTURE, puis
    execute a la barre suivante. Un stop suiveur qui se declenche EN COURS de
    barre reste une affaire de moteur, pas de signal ; les deux ne donnent pas
    le meme prix de sortie sur une barre violente.

    Hors d'un runner, la position est toujours a plat : un `Context` ne peut
    pas inventer une position que personne n'a prise.
    """

    NODE_TYPE: ClassVar[str] = "position"
    NODE_VERSION: ClassVar[int] = 1

    field: str = "quantity"

    def __post_init__(self) -> None:
        if self.field not in POSITION_FIELDS:
            raise ConfigurationError(
                f"'position' : champ inconnu {self.field!r}. "
                f"Attendus : {', '.join(POSITION_FIELDS)}"
            )

    @property
    def warmup_bars(self) -> int:
        """Zero : ce noeud ne lit aucun historique de prix."""
        return 0

    def __call__(self, ctx: Context) -> float | None:
        return ctx.position.field(self.field)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "field": self.field,
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        field_ = spec.get("field", "quantity")
        if not isinstance(field_, str):
            raise ConfigurationError(f"'position' : 'field' doit etre textuel, recu {field_!r}")
        return cls(field_)


@signal_node(
    "account",
    summary="Feuille : ce que la strategie sait de SON compte (equity, drawdown).",
    fields=(
        NodeField(
            "field",
            FieldKind.STRING,
            required=False,
            default="equity",
            choices=ACCOUNT_FIELDS,
            description=(
                "equity (marquee au marche), cash, peak_equity, initial_equity, "
                "drawdown (fraction negative ou nulle), total_return (fraction)."
            ),
        ),
    ),
)
@dataclass(frozen=True, slots=True)
class Account:
    """Etat du COMPTE, lu depuis le `Context`.

    Le pendant de `position` au niveau du portefeuille : la position dit ce
    qu'on detient, le compte dit ce que ca a donne. C'est ce noeud qui rend
    exprimable la gestion du risque pilotee par la PERFORMANCE :

        exit_long = account("drawdown") < -0.10
        entry_long = all_of(signal, account("drawdown") > -0.05)

    Jusqu'au 2026-09-12, la couche risque voyait l'equity - `RiskManager`
    la recoit - mais la DECISION non. Le dimensionnement pouvait composer avec
    le capital ; aucune regle ne pouvait y reagir.

    Pourquoi ce n'est pas du look-ahead
    ------------------------------------
    Meme argument que pour `position`, et le changement d'echelle ne
    l'affaiblit pas : l'equity a la barre `t` vient des fills - donc de barres
    closes - et des marques de la barre `t`, close elle aussi. La strategie
    n'apprend rien qu'elle n'ait provoque : la boucle de retroaction est dans
    le TEMPS, jamais a l'interieur d'une barre.

    Le piege a connaitre
    --------------------
    Une regle qui lit son propre drawdown se referme sur elle-meme. Couper a
    -10 % change l'equity, donc le drawdown, donc les coupes suivantes. Le
    backtest reste juste - il simule exactement cela - mais la sensibilite au
    seuil est BIEN plus forte qu'elle n'en a l'air, et un seuil ajuste sur
    l'echantillon est du sur-ajustement particulierement difficile a voir.

    Hors runner, ce noeud LEVE
    ---------------------------
    Contrairement a `position`, qui vaut `FLAT` par deduction. Hors runner une
    equity n'est pas nulle, elle est inconnue, et repondre zero ferait d'un
    `drawdown` une division par zero silencieuse. Meme regle que `session`
    sans calendrier declare : le socle n'invente pas.
    """

    NODE_TYPE: ClassVar[str] = "account"
    NODE_VERSION: ClassVar[int] = 1

    field: str = "equity"

    def __post_init__(self) -> None:
        if self.field not in ACCOUNT_FIELDS:
            raise ConfigurationError(
                f"'account' : champ inconnu {self.field!r}. "
                f"Attendus : {', '.join(ACCOUNT_FIELDS)}"
            )

    @property
    def warmup_bars(self) -> int:
        """Zero : ce noeud ne lit aucun historique de prix."""
        return 0

    def __call__(self, ctx: Context) -> float | None:
        return ctx.account_value(self.field)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "field": self.field,
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        field_ = spec.get("field", "equity")
        if not isinstance(field_, str):
            raise ConfigurationError(f"'account' : 'field' doit etre textuel, recu {field_!r}")
        return cls(field_)


def account(field: str = "equity") -> Account:
    """Raccourci : `account("drawdown")`."""
    return Account(field)


def position(field: str = "quantity") -> Position:
    """Raccourci : `position("bars_held")`."""
    return Position(field)


@signal_node(
    "time",
    summary="Feuille : un champ calendaire de la barre courante (UTC).",
    fields=(
        NodeField(
            "field",
            FieldKind.STRING,
            required=False,
            default="weekday",
            choices=TIME_FIELDS,
            description=(
                "weekday (lundi = 0), hour, minute, day, month, day_of_year, year. "
                "Toujours en UTC : le socle ne convertit aucun fuseau."
            ),
        ),
    ),
)
@dataclass(frozen=True, slots=True)
class Time:
    """Champ calendaire de la barre courante.

    Le calendrier n'est pas de l'information de marche. La date de la barre
    courante est connue de tous, et meme connue a l'avance : l'exposer n'ouvre
    aucune fuite, contrairement au PRIX de la barre suivante, qui n'existe pas
    encore.

    L'horodatage est celui de la CLOTURE (`ctx.ts`), pas de l'ouverture -
    l'instant ou l'information devient disponible, comme partout ailleurs
    (`docs/execution-model.md` §1.1). Une barre d'une minute ouverte a 23:59
    le vendredi est donc datee du samedi.

    Tout est en UTC. Le socle ne convertit aucun fuseau : « ne pas trader le
    lundi » se lit en UTC, et sur des futures dont la seance ouvre le dimanche
    soir a New York, ce n'est pas le meme lundi que celui du calendrier local.
    """

    NODE_TYPE: ClassVar[str] = "time"
    NODE_VERSION: ClassVar[int] = 1

    field: str = "weekday"

    def __post_init__(self) -> None:
        if self.field not in TIME_FIELDS:
            raise ConfigurationError(
                f"'time' : champ inconnu {self.field!r}. Attendus : {', '.join(TIME_FIELDS)}"
            )

    @property
    def warmup_bars(self) -> int:
        """Une barre : il en faut une pour avoir un horodatage."""
        return 1

    def __call__(self, ctx: Context) -> float | None:
        return time_field(ctx.ts, self.field)

    def describe(self) -> SpecDict:
        return {"type": self.NODE_TYPE, "version": self.NODE_VERSION, "field": self.field}

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        field_ = spec.get("field", "weekday")
        if not isinstance(field_, str):
            raise ConfigurationError(f"'time' : 'field' doit etre textuel, recu {field_!r}")
        return cls(field_)


@signal_node(
    "peer",
    summary="Evalue un sous-signal sur un AUTRE instrument, au meme instant.",
    fields=(
        NodeField(
            "symbol",
            FieldKind.STRING,
            description="Symbole du panneau, ex. 'NQ.v.0'.",
        ),
        NodeField("inner", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class Peer:
    """Sous-signal evalue sur un autre instrument du panneau.

    C'est ce noeud qui rend exprimables les spreads, ratios et couvertures :

        {"type": "arith", "op": "-",
         "left":  {"type": "price", "field": "close"},
         "right": {"type": "peer", "symbol": "NQ.v.0",
                   "inner": {"type": "price", "field": "close"}}}

    Le pair est resolu au MEME instant - meme ligne de panneau - et rendu sous
    forme de `Context` ordinaire : ses propres gardes s'appliquent, et il ne
    montre que des barres closes.

    Un pair ABSENT a cet instant rend `None`, pas une exception. L'absence est
    un etat legitime d'une coupe transversale, et « je ne sais pas » se propage
    deja partout ailleurs dans ce module. Faire echouer le run priverait la
    strategie du droit de dire « alors je ne fais rien ».

    Hors panneau, ou sur un symbole qui n'appartient pas au panneau, c'est en
    revanche une ERREUR de configuration qui remonte : une strategie qui lit
    deux instruments ne peut pas tourner sur un seul, et le decouvrir en
    silence serait pire que d'echouer. La distinction est faite par
    `Context.peer`, qui leve deux exceptions differentes.
    """

    NODE_TYPE: ClassVar[str] = "peer"
    NODE_VERSION: ClassVar[int] = 1

    symbol: str
    inner: Signal

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ConfigurationError("'peer' exige un `symbol` non vide")

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars

    def __call__(self, ctx: Context) -> float | None:
        try:
            other = ctx.peer(self.symbol)
        except SymbolNotAvailableError:
            return None
        try:
            return self.inner(other)
        except InsufficientHistoryError:
            # Le pair existe mais n'a pas encore assez d'historique : c'est un
            # « pas encore », pas une erreur. Un instrument qui demarre au
            # milieu de l'echantillon passerait sinon par une exception a
            # chacune de ses premieres barres.
            return None

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "symbol": self.symbol,
            "inner": self.inner.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        symbol = spec.get("symbol")
        if not isinstance(symbol, str):
            raise ConfigurationError(f"'peer' exige un `symbol` textuel, recu {symbol!r}")
        return cls(symbol, _child(spec, "inner", build))


def when(field: str = "weekday") -> Time:
    """Raccourci : `when("weekday")`."""
    return Time(field)


def peer(symbol: str, inner: Signal) -> Peer:
    """Raccourci : `peer("NQ.v.0", price("close"))`."""
    return Peer(symbol, inner)


@signal_node(
    "event",
    summary="Feuille : distance a un evenement d'un calendrier DECLARE.",
    fields=(
        NodeField("name", FieldKind.STRING, description="Nom declare dans `events`."),
        NodeField(
            "field",
            FieldKind.STRING,
            required=False,
            default=EventField.MINUTES_SINCE.value,
            choices=tuple(f.value for f in EventField),
        ),
    ),
)
@dataclass(frozen=True, slots=True)
class Event:
    """Ce que la strategie sait d'un calendrier d'ANNONCES.

    Exige une entree `events` dans la specification. Sans elle le noeud
    leve : le socle ne devine pas plus un calendrier d'annonces qu'un
    calendrier de seance.

    Ce que chaque champ lit
    ------------------------
    | Champ | Sens | Disponible |
    |---|---|---|
    | `minutes_since` | depuis la derniere annonce | toujours |
    | `minutes_until` | avant la prochaine | si `known_in_advance` |
    | `is_now` | une annonce tombe sur cette barre | toujours |

    Pourquoi `minutes_until` est conditionne
    -----------------------------------------
    Il lit un instant FUTUR. Ce n'est pas du look-ahead pour autant : un
    calendrier economique est PUBLIE A L'AVANCE, et savoir que le FOMC parle
    a 14 h ne dit rien du prix qu'il fera.

    Mais cette propriete depend du FICHIER, pas du socle. Un calendrier
    reconstruit apres coup - dates revisees, evenements ajoutes
    retrospectivement - ferait entrer du futur par la porte de derriere, et
    aucune inspection du code ne le verrait. La source doit donc declarer
    `known_in_advance: true`, ce qui n'est pas une garantie mais une
    AFFIRMATION signee : elle entre dans le `config_hash`.

    Ce que le noeud rend quand il n'a rien a dire : `None`
    ------------------------------------------------------
    Aucune annonce avant la barre, ou aucune apres. Et non zero : « pas
    d'annonce en vue » et « annonce dans zero minute » sont deux choses, et
    les confondre ferait declencher une regle sur un evenement absent
    ([[lessons]] L30).
    """

    NODE_TYPE: ClassVar[str] = "event"
    NODE_VERSION: ClassVar[int] = 1

    name: str
    field: EventField = EventField.MINUTES_SINCE

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigurationError(
                "'event' exige un `name` non vide : celui declare dans `events`"
            )

    @property
    def warmup_bars(self) -> int:
        """Une barre suffit : le calendrier ne depend pas de l'historique."""
        return 1

    def __call__(self, ctx: Context) -> float | None:
        return ctx.event_value(self.name, self.field)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "name": self.name,
            "field": self.field.value,
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        nom = spec.get("name")
        if not isinstance(nom, str) or not nom:
            raise ConfigurationError(
                f"'event' exige un `name` texte non vide, recu {nom!r}"
            )
        brut = spec.get("field", EventField.MINUTES_SINCE.value)
        if not isinstance(brut, str) or brut not in set(EventField):
            raise ConfigurationError(
                f"'event' : champ invalide {brut!r}. Attendu l'un de "
                f"{', '.join(f.value for f in EventField)}"
            )
        return cls(nom, EventField(brut))


@signal_node(
    "exogenous",
    summary="Feuille : derniere valeur connue d'une serie EXOGENE declaree.",
    fields=(
        NodeField("name", FieldKind.STRING,
                  description="Nom declare dans `exogenous`."),
        NodeField(
            "field",
            FieldKind.STRING,
            required=False,
            default=ChampExogene.VALUE.value,
            choices=tuple(f.value for f in ChampExogene),
        ),
    ),
)
@dataclass(frozen=True, slots=True)
class Exogenous:
    """Une grandeur qui ne vient pas du prix : COT, open interest, sentiment.

    Exige une entree `exogenous` dans la specification. Sans elle le noeud
    leve : le socle ne devine aucune source, pas plus qu'une seance ou un
    calendrier d'annonces.

    Ce que chaque champ lit
    ------------------------
    | Champ | Sens |
    |---|---|
    | `value` | derniere valeur publiee a ou avant la cloture |
    | `age_minutes` | anciennete de cette publication |

    Pourquoi `age_minutes` existe, et pourquoi il faut s'en servir
    ---------------------------------------------------------------
    Une serie qui cesse d'etre alimentee continue de rendre sa DERNIERE valeur
    indefiniment. La strategie tournerait alors sur un fossile sans que rien
    ne le signale - meme famille que [[lessons]] L30, ou une valeur neutre
    passait pour une mesure. Composer avec `age_minutes` permet de refuser une
    donnee perimee :

        all_of(
          compare(<, exogenous("cot_net", "age_minutes"), 10080),
          compare(>, exogenous("cot_net"), 0)
        )

    Ce que le noeud rend quand il n'a rien a dire : `None`
    ------------------------------------------------------
    Aucune publication avant la barre. Et non zero, qui se lirait comme une
    mesure nulle - un positionnement net de zero est une information, son
    absence n'en est pas une.

    La causalite, et ou elle se joue
    ----------------------------------
    PAS dans ce noeud : lire la derniere valeur connue est aussi causal qu'un
    `lag`. Elle se joue dans le FICHIER, qui doit etre horodate a la
    PUBLICATION et non a la mesure. Voir `rsl.data.exogene` : la source signe
    `horodatee_a_la_publication`, ou declare un `publication_lag_minutes`
    strictement positif.
    """

    NODE_TYPE: ClassVar[str] = "exogenous"
    NODE_VERSION: ClassVar[int] = 1

    name: str
    field: ChampExogene = ChampExogene.VALUE

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigurationError(
                "'exogenous' exige un `name` non vide : celui declare dans "
                "`exogenous`"
            )

    @property
    def warmup_bars(self) -> int:
        """Une barre suffit : la serie ne depend pas de l'historique de prix."""
        return 1

    def __call__(self, ctx: Context) -> float | None:
        return ctx.exogenous_value(self.name, self.field)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "name": self.name,
            "field": self.field.value,
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        nom = spec.get("name")
        if not isinstance(nom, str) or not nom:
            raise ConfigurationError(
                f"'exogenous' exige un `name` texte non vide, recu {nom!r}"
            )
        brut = spec.get("field", ChampExogene.VALUE.value)
        if not isinstance(brut, str) or brut not in set(ChampExogene):
            raise ConfigurationError(
                f"'exogenous' : champ invalide {brut!r}. Attendu l'un de "
                f"{', '.join(f.value for f in ChampExogene)}"
            )
        return cls(nom, ChampExogene(brut))


@signal_node(
    "session",
    summary="Feuille : une grandeur de la seance courante ou d'une seance close.",
    pieges=(
        Piege(
            champ="is_last",
            promesse="la derniere barre de la seance",
            realite=(
                "la PREMIERE barre a atteindre l'heure de fermeture DECLAREE"
            ),
            quand=(
                "une seance qui s'arrete avant l'heure declaree - demi-journee, "
                "trou de donnees - ne porte AUCUN `is_last`, et une regle qui le "
                "cite n'y declenche jamais. Mesure sur NQ le 2026-09-15 : 90 "
                "seances sur 2 748. Le nom ne PEUT pas etre corrige : la "
                "derniere barre d'une seance est un fait FUTUR, il faudrait "
                "regarder la barre suivante pour le savoir."
            ),
            controle="is_last-absent",
        ),
        Piege(
            champ="minutes_from_open",
            promesse="minutes ecoulees depuis l'ouverture, donc 0 a l'ouverture",
            realite="parcourt 1..N et ne vaut JAMAIS zero",
            quand=(
                "une barre est horodatee a sa CLOTURE : la premiere barre d'une "
                "seance d'une minute clot une minute apres l'ouverture. Comparer "
                "a zero donne une regle qui ne se declenche jamais."
            ),
            controle="minutes-jamais-nulles",
        ),
    ),
    fields=(
        NodeField(
            "field",
            FieldKind.STRING,
            required=False,
            default=SessionField.OPEN.value,
            choices=tuple(f.value for f in SessionField),
        ),
        NodeField("lag", FieldKind.INTEGER, required=False, default=0, minimum=0),
    ),
)
@dataclass(frozen=True, slots=True)
class Session:
    """Ce que la strategie sait de la SEANCE, et seulement si elle en a declare une.

    Exige un bloc `session` sur l'entree `data` de l'instrument. Sans lui le
    noeud leve : le socle ne deduit aucune frontiere de seance d'un trou dans
    les donnees, et les series continues en sont pleines.

    Ce qui est lisible, et quand :

    | Champ | `lag` 0 | `lag >= 1` |
    |---|---|---|
    | `open` | oui, connu des la premiere barre | oui |
    | `high`, `low`, `close`, `volume` | **non**, la seance n'est pas finie | oui |
    | positionnels (voir plus bas) | oui | **non** |

    Les champs positionnels sont `bar_index`, `minutes_from_open`, `is_first`
    et `is_last` : ils decrivent la barre COURANTE dans sa seance, donc n'ont
    pas de sens pour une seance passee prise en bloc.

    `lag` se compte en SEANCES, pas en barres - c'est toute la difference avec
    le champ `lag` du noeud `price`.
    """

    NODE_TYPE: ClassVar[str] = "session"
    NODE_VERSION: ClassVar[int] = 1

    field: SessionField = SessionField.OPEN
    lag: int = 0

    def __post_init__(self) -> None:
        if self.lag < 0:
            raise LookAheadError(
                f"session : lag negatif ({self.lag}) - le futur n'est pas lisible"
            )

    @property
    def warmup_bars(self) -> int:
        """Une barre suffit au socle ; c'est la disponibilite des seances
        passees qui limite, et elle est verifiee a l'evaluation."""
        return 1

    def __call__(self, ctx: Context) -> float | None:
        try:
            return ctx.session_value(self.field, self.lag)
        except InsufficientHistoryError:
            return None

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "field": self.field.value,
            "lag": self.lag,
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        brut = spec.get("field", SessionField.OPEN.value)
        if not isinstance(brut, str) or brut not in set(SessionField):
            raise ConfigurationError(
                f"'session' : champ invalide {brut!r}. "
                f"Attendu l'un de {', '.join(f.value for f in SessionField)}"
            )
        lag = spec.get("lag", 0)
        if not isinstance(lag, int) or isinstance(lag, bool):
            raise ConfigurationError(f"'session' exige un `lag` entier, recu {lag!r}")
        return cls(SessionField(brut), lag)


def session(field: str = "open", lag: int = 0) -> Session:
    """Raccourci : `session("high", lag=1)`."""
    return Session(SessionField(field), lag)
