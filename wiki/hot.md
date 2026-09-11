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
| Pages de wiki | 20 |
| Entrees de log | 20 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 8 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 5 |
| Pages `research/` | 1 |

**Activite par type :** note × 12, fix × 5, setup × 1, lint × 1, experiment × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | correction finale des chiffres de `src/rsl/env.py` (les deux entrees precedentes sont fausses toutes les deux) | chiffres verifies : **133 lignes**, **20 fonctions de test** dans `tests/unit/test_env.py` soit **23 tests collectes** (une est parametree sur 4 encodages). Total de la suite : 1180 -> 1203
- **2026-09-11** — note | correction de l'entree `fix` ci-dessus (log append-only : on corrige par ajout) | `src/rsl/env.py` fait 128 lignes et non 103 -- le chiffre notait l'etat avant le durcissement (borne de depot + encodages) ; le nombre de tests ajoutes est 25
- **2026-09-11** — note | P6 (`all(())` vaut `True`) est MASQUE, pas corrige | le test `test_missing_data_sources_are_flagged` passe desormais uniquement parce que l'arbre de travail est sale, ce qui met `git.is_reproducible` a `False`. Il redeviendra rouge au prochain commit propre
- **2026-09-11** — note | question « peut-on creer une strategie sans une ligne de code » : verifie au shell | OUI dans le vocabulaire (13 primitives x 15 noeuds composables, 3 moules) ; NON au-dela : une primitive ou un type de noeud absent est refuse avec rc=1 et l'enumeration de ce qui existe. Ecrire l'un des deux demande du Python et un enregistrement `@1`
- **2026-09-11** — experiment | rsi-survendu-hors-lundi | `non-conclusif` : Sharpe 0,46 sur 2732 barres, 49 trades, 54 % du resultat dans un pli sur neuf ; le filtre calendaire n'a pas de temoin. Essai fait comme preuve qu'une strategie neuve s'ecrit en JSON seul -- compte quand meme au compteur (L2)
- **2026-09-11** — note | durcissement trouve par un test que j'ecrivais : la remontee vers le `.env` sortait du depot | elle atteignait `C:\Users\Mathis\.env` (118 o, UTF-16), etranger au projet. Bornee aux marqueurs `.git` / `pyproject.toml`, et lecture UTF-8/UTF-16/CP1252 (PowerShell 5.1 redirige en UTF-16)
- **2026-09-11** — fix | chemins de donnees rendus portables : `RSL_DATA_DIR` + `.env`, et `config_hash` debarrasse du chemin absolu | nouveau `src/rsl/env.py` (103 l., zero dependance) ; 15 chemins absolus retires de `examples/` et `cli.py` ; 25 tests ajoutes ; les 4 empreintes de resultat sont INCHANGEES, seul le `config_hash` bouge -> voir [[lessons]] L7
- **2026-09-11** — note | defaut trouve sur `rsl schema` redirige : sortie en CP1252, pas en UTF-8 | `ensure_ascii=False` + stdout Windows ; le `§` sort en octet 0xA7, le fichier est illisible en UTF-8. `--out` ecrit correctement en UTF-8 : le defaut ne touche que la redirection `>`

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
