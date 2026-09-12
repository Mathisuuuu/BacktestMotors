---
type: hub
updated: 2026-09-12
generated: true
---

# hot — etat courant

> [!WARNING] FICHIER AUTO-GENERE — NE PAS EDITER A LA MAIN
> Produit par [`wiki/update_hot.py`](update_hot.py), relance par le hook
> `Stop` a chaque fin de session. Toute modification hors du bloc
> **Next Actions** sera ecrasee sans avertissement.
> Derniere generation : 2026-09-12.

## Current State

| Indicateur | Valeur |
|---|---|
| Pages de wiki | 23 |
| Entrees de log | 106 |
| Derniere activite | 2026-09-12 |
| Idees ecartees (ledger) | 18 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 4 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 52, fix × 23, feat × 13, decision × 12, experiment × 2, setup × 1, lint × 1, audit × 1, refactor × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/paire-es-nq-retour-a-la-moyenne]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-12** — note | fausse alerte de duree, tranchee par une seconde mesure | la suite complete a rendu 4 747 s (79 min) une fois, contre ~100 s d'habitude. Verifie plutot que suppose : suite rapide 41,7 s, partie `slow` normale, suite complete 67 s au passage suivant. Contention externe, pas une regression
- **2026-09-12** — note | trouve par un test sur un exemple REEL, pas sur une fixture | les objets construits dans un test n'ont pas de region libre a exercer : mon test « une note ne change pas le config_hash » passait sur une specification minimale et ratait le cas des noeuds. Celui qui a trouve le defaut lisait `examples/paire_es_nq.json` apres l'avoir annote
- **2026-09-12** — fix | ma premiere version de `note` cassait le `config_hash` la ou elle comptait le plus | `Field(exclude=True)` protege les blocs TYPES, et ne peut rien pour les noeuds, qui vivent dans `strategy.params.rules` -- un `dict[str, object]` que pydantic recopie tel quel. Annoter un seuil faisait passer le `config_hash` de `c686c31f` a `bf0f2f3f`. Corrige : `canonical()` retire les notes a toute profondeur, recursivement, pour qu'une region libre apparue demain soit couverte. `note` devient un mot RESERVE dans une specification -> [[lessons]] L19
- **2026-09-12** — feat | champ `note` : le seul manque reel de JSON, comble sans changer de format | accepte sur tout bloc de specification, tout jeu de parametres de strategie, et TOUT noeud de signal. Texte, ou liste de textes pour plusieurs lignes -- JSON n'ayant pas de chaine multiligne. Ignore par le moteur, absent de `describe()`, absent du rapport. Publie dans les trois contrats engendres, mais dit UNE FOIS dans `contraintes` plutot que repete sur chacun des 22 noeuds. `examples/paire_es_nq.json` est annote pour que la fonctionnalite soit exercee et pas seulement publiee
- **2026-09-12** — decision | YAML envisage puis ecarte, sur trois mesures et non sur un gout | (1) cinq des dix operateurs du vocabulaire cassent ecrits a la main sans guillemets -- `>` devient la chaine VIDE sans erreur, `>=`, `!=`, `-` et `*` levent ; (2) le proces habituel fait a YAML ne tenait pas ici : `17:00` -> `1020` et `NO` -> `False` sont bien produits, mais les modeles stricts les REFUSENT, donc le danger etait ergonomique et non une faille ; (3) YAML gagne reellement en compacite (21 lignes contre 29, indentation 8 contre 10) mais les arbres descendent a la profondeur 12, ou l'absence de delimiteur de fermeture coute plus qu'elle ne rapporte. PyYAML installe dans le bac a sable seulement, pour mesurer plutot qu'affirmer -> [[Failed Ideas/ledger]]
- **2026-09-11** — note | mes trois premiers tests par le runner echouaient, et ils avaient tort | le `Watcher` lisait cinq barres en arriere sans declarer de `warmup_bars` : la borne a refuse, exactement comme elle doit. Une strategie a REGLES, elle, derive son warmup de son arbre -- le cas reel etait donc sur, et c'est le montage a la main qui devait etre corrige. Un test de plus verifie desormais ce chemin declaratif
- **2026-09-11** — fix | ma premiere purge de l'historique balayait tout le dictionnaire a chaque barre | O(portee) par barre, soit 740 millions d'operations sur les 3,7 M de barres minute d'ES pour une profondeur de 200. Remplacee par un retrait en O(1) -- le runner enregistre barre par barre, donc une seule cle sort de la fenetre a chaque appel. Le balayage reste en secours pour le cas non sequentiel. Verifie sans regression : 11,2-12,3 ms des deux cotes sur `_moule_universel`, soit du bruit
- **2026-09-11** — fix | trou referme, que j'avais introduit deux heures plus tot avec `FrozenPeers` | le resolveur de pairs fige construisait un `BarContext` neuf, donc sans historique de position : `peer(NQ, position("quantity"))` rendait zero depuis une vue reculee alors qu'il rendait la bonne valeur depuis la vue courante. Aucun exemple ne l'exercait, donc aucune empreinte ne l'aurait signale. Trouve en enumerant ce que `FrozenPeers` ne transmettait pas

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
