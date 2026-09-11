"""Signaux composables : patron Composite + registre de types de noeuds.

Un signal est une expression evaluee sur un `Context` : `Signal(ctx) -> float |
None`. Les feuilles sont des primitives liees ou des constantes ; les noeuds
internes combinent des sous-signaux. Tout arbre de signaux est donc lui-meme un
signal, et se compose sans limite.

C'est ce qui rend le socle extensible SANS reecriture :

  - un indicateur nouveau        -> une primitive de plus dans le registre
  - une regle nouvelle           -> une composition de noeuds existants
  - un type de noeud nouveau     -> `@signal_node("mon_noeud", version=1)`

Aucun des trois n'oblige a toucher a du code publie.

Convention booleenne : `1.0` vrai, `0.0` faux, `None` indefini. `None` se
propage - une comparaison dont un membre est indefini est indefinie, elle n'est
pas fausse. C'est le meme raisonnement que le refus des `NaN` dans le
`Context` : "je ne sais pas" ne doit jamais se transformer silencieusement en
"non".
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Final, Protocol, runtime_checkable

import numpy as np

from rsl.data.feed import Context
from rsl.data.schema import POSITION_FIELDS, TIME_FIELDS, time_field
from rsl.data.session import SessionField
from rsl.errors import (
    ConfigurationError,
    InsufficientHistoryError,
    LookAheadError,
    RegistryError,
    SymbolNotAvailableError,
)
from rsl.primitives.base import BoundPrimitive
from rsl.primitives.registry import get_primitive
from rsl.strategies.memoire import (
    Leve,
    Memoire,
    memoire_pour,
    valeur_a,
    valeurs_de_fenetre,
)

TRUE: Final[float] = 1.0
FALSE: Final[float] = 0.0

SpecDict = dict[str, object]


@runtime_checkable
class Signal(Protocol):
    """Une expression evaluable sur un `Context`."""

    @property
    def warmup_bars(self) -> int:
        """Barres closes necessaires avant que l'expression soit calculable."""
        ...

    def __call__(self, ctx: Context) -> float | None: ...

    def describe(self) -> SpecDict:
        """Specification declarative de ce noeud, reconstructible par `build_signal`."""
        ...


# ---------------------------------------------------------------------------
# Registre des types de noeuds
# ---------------------------------------------------------------------------

Builder = Callable[[SpecDict], Signal]
FromSpec = Callable[[SpecDict, Builder], Signal]

NODE_REF: Final[str] = "#/$defs/node"


class FieldKind(StrEnum):
    """Nature d'un champ de noeud, du point de vue du schema."""

    NUMBER = "number"
    INTEGER = "integer"
    STRING = "string"
    BOOLEAN = "boolean"
    OBJECT = "object"
    NODE = "node"
    """Un sous-noeud : recursion."""

    NODE_LIST = "node_list"
    """Une liste non vide de sous-noeuds."""


@dataclass(frozen=True, slots=True)
class NodeField:
    """Un champ d'un type de noeud, decrit une seule fois.

    Le schema JSON en est DERIVE, il n'est pas saisi a cote. Un schema
    recopie a la main derive de son constructeur au premier changement, et un
    schema faux est pire que pas de schema : une machine lui fait confiance.
    Un test verifie en plus, pour chaque noeud enregistre, que son schema et
    son `from_spec` acceptent et refusent les memes choses.
    """

    name: str
    kind: FieldKind
    required: bool = True
    default: object | None = None
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    description: str = ""

    def json_schema(self) -> SpecDict:
        match self.kind:
            case FieldKind.NODE:
                schema: SpecDict = {"$ref": NODE_REF}
            case FieldKind.NODE_LIST:
                schema = {"type": "array", "items": {"$ref": NODE_REF}, "minItems": 1}
            case FieldKind.OBJECT:
                schema = {"type": "object"}
            case _:
                schema = {"type": self.kind.value}
                if self.choices:
                    schema["enum"] = list(self.choices)
                if self.minimum is not None:
                    schema["minimum"] = self.minimum
        if self.description:
            schema["description"] = self.description
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass(frozen=True, slots=True)
class NodeType:
    name: str
    version: int
    from_spec: FromSpec
    summary: str
    fields: tuple[NodeField, ...] = ()

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def json_schema(self) -> SpecDict:
        """Schema d'un noeud de ce type, references recursives comprises."""
        properties: SpecDict = {
            "type": {"const": self.name},
            "version": {"type": "integer", "const": self.version},
        }
        for field_ in self.fields:
            properties[field_.name] = field_.json_schema()
        return {
            "title": self.ref,
            "description": self.summary,
            "type": "object",
            "properties": properties,
            "required": ["type", *[f.name for f in self.fields if f.required]],
            "additionalProperties": False,
        }


_NODES: Final[dict[tuple[str, int], NodeType]] = {}


def signal_node(
    name: str,
    *,
    version: int = 1,
    summary: str = "",
    fields: tuple[NodeField, ...] = (),
) -> Callable[[type[Signal]], type[Signal]]:
    """Enregistre un type de noeud sous `(name, version)`.

    Meme regle que pour les primitives : une version publiee ne se modifie
    jamais. Un comportement a corriger devient `version + 1`, et les
    specifications archivees qui epinglent l'ancienne continuent de se
    reconstruire a l'identique.

    `fields` n'est pas facultatif en pratique. Il sert a deux choses a la fois :
    engendrer le JSON Schema publie, et refuser dans `build_signal` tout champ
    non declare. Un noeud qui ne declare rien publie donc un schema qui ment
    par omission, ET voit ses propres champs rejetes a la construction. Les
    deux effets viennent de la meme declaration, ce qui rend leur divergence
    impossible.
    """

    def decorate(cls: type[Signal]) -> type[Signal]:
        key = (name, version)
        if key in _NODES:
            raise RegistryError(
                f"type de noeud '{name}@{version}' deja enregistre. "
                f"Enregistrez '{name}@{version + 1}' plutot que de modifier celui-ci."
            )
        builder = getattr(cls, "from_spec", None)
        if builder is None:
            raise RegistryError(f"'{cls.__name__}' doit exposer une classmethod `from_spec`")
        _NODES[key] = NodeType(
            name=name,
            version=version,
            from_spec=builder,
            summary=summary or (cls.__doc__ or "").strip().split("\n")[0],
            fields=fields,
        )
        # Les classes declarent deja NODE_TYPE / NODE_VERSION ; on les
        # reaffirme depuis le decorateur pour qu'une divergence entre les deux
        # soit impossible.
        cls.NODE_TYPE = name  # type: ignore[attr-defined]
        cls.NODE_VERSION = version  # type: ignore[attr-defined]
        return cls

    return decorate


def get_node_type(name: str, version: int | None = None) -> NodeType:
    versions = sorted(v for (n, v) in _NODES if n == name)
    if not versions:
        known = ", ".join(sorted({n for n, _ in _NODES}))
        raise RegistryError(f"type de noeud inconnu : '{name}'. Connus : {known}")
    chosen = versions[-1] if version is None else version
    if chosen not in versions:
        raise RegistryError(
            f"'{name}@{version}' inconnu. Versions : {', '.join(str(v) for v in versions)}"
        )
    return _NODES[(name, chosen)]


def list_node_types() -> tuple[NodeType, ...]:
    """Tries par (nom, version) : l'ordre du dictionnaire n'influence rien."""
    return tuple(_NODES[key] for key in sorted(_NODES))


def describe_node_types() -> list[SpecDict]:
    """Catalogue machine des noeuds disponibles, schemas compris.

    Point de branchement du futur compilateur de specifications ; aucune brique
    LLM n'est construite ici.
    """
    return [
        {
            "type": n.name,
            "version": n.version,
            "summary": n.summary,
            "schema": n.json_schema(),
        }
        for n in list_node_types()
    ]


def signal_json_schema() -> SpecDict:
    """Schema complet d'un ARBRE de signaux, pas d'un noeud isole.

    C'est le document qui a une valeur pratique : un `$defs/node` qui enumere
    tous les types enregistres, et vers lequel chaque champ de sous-noeud
    pointe. Un validateur JSON Schema ordinaire y verifie donc un arbre entier,
    a n'importe quelle profondeur.

    Il est engendre depuis le registre : un type de noeud ajoute apparait sans
    que ce document soit touche.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Arbre de signaux rsl",
        "description": (
            "Expression evaluee sur un Context. Les feuilles sont des constantes, "
            "des champs de prix ou des primitives du registre ; les noeuds internes "
            "les combinent."
        ),
        "$ref": NODE_REF,
        "$defs": {
            "node": {
                "oneOf": [node.json_schema() for node in list_node_types()],
            }
        },
    }


def build_signal(spec: SpecDict) -> Signal:
    """Reconstruit un arbre de signaux a partir de sa specification declarative.

    Patron Fabrique : `build_signal` ne connait aucun type de noeud en propre,
    il delegue au registre. Ajouter un type de noeud ne modifie donc pas cette
    fonction.
    """
    if not isinstance(spec, dict):
        raise ConfigurationError(f"specification de noeud attendue, recu {type(spec).__name__}")
    raw_type = spec.get("type")
    if not isinstance(raw_type, str):
        raise ConfigurationError(f"champ 'type' manquant ou non textuel dans {spec!r}")
    raw_version = spec.get("version")
    if raw_version is not None and not isinstance(raw_version, int):
        raise ConfigurationError(f"champ 'version' doit etre un entier, recu {raw_version!r}")
    node_type = get_node_type(raw_type, raw_version)

    # Meme regle que partout ailleurs : un champ inconnu est une erreur, jamais
    # un defaut silencieux. Sans cela, une coquille - `oprands` au lieu de
    # `operands` - produirait un noeud amputé au lieu d'un message. C'est aussi
    # ce qui fait coincider ce constructeur avec le schema publie, qui pose
    # `additionalProperties: false` ; un schema plus strict que le code laisse
    # passer a l'execution ce qu'il pretend interdire.
    allowed = {"type", "version"} | {f.name for f in node_type.fields}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ConfigurationError(
            f"noeud '{raw_type}' : champ(s) inconnu(s) {', '.join(unknown)}. "
            f"Attendus : {', '.join(sorted(allowed))}"
        )
    return node_type.from_spec(spec, build_signal)


def _child(spec: SpecDict, key: str, build: Builder) -> Signal:
    value = spec.get(key)
    if not isinstance(value, dict):
        raise ConfigurationError(
            f"noeud '{spec.get('type')}' : champ '{key}' doit etre une specification de noeud"
        )
    return build(value)


def _children(spec: SpecDict, key: str, build: Builder) -> tuple[Signal, ...]:
    value = spec.get(key)
    if not isinstance(value, list) or not value:
        raise ConfigurationError(
            f"noeud '{spec.get('type')}' : champ '{key}' doit etre une liste non vide"
        )
    return tuple(build(item) for item in value if isinstance(item, dict))


# ---------------------------------------------------------------------------
# Feuilles
# ---------------------------------------------------------------------------


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
    _memoire: Memoire | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
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
        return self.inner.warmup_bars + (self.window - 1) * self.stride

    def __call__(self, ctx: Context) -> float | None:
        values = valeurs_de_fenetre(
            self._memoire,
            self.inner,
            ctx,
            range(0, self.window * self.stride, self.stride),
        )
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
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "stat": self.stat.value,
            "window": self.window,
            "stride": self.stride,
            "inner": self.inner.describe(),
        }

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
        return cls(RollingStat(raw), window, _child(spec, "inner", build), stride)


def rolling(stat: str, window: int, inner: Signal, stride: int = 1) -> Rolling:
    """Raccourci : `rolling("zscore", 100, spread)`."""
    return Rolling(RollingStat(stat), window, inner, stride)


# ---------------------------------------------------------------------------
# Noeuds internes
# ---------------------------------------------------------------------------


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


class CompareOp(StrEnum):
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    EQ = "=="
    NE = "!="


@signal_node(
    "compare",
    summary="Comparaison de deux sous-signaux, resultat booleen.",
    fields=(
        NodeField("op", FieldKind.STRING, choices=(">", ">=", "<", "<=", "==", "!=")),
        NodeField("left", FieldKind.NODE),
        NodeField("right", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class Compare:
    """Comparaison. `None` d'un cote rend le resultat indefini, pas faux."""

    NODE_TYPE: ClassVar[str] = "compare"
    NODE_VERSION: ClassVar[int] = 1

    left: Signal
    op: CompareOp
    right: Signal

    @property
    def warmup_bars(self) -> int:
        return max(self.left.warmup_bars, self.right.warmup_bars)

    def __call__(self, ctx: Context) -> float | None:
        a = self.left(ctx)
        b = self.right(ctx)
        if a is None or b is None:
            return None
        match self.op:
            case CompareOp.GT:
                return TRUE if a > b else FALSE
            case CompareOp.GE:
                return TRUE if a >= b else FALSE
            case CompareOp.LT:
                return TRUE if a < b else FALSE
            case CompareOp.LE:
                return TRUE if a <= b else FALSE
            case CompareOp.EQ:
                return TRUE if a == b else FALSE
            case CompareOp.NE:
                return TRUE if a != b else FALSE

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "op": self.op.value,
            "left": self.left.describe(),
            "right": self.right.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        raw = spec.get("op")
        if not isinstance(raw, str) or raw not in set(CompareOp):
            raise ConfigurationError(
                f"'compare' : operateur invalide {raw!r}. "
                f"Attendu l'un de {', '.join(o.value for o in CompareOp)}"
            )
        return cls(_child(spec, "left", build), CompareOp(raw), _child(spec, "right", build))


class ArithOp(StrEnum):
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"


@signal_node(
    "arith",
    summary="Operation arithmetique entre deux sous-signaux.",
    fields=(
        NodeField("op", FieldKind.STRING, choices=("+", "-", "*", "/")),
        NodeField("left", FieldKind.NODE),
        NodeField("right", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class Arith:
    """Arithmetique. Une division par zero rend `None`, jamais `inf`."""

    NODE_TYPE: ClassVar[str] = "arith"
    NODE_VERSION: ClassVar[int] = 1

    left: Signal
    op: ArithOp
    right: Signal

    @property
    def warmup_bars(self) -> int:
        return max(self.left.warmup_bars, self.right.warmup_bars)

    def __call__(self, ctx: Context) -> float | None:
        a = self.left(ctx)
        b = self.right(ctx)
        if a is None or b is None:
            return None
        match self.op:
            case ArithOp.ADD:
                return a + b
            case ArithOp.SUB:
                return a - b
            case ArithOp.MUL:
                return a * b
            case ArithOp.DIV:
                return None if b == 0.0 else a / b

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "op": self.op.value,
            "left": self.left.describe(),
            "right": self.right.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        raw = spec.get("op")
        if not isinstance(raw, str) or raw not in set(ArithOp):
            raise ConfigurationError(
                f"'arith' : operateur invalide {raw!r}. "
                f"Attendu l'un de {', '.join(o.value for o in ArithOp)}"
            )
        return cls(_child(spec, "left", build), ArithOp(raw), _child(spec, "right", build))


@signal_node(
    "all_of",
    summary="Conjonction : vrai si tous les sous-signaux sont vrais.",
    fields=(NodeField("operands", FieldKind.NODE_LIST),),
)
@dataclass(frozen=True, slots=True)
class AllOf:
    """Conjonction stricte.

    Pas de court-circuit sur `None` : si un membre est indefini, le resultat
    est indefini meme si un autre est faux. Un "je ne sais pas" ne doit pas
    etre absorbe par un "non" - la strategie doit voir qu'elle n'a pas
    d'information.
    """

    NODE_TYPE: ClassVar[str] = "all_of"
    NODE_VERSION: ClassVar[int] = 1

    operands: tuple[Signal, ...]

    def __post_init__(self) -> None:
        if not self.operands:
            raise ConfigurationError("'all_of' exige au moins un operande")

    @property
    def warmup_bars(self) -> int:
        return max(s.warmup_bars for s in self.operands)

    def __call__(self, ctx: Context) -> float | None:
        result = TRUE
        for operand in self.operands:
            value = operand(ctx)
            if value is None:
                return None
            if value == FALSE:
                result = FALSE
        return result

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "operands": [s.describe() for s in self.operands],
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        return cls(_children(spec, "operands", build))


@signal_node(
    "any_of",
    summary="Disjonction : vrai si au moins un sous-signal est vrai.",
    fields=(NodeField("operands", FieldKind.NODE_LIST),),
)
@dataclass(frozen=True, slots=True)
class AnyOf:
    """Disjonction stricte. Meme traitement de `None` que `all_of`."""

    NODE_TYPE: ClassVar[str] = "any_of"
    NODE_VERSION: ClassVar[int] = 1

    operands: tuple[Signal, ...]

    def __post_init__(self) -> None:
        if not self.operands:
            raise ConfigurationError("'any_of' exige au moins un operande")

    @property
    def warmup_bars(self) -> int:
        return max(s.warmup_bars for s in self.operands)

    def __call__(self, ctx: Context) -> float | None:
        result = FALSE
        for operand in self.operands:
            value = operand(ctx)
            if value is None:
                return None
            if value != FALSE:
                result = TRUE
        return result

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "operands": [s.describe() for s in self.operands],
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        return cls(_children(spec, "operands", build))


@signal_node(
    "not",
    summary="Negation booleenne.",
    fields=(NodeField("inner", FieldKind.NODE),),
)
@dataclass(frozen=True, slots=True)
class Not:
    """Negation. `None` reste `None`."""

    NODE_TYPE: ClassVar[str] = "not"
    NODE_VERSION: ClassVar[int] = 1

    inner: Signal

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars

    def __call__(self, ctx: Context) -> float | None:
        value = self.inner(ctx)
        if value is None:
            return None
        return FALSE if value != FALSE else TRUE

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "inner": self.inner.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        return cls(_child(spec, "inner", build))


@signal_node(
    "crosses_above",
    summary="`fast` passe au-dessus de `slow` entre t-1 et t.",
    fields=(NodeField("fast", FieldKind.NODE), NodeField("slow", FieldKind.NODE)),
)
@dataclass(frozen=True, slots=True)
class CrossesAbove:
    """Croisement haussier.

    Volontairement sans etat : le noeud lit la barre precedente via
    `Context.shifted(1)` plutot que de memoriser la valeur d'hier. Un etat
    interne survivrait d'un run a l'autre et casserait le determinisme et le
    test de corruption du futur.
    """

    NODE_TYPE: ClassVar[str] = "crosses_above"
    NODE_VERSION: ClassVar[int] = 1

    fast: Signal
    slow: Signal

    @property
    def warmup_bars(self) -> int:
        return max(self.fast.warmup_bars, self.slow.warmup_bars) + 1

    def __call__(self, ctx: Context) -> float | None:
        now_fast = self.fast(ctx)
        now_slow = self.slow(ctx)
        if now_fast is None or now_slow is None:
            return None
        past = ctx.shifted(1)
        prev_fast = self.fast(past)
        prev_slow = self.slow(past)
        if prev_fast is None or prev_slow is None:
            return None
        crossed = prev_fast <= prev_slow and now_fast > now_slow
        return TRUE if crossed else FALSE

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "fast": self.fast.describe(),
            "slow": self.slow.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        return cls(_child(spec, "fast", build), _child(spec, "slow", build))


@signal_node(
    "crosses_below",
    summary="`fast` passe sous `slow` entre t-1 et t.",
    fields=(NodeField("fast", FieldKind.NODE), NodeField("slow", FieldKind.NODE)),
)
@dataclass(frozen=True, slots=True)
class CrossesBelow:
    """Croisement baissier. Symetrique de `crosses_above`."""

    NODE_TYPE: ClassVar[str] = "crosses_below"
    NODE_VERSION: ClassVar[int] = 1

    fast: Signal
    slow: Signal

    @property
    def warmup_bars(self) -> int:
        return max(self.fast.warmup_bars, self.slow.warmup_bars) + 1

    def __call__(self, ctx: Context) -> float | None:
        now_fast = self.fast(ctx)
        now_slow = self.slow(ctx)
        if now_fast is None or now_slow is None:
            return None
        past = ctx.shifted(1)
        prev_fast = self.fast(past)
        prev_slow = self.slow(past)
        if prev_fast is None or prev_slow is None:
            return None
        crossed = prev_fast >= prev_slow and now_fast < now_slow
        return TRUE if crossed else FALSE

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "fast": self.fast.describe(),
            "slow": self.slow.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        return cls(_child(spec, "fast", build), _child(spec, "slow", build))


# ---------------------------------------------------------------------------
# Confort de construction en Python (les stratégies ecrites a la main)
# ---------------------------------------------------------------------------


def prim(ref: str, **params: object) -> PrimitiveSignal:
    """Raccourci : `prim("sma@1", window=20)`."""
    return PrimitiveSignal.of(ref, **params)


def const(value: float) -> Constant:
    return Constant(float(value))


def price(field: str = "close", lag: int = 0) -> Price:
    return Price(field, lag)


def all_of(*operands: Signal) -> AllOf:
    return AllOf(tuple(operands))


def any_of(*operands: Signal) -> AnyOf:
    return AnyOf(tuple(operands))


def warmup_of(signals: Sequence[Signal]) -> int:
    """Warmup d'un ensemble de signaux : le maximum, 0 si l'ensemble est vide."""
    return max((s.warmup_bars for s in signals), default=0)


# ---------------------------------------------------------------------------
# Noeuds ajoutes en second temps : conditionnel, arithmetique unaire,
# extremes n-aires, et recherche dans le passe recent.
# ---------------------------------------------------------------------------


@signal_node(
    "if_then_else",
    summary="Choisit entre deux sous-signaux selon une condition.",
    fields=(
        NodeField("condition", FieldKind.NODE),
        NodeField("then", FieldKind.NODE),
        NodeField("otherwise", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class IfThenElse:
    """Expression conditionnelle.

    Sans elle, "le stop vaut 2 ATR en tendance et 1 ATR sinon" n'est pas
    exprimable : il faut ecrire deux strategies. Les deux branches sont
    construites - le warmup est celui du plus large des sous-arbres, pas celui
    de la branche retenue - parce qu'un warmup dependant de la condition
    dependrait du moment, donc ne serait pas calculable a l'avance.

    `otherwise` et non `else` : `else` est un mot reserve de Python, et un
    champ JSON qui ne peut pas devenir un attribut est une chausse-trappe.
    """

    NODE_TYPE: ClassVar[str] = "if_then_else"
    NODE_VERSION: ClassVar[int] = 1

    condition: Signal
    then: Signal
    otherwise: Signal

    @property
    def warmup_bars(self) -> int:
        return warmup_of((self.condition, self.then, self.otherwise))

    def __call__(self, ctx: Context) -> float | None:
        decision = self.condition(ctx)
        if decision is None:
            return None
        return self.then(ctx) if decision != FALSE else self.otherwise(ctx)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "condition": self.condition.describe(),
            "then": self.then.describe(),
            "otherwise": self.otherwise.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        return cls(
            _child(spec, "condition", build),
            _child(spec, "then", build),
            _child(spec, "otherwise", build),
        )


class MathOp(StrEnum):
    """Operations unaires disponibles."""

    ABS = "abs"
    NEG = "neg"
    SIGN = "sign"
    LOG = "log"
    EXP = "exp"
    SQRT = "sqrt"
    INVERSE = "inverse"
    FLOOR = "floor"
    CEIL = "ceil"


EXP_LIMIT: Final[float] = 700.0
"""Au-dela, `math.exp` deborde le flottant double. Rendre `None` plutot que
laisser lever : la convention du socle est qu'une valeur non calculable est
absente, pas fatale."""


@signal_node(
    "math",
    summary="Operation arithmetique UNAIRE sur un sous-signal.",
    fields=(
        NodeField("op", FieldKind.STRING, choices=tuple(o.value for o in MathOp)),
        NodeField("inner", FieldKind.NODE),
    ),
)
@dataclass(frozen=True, slots=True)
class MathNode:
    """Complement unaire de `arith`, qui est binaire.

    Les domaines invalides rendent `None`, jamais `NaN` : `log` d'un nombre
    negatif ou nul, `sqrt` d'un negatif, `inverse` de zero. Un `NaN` se
    propagerait en silence dans une comparaison, qui vaudrait `False`, et
    produirait "pas de signal" au lieu de "erreur" - la raison d'etre de la
    convention `None` du socle.
    """

    NODE_TYPE: ClassVar[str] = "math"
    NODE_VERSION: ClassVar[int] = 1

    op: MathOp
    inner: Signal

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars

    def __call__(self, ctx: Context) -> float | None:
        value = self.inner(ctx)
        if value is None:
            return None
        match self.op:
            case MathOp.ABS:
                return abs(value)
            case MathOp.NEG:
                return -value
            case MathOp.SIGN:
                return float((value > 0.0) - (value < 0.0))
            case MathOp.LOG:
                return None if value <= 0.0 else math.log(value)
            case MathOp.EXP:
                return None if value > EXP_LIMIT else math.exp(value)
            case MathOp.SQRT:
                return None if value < 0.0 else math.sqrt(value)
            case MathOp.INVERSE:
                return None if value == 0.0 else 1.0 / value
            case MathOp.FLOOR:
                return float(math.floor(value))
            case MathOp.CEIL:
                return float(math.ceil(value))

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "op": self.op.value,
            "inner": self.inner.describe(),
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        raw = spec.get("op")
        if not isinstance(raw, str) or raw not in set(MathOp):
            raise ConfigurationError(
                f"'math' : operation invalide {raw!r}. "
                f"Attendu l'un de {', '.join(o.value for o in MathOp)}"
            )
        return cls(MathOp(raw), _child(spec, "inner", build))


@signal_node(
    "min_of",
    summary="Plus petite valeur parmi plusieurs sous-signaux.",
    fields=(NodeField("operands", FieldKind.NODE_LIST),),
)
@dataclass(frozen=True, slots=True)
class MinOf:
    """Minimum n-aire. Un seul operande indefini rend le tout indefini."""

    NODE_TYPE: ClassVar[str] = "min_of"
    NODE_VERSION: ClassVar[int] = 1

    operands: tuple[Signal, ...]

    @property
    def warmup_bars(self) -> int:
        return warmup_of(self.operands)

    def __call__(self, ctx: Context) -> float | None:
        valeurs = [operande(ctx) for operande in self.operands]
        retenues = [v for v in valeurs if v is not None]
        if len(retenues) != len(valeurs):
            return None
        return min(retenues)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "operands": [o.describe() for o in self.operands],
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        return cls(_children(spec, "operands", build))


@signal_node(
    "max_of",
    summary="Plus grande valeur parmi plusieurs sous-signaux.",
    fields=(NodeField("operands", FieldKind.NODE_LIST),),
)
@dataclass(frozen=True, slots=True)
class MaxOf:
    """Maximum n-aire. Avec `min_of`, permet de borner une expression."""

    NODE_TYPE: ClassVar[str] = "max_of"
    NODE_VERSION: ClassVar[int] = 1

    operands: tuple[Signal, ...]

    @property
    def warmup_bars(self) -> int:
        return warmup_of(self.operands)

    def __call__(self, ctx: Context) -> float | None:
        valeurs = [operande(ctx) for operande in self.operands]
        retenues = [v for v in valeurs if v is not None]
        if len(retenues) != len(valeurs):
            return None
        return max(retenues)

    def describe(self) -> SpecDict:
        return {
            "type": self.NODE_TYPE,
            "version": self.NODE_VERSION,
            "operands": [o.describe() for o in self.operands],
        }

    @classmethod
    def from_spec(cls, spec: SpecDict, build: Builder) -> Signal:
        return cls(_children(spec, "operands", build))


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


def if_then_else(condition: Signal, then: Signal, otherwise: Signal) -> IfThenElse:
    """Raccourci : `if_then_else(cond, a, b)`."""
    return IfThenElse(condition, then, otherwise)


def unary(op: str, inner: Signal) -> MathNode:
    """Raccourci : `unary("abs", spread)`."""
    return MathNode(MathOp(op), inner)


def min_of(*operands: Signal) -> MinOf:
    return MinOf(tuple(operands))


def max_of(*operands: Signal) -> MaxOf:
    return MaxOf(tuple(operands))


def bars_since(lookback: int, inner: Signal) -> BarsSince:
    """Raccourci : `bars_since(50, condition)`."""
    return BarsSince(lookback, inner)


@signal_node(
    "session",
    summary="Feuille : une grandeur de la seance courante ou d'une seance close.",
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


class CumulativeStat(StrEnum):
    """Statistique cumulee depuis l'ouverture de la seance."""

    SUM = "sum"
    MEAN = "mean"
    MIN = "min"
    MAX = "max"
    FIRST = "first"
    LAST = "last"
    COUNT_TRUE = "count_true"


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
        rang = ctx.session_value(SessionField.BAR_INDEX, 0)
        values = valeurs_de_fenetre(
            self._memoire, self.inner, ctx, range(int(rang) + 1)
        )
        if values is None:
            return None

        # `values[0]` est le PRESENT, les lags croissants remontent le temps :
        # `first` est donc le dernier element, `last` le premier.
        fenetre = np.array(values, dtype=np.float64)
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
                return values[-1]
            case CumulativeStat.LAST:
                return values[0]
            case CumulativeStat.COUNT_TRUE:
                return float(np.count_nonzero(fenetre > 0.0))

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
