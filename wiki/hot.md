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
| Entrees de log | 69 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 16 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 40, fix × 9, feat × 9, decision × 8, setup × 1, lint × 1, experiment × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | distinction mise au jour par un test qui echouait | `RuleStrategy._position` (compteur interne, alimente par `on_fill`) et `ctx.position` (etat expose par le RUNNER) sont deux choses differentes. En run reel le runner les garde d'accord ; dans un test sur `BarContext` nu, il faut renseigner les deux, sinon le noeud `position` lit une position a plat
- **2026-09-11** — note | premier essai de verification trompeur, rattrape | mes trois variantes donnaient des chiffres quasi identiques : `_moule.json` porte `sizing: {fixed, contracts: 1}`, qui ECRASE la quantite de la strategie. Chaque position ne faisait qu'un contrat, il n'y avait rien a alleger. Refait avec `contracts: 4` : 8 trades en sortie totale, 9 en moitie, 9 en un contrat, facteurs de profit distincts
- **2026-09-11** — feat | `exit_quantity` : les sorties cessent d'etre tout ou rien | troisieme et derniere brique des manques trouves en comparant le moteur au vocabulaire. Un noeud donnant un nombre de contrats ; absent, la position entiere est fermee comme avant. La valeur est une MAGNITUDE, son signe ignore, ce qui permet d'ecrire `position.quantity * 0.5` sans `abs` et d'alleger de moitie long comme court. Suite 1512 -> 1523 tests, empreintes inchangees
- **2026-09-11** — note | deux defauts de conception trouves par les tests, pas par relecture | (1) je construisais chaque livre en appelant `RuleStrategy.from_spec` directement, ce qui contournait les defauts et la validation de `RuleStrategyParams` -- un livre sans `quantity` levait un message obscur. Corrige en passant par le modele. (2) une verification `isinstance(brut, dict)` etait du code mort : l'annotation `dict[str, dict[str, object]]` rejette deja la valeur avant le constructeur. Retiree, et le test dit maintenant ce qui se passe vraiment
- **2026-09-11** — feat | `multi_rules@1` : un jeu de regles PAR instrument, dans un portefeuille commun | leve la brique 2 des trois manques trouves en comparant le moteur au vocabulaire. Un livre est un jeu de parametres `rules@1` moins le symbole, VALIDE par le meme modele -- memes defauts, meme `extra=forbid`. Livres tries par symbole pour que l'ordre des cles JSON n'entre pas dans l'empreinte. `peer` continue de fonctionner dans chaque livre. Essai reel : ES en 20/100 et NQ en 10/40 quantite double, 46 trades, Sharpe 0,85. Suite 1494 -> 1512 tests
- **2026-09-11** — note | comment ce manque a ete trouve, et deux autres avec lui | en comparant ce que le MOTEUR accepte a ce que le VOCABULAIRE sait produire, pas en lisant la documentation. Les deux autres ecarts restent ouverts : une strategie a regles ne traite qu'un seul symbole, et les sorties sont tout ou rien (pas d'allegement) -> [[lessons]] L13
- **2026-09-11** — decision | un prix d'entree indefini ABANDONNE l'entree, il ne retombe pas sur un ordre au marche | retomber changerait silencieusement le type d'ordre, donc le comportement, au moment precis ou l'on en sait le moins. Meme regle que partout : « je ne sais pas » n'est pas une raison d'agir
- **2026-09-11** — note | semantique a connaitre : un ordre a limite vaut pour la SEULE barre d'execution | mesure sur ES quotidien, limite a 1 ATR sous la cloture : 1 trade contre 18 au marche, et 0 pour un stop a 1 ATR au-dessus. Les abandons sont visibles (`n_orders_cancelled_unfilled: 17` sur `n_orders_submitted: 19`) mais rien ne previent -- d'ou un paragraphe dedie dans [[reference/vocabulaire-signaux]]. Ce n'est pas un ordre au carnet

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
