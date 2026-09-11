"""Types de noeuds du vocabulaire de signaux, ranges par famille.

Importer ce paquet suffit a peupler le registre : chaque module s'y enregistre
a l'import, comme `rsl.primitives.builtin`. L'import est explicite plutot que
decouvert par balayage de repertoire - un balayage dependrait de l'ordre du
systeme de fichiers, ce qui contredit l'exigence de reproductibilite.

    contrat      ce qu'est un signal, et comment on publie un type de noeud
    feuilles     ce qui lit le monde : prix, primitive, position, seance, pair
    fenetres     ce qui regarde plusieurs barres : rolling, lag, cumulative
    operateurs   ce qui combine : comparaison, arithmetique, logique
    raccourcis   abreviations pour les strategies ecrites a la main

Les quatre familles importent `contrat`, jamais l'inverse : c'est ce qui rend
le paquet acyclique, et `tests/unit/test_couches.py` le verifie.

`rsl.strategies.signals` reste la facade publique et reexporte tout. Ce
paquet existe parce que `signals.py` avait atteint 1 949 lignes ; l'ouvrir
pour trouver un noeud demandait de savoir ou il se trouvait.
"""

from __future__ import annotations

from rsl.strategies.noeuds import (  # effet de bord : enregistrement
    contrat,
    fenetres,
    feuilles,
    operateurs,
    raccourcis,
)

__all__ = [
    "contrat",
    "fenetres",
    "feuilles",
    "operateurs",
    "raccourcis",
]
