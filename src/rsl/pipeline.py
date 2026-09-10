"""Points de branchement de la phase suivante. AUCUNE implementation ici.

La phase 1 construit le socle, pas la chaine papier -> specification -> code.
Ce module ne contient que les protocoles auxquels ces briques se conformeront,
pour que leur forme soit fixee pendant que la verite terrain est encore fraiche
- et pour qu'il soit visible, en lisant le socle, ou elles se brancheront.

Ce que la phase 1 leur fournit deja :

  - `rsl.primitives.registry.describe_registry()` : le catalogue des primitives
    existantes, avec le schema JSON de leurs parametres ;
  - `rsl.strategies.signals.describe_node_types()` : les types de noeuds
    composables ;
  - `rsl.strategies.base.describe_strategies()` : les familles de strategies
    enregistrees ;
  - `build_signal` / `build_strategy` : la reconstruction d'un objet a partir
    d'une specification declarative, sans generation de code.

Autrement dit, un compilateur de specifications n'aura RIEN a generer tant
qu'il reste dans le vocabulaire existant. La generation de code n'est requise
que pour une primitive reellement nouvelle - et c'est precisement la que le
socle sert de verite terrain.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

SpecDict = dict[str, object]


@runtime_checkable
class PaperSource(Protocol):
    """Fournit le texte d'un article de recherche. Non implemente en phase 1."""

    def fetch(self, identifier: str) -> str: ...


@runtime_checkable
class SpecExtractor(Protocol):
    """Texte -> specification de strategie declarative. Non implemente en phase 1.

    La sortie doit etre acceptee telle quelle par
    `rsl.strategies.base.build_strategy`. Aucune tolerance n'est prevue : une
    specification invalide doit echouer a la construction, pas produire une
    strategie approximative.
    """

    def extract(self, text: str) -> SpecDict: ...


@runtime_checkable
class PrimitiveSynthesizer(Protocol):
    """Genere une primitive absente du registre. Non implemente en phase 1.

    Contrainte deja fixee par le socle : la primitive produite devra respecter
    la signature `(Context, params) -> float | None` et s'enregistrer sous une
    version neuve. Elle ne pourra donc pas lire au-dela du curseur, quelle que
    soit la maniere dont elle a ete ecrite - c'est tout l'interet d'avoir bati
    le socle en premier.
    """

    def synthesize(self, description: str) -> str: ...


@runtime_checkable
class SpecValidator(Protocol):
    """Verifie qu'une specification generee correspond bien au papier source.

    Non implemente en phase 1.
    """

    def validate(self, spec: SpecDict, text: str) -> tuple[bool, str]: ...
