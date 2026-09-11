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
| Pages de wiki | 23 |
| Entrees de log | 101 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 17 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 4 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 50, fix × 22, feat × 12, decision × 11, experiment × 2, setup × 1, lint × 1, audit × 1, refactor × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/paire-es-nq-retour-a-la-moyenne]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | mes trois premiers tests par le runner echouaient, et ils avaient tort | le `Watcher` lisait cinq barres en arriere sans declarer de `warmup_bars` : la borne a refuse, exactement comme elle doit. Une strategie a REGLES, elle, derive son warmup de son arbre -- le cas reel etait donc sur, et c'est le montage a la main qui devait etre corrige. Un test de plus verifie desormais ce chemin declaratif
- **2026-09-11** — fix | ma premiere purge de l'historique balayait tout le dictionnaire a chaque barre | O(portee) par barre, soit 740 millions d'operations sur les 3,7 M de barres minute d'ES pour une profondeur de 200. Remplacee par un retrait en O(1) -- le runner enregistre barre par barre, donc une seule cle sort de la fenetre a chaque appel. Le balayage reste en secours pour le cas non sequentiel. Verifie sans regression : 11,2-12,3 ms des deux cotes sur `_moule_universel`, soit du bruit
- **2026-09-11** — fix | trou referme, que j'avais introduit deux heures plus tot avec `FrozenPeers` | le resolveur de pairs fige construisait un `BarContext` neuf, donc sans historique de position : `peer(NQ, position("quantity"))` rendait zero depuis une vue reculee alors qu'il rendait la bonne valeur depuis la vue courante. Aucun exemple ne l'exercait, donc aucune empreinte ne l'aurait signale. Trouve en enumerant ce que `FrozenPeers` ne transmettait pas
- **2026-09-11** — decision | l'historique de positions est BORNE par le `warmup_bars` declare, et ce qui est hors borne est distingue | un etat par barre sur 3,7 M de barres minute pese des centaines de Mo. La borne est le budget de lecture en arriere que la strategie annonce elle-meme -- une strategie a regles le derive de son arbre, donc le cas declaratif n'a rien a regler. Deux cas hors borne, traites differemment : AVANT la premiere barre enregistree, « a plat » est une DEDUCTION (le runner n'appelle pas la strategie pendant le prechauffage, aucun ordre n'a pu etre emis) ; AU-DELA de la borne, ca leve, plutot que de rendre un etat plat qui passerait pour une mesure
- **2026-09-11** — fix | `position` sous une vue reculee : meme defaut que `peer`, corrige le meme jour | `shifted` recopiait l'etat COURANT, donc `rolling(mean, 20, position("bars_held"))` lisait vingt fois la meme valeur, en silence. Le runner enregistre desormais l'etat a chaque barre dans un `PositionHistory` porte par le feed, et `shifted(k)` y lit la barre `i-k`. **Les 7 empreintes sont inchangees** : aucun exemple ne lisait `position` sous un noeud qui recule, ce qui a ete VERIFIE avant de toucher au code plutot que constate apres
- **2026-09-11** — experiment | paire ES/NQ : premiers chiffres ou le terme distant compte | Sharpe 0,61, 149 trades, profit factor 1,77 sur 2633 barres quotidiennes. **A ne pas lire comme une amelioration** : l'ancien 0,24 venait d'une strategie DIFFERENTE, qui ne regardait pas NQ. Un seul echantillon, aucun walk-forward, seuils herites de l'epoque ou le signal etait inerte, roulement non ajuste. Verdict `non-conclusif` -> [[experiments/paire-es-nq-retour-a-la-moyenne]]
- **2026-09-11** — note | mon premier test de la correction echouait sur du code juste, pour la meme raison mathematique que le defaut | montage : `A = 100 + k` et `B = 1000 + 10k`, dont le ratio vaut 0,1 pour TOUT k. Deux rampes proportionnelles sont un cas degenere qui annule le terme a verifier. Corrige en prenant `B = 500 + 7k`
- **2026-09-11** — note | ce qui ne pouvait pas voir ce defaut, et pourquoi les empreintes en font partie | tests unitaires (chaque noeud pris seul est juste), `mypy`/`ruff` (rien d'incorrect), corruption du futur (aucune fuite : `NQ[t]` lu en `t` est du passe), relecture (`sub._set_peers(self._peers)` est la ligne qu'on ecrit) -- et les EMPREINTES, qui garantissent qu'un resultat ne change pas, jamais qu'il est juste. Un defaut deterministe leur est transparent par construction -> [[lessons]] L18

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

Etat au 2026-09-11, l'audit d'architecture etant **entierement traite** (A-P0
a A-P3) et la bibliotheque portee a 136 primitives : **3566 tests passent,
aucun n'echoue** - dont 183 marques `slow`, qui tournent sur les donnees
reelles et sautent proprement sans elles. ; `ruff` et `mypy --strict` sont propres sur `src` et `tests` ;
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
- [ ] **A-P2 devient PLUS urgent avec 136 primitives.** La bibliotheque ne
      change rien au cout unitaire d'un `rolling`, mais elle multiplie les
      occasions d'en ecrire un. Arbitrage a rendre, pas tache a executer : `rolling(zscore,120)`
      sur un `arith` de deux primitives coute **1549 us/barre**, soit 1,6 h pour
      un signal sur les 3,7 M de barres minute d'ES et 14,4 h sur l'univers de
      dix. Trois voies, aucune gratuite : elimination des sous-expressions
      communes DANS une barre (~2x, sans toucher a une garantie) ;
      memoisation ENTRE barres (rapide, mais se heurte au rejet des noeuds a
      etat, [[Failed Ideas/ledger]]) ; primitives dediees (deja « en attente »
      au ledger). Recommandation : la troisieme, apres avoir mesure quels cas
      la justifient.
- [x] **A-P3 fait (2026-09-11)**, ses trois points :
      - `signals.py` (1 949 lignes) devient une FACADE de 168 lignes ; le code
        vit dans `rsl/strategies/noeuds/`, range par famille (`contrat`,
        `feuilles`, `fenetres`, `operateurs`, `raccourcis`). Aucun import du
        depot ne change, les 7 empreintes et les TROIS contrats engendres sont
        identiques au fichier pres ;
      - `gui/app.py` n'injecte plus d'attribut `teinte` sur un `tk.Label` : la
        table `TEINTES` est derivee de `GROUPES`, et une cle inconnue LEVE au
        lieu de peindre en noir en silence ;
      - la couverture `slow` passe de 1 fichier a 2 : `test_integration_reelle.py`
        verifie de bout en bout, sur donnees reelles, ce que je verifiais
        jusqu'ici A LA MAIN - les 7 empreintes, les hash de configuration, le
        determinisme, l'equivalence avec et sans memoisation, et les 136
        primitives sur une vraie serie. 183 tests `slow` contre 12 avant.

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
- [x] **`peer` sous `rolling` : CORRIGE (2026-09-11).** Ce n'etait pas une
      convention mais un defaut : le terme distant restait a l'instant courant,
      donc constant sur la fenetre, donc - z-score etant invariant d'echelle -
      **sans aucun effet** (ecart 2,08e-14 avec un z-score du seul numerateur).
      `shifted` recule maintenant aussi le resolveur de pairs, par les REGLES DU
      PANNEAU : un instrument absent le reste. L'empreinte de `paire_es_nq`
      change (15 -> 149 trades), son `config_hash` non. Essai enregistre en
      [[experiments/paire-es-nq-retour-a-la-moyenne]] ; ce qu'il ne faut PAS en
      conclure y est ecrit. Cout : le run passe de 3,6 a 5,4 s, le pair etant
      desormais reellement resolu 120 fois par barre ([[lessons]] L18).
- [x] **`position` sous une vue reculee : CORRIGE (2026-09-11)**, le meme jour
      que `peer` et par le meme raisonnement. Le runner enregistre l'etat a
      chaque barre dans un historique BORNE par le `warmup_bars` declare ;
      `shifted(k)` y lit la barre `i-k`. Les 7 empreintes sont INCHANGEES -
      aucun exemple ne lisait `position` sous un noeud qui recule, ce qui avait
      ete verifie avant de toucher au code. Trou referme au passage :
      `FrozenPeers` rendait un contexte de pair sans historique de position,
      donc `peer(NQ, position(...))` valait zero depuis une vue reculee.
      `docs/no-lookahead.md` §2.5 mis a jour : il est normatif.
- [ ] Relancer les deux experiences seminales **avec manifeste et empreinte
      archives** -- l'audit a montre qu'elles se reproduisent
      (`sma_es_daily` : Sharpe 0,60, empreinte `e96832fb121b91fb`,
      `verify` identique ; walk-forward 9 plis, 57 % dans un pli), mais rien
      n'a ete archive en `runs/` a cette occasion.
- [ ] Obtenir et ingerer la source du Deflated Sharpe (independance des essais).
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
