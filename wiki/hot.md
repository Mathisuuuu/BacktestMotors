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
| Entrees de log | 5 |
| Derniere activite | 2026-09-10 |
| Idees ecartees (ledger) | 7 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 2 |
| Pages `reference/` | 5 |
| Pages `research/` | 1 |

**Activite par type :** note × 2, setup × 1, fix × 1, lint × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 5 entree(s)

- **2026-09-10** — note | correction de l'entree `note` ci-dessus (log append-only : on corrige par ajout) | le bon compte est 5 routeurs et 15 pages de contenu, pas 4 et 13
- **2026-09-10** — lint | premier passage : 20 pages, wikilinks et liens relatifs verifies | 0 orpheline, 1 lien mort reel (rsl.data) annote, placeholders de gabarits exclus
- **2026-09-10** — fix | decouverte en verifiant les liens : `.gitignore:1` `data/` attrape aussi `src/rsl/data/` | paquet `rsl.data` jamais commite et absent du disque, `import rsl.data` leve ; signale, non corrige
- **2026-09-10** — note | amorcage : 6 concepts, 4 routeurs, 2 experiences, 1 source a ingerer, 7 idees au ledger | tout tire du depot existant, aucune connaissance inventee
- **2026-09-10** — setup | mise en place du wiki LLM (hubs, contenu, schema, hooks, Obsidian) | 5 hubs + 13 pages, generateur hot.md, hooks PowerShell, groupes de couleurs Obsidian

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

- [ ] **Bloquant** — `src/rsl/data/` est ignore par `.gitignore:1` (`data/`
      attrape tous les repertoires `data` a toute profondeur). Le paquet n'a
      jamais ete commite et `import rsl.data` leve. Decider : recuperer la
      couche donnees depuis une autre machine, ou la reecrire. Puis ancrer le
      motif (`/data/`) pour que ca ne se reproduise pas.
- [ ] Relancer les deux experiences seminales depuis ce wiki, avec manifeste et
      empreinte archives, pour qu'elles cessent d'etre des releves du README.
- [ ] Obtenir et ingerer la source du Deflated Sharpe, et trancher la question
      de l'independance des essais d'une grille de parametres voisins.
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
