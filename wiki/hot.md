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
| Entrees de log | 91 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 17 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 46, fix × 18, feat × 12, decision × 10, setup × 1, lint × 1, experiment × 1, audit × 1, refactor × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | fausse alerte de performance, tranchee par une mesure temoin | la suite rapide passait de 33 a 51 s apres le decoupage, ce qui aurait pu signifier une memoisation desactivee en silence -- plus lent, jamais faux, donc invisible aux tests. Verifie : `sma@1`, un chemin que le decoupage ne touche pas, etait AUSSI deux fois plus lent (10,65 contre 5,43 us). La machine tournait au ralenti, pas le code. Une mesure sans temoin ne tranche rien
- **2026-09-11** — note | la facade a perdu un nom pendant le decoupage, et seule la suite l'a dit | `ruff --fix` retire un import qui ne sert qu'a etre reexporte : `_NODES` a disparu, et `test_extension_closure.py` a echoue a la collecte. Corrige en pointant ce test vers `noeuds.contrat`, son module REEL -- un nom prive qui transite par une facade est un nom prive qu'on croit public. Et `test_couches.py` verifie desormais que tout ce que les familles DEFINISSENT passe par la facade, verification elle-meme validee en retirant `Rolling` et en constatant l'echec
- **2026-09-11** — refactor | A-P3.3 : `signals.py`, 1 949 lignes, devient une facade de 168 | le code vit dans `rsl/strategies/noeuds/` : `contrat` (ce qu'est un noeud), `feuilles` (ce qui lit le monde), `fenetres` (ce qui regarde plusieurs barres), `operateurs` (ce qui combine), `raccourcis`. Les quatre familles importent `contrat`, jamais l'inverse, et un test le verifie par analyse d'AST. Aucun import du depot ne change. Verifie : 7 empreintes inchangees, et les TROIS contrats engendres (squelette, schema des signaux, schema complet) identiques au fichier pres -- `list_node_types()` triant, l'ordre d'enregistrement n'entre nulle part
- **2026-09-11** — feat | A-P3.2 : la non-regression de bout en bout cesse d'etre verifiee A LA MAIN | depuis le debut de la session je relançais les exemples et comparais les empreintes a l'oeil. `tests/test_integration_reelle.py` le fait desormais : les 7 empreintes de resultat, les 7 hash de configuration, le nombre de trades, le determinisme de deux runs, l'equivalence avec et sans memoisation (dans un interpreteur separe, `RSL_NO_MEMO` etant lu a l'import), et les 136 primitives sur une VRAIE serie -- trouee, avec des week-ends de 49 h, ou le synthetique ne va pas. Marqueur `slow` : 12 tests avant, 183 apres. `tests/fixtures/empreintes_attendues.json` devient la verite terrain
- **2026-09-11** — fix | A-P3.1 : la teinte des cartes du tableau de bord cesse d'etre greffee sur un widget | `app.py` posait `valeur.teinte = teinte` sur un `tk.Label` puis la relisait par `getattr(etiquette, "teinte", "neutre")`. Deux defauts : une greffe sur un objet d'une bibliotheque tierce, que `mypy` ne couvrait que par un `type: ignore` ; et un defaut `"neutre"` qui rendait l'echec MUET -- une cle mal orthographiee peignait tout en noir sans qu'aucun test ni aucun lint ne le voie. La table `TEINTES` est desormais DERIVEE de `GROUPES`, ou la teinte etait deja declaree, et une cle inconnue leve
- **2026-09-11** — note | `Context.data_token` rejoint la surface publique, et ce qu'il a fallu pour que ce soit acceptable | premiere version : le jeton ETAIT le magasin, ce qui donnait l'historique complet -- futur inclus -- a qui sait le caster. `test_forbidden_access.py` l'a refuse, et il avait raison. Corrige : le jeton est un `object()` NU porte par `BarStore`, sans aucun attribut. Ni le magasin (fuite), ni un entier d'identite (reattribue apres ramassage, donc deux series confondues en silence)
- **2026-09-11** — note | semantique de `peer` sous `rolling`, mise au jour par le travail sur la memoisation | dans `rolling(zscore, 120, close / peer(NQ, close))`, le terme NQ vaut la barre COURANTE pour les 120 decalages : il ne glisse pas avec la fenetre. Ce n'est ni documente ni evidemment voulu. NON corrige ici -- le changer modifierait l'empreinte archivee de `examples/paire_es_nq.json`, donc c'est une decision a prendre a part
- **2026-09-11** — fix | la memoisation a change une empreinte avant d'etre corrigee, et c'est ce qui l'a rendue sure | `examples/paire_es_nq.json` passait a 634 remplissages au lieu de 30. Cause : `BarContext.shifted` recopie le resolveur de pairs et l'etat de position, donc un sous-arbre contenant `peer` ou `position` ne depend PAS que de `(serie, barre)`. Regle demontree et non supposee : un `BarContext` porte exactement quatre attributs, la cle en couvre deux, les deux autres ne s'atteignent que par ces deux noeuds. Ces sous-arbres ne sont donc pas memoises -> [[lessons]] L17

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
- [ ] **Decision a prendre : la semantique de `peer` sous `rolling`.** Le terme
      distant vaut la barre COURANTE pour tous les decalages de la fenetre - il
      ne glisse pas avec elle. Mis au jour par le travail sur la memoisation, ni
      documente ni evidemment voulu. Le corriger changerait l'empreinte archivee
      de `examples/paire_es_nq.json`.
- [ ] Relancer les deux experiences seminales **avec manifeste et empreinte
      archives** -- l'audit a montre qu'elles se reproduisent
      (`sma_es_daily` : Sharpe 0,60, empreinte `e96832fb121b91fb`,
      `verify` identique ; walk-forward 9 plis, 57 % dans un pli), mais rien
      n'a ete archive en `runs/` a cette occasion.
- [ ] Obtenir et ingerer la source du Deflated Sharpe (independance des essais).
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
