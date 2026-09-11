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
| Pages de wiki | 22 |
| Entrees de log | 55 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 16 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 32, fix × 9, decision × 6, feat × 5, setup × 1, lint × 1, experiment × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | effet de bord decouvert en designorant : ruff respecte `.gitignore` | la couche donnees n'avait donc JAMAIS ete analysee. 7 defauts dormaient dans du code central (4 `__slots__` non tries, 2 blocs d'imports, 1 generateur). Corriges ; les empreintes de `sma_es_daily`, `paire_es_nq` et `_moule` sont identiques avant et apres, ce qui prouve la neutralite. A ne pas confondre avec les 28 `I001` du ledger, qui etaient des symptomes de l'ABSENCE du paquet -> [[lessons]] L12
- **2026-09-11** — fix | P1 RESOLU : motif `.gitignore` ancre en `/data/`, couche donnees enfin versionnee | 8 fichiers, 2 446 lignes, dont `session.py` ecrit aujourd'hui. Diagnostic au moment de pousser : `git ls-files src/` rendait 45 fichiers contre 53 sur le disque, et des tests DEJA pousses importaient `rsl.data.session`, absent du depot -- un clone frais etait casse. `data/` a la racine reste ignore, verifie
- **2026-09-11** — note | pourquoi P6 a survecu a 1400 tests alors qu'un test le visait | le test n'echouait que sur un arbre PROPRE : des que l'arbre etait modifie, `git.is_reproducible` valait deja `False` et masquait tout. Il passait au vert exactement pendant qu'on travaille. Deux tests de regression FIXENT desormais un `GitState` propre au lieu de subir celui du depot -> [[lessons]] L11
- **2026-09-11** — fix | P6 corrige : `RunManifest.is_reproducible` ne ment plus par vacuite | `all(())` vaut `True`, donc un run sans AUCUNE source enregistree se declarait `Rejouable oui` -- le cas ou l'on en sait le moins etait celui ou l'on affirmait le plus. `bool(self.data_sources)` devient une condition a part entiere. Verifie en isolant l'etat git : aucune source -> False, une source hachee -> True, source sans hash -> False, arbre sale -> False. Les runs reels sont inchanges
- **2026-09-11** — note | P6 est ressorti puis re-masque, comme annonce | la suite a echoue sur `test_missing_data_sources_are_flagged` des que l'arbre est devenu propre (le hook avait commite), puis a repasse au vert des mes modifications suivantes. Le defaut `all(())` est intact : il n'est visible que sur un arbre propre
- **2026-09-11** — note | VWAP ancre sur la seance : exprimable par COMPOSITION, sans primitive nouvelle | `arith(/, cumulative(sum, prix*volume), cumulative(sum, volume))`. Verifie analytiquement : a volumes constants il vaut la moyenne des clotures depuis l'ouverture, exact au 1e-9. C'etait l'exemple motivant de la proposition
- **2026-09-11** — note | la surface publique du `Context` s'est elargie, et un test adversarial l'a signale | `test_public_surface_is_the_declared_one` a echoue a l'ajout de `session_value` : il fait exactement son travail. Avant d'elargir la liste blanche, j'ai ecrit `tests/adversarial/test_session_closure.py` -- 26 tests dont le decisif : corrompre toutes les barres apres un point ne change AUCUNE valeur de seance lue avant. Les agregats de seance sont calcules a la construction du magasin, donc c'etait le canal de fuite plausible
- **2026-09-11** — decision | deux lignes du ledger REPRISES le jour meme de leur ecriture | `session` et `cumulative` avaient ete ecartes parce qu'il aurait fallu DEVINER la frontiere de seance. Une declaration ne devine rien : le motif du rejet tombe, et les deux lignes de reprise le disent en citant les anciennes. `reset: never` de `cumulative` reste ecarte -- son motif (historique non borne, warmup indefinissable) ne depend pas du calendrier

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

Etat verifie par l'audit du 2026-09-11 (suite complete, CLI de bout en bout sur
donnees reelles) : **1179 tests passent, 1 echoue** ; `ruff` et `mypy` sont
propres sur `src` et `tests` ; les deux experiences seminales se reproduisent au
chiffre pres.

- [x] **P1 RESOLU (2026-09-11)** -- `rsl.data` est **revenu
      sur le disque** (7 fichiers, 2063 lignes, tests verts) mais reste **non
      versionne** : `.gitignore:1` porte encore `data/` non ancre.
      `git ls-files src/` = 36 fichiers contre 43 sur le disque, et
      `git status` affiche « propre ». Un `git clean -xfd` ou un clone frais
      reperd tout. **Corrige** : motif ancre en `/data/`, et les 8 fichiers de
      `src/rsl/data/` (2 446 lignes) sont versionnes. `data/` a la racine reste
      ignore. Effet de bord decouvert a cette occasion : ruff n'avait jamais
      analyse ce paquet -- 7 defauts corriges, empreintes inchangees ([[lessons]] L12).
- [x] **P6 resolu (2026-09-11)** -- `RunManifest.is_reproducible` mentait par vacuite :
      `all(s.source_hash for s in self.data_sources)` vaut `True` sur un tuple
      vide, donc un run **sans aucune source enregistree** se declare
      `Rejouable oui`. `tests/unit/test_manifest.py::test_missing_data_sources_are_flagged`
      echoue et a raison. Le champ que [[concepts/determinisme]] designe comme
      le seul qui compte est exactement celui qui se trompe.
      Corrige : `bool(self.data_sources)` est desormais une condition a part
      entiere. Deux tests de regression FIXENT l'etat git, parce que l'ancien
      ne voyait le defaut que sur un arbre propre -- voir [[lessons]] L11.
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
