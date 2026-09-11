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
| Entrees de log | 51 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 16 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 30, fix × 7, decision × 6, feat × 5, setup × 1, lint × 1, experiment × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | P6 est ressorti puis re-masque, comme annonce | la suite a echoue sur `test_missing_data_sources_are_flagged` des que l'arbre est devenu propre (le hook avait commite), puis a repasse au vert des mes modifications suivantes. Le defaut `all(())` est intact : il n'est visible que sur un arbre propre
- **2026-09-11** — note | VWAP ancre sur la seance : exprimable par COMPOSITION, sans primitive nouvelle | `arith(/, cumulative(sum, prix*volume), cumulative(sum, volume))`. Verifie analytiquement : a volumes constants il vaut la moyenne des clotures depuis l'ouverture, exact au 1e-9. C'etait l'exemple motivant de la proposition
- **2026-09-11** — note | la surface publique du `Context` s'est elargie, et un test adversarial l'a signale | `test_public_surface_is_the_declared_one` a echoue a l'ajout de `session_value` : il fait exactement son travail. Avant d'elargir la liste blanche, j'ai ecrit `tests/adversarial/test_session_closure.py` -- 26 tests dont le decisif : corrompre toutes les barres apres un point ne change AUCUNE valeur de seance lue avant. Les agregats de seance sont calcules a la construction du magasin, donc c'etait le canal de fuite plausible
- **2026-09-11** — decision | deux lignes du ledger REPRISES le jour meme de leur ecriture | `session` et `cumulative` avaient ete ecartes parce qu'il aurait fallu DEVINER la frontiere de seance. Une declaration ne devine rien : le motif du rejet tombe, et les deux lignes de reprise le disent en citant les anciennes. `reset: never` de `cumulative` reste ecarte -- son motif (historique non borne, warmup indefinissable) ne depend pas du calendrier
- **2026-09-11** — feat | calendrier de seance DECLARE par instrument, et les deux noeuds qu'il debloque | nouveau `src/rsl/data/session.py` ; `data[].session` (start, end, timezone IANA) entre dans le `config_hash` ; `BarStore` porte un champ optionnel `sessions`, ce qui fait que `shifted`, `peer` et les deux feeds en heritent sans plomberie. Noeuds 20 -> 22 : `session@1` (feuille) et `cumulative@1` (fenetre a longueur variable). Suite 1434 -> 1460 tests
- **2026-09-11** — note | `vol_target` verifie sur le mecanisme, pas sur un resultat | doubler la volatilite divise la taille par deux : 494, 197, 98, 49, 19 contrats pour des volatilites de 0,002 a 0,050 par barre. Piege d'interpretation observe au passage : une cible de 1 % PAR BARRE sur du quotidien avec une base de 20 donne ~18 contrats ES sur 100 k d'equity -- un levier considerable, meme famille de piege que celui deja documente pour `equity_fraction`. **3 executions sur donnees reelles, donc 3 essais** (L2)
- **2026-09-11** — note | piege trouve en testant `vol_target` : la troncature peut annuler la strategie | `int(1 * 0.9)` vaut 0 : avec `contracts: 1` et un facteur d'echelle sous 1, aucune position n'est jamais prise, sans erreur ni avertissement. Documente dans la regle et couvert par un test ; remede = une base assez grande (`contracts: 10` donne dix paliers)
- **2026-09-11** — note | le decalage d'une periode exige par la proposition est inutile ICI, et je l'ai omis | le `Context` n'expose que des barres closes et l'execution est retardee (`lag_bars >= 1`) : lire la barre courante n'est pas lire son propre resultat. `RiskFraction` herite deja de cette garantie pour son ATR sans regle supplementaire. Ajouter un decalage aurait ete un reglage sans effet, donc une fausse precaution

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
