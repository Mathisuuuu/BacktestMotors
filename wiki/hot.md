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
| Entrees de log | 46 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 14 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 6 |
| Pages `research/` | 1 |

**Activite par type :** note × 27, fix × 7, decision × 5, feat × 4, setup × 1, lint × 1, experiment × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | `vol_target` verifie sur le mecanisme, pas sur un resultat | doubler la volatilite divise la taille par deux : 494, 197, 98, 49, 19 contrats pour des volatilites de 0,002 a 0,050 par barre. Piege d'interpretation observe au passage : une cible de 1 % PAR BARRE sur du quotidien avec une base de 20 donne ~18 contrats ES sur 100 k d'equity -- un levier considerable, meme famille de piege que celui deja documente pour `equity_fraction`. **3 executions sur donnees reelles, donc 3 essais** (L2)
- **2026-09-11** — note | piege trouve en testant `vol_target` : la troncature peut annuler la strategie | `int(1 * 0.9)` vaut 0 : avec `contracts: 1` et un facteur d'echelle sous 1, aucune position n'est jamais prise, sans erreur ni avertissement. Documente dans la regle et couvert par un test ; remede = une base assez grande (`contracts: 10` donne dix paliers)
- **2026-09-11** — note | le decalage d'une periode exige par la proposition est inutile ICI, et je l'ai omis | le `Context` n'expose que des barres closes et l'execution est retardee (`lag_bars >= 1`) : lire la barre courante n'est pas lire son propre resultat. `RiskFraction` herite deja de cette garantie pour son ATR sans regle supplementaire. Ajouter un decalage aurait ete un reglage sans effet, donc une fausse precaution
- **2026-09-11** — note | la cible de `vol_target` est PAR BARRE, pas annualisee -- correction de la proposition | elle demandait `vol_window` "en SEANCES" et une cible implicitement annuelle. Le ledger a deja ecarte les fenetres exprimees autrement qu'en barres, et l'annualisation par facteur suppose (gonflement d'un facteur ~2 sur donnees minute). Une regle de dimensionnement ne connait pas le pas d'annualisation, qui se mesure apres coup sur l'echantillon
- **2026-09-11** — decision | proposition d'extensions "seance" recue et arbitree : 2 ajouts sur 4 retenus | RETENUS : `sizing.kind: "vol_target"` (dimensionnement en volatilite cible, distinct de `risk_fraction` qui dimensionne sur la distance au stop) et `rolling.stride` (pas d'echantillonnage, qui couvre le besoin de `across: sessions_same_offset` sans deviner de frontiere). ECARTES : noeuds `session` et `cumulative` -> ledger. Suite 1405 -> 1434 tests, 4 empreintes d'exemples inchangees
- **2026-09-11** — note | les cles de `rules` ne sont plus recopiees nulle part | elles etaient enumerees trois fois dans `rules.py` ; le squelette les DERIVE de `RuleStrategy.describe()` plutot que d'en faire une quatrieme copie
- **2026-09-11** — note | suffisance du squelette verifiee, pas supposee | trois tests construisent, a partir du SEUL document, une specification valide, puis chaque type de noeud, puis chaque primitive. Verification pratique en plus : un script n'important pas `rsl` a lu le squelette, ecrit une strategie MACD + ADX + stop ATR de Wilder, et l'a executee -> 50 trades, +65,59 %, code 0, empreinte 104e266aa7bdfaf6. **Cette execution consomme un essai** (L2)
- **2026-09-11** — feat | `rsl squelette` : le vocabulaire presente comme un formulaire a remplir | nouveau `src/rsl/skeleton.py` + `schemas/squelette.json` (33 ko, ASCII pur). Chaque emplacement d'une specification y porte son type, ses choix, son defaut. Trois renvois croises rendus enumerables : `root` (10 instruments), `strategy.ref` (6), `primitive.ref` (22). ENGENDRE depuis les registres, garde par un test de derive comme `schemas/` (L4)

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
