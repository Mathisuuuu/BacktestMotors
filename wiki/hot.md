---
type: hub
updated: 2026-09-10
generated: true
---

# hot — etat courant

> [!WARNING] FICHIER AUTO-GENERE — NE PAS EDITER A LA MAIN
> Produit par [`wiki/update_hot.py`](update_hot.py), relance par le hook
> `Stop` a chaque fin de session. Toute modification hors du bloc
> **Next Actions** sera ecrasee sans avertissement.
> Derniere generation : 2026-09-10.

## Current State

| Indicateur | Valeur |
|---|---|
| Pages de wiki | 19 |
| Entrees de log | 6 |
| Derniere activite | 2026-09-10 |
| Idees ecartees (ledger) | 7 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 2 |
| Pages `reference/` | 5 |
| Pages `research/` | 1 |

**Activite par type :** note × 3, setup × 1, fix × 1, lint × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 6 entree(s)

- **2026-09-10** — note | audit « quels sont les problemes a regler » : etendue de la casse rsl.data mesuree, recuperation locale cherchee | 6 modules / 42 symboles perdus, aucune copie sur la machine, ~128 tests specificateurs intacts ; 3 problemes classes P1-P3
- **2026-09-10** — note | correction de l'entree `note` ci-dessus (log append-only : on corrige par ajout) | le bon compte est 5 routeurs et 15 pages de contenu, pas 4 et 13
- **2026-09-10** — lint | premier passage : 20 pages, wikilinks et liens relatifs verifies | 0 orpheline, 1 lien mort reel (rsl.data) annote, placeholders de gabarits exclus
- **2026-09-10** — fix | decouverte en verifiant les liens : `.gitignore:1` `data/` attrape aussi `src/rsl/data/` | paquet `rsl.data` jamais commite et absent du disque, `import rsl.data` leve ; signale, non corrige
- **2026-09-10** — note | amorcage : 6 concepts, 4 routeurs, 2 experiences, 1 source a ingerer, 7 idees au ledger | tout tire du depot existant, aucune connaissance inventee
- **2026-09-10** — setup | mise en place du wiki LLM (hubs, contenu, schema, hooks, Obsidian) | 5 hubs + 13 pages, generateur hot.md, hooks PowerShell, groupes de couleurs Obsidian

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

- [ ] **P1 bloquant** -- couche `rsl.data` absente (6 modules, 42 symboles).
      Cause : `.gitignore:1` `data/` non ancre. Aucune copie locale retrouvee.
      Ordre : (a) chercher sur une autre machine / sauvegarde / historique local
      de l'IDE ; (b) a defaut, reconstruire en TDD -- les ~128 tests qui
      specifient ces modules ont survecu ; (c) ancrer le motif en `/data/`.
- [ ] **P2** -- environnement non installe : ni venv, ni polars/pydantic/
      hypothesis/ruff/mypy. `pytest` ne collecte meme pas. Creer un venv en
      3.11/3.12 (le python global est en 3.14) avant toute verification.
- [ ] **P3** -- `docs/` porte encore « decisions de design, avant
      implementation » et 4 points `[A ARBITRER]` ouverts, alors que le README
      donne tout pour fait. Dans un depot ou `docs/` est normatif, trancher :
      soit les decisions sont prises et les docs mentent, soit le code a
      tranche implicitement.
- [ ] Relancer les deux experiences seminales une fois P1 et P2 leves, avec
      manifeste et empreinte archives.
- [ ] Obtenir et ingerer la source du Deflated Sharpe (independance des essais).
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
