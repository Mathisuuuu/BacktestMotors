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
| Entrees de log | 25 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 8 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 6 |
| Pages `research/` | 1 |

**Activite par type :** note × 14, fix × 6, setup × 1, lint × 1, experiment × 1, feat × 1, decision × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | defaut de mise en page : la barre d'export etait poussee hors de la fenetre par les zones extensibles | empilee en dernier, elle sortait du cadre sans avertissement. Construite avant les zones extensibles et ancree `side="bottom"` ; geometrie verifiee au widget pres (tous les blocs dans les 793 px de la fenetre)
- **2026-09-11** — note | defaut trouve puis verrouille : l'axe des dates annoncait 2010-2040 pour des donnees 2017-2026 | matplotlib ajoute 5 % de marge et peut reautoscaler au redimensionnement ; bornes fixees ET `set_autoscalex_on(False)` ET rejouees sur `<Configure>`. Couvert par `tests/unit/test_gui_charts.py`
- **2026-09-11** — decision | matplotlib declaree en dependance OPTIONNELLE, pas en dependance du projet | `TRACKED_DEPENDENCIES` ne l'enregistre pas : un rapport produit sur une machine avec interface reste comparable a un rapport produit sans. `rsl gui` sans matplotlib rend 1 avec un message, aucune autre commande n'est touchee
- **2026-09-11** — fix | couture `run_backtest_detailed` ajoutee a `report.py` | le rapport ne porte ni fills ni equity ni trades, seulement leurs agregats ; la rendre par une seconde fonction evite de rejouer le run pour l'afficher. Refactor pur : les 4 empreintes d'exemple sont inchangees
- **2026-09-11** — feat | tableau de bord graphique `rsl gui` : indicateurs, filtres annee/long/short, courbes capital et drawdown, carnet d'ordres, export CSV/TXT | tkinter + matplotlib en extra `gui` ; 3 modules (`model` 400 l., `charts`, `app`), 37 tests ajoutes, suite a 1240 ; noir et blanc strict, chrome Windows 95
- **2026-09-11** — note | correction finale des chiffres de `src/rsl/env.py` (les deux entrees precedentes sont fausses toutes les deux) | chiffres verifies : **133 lignes**, **20 fonctions de test** dans `tests/unit/test_env.py` soit **23 tests collectes** (une est parametree sur 4 encodages). Total de la suite : 1180 -> 1203
- **2026-09-11** — note | correction de l'entree `fix` ci-dessus (log append-only : on corrige par ajout) | `src/rsl/env.py` fait 128 lignes et non 103 -- le chiffre notait l'etat avant le durcissement (borne de depot + encodages) ; le nombre de tests ajoutes est 25
- **2026-09-11** — note | P6 (`all(())` vaut `True`) est MASQUE, pas corrige | le test `test_missing_data_sources_are_flagged` passe desormais uniquement parce que l'arbre de travail est sale, ce qui met `git.is_reproducible` a `False`. Il redeviendra rouge au prochain commit propre

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
