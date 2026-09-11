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
| Pages de wiki | 21 |
| Entrees de log | 38 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 11 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 6 |
| Pages `research/` | 1 |

**Activite par type :** note × 21, fix × 7, decision × 4, feat × 3, setup × 1, lint × 1, experiment × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | MACD verifie analytiquement, pas contre une seconde implementation | sur une droite de pente `s`, une EMA de fenetre `w` retarde de `s*(w-1)/2`, donc la ligne MACD vaut `s*(slow-fast)/2`. Mesure : 7,000000 pour s=1, fast=12, slow=26. ADX sature a 100 en tendance pure, OBV vaut exactement la somme des volumes, ratio d'efficience vaut 1 sur un chemin droit
- **2026-09-11** — note | `examples/_moule_universel.json` : reference exhaustive du vocabulaire | 20/20 types de noeuds, 7 primitives nouvelles, long et short, stop adaptatif par `if_then_else`, objectif borne par `min_of`/`max_of`. Verifie a l'execution (66 trades, Sharpe 0,29, empreinte 5dd6973012b4c68b) et garde par `tests/unit/test_moule_universel.py`, qui nomme les types manquants. Mutation testee : retirer `time` fait echouer le test. **Cette execution consomme un essai** (L2)
- **2026-09-11** — decision | variantes de Wilder publiees sous des NOMS distincts, pas en `@2` | `registry.py:124` resout une reference sans version vers la plus recente : `atr@2` aurait fait basculer tout `"ref": "atr"` non epingle d'une moyenne simple a une exponentielle, en silence. Les docstrings de `atr@1` et `rsi@1` recommandent pourtant ce chemin -> ledger + [[lessons]] L10
- **2026-09-11** — decision | `rolling@1` gagne 6 statistiques par extension ADDITIVE, sans `rolling@2` | le levier structurel est `stat: "ema"` : avant lui, lisser une EXPRESSION etait impossible (`primitive` est une feuille), donc la ligne de signal d'un MACD etait inexprimable. Verification : les empreintes de `sma_es_daily`, `paire_es_nq`, `momentum`, `retour_moyenne` et `_moule` sont identiques avant et apres -> ledger
- **2026-09-11** — feat | vocabulaire etendu : 9 primitives et 5 types de noeuds ajoutes, plus 6 statistiques sur `rolling@1` | primitives 13 -> 22 (`macd@1` avec ligne de signal et histogramme, `atr_wilder@1`, `rsi_wilder@1`, `adx@1`, `cci@1`, `williams_r@1`, `efficiency_ratio@1`, `vwap@1`, `obv@1`) ; noeuds 15 -> 20 (`if_then_else`, `math`, `min_of`, `max_of`, `bars_since`) ; `rolling` gagne `ema`, `median`, `var`, `slope`, `rank`, `count_true`. Suite 1263 -> 1387 tests. **Les 5 empreintes d'exemples sont inchangees**
- **2026-09-11** — note | sondage d'expressivite du vocabulaire, 5 configurations lancees sur ES quotidien | EXPRIMABLE : MACD (difference de deux `ema@1` par `arith`, Sharpe 0,81, 33 trades), ligne de signal par `rolling mean` (Sharpe 0,74, 115 trades), stop suiveur via `position.high_since_entry` (Sharpe 0,64, 18 trades). REFUSE : EMA d'un sous-arbre (`primitive` est une feuille, pas de champ `inner`), et deux granularites du meme instrument (`'ES.v.0' apparait deux fois`). **Ces 5 executions consomment 5 essais** au sens de [[lessons]] L2 -- non promues en pages d'experience, aucune n'ayant d'hypothese
- **2026-09-11** — note | gabarit de specification ajoute : `examples/_moule.json` | tous les blocs d'une specification plus une strategie `rules@1` complete (entree composee, sortie a deux conditions, stop ATR, objectif ATR). Verifie en l'executant : 18 trades, Sharpe 0,39, empreinte 58a9d31a2dae3658. **Cette execution consomme un essai** au sens de [[lessons]] L2 -- a promouvoir en page d'experience si le chiffre est conserve
- **2026-09-11** — fix | deux tests de graphiques se sautaient en silence ("aucun affichage disponible") alors que Tk fonctionnait | creer puis detruire une racine `Tk()` par test echoue par intermittence sur les derniers. Fixture passee en portee `module` : une seule racine partagee, 3 executions consecutives sans saut

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
