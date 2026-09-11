"""Squelette a trous : le vocabulaire presente comme un formulaire a remplir.

`rsl schema` publie un JSON Schema - exact, verbeux, fait pour valider. Ce
module publie autre chose, fait pour **ecrire** : chaque emplacement d'une
specification y est decrit par ce qu'on a le droit d'y mettre. Un lecteur qui
n'aurait que ce fichier doit pouvoir produire une specification valide sans
rien connaitre d'autre du depot.

Il est **engendre** depuis les registres, jamais saisi a la main. C'est la
meme regle que pour les schemas (voir `lessons` L4) et elle a la meme raison :
une liste de choix recopiee devient fausse au premier noeud ajoute, et une
liste de choix fausse est pire qu'absente - un lecteur lui fait confiance.

Vocabulaire des descripteurs, volontairement court :

| Cle | Sens |
|---|---|
| `type` | `entier`, `nombre`, `texte`, `booleen`, `liste`, `objet`, `noeud` |
| `choix` | les seules valeurs acceptees |
| `defaut` | valeur prise si la cle est absente |
| `requis` | la cle doit etre presente |
| `min` | borne inferieure |
| `element` | pour une `liste` : la forme de chaque element |
| `champs` | pour un `objet` : ses cles |

`noeud` est le type recursif : tout emplacement qui le porte accepte
n'importe quel objet du catalogue `noeuds`, lui-meme pouvant en contenir
d'autres. C'est la seule recursion du format.
"""

from __future__ import annotations

from typing import Any

from rsl.config import BacktestSpec
from rsl.data.instruments import known_roots
from rsl.primitives.registry import describe_registry
from rsl.strategies.base import describe_strategies
from rsl.strategies.rules import RuleStrategy
from rsl.strategies.signals import const, describe_node_types

SpecDict = dict[str, Any]

FORMAT = "rsl-squelette@1"

TYPES = {
    "integer": "entier",
    "number": "nombre",
    "string": "texte",
    "boolean": "booleen",
    "array": "liste",
    "object": "objet",
    "null": "nul",
}

MODE_D_EMPLOI = [
    "Ce fichier decrit CE QU'ON PEUT ECRIRE, pas un backtest. Pour en produire un,",
    "recopier la forme de `specification` en remplacant chaque descripteur par une",
    "valeur prise dans son `choix`, ou conforme a son `type`.",
    "",
    "Un descripteur est un objet portant une cle `type`. Il n'apparait jamais dans",
    "une specification finale : il indique quoi mettre a sa place.",
    "",
    "Une cle `requis: true` doit etre presente. Une cle qui porte un `defaut` peut",
    "etre omise ; elle vaudra ce defaut.",
    "",
    "Le type `noeud` est recursif : y ecrire n'importe quel objet du catalogue",
    "`noeuds`, choisi par sa cle `type`. Un noeud contient souvent d'autres noeuds.",
    "C'est de cette recursion que vient toute l'expressivite du vocabulaire.",
    "",
    "Les seules feuilles d'un arbre de noeuds - celles qui n'en contiennent pas",
    "d'autres - sont `constant`, `price`, `time`, `position` et `primitive`.",
    "Un arbre qui ne se termine pas par des feuilles est invalide.",
    "",
    "`primitive` prend une `ref` du catalogue `primitives` et ses `params`. Elle ne",
    "lit QUE des champs de prix : pour appliquer un calcul a une expression",
    "quelconque, utiliser le noeud `rolling`.",
    "",
    "Toute erreur est refusee, jamais ignoree : cle inconnue, valeur hors `choix`,",
    "`ref` inexistante. La commande rend alors le code de sortie 1 et nomme ce",
    "qu'elle attendait.",
]

CONTRAINTES = [
    "Un meme instrument ne peut apparaitre qu'une fois dans `data` : deux",
    "granularites du meme symbole sont refusees ('X apparait deux fois').",
    "",
    "`path` doit etre RELATIF a la racine declaree par la variable d'environnement",
    "RSL_DATA_DIR (ou un fichier `.env`). Un chemin absolu fonctionne mais n'est",
    "pas portable, et fait diverger le `config_hash` entre deux machines.",
    "",
    "`root` doit figurer dans la liste `instruments` : c'est elle qui determine",
    "multiplicateur, tick et frais.",
    "",
    "Pour `macd@1`, `fast` doit etre strictement inferieur a `slow`.",
    "",
    "Pour le noeud `rolling`, les statistiques `stdev`, `zscore`, `var` et `slope`",
    "exigent `window >= 2` : une observation unique n'a ni dispersion ni pente.",
    "",
    "Les fenetres sont en NOMBRE DE BARRES, jamais en duree. Sur des donnees",
    "minute trouees, `window: 60` ne fait pas une heure.",
    "",
    "`lag_bars` vaut au minimum 1 : une execution sur la barre qui a produit le",
    "signal serait du look-ahead, et le moteur la refuse.",
    "",
    "Les strategies marquees `cross_sectional: true` ignorent `symbol` et",
    "travaillent sur tout l'univers declare dans `data`.",
]


def _objet(valeur: object) -> SpecDict:
    """Retrecit un `object` de catalogue en dictionnaire, en le verifiant."""
    if not isinstance(valeur, dict):
        raise TypeError(f"objet attendu, recu {type(valeur).__name__}")
    return dict(valeur)


def _slot(schema: SpecDict, defs: SpecDict, *, requis: bool) -> SpecDict:
    """Reduit une propriete de JSON Schema a un descripteur lisible."""
    resolu = _resoudre(schema, defs)
    descripteur: SpecDict = {}

    if "const" in resolu:
        descripteur["type"] = "texte"
        descripteur["impose"] = resolu["const"]
        return descripteur

    if "enum" in resolu:
        descripteur["type"] = "choix"
        descripteur["choix"] = list(resolu["enum"])
    elif resolu.get("type") == "array":
        descripteur["type"] = "liste"
        element = resolu.get("items")
        if isinstance(element, dict):
            descripteur["element"] = _slot(element, defs, requis=True)
    elif resolu.get("type") == "object" and "properties" in resolu:
        descripteur["type"] = "objet"
        descripteur["champs"] = _champs(resolu, defs)
    else:
        descripteur["type"] = TYPES.get(str(resolu.get("type")), "quelconque")

    for source, cible in (("minimum", "min"), ("exclusiveMinimum", "min_exclu"),
                          ("maximum", "max")):
        if source in resolu:
            descripteur[cible] = resolu[source]
    if "default" in schema:
        descripteur["defaut"] = schema["default"]
    elif "default" in resolu:
        descripteur["defaut"] = resolu["default"]
    if requis:
        descripteur["requis"] = True
    if resolu.get("nullable"):
        descripteur["accepte_null"] = True
    return descripteur


def _resoudre(schema: SpecDict, defs: SpecDict) -> SpecDict:
    """Suit les `$ref` et aplatit les `anyOf` de la forme `X | None`."""
    courant = dict(schema)
    if "$ref" in courant:
        nom = str(courant.pop("$ref")).rsplit("/", 1)[-1]
        cible = dict(defs.get(nom, {}))
        cible.update(courant)
        return _resoudre(cible, defs)

    variantes = courant.get("anyOf")
    if isinstance(variantes, list):
        utiles = [v for v in variantes if isinstance(v, dict) and v.get("type") != "null"]
        nullable = len(utiles) != len(variantes)
        if len(utiles) == 1:
            resolu = _resoudre(utiles[0], defs)
            resolu = {**resolu, **{k: v for k, v in courant.items() if k != "anyOf"}}
            if nullable:
                resolu["nullable"] = True
            return resolu
    return courant


def _champs(schema: SpecDict, defs: SpecDict) -> SpecDict:
    requis = set(schema.get("required", []))
    proprietes = schema.get("properties", {})
    return {
        nom: _slot(corps, defs, requis=nom in requis)
        for nom, corps in proprietes.items()
        if isinstance(corps, dict)
    }


def _depuis_modele(schema: SpecDict) -> SpecDict:
    defs = schema.get("$defs", {})
    return _champs(schema, defs)


def build_skeleton() -> SpecDict:
    """Document complet, engendre depuis les registres."""
    document = _assembler()
    _croiser(document)
    return document


def _croiser(document: SpecDict) -> None:
    """Remplace trois emplacements textuels par la liste de leurs valeurs.

    `root`, `strategy.ref` et `primitive.ref` sont typees `str` cote pydantic :
    leur validite est verifiee a l'execution contre un registre, pas par le
    type. Le squelette, lui, sert a ECRIRE - laisser "texte" a ces trois
    endroits obligerait le lecteur a deviner, alors que les valeurs sont
    enumerables. Elles sont recopiees depuis les catalogues du meme document,
    donc jamais desynchronisees.
    """
    source = document["data"] if "data" in document else document["specification"]["data"]
    racine = source["element"]["champs"]["root"]
    racine["type"] = "choix"
    racine["choix"] = list(document["instruments"])

    reference = document["specification"]["strategy"]["champs"]["ref"]
    reference["type"] = "choix"
    reference["choix"] = list(document["strategies"])
    reference["note"] = "les `params` attendus dependent de la strategie choisie"

    primitive = document["noeuds"]["primitive"]["champs"]["ref"]
    primitive["type"] = "choix"
    primitive["choix"] = list(document["primitives"])
    primitive["note"] = "les `params` attendus dependent de la primitive choisie"


def _assembler() -> SpecDict:
    return {
        "format": FORMAT,
        "engendre_par": "rsl squelette",
        "mode_d_emploi": MODE_D_EMPLOI,
        "contraintes": CONTRAINTES,
        "specification": _depuis_modele(BacktestSpec.model_json_schema()),
        "instruments": sorted(known_roots()),
        "cles_de_rules": _cles_de_rules(),
        "strategies": {
            str(entree["ref"]): {
                "resume": entree["summary"],
                "transversale": entree["cross_sectional"],
                "params": _depuis_modele(_objet(entree["params"])),
            }
            for entree in describe_strategies()
        },
        "noeuds": {
            str(entree["type"]): {
                "resume": entree["summary"],
                "champs": _champs_de_noeud(_objet(entree["schema"])),
            }
            for entree in describe_node_types()
        },
        "primitives": {
            str(entree["ref"]): {
                "resume": entree["summary"],
                "params": _depuis_modele(_objet(entree["params"])),
            }
            for entree in describe_registry()
        },
    }


def _cles_de_rules() -> list[str]:
    """Les cles acceptees par , DERIVEES et non recopiees.

     les enumere dans son  ; les relister ici en
    ferait une quatrieme copie, donc une quatrieme occasion de diverger.
    """
    # Une entree est exigee a la construction - une strategie sans entree ne
    # peut rien faire, et le moteur le refuse. On en fournit une factice : seule
    # la LISTE des cles nous interesse, pas leur contenu.
    temoin = RuleStrategy(symbol="X", quantity=1, entry_long=const(1.0))
    regles = temoin.describe()["rules"]
    assert isinstance(regles, dict)
    return list(regles)


def _champs_de_noeud(schema: SpecDict) -> SpecDict:
    """Champs d'un noeud, `type` et `version` retires.

    `type` est impose par le nom sous lequel le noeud est range, et `version`
    est facultative partout : les repeter dans chaque entree ajouterait du
    bruit a un document qui sert justement a y voir clair.
    """
    defs = schema.get("$defs", {})
    requis = set(schema.get("required", []))
    sortie: SpecDict = {}
    for nom, corps in schema.get("properties", {}).items():
        if nom in ("type", "version") or not isinstance(corps, dict):
            continue
        if corps.get("$ref", "").endswith("/node"):
            sortie[nom] = {"type": "noeud", "requis": nom in requis}
            continue
        if corps.get("type") == "array" and str(
            corps.get("items", {}).get("$ref", "")
        ).endswith("/node"):
            sortie[nom] = {
                "type": "liste",
                "element": {"type": "noeud"},
                "min_elements": corps.get("minItems", 1),
                "requis": nom in requis,
            }
            continue
        sortie[nom] = _slot(corps, defs, requis=nom in requis)
    return sortie
