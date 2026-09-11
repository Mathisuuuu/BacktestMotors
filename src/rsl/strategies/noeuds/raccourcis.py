"""Confort de construction en Python, pour les strategies ecrites a la main.

Ces fonctions ne font rien qu'un constructeur ne fasse : elles abregent.
`prim("sma@1", window=20)` se lit mieux que
`PrimitiveSignal.of("sma@1", window=20)`, et c'est tout.

Elles ne servent PAS au chemin declaratif : une specification JSON passe par
`build_signal`, qui ne les connait pas.
"""

from __future__ import annotations

from rsl.strategies.noeuds.contrat import Signal
from rsl.strategies.noeuds.feuilles import Constant, Price, PrimitiveSignal
from rsl.strategies.noeuds.operateurs import AllOf, AnyOf


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
