"""Primitives integrees.

Importer ce paquet suffit a peupler le registre : chaque module s'enregistre a
l'import. Ajouter une primitive = ajouter un module (ou une fonction decoree
dans un module existant) et l'importer ici. Aucun module deja publie n'est
modifie.

L'import est explicite plutot que decouvert dynamiquement : un balayage de
repertoire dependrait de l'ordre du systeme de fichiers, ce qui contredit
l'exigence de reproductibilite.
"""

from __future__ import annotations

from rsl.primitives.builtin import (
    momentum,
    oscillators,
    ranges,
    stats,
    trend,
    volume,
    wilder,
)

__all__ = [
    "momentum",
    "oscillators",
    "ranges",
    "stats",
    "trend",
    "volume",
    "wilder",
]
