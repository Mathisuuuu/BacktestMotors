---
type: reference
updated: 2026-09-17
autorite: src/rsl/definitions.py
---

# `definitions` / `$ref` — ecrire une grandeur une fois

> Page **routeur**. L'autorite est
> [src/rsl/definitions.py](../../src/rsl/definitions.py) et ses tests,
> [tests/unit/test_definitions.py](../../tests/unit/test_definitions.py).
> Les chiffres ci-dessous ont ete mesures les 2026-09-16 et 2026-09-17 ; le
> module, lui, ne vieillit pas.

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

## Les exemples factorises (2026-09-17)

Quatre specifications du depot portent desormais un bloc `definitions`, et
**les onze `config_hash` archives sont inchanges** :

| Specification | lignes | definitions |
|---|---|---|
| `nq_zarattini_60_30_15` | 984 -> **491** (-50 %) | `sigma_minute`, `vwap_ancre`, `bande_haute`, `bande_basse`, `points_de_controle`, `cloture_forcee` |
| `intraday_vwap_reversion` | 731 -> **375** (-48 %) | `dispersion`, `grille_horaire`, `vwap_ancre` |
| `intraday_momentum_filtre_quotidien` | 582 -> **340** (-41 %) | `grille_horaire`, `filtre_multi`, `vwap_ancre` |
| `intraday_opening_range` | 343 -> **293** (-14 %) | `vwap_ancre` |

L'`entry_long` de Zarattini se lit maintenant en une phrase - « les points de
controle, ET la cloture au-dessus de la bande haute, ET au-dessus du VWAP » - la
ou il fallait descendre douze niveaux.

**Regle d'extraction** : seuls les sous-arbres **deja annotes** sont nommes, et
le nom vient de leur note. Une definition appelee `arith_7` serait pire que la
recopie qu'elle remplace - elle donnerait un nom a ce que personne ne sait
nommer, dans un fichier dont tout l'interet est de servir de modele.

**`_moule_universel` n'est PAS factorise**, deliberement : il existe pour
MONTRER chaque type de noeud, et le factoriser cacherait derriere des noms ce
qu'il est cense exposer - pour 3 % de lignes en moins, mesure avant de renoncer.

## Le schema publie accepte `$ref`

Defaut trouve APRES avoir factorise les exemples, et corrige : le
`signals.schema.json` publie refusait `{"$ref": "nom"}`, donc **un editeur
branche dessus aurait signale les quatre exemples du depot comme invalides**.

Le schema porte desormais une branche de plus dans son `oneOf` - « reference a
une definition » - avec `additionalProperties: false`, qui y grave la meme regle
que le socle : un `$ref` accompagne d'autres cles est refuse.

Ce n'est PAS un type de noeud. Il n'apparait ni dans `list_node_types()`, ni
dans `describe_node_types()`, et le moteur ne le voit jamais. Un test garde
l'egalite stricte : la SEULE branche etrangere admise est celle-la.

## Ce que cela ne fait pas

- **Ce n'est pas un noeud.** Il n'y a rien a evaluer, rien a memoiser, rien
  dans `describe()`. Le [[Failed Ideas/ledger]] refuse les noeuds a memoire ;
  cette forme ne pose pas la question, elle n'existe plus a l'execution.
- **Ce n'est pas un parametrage.** `{"$ref": "sigma", "window": 20}` est
  refuse. Pour faire varier une definition, en ecrire deux.
- **Rien n'OBLIGE a factoriser.** Ecrire une grandeur quatre fois reste une
  specification valide. Un controle `rsl check` qui signalerait les sous-arbres
  repetes serait le pendant naturel ; il attend la trace datee d'un cas ou deux
  copies ont reellement diverge, comme l'exige le critere d'admission de
  [[lessons]] L37.

## Voisins

- [[reference/vocabulaire-signaux]] — ce que `$ref` remplace.
- [[reference/controles]] — ce que `rsl check` voit, et qu'un schema ne voit
  pas.
- [[concepts/determinisme]] — la raison pour laquelle le hash porte sur la
  forme developpee.
