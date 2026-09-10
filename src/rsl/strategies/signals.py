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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Final, Protocol, runtime_checkable

from rsl.data.feed import Context
from rsl.data.schema import POSITION_FIELDS
from rsl.errors import ConfigurationError, RegistryError
from rsl.primitives.base import BoundPrimitive
from rsl.primitives.registry import get_primitive

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
