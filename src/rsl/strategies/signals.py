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

Ce module est une FACADE depuis le 2026-09-11
----------------------------------------------
Le code vit dans `rsl/strategies/noeuds/`, range par famille : `contrat`,
`feuilles`, `fenetres`, `operateurs`, `raccourcis`. Il avait atteint 1 949
lignes ici, et ouvrir le fichier pour trouver un noeud demandait de savoir ou
il se trouvait.

La facade est conservee plutot que retiree parce qu'elle ne coute rien et
qu'elle epargne un renommage dans une trentaine de fichiers. Elle reexporte
EXACTEMENT ce qui etait public avant le decoupage - un test le verifie
(`tests/unit/test_couches.py`), pour qu'un nom ne disparaisse pas sans qu'on
le voie.
"""

from __future__ import annotations

from rsl.strategies.noeuds.contrat import (
    FALSE,
    NODE_REF,
    TRUE,
    Builder,
    FieldKind,
    FromSpec,
    NodeField,
    NodeType,
    Signal,
    SpecDict,
    build_signal,
    describe_node_types,
    get_node_type,
    list_node_types,
    signal_json_schema,
    signal_node,
    warmup_of,
)
from rsl.strategies.noeuds.fenetres import (
    DISPERSION_STATS,
    BarsSince,
    Cumulative,
    CumulativeStat,
    Lag,
    Rolling,
    RollingAcross,
    RollingStat,
    SessionLag,
    bars_since,
    cumulative,
    rolling,
)
from rsl.strategies.noeuds.feuilles import (
    Account,
    Constant,
    Peer,
    Position,
    Price,
    PrimitiveSignal,
    Session,
    Time,
    account,
    peer,
    position,
    session,
    when,
)
from rsl.strategies.noeuds.operateurs import (
    EXP_LIMIT,
    AllOf,
    AnyOf,
    Arith,
    ArithOp,
    Compare,
    CompareOp,
    CrossesAbove,
    CrossesBelow,
    IfThenElse,
    MathNode,
    MathOp,
    MaxOf,
    MinOf,
    Not,
    if_then_else,
    max_of,
    min_of,
    unary,
)
from rsl.strategies.noeuds.raccourcis import all_of, any_of, const, price, prim

__all__ = [
    "DISPERSION_STATS",
    "EXP_LIMIT",
    "FALSE",
    "NODE_REF",
    "TRUE",
    "Account",
    "AllOf",
    "AnyOf",
    "Arith",
    "ArithOp",
    "BarsSince",
    "Builder",
    "Compare",
    "CompareOp",
    "Constant",
    "CrossesAbove",
    "CrossesBelow",
    "Cumulative",
    "CumulativeStat",
    "FieldKind",
    "FromSpec",
    "IfThenElse",
    "Lag",
    "MathNode",
    "MathOp",
    "MaxOf",
    "MinOf",
    "NodeField",
    "NodeType",
    "Not",
    "Peer",
    "Position",
    "Price",
    "PrimitiveSignal",
    "Rolling",
    "RollingAcross",
    "RollingStat",
    "Session",
    "SessionLag",
    "Signal",
    "SpecDict",
    "Time",
    "account",
    "all_of",
    "any_of",
    "bars_since",
    "build_signal",
    "const",
    "cumulative",
    "describe_node_types",
    "get_node_type",
    "if_then_else",
    "list_node_types",
    "max_of",
    "min_of",
    "peer",
    "position",
    "price",
    "prim",
    "rolling",
    "session",
    "signal_json_schema",
    "signal_node",
    "unary",
    "warmup_of",
    "when",
]
