"""Ecrire une grandeur UNE fois, s'y referer partout ailleurs.

Le probleme, mesure
-------------------
Les arbres de signaux du depot sont ecrits en grande partie DEUX fois ou plus.
Mesure le 2026-09-16, en comptant les formes DISTINCTES de sous-arbre :

| Specification | noeuds | distincts | profondeur |
|---|---|---|---|
| `intraday_vwap_reversion` | 150 | **41** | 19 |
| `nq_zarattini_60_30_15` | 164 | **51** | 18 |
| `intraday_momentum_filtre_quotidien` | 113 | **40** | 14 |

Sur Zarattini, `sigma` est recopie quatre fois - trente-six lignes chacune -
et le VWAP quatre fois. Rien ne verifie que les quatre copies disent la meme
chose. Un auteur qui corrige un seuil dans trois des quatre produit une
specification **parfaitement valide** dont le sens a change sans qu'aucun
controle du socle puisse le voir : quatre sigmas legerement differents sont
quatre expressions legitimes.

C'est le defaut que ce module ferme, et il compte surtout pour un auteur
MACHINE : une IA qui engendre sept cent vingt-huit lignes de regles dont les
trois quarts sont des copies n'a aucun moyen de les garder d'accord.

La forme
--------
Un bloc `definitions` a la racine du document, et le marqueur `{"$ref": "nom"}`
partout ailleurs ::

    {
      "definitions": {
        "sigma": { ... trente-six lignes ... }
      },
      "strategy": {"params": {"rules": {
        "entry_long": {"type": "compare", "op": ">",
                       "left": {"type": "price", "field": "close"},
                       "right": {"$ref": "sigma"}}
      }}}
    }

L'orthographe est celle de JSON Schema - `definitions` et `$ref` - et ce choix
n'est pas cosmetique. C'est la seule convention de factorisation que tout
generateur de JSON a deja vue des milliers de fois, et le dollar est le seul
caractere qui ne puisse entrer en collision avec le vocabulaire : verifie le
2026-09-16, aucune cle d'aucune specification du depot ne le porte.

Ce que ce module N'EST PAS, et c'est le point
----------------------------------------------
**Une substitution textuelle, faite avant toute validation.** Le moteur ne voit
jamais un `$ref` ; il recoit l'arbre developpe, exactement celui qu'on aurait
tape a la main. Consequences, toutes voulues :

- aucun type de noeud nouveau, donc aucune surface ajoutee a `signals.py`, a la
  memoisation, au calcul de `warmup_bars`, a `describe()` ;
- **le `config_hash` porte sur la forme DEVELOPPEE.** Une specification
  factorisee et son equivalent recopie a la main sont le MEME run et ont la
  meme empreinte. C'est la propriete non negociable : sans elle, factoriser une
  specification changerait une empreinte archivee sans qu'aucune decision n'ait
  bouge ;
- le bloc `definitions` est `exclude=True` cote pydantic, donc absent de
  `model_dump`, donc absent du hachage - meme dispositif que `note`, et pour la
  meme raison ;
- rien ne change a l'execution. Deux sites qui referencent le meme nom
  produisent deux arbres INDEPENDANTS, structurellement identiques - ce que la
  memoisation dedoublonnait deja.

Le prix, qu'il faut dire
-------------------------
La factorisation est **perdue a la sortie**. Un rapport archive, un
`rsl schema --what spec`, une empreinte : tous montrent la forme developpee. On
ecrit deux cents lignes et on en relit neuf cent quatre-vingts.

C'est le bon sens de l'echange. L'inverse - hacher la forme factorisee - ferait
diverger l'empreinte de deux specifications qui donnent le meme resultat, et le
depot entier repose sur le contraire.

Ce qui est refuse
-----------------
Tout ce qui pourrait produire un resultat lisible mais faux ([[lessons]] L30) :
un nom inconnu, un cycle, un `$ref` accompagne d'autres cles, un pointeur JSON
Schema (`#/definitions/x`), et une definition **jamais utilisee** - ce dernier
cas etant precisement la copie devenue orpheline que ce module existe pour
empecher.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Final

from rsl.errors import ConfigurationError

BLOC: Final[str] = "definitions"
"""Mot RESERVE a la racine d'un document, au meme titre que `note`."""

MARQUEUR: Final[str] = "$ref"
"""Mot RESERVE comme CLE, a toute profondeur."""

PLAFOND: Final[int] = 50_000
"""Nombre maximal de valeurs dans la forme developpee.

Une definition qui en reference une autre plusieurs fois grandit de facon
MULTIPLICATIVE : dix definitions citant chacune deux fois la precedente font
mille vingt-quatre copies de la premiere. Le plafond borne l'explosion au lieu
de laisser la machine ramer sur un document de quelques lignes.

Repere : la plus grosse specification du depot, `nq_zarattini_60_30_15`,
developpee, porte moins de deux mille valeurs.
"""


def expanser(document: Mapping[str, Any]) -> dict[str, Any]:
    """Rend le document avec chaque `{"$ref": "nom"}` remplace par sa valeur.

    Appelee AVANT la validation pydantic, donc avant que quoi que ce soit du
    document ne soit type : c'est ce qui permet aux definitions de servir
    partout, y compris dans `risk.sizing.signal`, et non seulement dans la
    region libre `strategy.params.rules`.

    Un document sans `definitions` et sans `$ref` la traverse inchange, la
    copie mise a part.

    Ne traite QUE des documents : les deux validateurs qui l'appellent laissent
    passer tout le reste a pydantic, qui dira bien mieux que nous ce qui ne va
    pas dans un document qui n'est pas un objet.
    """
    definitions = _lire_le_bloc(document.get(BLOC))
    resolues: dict[str, Any] = {}
    tailles: dict[str, int] = {}
    produit = [0]

    def compter(combien: int) -> None:
        """Borne la taille PRODUITE, et non le travail fourni.

        La distinction n'est pas theorique : une premiere version comptait les
        appels d'expansion, qui sont memoises. Une cascade de quinze
        definitions citant chacune deux fois la precedente faisait trente-deux
        mille copies de la premiere en seize appels - le plafond ne voyait donc
        rien, et un plafond qui ne plafonne pas est pire qu'aucun ([[lessons]]
        L30). C'est la taille des valeurs RECOPIEES qu'il faut sommer.
        """
        produit[0] += combien
        if produit[0] > PLAFOND:
            raise ConfigurationError(
                f"`{BLOC}` : la forme developpee depasse {PLAFOND} valeurs. Des "
                f"definitions qui s'appellent en cascade grandissent de facon "
                f"multiplicative ; verifiez qu'aucune n'est citee plusieurs "
                f"fois par plusieurs autres."
            )

    def resoudre(nom: str, pile: tuple[str, ...]) -> Any:
        if nom in resolues:
            return resolues[nom]
        if nom in pile:
            chaine = " -> ".join([*pile, nom])
            raise ConfigurationError(
                f"`{BLOC}` : cycle {chaine}. Une definition qui se reference, "
                f"directement ou non, n'a pas de forme developpee."
            )
        if nom not in definitions:
            raise ConfigurationError(
                f'`{MARQUEUR}: "{nom}"` ne designe aucune definition. '
                f"{_connues(definitions)}"
            )
        valeur = _remplacer(definitions[nom], (*pile, nom))
        resolues[nom] = valeur
        tailles[nom] = _taille(valeur)
        return valeur

    def _remplacer(valeur: Any, pile: tuple[str, ...]) -> Any:
        compter(1)
        if isinstance(valeur, dict):
            if MARQUEUR in valeur:
                nom = _nom_du_marqueur(valeur)
                resolu = resoudre(nom, pile)
                compter(tailles[nom])
                return copy.deepcopy(resolu)
            return {cle: _remplacer(v, pile) for cle, v in valeur.items()}
        if isinstance(valeur, list):
            return [_remplacer(v, pile) for v in valeur]
        return valeur

    corps = {cle: valeur for cle, valeur in document.items() if cle != BLOC}

    # L'expansion D'ABORD : elle refuse les marqueurs mal ecrits. Compter les
    # usages sur un document non valide designerait comme morte une definition
    # referencee par un marqueur que la ligne suivante allait rejeter.
    developpe = _remplacer(corps, ())
    assert isinstance(developpe, dict)

    _refuser_les_inutilisees(definitions, _atteintes(definitions, _noms_cites(corps)))

    if definitions:
        developpe[BLOC] = copy.deepcopy(dict(definitions))
    return developpe


def _lire_le_bloc(brut: object) -> dict[str, Any]:
    """Valide la forme du bloc avant de s'en servir.

    Un bloc ABSENT et un bloc VIDE sont traites pareil, et ni l'un ni l'autre
    n'est refuse : c'est le traitement deja retenu pour un `risk.limits`
    entierement nul, ou l'absence et le bloc muet disent la meme chose.
    """
    if brut is None:
        return {}
    if not isinstance(brut, dict):
        raise ConfigurationError(
            f'`{BLOC}` doit etre un objet de la forme {{"nom": <valeur>}}, '
            f"recu {type(brut).__name__}."
        )
    for nom in brut:
        if not isinstance(nom, str) or not nom.strip():
            raise ConfigurationError(f"`{BLOC}` : nom de definition vide ou invalide ({nom!r}).")
    return dict(brut)


def _nom_du_marqueur(valeur: Mapping[str, Any]) -> str:
    """Extrait le nom, en refusant les trois facons de l'ecrire de travers."""
    if len(valeur) != 1:
        autres = sorted(cle for cle in valeur if cle != MARQUEUR)
        raise ConfigurationError(
            f"`{MARQUEUR}` doit etre SEUL dans son objet ; trouve aussi {autres}. "
            f"Ces cles seraient silencieusement perdues, la definition "
            f"remplacant l'objet entier. Pour faire varier une definition, en "
            f"ecrire deux."
        )
    nom = valeur[MARQUEUR]
    if not isinstance(nom, str) or not nom.strip():
        raise ConfigurationError(f"`{MARQUEUR}` attend un nom de definition, recu {nom!r}.")
    if nom.startswith("#"):
        propre = nom.rsplit("/", 1)[-1]
        raise ConfigurationError(
            f'`{MARQUEUR}: "{nom}"` est un pointeur JSON Schema. Ici on ecrit '
            f'le NOM seul : {{"{MARQUEUR}": "{propre}"}}.'
        )
    return nom


def _atteintes(definitions: Mapping[str, Any], directs: list[str]) -> set[str]:
    """Fermeture transitive des noms cites depuis le CORPS du document.

    Une definition citee uniquement par une autre qui n'est elle-meme jamais
    referencee reste morte : c'est bien depuis le corps que l'usage se compte,
    pas depuis le bloc.
    """
    utilisees: set[str] = set()
    a_voir = list(directs)
    while a_voir:
        nom = a_voir.pop()
        if nom in utilisees:
            continue
        utilisees.add(nom)
        a_voir.extend(_noms_cites(definitions.get(nom)))
    return utilisees


def _taille(valeur: object) -> int:
    """Nombre de valeurs d'une structure, toutes profondeurs confondues."""
    if isinstance(valeur, dict):
        return 1 + sum(_taille(v) for v in valeur.values())
    if isinstance(valeur, list):
        return 1 + sum(_taille(v) for v in valeur)
    return 1


def _noms_cites(valeur: object) -> list[str]:
    if isinstance(valeur, dict):
        cible = valeur.get(MARQUEUR)
        if isinstance(cible, str):
            return [cible]
        return [nom for v in valeur.values() for nom in _noms_cites(v)]
    if isinstance(valeur, list):
        return [nom for v in valeur for nom in _noms_cites(v)]
    return []


def _refuser_les_inutilisees(definitions: Mapping[str, Any], utilisees: set[str]) -> None:
    """Une definition morte est le defaut que ce module existe pour empecher.

    Le cas concret : on factorise `sigma`, puis on renomme le point d'appel en
    `sigma_60` sans supprimer l'ancien. Les deux coexistent, l'un sert, l'autre
    derive - et c'est exactement la divergence silencieuse entre copies.
    """
    mortes = sorted(set(definitions) - utilisees)
    if mortes:
        raise ConfigurationError(
            f"`{BLOC}` : {mortes} n'est jamais reference. Une definition morte "
            f"derive sans que rien ne le voie - c'est le defaut que le bloc sert "
            f"a empecher. La supprimer, ou l'utiliser."
        )


def _connues(definitions: Mapping[str, Any]) -> str:
    if not definitions:
        return f"Aucun bloc `{BLOC}` n'est declare a la racine du document."
    return f"Definitions declarees : {sorted(definitions)}."


__all__ = ["BLOC", "MARQUEUR", "PLAFOND", "expanser"]
