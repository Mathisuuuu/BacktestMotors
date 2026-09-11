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
| Entrees de log | 77 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 16 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 42, fix × 14, feat × 9, decision × 8, setup × 1, lint × 1, experiment × 1, audit × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | erreur de manipulation rattrapee, a ne pas refaire | `rsl schema --out schemas/rsl.schema.json` sans `--what all` ecrase le schema complet par le SEUL schema des signaux : le defaut de `--what` est `signals`. Le diff (616 insertions, 1505 suppressions) m'a d'abord fait croire que le fichier commite etait perime. Il ne l'etait pas -- verifie en le regenerant depuis un worktree au commit precedent
- **2026-09-11** — fix | effet de bord de P1.b : une cle de `rules` inconnue etait IGNOREE | `rules` est un `dict[str, object]`, le `extra=forbid` de pydantic ne s'y applique pas. `exit_lng` au lieu de `exit_long` donnait une strategie qui entre et ne sort jamais, sans un mot -- un backtest faux, pas un backtest en erreur. Le schema publie annoncait meme `additionalProperties: true`, donc plus permissif que le code : il porte maintenant `propertyNames.enum`, derive de la meme liste. 1548 -> 1552 tests, 7 empreintes d'exemples inchangees
- **2026-09-11** — fix | P1.b : les neuf cles de `rules` cessent d'etre recopiees quatre fois | champs de la classe, `warmup_bars`, `describe()`, `from_spec`, plus une derivation de contournement dans `skeleton.py` qui construisait une strategie temoin pour lire les cles de son descripteur. Desormais `RULE_KEYS`, derive des champs `Signal | None`. Les quatre copies etaient d'accord : le defaut n'etait pas une divergence mais le fait qu'un oubli echoue en silence, et differemment selon l'endroit
- **2026-09-11** — fix | P1.a : `orders.py` sort de `engine/` et le sens unique redevient verifiable | `import rsl.strategies` chargeait SEPT modules de moteur : le runner a besoin du protocole `Strategy`, les strategies ont besoin d'`Order`. Le cycle ne plantait pas -- trois tentatives de le casser en reordonnant les imports ont echoue, `orders` etant une feuille -- donc le cout etait l'impossibilite de raisonner sur une couche seule, pas un risque d'erreur. `Order` et `Fill` n'appartiennent a aucune des deux couches : places sous les deux, avec `errors.py`. 33 modules charges -> 27. `tests/unit/test_couches.py` le tient ferme dans un interpreteur neuf, ce qu'aucun outil du depot ne sait faire
- **2026-09-11** — note | mesures de performance de l'audit, a conserver | `primitive sma@1(20)` 5,9 us/barre ; `rolling(mean,20)` 44,9 us ; `rolling(zscore,120)` sur un `arith` de deux primitives **1549 us**. Extrapole sur les 3,7 M de barres minute d'ES : 1,6 h pour UN signal, 14,4 h sur l'univers de dix. `cumulative` est quadratique par seance : 952 890 evaluations de sous-arbre sur une seance d'une minute. C'est la dette qui empeche le vocabulaire compose de servir a l'echelle minute
- **2026-09-11** — fix | P0.2 : `ExecutionStats` etait calcule puis jete | `n_limit_not_touched`, `n_stop_not_triggered` et `n_slippage_clamped` etaient incrementes sans que `describe()` soit appele nulle part. Remontes dans un bloc `execution_stats` SEPARE de `counters` -- ce dernier entre dans l'empreinte, l'y fusionner aurait change toutes les empreintes archivees. Verifie : une strategie a limite rapporte `n_limit_not_touched: 17`
- **2026-09-11** — fix | P0.1 : la strategie est construite AVANT le chargement des donnees | `report.py` lisait le parquet puis decouvrait que la specification etait fausse. Mesure sur dix instruments : 6,1 s avant, 0,89 s apres -- dont 0,786 s de demarrage de l'interpreteur, donc le cout de rejet est desormais negligeable. Meme sonde de validation ajoutee a `walkforward.py`. Les 6 empreintes d'exemples sont inchangees
- **2026-09-11** — audit | audit complet du socle : securite, architecture, performance | securite EXEMPLAIRE (zero eval/exec/pickle, 5 modeles pydantic tous `frozen`+`extra=forbid`, un seul subprocess a arguments litteraux). Ouvert/Ferme verifie : 16 ajouts dans la journee sans toucher au noyau, et le squelette les a publies seul. Trois dettes chiffrees : validation apres I/O, cycle `engine <-> strategies`, et le cout des boucles Python de `rolling`

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

Etat au 2026-09-11, apres P1 de l'audit d'architecture : **1552 tests passent,
aucun n'echoue** ; `ruff` et `mypy --strict` sont propres sur `src` et `tests` ;
les **7 empreintes d'exemples sont inchangees** depuis l'avant-derniere
session. (L'audit du meme jour partait de 1179 tests dont 1 echouait ; cet
echec est le P6 ci-dessous, corrige.)

## Plan de l'audit d'architecture (2026-09-11)

Numerotation PROPRE a cet audit, sans rapport avec les P1..P7 de la liste
suivante, qui viennent de l'audit fonctionnel du 2026-09-10.

- [x] **A-P0 fait** -- valider avant de lire (6,1 s -> 0,89 s pour rejeter une
      specification fausse), et rapporter `execution_stats`, qui etait calcule
      puis jete.
- [x] **A-P1 fait** -- `orders.py` sort de `engine/` : le sens unique entre les
      couches redevient verifiable ([[lessons]] L14). Et les neuf cles de
      `rules` cessent d'etre recopiees quatre fois, ce qui permet enfin de
      **refuser une cle inconnue** ([[lessons]] L15).
- [ ] **A-P2 -- arbitrage a rendre, pas tache a executer.** `rolling(zscore,120)`
      sur un `arith` de deux primitives coute **1549 us/barre**, soit 1,6 h pour
      un signal sur les 3,7 M de barres minute d'ES et 14,4 h sur l'univers de
      dix. Trois voies, aucune gratuite : elimination des sous-expressions
      communes DANS une barre (~2x, sans toucher a une garantie) ;
      memoisation ENTRE barres (rapide, mais se heurte au rejet des noeuds a
      etat, [[Failed Ideas/ledger]]) ; primitives dediees (deja « en attente »
      au ledger). Recommandation : la troisieme, apres avoir mesure quels cas
      la justifient.
- [ ] **A-P3** -- `signals.py` fait 1915 lignes ; `gui/app.py:275` injecte un
      attribut `teinte` sur un `tk.Label` ; un seul test porte le marqueur
      `slow`.

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
