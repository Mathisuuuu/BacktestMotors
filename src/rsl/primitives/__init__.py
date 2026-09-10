"""Primitives : contrat, registre statique, bibliotheque integree.

Importer ce paquet peuple le registre avec les primitives integrees.
"""

from __future__ import annotations

from rsl.primitives import builtin  # noqa: F401  (effet de bord : enregistrement)
from rsl.primitives.base import BoundPrimitive, Primitive, PrimitiveParams, PrimitiveRef
from rsl.primitives.registry import (
    bind_primitive,
    describe_registry,
    get_primitive,
    list_primitives,
    primitive,
)

__all__ = [
    "BoundPrimitive",
    "Primitive",
    "PrimitiveParams",
    "PrimitiveRef",
    "bind_primitive",
    "describe_registry",
    "get_primitive",
    "list_primitives",
    "primitive",
]
