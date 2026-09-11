"""Parcours du registre de primitives, pour les tests qui valent pour TOUTES.

Une bibliotheque d'indicateurs ne se verifie pas indicateur par indicateur :
chaque ajout apporterait sa propre couverture, et l'oubli d'un cas passerait
inapercu. Les proprietes qui doivent tenir pour toutes - warmup honnete,
insensibilite au futur, parametres refuses hors bornes - se testent une fois
et s'appliquent d'office a ce qui sera ajoute demain.

D'ou ce module : il fabrique des PARAMETRES VALIDES pour n'importe quelle
primitive, en lisant son schema. Aucune liste a tenir a jour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rsl.primitives.base import Primitive
from rsl.primitives.registry import describe_registry, get_primitive

FENETRE = 14
"""Fenetre utilisee partout ou une primitive en demande une. Assez courte pour
que les tests restent rapides, assez longue pour que les indicateurs qui
empilent deux lissages aient de quoi travailler."""


@dataclass(frozen=True, slots=True)
class Cas:
    """Une primitive + un jeu de parametres valides. L'unite de parametrage."""

    ref: str
    params: dict[str, object]

    @property
    def primitive(self) -> Primitive:
        return get_primitive(self.ref)

    def __str__(self) -> str:
        if not self.params:
            return self.ref
        variantes = {k: v for k, v in self.params.items() if k != "window"}
        if not variantes:
            return self.ref
        return f"{self.ref}[{','.join(f'{k}={v}' for k, v in sorted(variantes.items()))}]"


def _resoudre(corps: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Deplie un `$ref` ou un `allOf` de reference vers le `$defs`."""
    if "$ref" in corps:
        return dict(defs.get(corps["$ref"].rsplit("/", 1)[-1], {}))
    tous = corps.get("allOf")
    if isinstance(tous, list) and tous and "$ref" in tous[0]:
        fusion = dict(defs.get(tous[0]["$ref"].rsplit("/", 1)[-1], {}))
        fusion.update({k: v for k, v in corps.items() if k != "allOf"})
        return fusion
    return dict(corps)


def _valeur(nom: str, corps: dict[str, Any], fenetre: int = FENETRE) -> object | None:
    """Une valeur valide pour un champ, ou `None` si on ne sait pas en produire.

    Deliberatement conservateur : mieux vaut ne pas engendrer un cas que
    d'engendrer un cas faux, qui ferait echouer un test pour une raison sans
    rapport avec ce qu'il verifie.
    """
    if "enum" in corps:
        choix = corps["enum"]
        return choix[0] if choix else None
    kind = corps.get("type")
    if kind == "integer":
        return max(int(corps.get("minimum", 1)), 2 if "window" not in nom else fenetre)
    if kind == "number":
        return float(corps.get("minimum", 2.0)) or 2.0
    if kind == "boolean":
        return False
    return None


def _enumerations(schema: dict[str, Any]) -> dict[str, list[object]]:
    """Les champs a choix fini, qu'on veut exercer EN ENTIER.

    `adx@1` avec `output=adx` et avec `output=minus_di` sont deux calculs
    differents ; n'en tester qu'un laisserait l'autre sans couverture.
    """
    defs = schema.get("$defs", {})
    sortie: dict[str, list[object]] = {}
    for nom, brut in schema.get("properties", {}).items():
        corps = _resoudre(brut, defs)
        if "enum" in corps and nom not in ("field",):
            sortie[nom] = list(corps["enum"])
    return sortie


FENETRES_DE_SECOURS = (14, 5, 3, 2, 20, 30)
"""Fenetres essayees dans l'ordre.

Une seule valeur ne suffit pas : certaines primitives contraignent leurs
parametres les uns par rapport aux autres. `adosc@1` porte une fenetre lente
qui vaut 10 par defaut et doit rester superieure a la rapide - `window=14` est
donc INVALIDE pour elle, alors qu'elle l'est pour toutes les autres.

Fixer ces defauts pour faire passer le harnais serait l'inverse de ce qu'on
veut : la contrainte est juste, c'est le harnais qui doit s'y plier.
"""


def parametres_de(ref: str) -> dict[str, object]:
    """Un jeu de parametres valides minimal pour cette primitive.

    Leve si aucune fenetre ne convient : un modele qu'on ne peut pas instancier
    est un defaut a voir, pas un cas a sauter en silence.
    """
    primitive = get_primitive(ref)
    schema = primitive.params_model.model_json_schema()
    defs = schema.get("$defs", {})
    requis = set(schema.get("required", []))

    refus: list[str] = []
    for fenetre in FENETRES_DE_SECOURS:
        valeurs: dict[str, object] = {}
        for nom, brut in schema.get("properties", {}).items():
            if nom not in requis:
                continue
            valeur = _valeur(nom, _resoudre(brut, defs), fenetre)
            if valeur is not None:
                valeurs[nom] = valeur
        try:
            primitive.parse_params(valeurs)
        except (ValueError, TypeError) as erreur:
            refus.append(f"window={fenetre} : {str(erreur).splitlines()[-1][:80]}")
            continue
        return valeurs
    raise AssertionError(
        f"aucun jeu de parametres valide trouve pour {ref}. Essais : "
        + " | ".join(refus)
    )


def tous_les_cas() -> list[Cas]:
    """Un cas par primitive, multiplie par ses champs a choix fini.

    Trie, parce que l'ordre des cas de test ne doit pas dependre de l'ordre
    d'insertion dans un dictionnaire.
    """
    cas: list[Cas] = []
    for entree in describe_registry():
        ref = str(entree["ref"])
        base = parametres_de(ref)
        schema = get_primitive(ref).params_model.model_json_schema()
        choix = _enumerations(schema)
        if not choix:
            cas.append(Cas(ref, base))
            continue
        nom, valeurs = next(iter(sorted(choix.items())))
        for valeur in valeurs:
            cas.append(Cas(ref, {**base, nom: valeur}))
    return sorted(cas, key=str)


def references() -> list[str]:
    return sorted(str(e["ref"]) for e in describe_registry())
