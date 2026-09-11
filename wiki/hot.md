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
| Entrees de log | 32 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 8 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 6 |
| Pages `research/` | 1 |

**Activite par type :** note × 18, fix × 7, feat × 2, decision × 2, setup × 1, lint × 1, experiment × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | gabarit de specification ajoute : `examples/_moule.json` | tous les blocs d'une specification plus une strategie `rules@1` complete (entree composee, sortie a deux conditions, stop ATR, objectif ATR). Verifie en l'executant : 18 trades, Sharpe 0,39, empreinte 58a9d31a2dae3658. **Cette execution consomme un essai** au sens de [[lessons]] L2 -- a promouvoir en page d'experience si le chiffre est conserve
- **2026-09-11** — fix | deux tests de graphiques se sautaient en silence ("aucun affichage disponible") alors que Tk fonctionnait | creer puis detruire une racine `Tk()` par test echoue par intermittence sur les derniers. Fixture passee en portee `module` : une seule racine partagee, 3 executions consecutives sans saut
- **2026-09-11** — note | correction de l'entree `feat` ci-dessus (log append-only : on corrige par ajout) | le compte exact est **1263 tests**, pas 1275
- **2026-09-11** — decision | `mplfinance` ecarte pour les bougies | exigerait pandas, dont le rejet figure au ledger. Le motif du rejet vise la couche donnees et non l'affichage, mais une `LineCollection` plus un `bar` suffisent : pas de raison d'ouvrir le debat pour un graphique
- **2026-09-11** — note | defaut trouve : le bouton de filtre actif s'affichait vide | avec `indicatoron=False`, Tk peint l'etat selectionne avec `selectcolor` et ignore `bg` ; libelle blanc sur fond blanc. `selectcolor` regle en meme temps que `bg`
- **2026-09-11** — note | defaut trouve et verrouille : l'echelle des prix restait figee au zoom | `Axes.clear()` reinitialise le registre de callbacks de matplotlib, donc le `xlim_changed` connecte a la construction ne survivait pas au premier redessin. Remplace par un point d'extension explicite `_apres_fenetre()` -> voir [[lessons]] L9
- **2026-09-11** — feat | tableau de bord refondu : 4 onglets, style plat blanc, vert/rouge porteurs de sens, onglet PRIX & ORDRES avec bougies et ordres, duree moyenne en position | style Windows 95 abandonne sur demande ; `RunArtifacts` remplace le tuple rendu par `run_backtest_detailed` pour transporter aussi les barres servies au moteur ; suite a 1275 tests
- **2026-09-11** — note | defaut de mise en page : la barre d'export etait poussee hors de la fenetre par les zones extensibles | empilee en dernier, elle sortait du cadre sans avertissement. Construite avant les zones extensibles et ancree `side="bottom"` ; geometrie verifiee au widget pres (tous les blocs dans les 793 px de la fenetre)

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
