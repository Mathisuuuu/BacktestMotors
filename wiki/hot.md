---
type: hub
updated: 2026-09-11
generated: true
---

# hot — etat courant

> [!WARNING] FICHIER AUTO-GENERE — NE PAS EDITER A LA MAIN
> Produit par [`wiki/update_hot.py`](update_hot.py), relance par le hook
> `Stop` a chaque fin de session. Toute modification hors du bloc
> **Next Actions** sera ecrasee sans avertissement.
> Derniere generation : 2026-09-11.

## Current State

| Indicateur | Valeur |
|---|---|
| Pages de wiki | 19 |
| Entrees de log | 13 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 8 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 2 |
| Pages `reference/` | 5 |
| Pages `research/` | 1 |

**Activite par type :** note × 7, fix × 4, setup × 1, lint × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | defaut trouve sur `rsl schema` redirige : sortie en CP1252, pas en UTF-8 | `ensure_ascii=False` + stdout Windows ; le `§` sort en octet 0xA7, le fichier est illisible en UTF-8. `--out` ecrit correctement en UTF-8 : le defaut ne touche que la redirection `>`
- **2026-09-11** — note | defaut trouve dans `RunManifest.is_reproducible` : `all(())` vaut `True` | un run sans aucune source de donnees enregistree se declare `Rejouable oui` ; `test_missing_data_sources_are_flagged` echoue et a raison. Le champ que [[concepts/determinisme]] designe comme le seul qui compte ment par vacuite
- **2026-09-11** — fix | P1 reexamine : `rsl.data` est revenu sur le disque mais reste NON VERSIONNE | `.gitignore:1` `data/` toujours non ancre ; 7 fichiers / 2063 lignes invisibles de git, `git status` affiche « propre » ; un clone frais ou un `git clean -xfd` reperd toute la couche donnees. Correctif : ancrer en `/data/`
- **2026-09-11** — note | audit « que fait l'application, est-ce que ca marche » : wiki relu, CLI exercee de bout en bout sur donnees reelles | 1179 tests passent / 1 echoue ; ruff et mypy propres ; les 2 experiences seminales se reproduisent au chiffre pres (Sharpe 0,60, 57 % dans un pli) ; P3 et P4 constates resolus ; 2 defauts vivants trouves -> voir entrees suivantes
- **2026-09-10** — fix | P5 : droits d'ecriture accordes, push reessaye | 3 commits pousses vers origin/main (26 fichiers, 1923 lignes) ; sync entre machines operationnelle
- **2026-09-10** — note | chaine d'outils passee sur l'arbre incomplet | `src/` propre sous ruff ; 28 I001 dans `tests/` et 35 des 36 erreurs mypy sont des symptomes de P1 ; 1 erreur reelle (stubs numpy vs python_version 3.11) -> P4 ; piege `ruff --fix` consigne au ledger
- **2026-09-10** — fix | P2 : venv Python 3.14.6 + `pip install -e ".[dev]"` | 29 paquets installes ; polars/pyarrow/pydantic identiques au manifeste du README, numpy 2.5.3 au lieu de 2.4.6
- **2026-09-10** — note | audit « quels sont les problemes a regler » : etendue de la casse rsl.data mesuree, recuperation locale cherchee | 6 modules / 42 symboles perdus, aucune copie sur la machine, ~128 tests specificateurs intacts ; 3 problemes classes P1-P3

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

Etat verifie par l'audit du 2026-09-11 (suite complete, CLI de bout en bout sur
donnees reelles) : **1179 tests passent, 1 echoue** ; `ruff` et `mypy` sont
propres sur `src` et `tests` ; les deux experiences seminales se reproduisent au
chiffre pres.

- [ ] **P1 toujours ouvert, sous une autre forme** -- `rsl.data` est **revenu
      sur le disque** (7 fichiers, 2063 lignes, tests verts) mais reste **non
      versionne** : `.gitignore:1` porte encore `data/` non ancre.
      `git ls-files src/` = 36 fichiers contre 43 sur le disque, et
      `git status` affiche « propre ». Un `git clean -xfd` ou un clone frais
      reperd tout. Correctif : `/data/` dans `.gitignore`, puis committer
      `src/rsl/data/`. **C'est le point le plus urgent du depot.**
- [ ] **P6 nouveau** -- `RunManifest.is_reproducible` ment par vacuite :
      `all(s.source_hash for s in self.data_sources)` vaut `True` sur un tuple
      vide, donc un run **sans aucune source enregistree** se declare
      `Rejouable oui`. `tests/unit/test_manifest.py::test_missing_data_sources_are_flagged`
      echoue et a raison. Le champ que [[concepts/determinisme]] designe comme
      le seul qui compte est exactement celui qui se trompe.
      Correctif : exiger `self.data_sources and all(...)`.
- [ ] **P7 nouveau** -- `rsl schema > fichier.json` ecrit du **CP1252**, pas de
      l'UTF-8 (`ensure_ascii=False` + stdout Windows). Le `§` sort en octet
      `0xA7` et le fichier devient illisible en UTF-8. `--out` ecrit
      correctement : seul le chemin de redirection est touche. Aujourd'hui le
      seul caractere concerne est encodable en CP1252 -- le jour ou une
      docstring portera un `≥` ou une fleche, la commande levera.
- [x] **P2 fait (2026-09-10)**, revu le 2026-09-11 : le `.venv` tourne
      desormais en **Python 3.11.9** avec **numpy 2.4.6**, conforme au manifeste
      archive du README.
- [x] **P3 resolu (constate 2026-09-11)** -- plus aucun point `[A ARBITRER]`
      dans `docs/` (`grep` rend 0).
- [x] **P4 resolu (constate 2026-09-11)** -- `mypy` rend
      `Success: no issues found in 43 source files`. Le retour a numpy 2.4.6 +
      Python 3.11.9 a supprime l'erreur de stubs.
- [x] **P5 resolu (2026-09-10)** -- push operationnel vers
      `Mathisuuuu/BacktestMotors`.
- [x] **`ruff --fix` : le piege est leve** -- la prediction du ledger est
      verifiee. `ruff check src tests` rend `All checks passed!` sans qu'aucun
      fichier de test ait ete touche : les 28 `I001` ont bien disparu d'
      elles-memes au retour de `rsl.data`.
- [ ] Relancer les deux experiences seminales **avec manifeste et empreinte
      archives** -- l'audit a montre qu'elles se reproduisent
      (`sma_es_daily` : Sharpe 0,60, empreinte `e96832fb121b91fb`,
      `verify` identique ; walk-forward 9 plis, 57 % dans un pli), mais rien
      n'a ete archive en `runs/` a cette occasion.
- [ ] Obtenir et ingerer la source du Deflated Sharpe (independance des essais).
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
