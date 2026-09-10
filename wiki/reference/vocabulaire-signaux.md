---
type: reference
updated: 2026-09-10
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
| Ou sont les moules de strategie descriptibles ? | [rules.py](../../src/rsl/strategies/rules.py) · [ranking.py](../../src/rsl/strategies/ranking.py) |
| Ou branchera le futur compilateur de specifications ? | [src/rsl/pipeline.py](../../src/rsl/pipeline.py) — decrit, sans implementation |

## Exemples executables

| Fichier | Ce qu'il montre |
|---|---|
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
