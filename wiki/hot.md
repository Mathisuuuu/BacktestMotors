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
| Entrees de log | 117 |
| Derniere activite | 2026-09-12 |
| Idees ecartees (ledger) | 18 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 4 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 58, fix × 23, feat × 16, decision × 14, experiment × 2, setup × 1, lint × 1, audit × 1, refactor × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/paire-es-nq-retour-a-la-moyenne]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-12** — note | dette assumee et tenue par un test : la table des dossiers de `gui/montage.py` | elle recopie l'arborescence reelle (`ES` -> `indices`, `GC` -> `metaux`...), que la table d'instruments ne porte pas. Le vrai correctif serait de l'y ajouter, et il touche a la couche donnees. En attendant, `test_gui_montage.py` verifie qu'elle couvre EXACTEMENT les racines connues, donc qu'un instrument ajoute ne soit pas oublie
- **2026-09-12** — note | deux details de la fenetre, corriges parce qu'un defaut arbitraire n'est pas neutre | (1) l'actif propose a l'ouverture etait `6A`, premier par ordre alphabetique, un contrat sur le dollar australien que personne ne teste en premier -- c'est `ES` desormais, choisi expres ; (2) `ttk.Notebook.select` n'etant pas annotee en amont, un `type: ignore` CIBLE sur une ligne plutot que l'elargissement de l'exception `disallow_untyped_calls` a sept cents lignes d'appels tkinter
- **2026-09-12** — feat | onglet MONTAGE dans la fenetre : actif, agregation, capital, contrats, frais, glissement | six reglages, ceux qu'on change d'un essai a l'autre. Les autres (`lag_bars`, `intrabar_priority`, `margin_policy`...) gardent les defauts du socle, qui sont des choix de prudence : les rendre reglables d'un clic inviterait a les desactiver sans y penser. La logique vit dans `gui/montage.py`, SANS tkinter, donc testee -- meme separation que `gui/model.py`
- **2026-09-12** — note | les 7 exemples se recomposent SANS UNE SEULE DIFFERENCE | chaque specification complete a ete coupee en `examples/strategies/` + `examples/reglages/`, et les recoller redonne exactement la forme canonique d'origine -- y compris pour les moules transversaux. Les 7 empreintes de resultat sont inchangees. Le test est parametre sur le repertoire : un exemple ajoute demain est couvert sans qu'une ligne soit ecrite
- **2026-09-12** — decision | le `config_hash` continue de couvrir le TOUT, et c'est le point non negociable | `compose()` construit une `BacktestSpec` complete, qui reste ce qui est hache et archive. Verifie : changer l'actif, le capital ou le glissement change le hash. La separation est une commodite d'ECRITURE, jamais un relachement de la reproductibilite. `compose()` ne redeclare aucun champ non plus -- il fait valider le dictionnaire de reglages PAR `BacktestSpec`, donc rien ne peut diverger d'elle
- **2026-09-12** — feat | la STRATEGIE est separee de son MONTAGE | une `BacktestSpec` melangeait la decision (`strategy`) et le montage (`data`, `initial_cash`, `execution`, `risk`) : la meme strategie sur ES et sur NQ demandait deux fichiers presque identiques, et rien ne disait lequel des deux mots avait change. Un fichier `"format": "rsl-strategy@1"` ne porte desormais que la decision ; le reste se choisit dans la fenetre ou par `rsl run --settings`. Le symbole est INJECTE a la composition, la detection se faisant sur le modele de parametres du moule et non sur une liste tenue a la main
- **2026-09-12** — note | seul le `config_hash` de `_moule_universel` change, pas son empreinte de resultat | `190584bb` -> `d990888c`. C'est la signature exacte d'un changement de SPECIFICATION sans changement de resultat, et c'est precisement ce que `test_integration_reelle.py` a ete ecrit pour rendre lisible. Les 7 empreintes de resultat sont inchangees
- **2026-09-12** — note | le moule universel exerce le noeud, et j'ai verifie qu'il n'etait pas INERTE | coupe-circuit a -12 % de drawdown ajoute a `exit_long` et `exit_short`. L'empreinte ne bouge pas -- exactement le piege de [[lessons]] L18. Verifie plutot que suppose : le drawdown maximum du run est de -9,65 %, le seuil n'est donc jamais atteint, et abaisser le seuil a -5 %, -2 % puis -1 % CHANGE bien l'empreinte a chaque fois. Le noeud est vivant

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
