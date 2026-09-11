"""Noeuds qui COMBINENT des sous-signaux : logique, comparaison, arithmetique.

Aucun d'eux ne lit le monde : ils prennent des valeurs deja calculees et en
font une autre. C'est la couche ou se construisent les regles - un croisement,
une conjonction de conditions, un ecart de deux moyennes.

Tous propagent `None` : une operation dont un operande est indefini est
indefinie. La regle est uniforme et elle n'a pas d'exception.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Final

from rsl.data.feed import Context
from rsl.errors import ConfigurationError
from rsl.strategies.noeuds.contrat import (
    FALSE,
    TRUE,
    Builder,
    FieldKind,
    NodeField,
    Signal,
    SpecDict,
    _child,
    _children,
    signal_node,
    warmup_of,
)


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
