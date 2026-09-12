"""Charger un exemple, maintenant qu'il vient en DEUX morceaux.

Depuis le 2026-09-12, `examples/` ne contient plus de specification complete :
une strategie dans `examples/strategies/`, son montage dans
`examples/reglages/`. Recoller les deux est l'affaire de `composition.compose`,
et ce module en fait un seul chemin pour toute la suite de tests.

Pourquoi un seul chemin
-----------------------
Cinq fichiers de tests chargeaient un exemple, chacun a sa maniere. Avec deux
morceaux a recoller ET un symbole a injecter, cinq manieres deviendraient cinq
occasions de le faire differemment - et une difference silencieuse entre ce que
teste un fichier et ce qu'en teste un autre.

Le symbole vient de `empreintes_attendues.json`, qui sert deja de verite
terrain : c'est aussi lui qui dit sur quel instrument chaque exemple a ete
mesure. Le stocker ailleurs ferait une seconde source.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from rsl.composition import StrategyFile, compose
from rsl.config import BacktestSpec

RACINE = Path(__file__).resolve().parents[2]
STRATEGIES = RACINE / "examples" / "strategies"
REGLAGES = RACINE / "examples" / "reglages"
REFERENCE = RACINE / "tests" / "fixtures" / "empreintes_attendues.json"


@lru_cache(maxsize=1)
def attendues() -> dict[str, dict[str, object]]:
    """La verite terrain : empreintes, hash de configuration, symbole."""
    charge = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert isinstance(charge, dict)
    return charge


def noms() -> list[str]:
    """Les exemples, tries. Sert a parametrer les tests sans liste a tenir."""
    return sorted(attendues())


def strategie(nom: str) -> StrategyFile:
    return StrategyFile.model_validate_json(
        (STRATEGIES / nom).read_text(encoding="utf-8")
    )


def montage(nom: str) -> dict[str, object]:
    charge = json.loads((REGLAGES / nom).read_text(encoding="utf-8"))
    assert isinstance(charge, dict)
    return charge


def specification(nom: str) -> BacktestSpec:
    """L'exemple recolle, tel que `rsl run --settings` le construirait."""
    symbole = attendues()[nom]["symbol"]
    assert symbole is None or isinstance(symbole, str)
    return compose(strategie(nom), montage(nom), symbol=symbole)
