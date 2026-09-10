"""Strategies : contrat, registre versionne, composition et references.

Importer ce paquet peuple le registre avec les strategies de reference. Sans
cela, `describe_strategies()` renverrait une liste vide selon le chemin
d'import emprunte - un catalogue qui depend de l'ordre des imports n'est pas un
catalogue.
"""

from __future__ import annotations

from rsl.strategies import handwritten  # effet de bord : enregistrement
from rsl.strategies.base import (
    CrossSectionalStrategy,
    Strategy,
    build_strategy,
    describe_strategies,
    get_strategy,
    list_strategies,
    strategy,
)

__all__ = [
    "CrossSectionalStrategy",
    "Strategy",
    "build_strategy",
    "describe_strategies",
    "get_strategy",
    "handwritten",
    "list_strategies",
    "strategy",
]
