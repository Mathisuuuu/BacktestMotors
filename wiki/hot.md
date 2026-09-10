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
| Entrees de log | 9 |
| Derniere activite | 2026-09-10 |
| Idees ecartees (ledger) | 8 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 2 |
| Pages `reference/` | 5 |
| Pages `research/` | 1 |

**Activite par type :** note × 4, fix × 3, setup × 1, lint × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-10** — fix | P5 : droits d'ecriture accordes, push reessaye | 3 commits pousses vers origin/main (26 fichiers, 1923 lignes) ; sync entre machines operationnelle
- **2026-09-10** — note | chaine d'outils passee sur l'arbre incomplet | `src/` propre sous ruff ; 28 I001 dans `tests/` et 35 des 36 erreurs mypy sont des symptomes de P1 ; 1 erreur reelle (stubs numpy vs python_version 3.11) -> P4 ; piege `ruff --fix` consigne au ledger
- **2026-09-10** — fix | P2 : venv Python 3.14.6 + `pip install -e ".[dev]"` | 29 paquets installes ; polars/pyarrow/pydantic identiques au manifeste du README, numpy 2.5.3 au lieu de 2.4.6
- **2026-09-10** — note | audit « quels sont les problemes a regler » : etendue de la casse rsl.data mesuree, recuperation locale cherchee | 6 modules / 42 symboles perdus, aucune copie sur la machine, ~128 tests specificateurs intacts ; 3 problemes classes P1-P3
- **2026-09-10** — note | correction de l'entree `note` ci-dessus (log append-only : on corrige par ajout) | le bon compte est 5 routeurs et 15 pages de contenu, pas 4 et 13
- **2026-09-10** — lint | premier passage : 20 pages, wikilinks et liens relatifs verifies | 0 orpheline, 1 lien mort reel (rsl.data) annote, placeholders de gabarits exclus
- **2026-09-10** — fix | decouverte en verifiant les liens : `.gitignore:1` `data/` attrape aussi `src/rsl/data/` | paquet `rsl.data` jamais commite et absent du disque, `import rsl.data` leve ; signale, non corrige
- **2026-09-10** — note | amorcage : 6 concepts, 4 routeurs, 2 experiences, 1 source a ingerer, 7 idees au ledger | tout tire du depot existant, aucune connaissance inventee

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

- [ ] **P1 bloquant** -- couche `rsl.data` absente (6 modules, 42 symboles).
      Cause : `.gitignore:1` `data/` non ancre. Aucune copie locale retrouvee.
      Ordre : (a) chercher sur une autre machine / sauvegarde / historique local
      de l'IDE ; (b) a defaut, reconstruire en TDD -- les ~128 tests qui
      specifient ces modules ont survecu ; (c) ancrer le motif en `/data/`.
- [x] **P2 fait (2026-09-10)** -- `.venv` cree en Python 3.14.6,
      `pip install -e ".[dev]"` reussi. `polars` 1.44.2, `pyarrow` 25.0.1 et
      `pydantic` 2.13.5 correspondent au manifeste archive du README.
- [ ] **P3** -- `docs/` porte encore « decisions de design, avant
      implementation » et 4 points `[A ARBITRER]` ouverts, alors que le README
      donne tout pour fait. Dans un depot ou `docs/` est normatif, trancher.
- [ ] **P4 nouveau** -- `mypy` casse sur les stubs de numpy 2.5.3 :
      `Type statement is only supported in Python 3.12 and greater`, parce que
      `pyproject.toml` fixe `python_version = "3.11"`. Le manifeste archive du
      README cite numpy **2.4.6**. Trancher : epingler `numpy<2.5`, ou relever
      `python_version` a 3.12+. Seule erreur mypy non imputable a P1.
- [x] **P5 resolu (2026-09-10)** -- droits d'ecriture obtenus sur
      `Mathisuuuu/BacktestMotors`. Push reussi : 3 commits, 26 fichiers,
      1923 lignes. La synchronisation entre machines est operationnelle.
- [ ] **Ne pas lancer `ruff --fix`** tant que P1 est ouvert -- voir le ledger.
- [ ] Relancer les deux experiences seminales une fois P1 leve, avec manifeste
      et empreinte archives.
- [ ] Obtenir et ingerer la source du Deflated Sharpe (independance des essais).
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
