---
type: reference
updated: 2026-09-16
autorite: src/rsl/definitions.py
---

# `definitions` / `$ref` — ecrire une grandeur une fois

> Page **routeur**. L'autorite est
> [src/rsl/definitions.py](../../src/rsl/definitions.py) et ses tests,
> [tests/unit/test_definitions.py](../../tests/unit/test_definitions.py).
> Les chiffres ci-dessous datent du 2026-09-16 ; le module, lui, ne vieillit
> pas.

| Question | Reponse faisant autorite |
|---|---|
| Que fait la substitution | [definitions.py](../../src/rsl/definitions.py), en-tete du module |
| Ce qui est refuse, et pourquoi | `TestLesCinqRefus` dans [test_definitions.py](../../tests/unit/test_definitions.py) |
| Pourquoi le hash ne bouge pas | `BacktestSpec.definitions` dans [config.py](../../src/rsl/config.py), champ `exclude=True` |
| Comment l'ecrire | `mode_d_emploi` et `contraintes` de [schemas/squelette.json](../../schemas/squelette.json) |

## Le defaut qu'elle ferme

Les arbres de signaux du depot etaient ecrits en grande partie deux fois ou
plus. Mesure sur les formes **distinctes** de sous-arbre :

| Specification | noeuds | distincts | profondeur |
|---|---|---|---|
| `intraday_vwap_reversion` | 150 | **41** | 19 |
| `nq_zarattini_60_30_15` | 164 | **51** | 18 |
| `intraday_momentum_filtre_quotidien` | 113 | **40** | 14 |

Sur Zarattini, `sigma` est recopie quatre fois - trente-six lignes chacune -
et le VWAP quatre fois. **Rien ne verifiait que les quatre copies disaient la
meme chose** : quatre sigmas legerement differents forment une specification
parfaitement valide, que ni `extra="forbid"` ni [[reference/controles]] ne
peuvent distinguer d'une intention.

Le defaut compte surtout pour un auteur MACHINE, qui est la direction du
depot : une IA qui engendre sept cent vingt-huit lignes de regles dont les
trois quarts sont des copies n'a aucun moyen de les garder d'accord.

## La propriete qui rend la chose gratuite

**Le `config_hash` ne bouge pas.** La substitution est textuelle et precede
toute validation ; c'est la forme DEVELOPPEE qui est hachee, et le bloc est
`exclude=True` comme `note`.

Mesure sur la plus grosse specification du depot, factorisee automatiquement
en cinq definitions sans chevauchement :

```
lignes       984 -> 546   (-44 %)
config_hash  61b318a98ce9862d... -> 61b318a98ce9862d...   IDENTIQUE
```

Sans cette propriete, factoriser une specification archivee l'aurait rendue
incomparable a elle-meme - le meme piege que
`_sans_plafonds_muets` evite pour un bloc `risk.limits` muet.

Corollaire : le moteur ne voit **jamais** un `$ref`. Aucun type de noeud
nouveau, aucun changement a `warmup_bars`, a la memoisation ni a `describe()`.

## Ce qui est perdu, et qu'il faut savoir

La factorisation **ne survit pas a la sortie**. Un rapport archive, un
`rsl schema --what spec`, une empreinte : tous montrent la forme developpee.
On ecrit deux cents lignes et on en relit neuf cent quatre-vingts.

L'echange est dans le bon sens. Hacher la forme factorisee ferait diverger
l'empreinte de deux specifications qui donnent le meme resultat, et le depot
entier repose sur le contraire ([[concepts/determinisme]]).

## Les cinq refus

Chacun evite une specification qui tournerait en disant autre chose que ce
qu'on croyait - la famille [[lessons]] L30.

| Ecriture | Pourquoi elle est refusee |
|---|---|
| nom inconnu | l'erreur nomme les definitions declarees |
| cycle, direct ou indirect | une definition qui se reference n'a pas de forme developpee |
| `$ref` avec d'autres cles | elles seraient perdues en silence, la valeur remplacant l'objet entier |
| `#/definitions/x` | pointeur JSON Schema ; le refus nomme la forme attendue |
| definition jamais referencee | **c'est la copie orpheline que le bloc sert a empecher** |

Le dernier merite son mot : on factorise `sigma`, on renomme le point d'appel
en `sigma_60`, l'ancien reste et derive. L'usage se compte depuis le CORPS du
document, jamais depuis le bloc - deux definitions qui se citent l'une l'autre
sans etre appelees sont mortes toutes les deux.

### Un plafond qui ne plafonnait rien

La premiere version bornait le nombre d'appels d'expansion. Ils sont memoises.
Une cascade de quinze definitions citant chacune deux fois la precedente
produisait trente-deux mille copies en **seize appels** : le plafond ne voyait
rien. Corrige en sommant la taille des valeurs RECOPIEES. Un plafond qui ne
plafonne pas est pire qu'aucun - il donne un chiffre lisible et faux.

## Ce que cela ne fait pas

- **Ce n'est pas un noeud.** Il n'y a rien a evaluer, rien a memoiser, rien
  dans `describe()`. Le [[Failed Ideas/ledger]] refuse les noeuds a memoire ;
  cette forme ne pose pas la question, elle n'existe plus a l'execution.
- **Ce n'est pas un parametrage.** `{"$ref": "sigma", "window": 20}` est
  refuse. Pour faire varier une definition, en ecrire deux.
- **Aucun exemple du depot n'est encore factorise.** Les onze empreintes
  archivees portent les formes recopiees. Les reecrire est un chantier
  separe, et sans risque puisque le hash ne bouge pas.

## Voisins

- [[reference/vocabulaire-signaux]] — ce que `$ref` remplace.
- [[reference/controles]] — ce que `rsl check` voit, et qu'un schema ne voit
  pas.
- [[concepts/determinisme]] — la raison pour laquelle le hash porte sur la
  forme developpee.
