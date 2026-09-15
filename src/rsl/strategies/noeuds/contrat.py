"""Le contrat d'un signal, et le registre des types de noeuds.

Un signal est une expression evaluee sur un `Context` : `Signal(ctx) -> float |
None`. Ce module ne definit AUCUN noeud - il definit ce qu'est un noeud, et
comment on en publie un nouveau.

Convention booleenne : `1.0` vrai, `0.0` faux, `None` indefini. `None` se
propage - une comparaison dont un membre est indefini est indefinie, elle
n'est pas fausse. Meme raisonnement que le refus des `NaN` dans le `Context` :
« je ne sais pas » ne doit jamais devenir « non » en silence.

Les familles de noeuds vivent a cote : `feuilles`, `fenetres`, `operateurs`.
Elles importent toutes ce module, jamais l'inverse.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from rsl.data.feed import Context
from rsl.errors import ConfigurationError, RegistryError

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

Builder = Callable[[SpecDict], Signal]
FromSpec = Callable[[SpecDict, Builder], Signal]

NODE_REF: Final[str] = "#/$defs/node"

NOTE_FIELD: Final[str] = "note"
"""Champ de commentaire accepte sur TOUT noeud, et ignore par le moteur.

JSON n'a pas de commentaires, et une expression declare `-1.5` ou `120` sans
pouvoir dire d'ou ils viennent. C'est le seul manque reel de JSON face a YAML
- mesure le 2026-09-12, le reste du proces ne tenant pas ici : les modeles
stricts attrapent les coercions de YAML, et cinq des dix operateurs du
vocabulaire (`>`, `>=`, `!=`, `-`, `*`) entrent en collision avec sa syntaxe,
`>` devenant meme la chaine vide SANS erreur.

Ignore, donc absent de `describe()`, donc absent du rapport de run et de
l'empreinte. Un commentaire decrit l'INTENTION de qui a ecrit la
specification ; le rapport decrit ce qui a TOURNE. Les deux ne se confondent
pas, et corriger une faute de frappe dans un commentaire ne doit pas rendre
un run incomparable a un run archive.

Une LISTE vaut plusieurs lignes : JSON n'a pas de chaine multiligne.
"""


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
class Piege:
    """Un ecart entre ce que le NOM d'un terme suggere et ce que sa DEFINITION fait.

    Pourquoi ce type existe
    ------------------------
    Le 2026-09-15, trois des cinq ecarts d'une replication venaient du meme
    defaut : `session.is_last` ne veut pas dire « la derniere barre de la
    seance » mais « la premiere barre a atteindre l'heure DECLAREE ». Sur une
    seance ecourtee, aucune barre n'est marquee, et une regle de securite
    adossee a ce champ n'y declenche jamais.

    Ces ecarts ne sont pas des bugs : chaque definition est necessaire, le plus
    souvent pour une raison de CAUSALITE. « La derniere barre » est un fait
    futur - pour le savoir il faudrait regarder la barre suivante. Le terme ne
    peut donc pas tenir la promesse de son nom, quel que soit le nom.

    Ce que ce type change
    ----------------------
    Le piege est declare **a cote de la definition qu'il decrit**, pas dans une
    liste tenue ailleurs. Une liste tenue ailleurs se perime sans prevenir -
    c'est exactement ce qui est arrive au recensement de couverture, dont deux
    verdicts sur quatre etaient devenus faux ([[lessons]] L36).

    `controle` nomme, quand il existe, le code du controle de `rsl check` qui
    l'attrape. Les pieges sans controle ne sont pas moins reels : ils ne sont
    simplement pas decidables depuis la specification seule.
    """

    champ: str | None
    """Le champ concerne, ou `None` quand le piege vise le noeud entier."""

    promesse: str
    """Ce que le nom laisse croire."""

    realite: str
    """Ce que la definition fait."""

    quand: str
    """La situation ou les deux divergent. Une phrase, pas une theorie."""

    controle: str | None = None
    """Code du controle de `rsl check`, si le piege est decidable avant le run."""

    def describe(self) -> SpecDict:
        return {
            "champ": self.champ,
            "promesse": self.promesse,
            "realite": self.realite,
            "quand": self.quand,
            "controle": self.controle,
        }


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
    pieges: tuple[Piege, ...] = ()
    """Les ecarts nom / definition de ce noeud. Vide = AUDITE, sans ecart.

    Un tuple vide est une AFFIRMATION, pas un oubli : `test_pieges.py`
    exige que chaque type enregistre ait ete audite et refuse tout noeud
    neuf absent de sa liste. On ne peut donc pas ajouter un terme au
    vocabulaire sans avoir tranche la question.
    """

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def json_schema(self) -> SpecDict:
        """Schema d'un noeud de ce type, references recursives comprises."""
        properties: SpecDict = {
            "type": {"const": self.name},
            "version": {"type": "integer", "const": self.version},
            # Publie parce que le constructeur l'accepte. Un schema plus STRICT
            # que le code refuserait ce qui tourne, et un editeur qui valide
            # contre lui signalerait une erreur la ou il n'y en a pas - le
            # defaut symetrique de celui que ce meme fichier evite plus bas.
            NOTE_FIELD: {
                "description": (
                    "Commentaire libre, ignore par le moteur. Une liste vaut "
                    "plusieurs lignes."
                ),
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
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
    pieges: tuple[Piege, ...] = (),
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
            pieges=pieges,
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
            "pieges": [p.describe() for p in n.pieges],
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
    allowed = {"type", "version", NOTE_FIELD} | {f.name for f in node_type.fields}
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ConfigurationError(
            f"noeud '{raw_type}' : champ(s) inconnu(s) {', '.join(unknown)}. "
            f"Attendus : {', '.join(sorted(allowed))}"
        )
    _verifier_note(spec, raw_type)
    return node_type.from_spec(spec, build_signal)


def _verifier_note(spec: SpecDict, raw_type: str) -> None:
    """La note est libre, sa FORME ne l'est pas.

    Un champ qu'on ne valide pas du tout est un champ ou une coquille passe :
    `"note": {"pourquoi": "..."}` serait accepte en silence, et le jour ou
    quelqu'un voudra afficher les notes il trouvera des formes inattendues.
    Texte, ou liste de textes.
    """
    valeur = spec.get(NOTE_FIELD)
    if valeur is None or isinstance(valeur, str):
        return
    if isinstance(valeur, list) and all(isinstance(v, str) for v in valeur):
        return
    raise ConfigurationError(
        f"noeud '{raw_type}' : `{NOTE_FIELD}` doit etre un texte ou une liste "
        f"de textes, recu {type(valeur).__name__}"
    )


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


def warmup_of(signals: Sequence[Signal]) -> int:
    """Warmup d'un ensemble de signaux : le maximum, 0 si l'ensemble est vide."""
    return max((s.warmup_bars for s in signals), default=0)
