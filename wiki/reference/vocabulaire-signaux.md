---
type: reference
updated: 2026-09-11
autorite: schemas/signals.schema.json (engendre, ne pas editer a la main)
---

# Vocabulaire des signaux — routeur

> Page routeur. L'autorite est le **schema engendre**, pas ce tableau.
> `rsl schema` le produit depuis les registres ; les fichiers de `schemas/` sont
> compares au registre a chaque execution des tests, donc ils ne peuvent pas
> rouiller.

| Question | Reponse faisant autorite |
|---|---|
| Quels types de noeuds existent, avec quels champs ? | [schemas/signals.schema.json](../../schemas/signals.schema.json) — `$defs/node` enumere les types enregistres |
| Quelle est la forme d'une specification complete ? | [schemas/rsl.schema.json](../../schemas/rsl.schema.json) |
| Quelles primitives, quels noeuds, quelles strategies sont enregistres **maintenant** ? | `rsl catalogue` |
| Comment regenerer les schemas ? | `rsl schema --out schemas/signals.schema.json` |
| Comment un arbre est-il reconstruit depuis du JSON ? | `build_signal(spec)` dans [src/rsl/strategies/signals.py](../../src/rsl/strategies/signals.py) |
| Que peut-on mettre dans CHAQUE emplacement ? | [schemas/squelette.json](../../schemas/squelette.json) — engendre par `rsl squelette`. Chaque trou y est decrit par ses valeurs acceptees |
| Par quoi commencer pour ecrire une strategie ? | [examples/_moule.json](../../examples/_moule.json), a copier puis editer |
| A quoi ressemble CHAQUE type de noeud en JSON ? | [examples/_moule_universel.json](../../examples/_moule_universel.json) — les 20, dans un fichier qui tourne |
| Comment lire une grandeur de SEANCE ? | `session` et `cumulative` — exigent un calendrier declare, voir [[reference/seances]] |
| Comment lisser une EXPRESSION (pas un champ de prix) ? | `rolling` avec `stat: "ema"`. `primitive` est une feuille : elle ne lit que des champs de prix |
| Wilder ou moyenne simple ? | `atr@1` / `rsi@1` sont des moyennes ARITHMETIQUES ; `atr_wilder@1` / `rsi_wilder@1` sont les variantes de Wilder. Des noms distincts, jamais des versions — voir [[lessons]] L10 |
| Ou sont les moules de strategie descriptibles ? | [rules.py](../../src/rsl/strategies/rules.py) · [ranking.py](../../src/rsl/strategies/ranking.py) |
| Ou branchera le futur compilateur de specifications ? | [src/rsl/pipeline.py](../../src/rsl/pipeline.py) — decrit, sans implementation |

## Ou passe la frontiere du « sans code »

Mesure du 2026-09-11, et pas une impression : le vocabulaire sait desormais
**reconstruire une de ses propres primitives**. Un `rsi@1` recompose avec les
seuls noeuds (`arith`, `lag`, `max_of`, `math`, `rolling`) rend des valeurs
identiques a la primitive sur 240 points, ecart maximum `0.00e+00`. Ce qui
suit de plus important : la meme composition s'applique a une EXPRESSION, donc
le RSI d'un spread ES/NQ s'ecrit, alors qu'aucune primitive ne le calcule.

Ce qui reste hors de portee sans Python, et pourquoi :

| Mur | Nature |
|---|---|
| Deux granularites du MEME symbole | structurel : `'X apparait deux fois'`. Contourne pour le cas quotidien-sur-intraday par `session` |
| Taille fonction d'un signal | `sizing` est un enum, pas une expression. `contracts` attend un entier |
| Optimisation de parametres | hors perimetre declare du runner ([[Failed Ideas/ledger]]) |
| Noeud a memoire entre barres | ecarte deliberement : casserait la reproductibilite bit-a-bit |
| Primitive vraiment nouvelle | ~30 lignes de Python et un enregistrement `@1` |

Astuce utile : `rolling` n'offre que l'EMA (`alpha = 2/(w+1)`), pas le lissage
de Wilder (`alpha = 1/n`). Les deux coincident pour `w = 2n - 1` - l'amorce
differe, les series convergent.

## Trois documents, trois usages

| Document | Sert a | Engendre ? |
|---|---|---|
| [schemas/squelette.json](../../schemas/squelette.json) | **ecrire** : chaque emplacement avec ses valeurs acceptees, les 10 instruments, les 22 primitives, les 20 noeuds, les 6 strategies | oui, `rsl squelette` |
| [schemas/signals.schema.json](../../schemas/signals.schema.json) | **valider** : JSON Schema exact | oui, `rsl schema` |
| [examples/_moule_universel.json](../../examples/_moule_universel.json) | **imiter** : un fichier qui tourne et exerce les 20 noeuds | non, teste |

Le squelette est en **ASCII pur** et se redirige donc sans risque (`rsl schema`
en sortie standard, lui, sort en CP1252 sur Windows).

Suffisance verifiee : un lecteur qui n'a QUE le squelette peut en tirer une
specification valide - trois tests de `tests/unit/test_skeleton.py` construisent
une specification, chaque type de noeud et chaque primitive a partir du seul
document.

## Exemples executables

| Fichier | Ce qu'il montre |
|---|---|
| [examples/_moule_universel.json](../../examples/_moule_universel.json) | **la reference exhaustive** : les **20** types de noeuds, long ET short, stop adaptatif, objectif borne. Un test echoue si un type de noeud enregistre n'y figure pas |
| [examples/_moule.json](../../examples/_moule.json) | **le gabarit de demarrage**, plus court : tous les blocs d'une specification et une strategie `rules@1` complete. Tourne tel quel |
| [examples/sma_es_daily.json](../../examples/sma_es_daily.json) | croisement de moyennes, mono-instrument |
| [examples/retour_moyenne_dans_tendance.json](../../examples/retour_moyenne_dans_tendance.json) | `rules@1` — strategie ecrite nulle part dans le code |
| [examples/paire_es_nq.json](../../examples/paire_es_nq.json) | `peer` + `rolling` — paire ES/NQ sur donnees reelles |
| [examples/momentum_12_1_mensuel.json](../../examples/momentum_12_1_mensuel.json) | transversal, classement |

## A savoir avant d'etendre

- `peer` et `rolling` vont ensemble : acces a un autre instrument au meme
  instant, et elevation de n'importe quelle expression en statistique glissante.
  L'un sans l'autre ne sert a rien.
- `rolling` a un **cout assume** : il reevalue son sous-arbre `window` fois par
  barre. Voir les idees en attente du [[Failed Ideas/ledger]].
- Ajouter un type de noeud **sans regenerer les schemas** fait echouer la suite
  de tests, avec la commande a lancer.

## Liens wiki

[[concepts/registre-versionne]] · [[reference/cli]] ·
[[Failed Ideas/ledger]]
