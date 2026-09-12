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
| Pages de wiki | 24 |
| Entrees de log | 134 |
| Derniere activite | 2026-09-12 |
| Idees ecartees (ledger) | 18 |
| Idees en attente (ledger) | 4 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 5 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 62, fix × 28, feat × 19, decision × 17, experiment × 2, essai × 2, setup × 1, lint × 1, audit × 1, refactor × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/allocation-momentum-12-1-trois-regles]] | `termine` | `non-conclusif` | 6 | 2026-09-12 |
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/paire-es-nq-retour-a-la-moyenne]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-12** — fix | P7 : `rsl <commande> > fichier` ecrivait dans l'encodage de la LOCALE (cp1252 sous Windows), pas en UTF-8 | corrige a l'entree de la CLI et non dans `schema` : trois commandes sur neuf saignaient (`schema --what all|spec|strategies`), les six autres passaient parce que leur sortie etait ASCII par hasard. 28 tests, valides en neutralisant le correctif
- **2026-09-12** — fix | Trou ouvert et referme le meme jour : un panneau agrege en intra-journalier avec des seances differentes | ES + FDAX en 4 h donnaient 100 % de lignes a un seul instrument, en silence. `allow_mixed_granularity` est aveugle au cas (meme granularite, ancrage different). Refuse a la validation
- **2026-09-12** — essai | Verification de bout en bout : `sma_crossover@1` sur ES en tranches de 1 h ancrees sur la seance CME | 62 785 barres, Sharpe 0,42, empreinte `f2f0e7e5`. Essai TECHNIQUE - la machinerie etait l'objet, pas la strategie - mais il compte au compteur du Deflated Sharpe, et aucun chiffre n'en a ete exploite pour choisir quoi que ce soit
- **2026-09-12** — note | Le garde-fou « jamais avant la derniere cloture observee » n'est pas theorique : il mord 74 fois sur 16 417 tranches de 4 h d'ES | des barres 1 min horodatees 16:00 cloturent a 16:01, apres la fermeture declaree. Sans lui, 74 barres agregees auraient ete disponibles avant une de leurs composantes. Lecon [[lessons]] L22
- **2026-09-12** — feat | Granularites intra-journalieres : `5min` a `4h`, ancrees sur la SEANCE declaree (`Period`, `tranches_de_seance`, champ SEANCE du montage) | livre ; 3992 tests ; 7 empreintes et 7 config_hash inchanges ; `docs/execution-model.md` §1.3
- **2026-09-12** — essai | Momentum 12-1, trois regles d'allocation, deux niveaux de capital -- SIX essais comptes | les trois premiers etaient inexploitables : la troncature en contrats entiers eliminait 28 a 43 % des noms, les GROS contrats d'abord. A 20 M$ : Sharpe 0,84 / 0,45 / 0,71. Verdict non-conclusif, lecon [[lessons]] L21
- **2026-09-12** — feat | Allocation transversale : `ranking@1` sait repartir (`equal_weight`, `inverse_volatility`, `signal`), `MultiContext.contract_value` donne la taille d'un contrat | livre ; 3923 tests ; 7 empreintes et 7 config_hash inchanges ; la combinaison allocation-en-argent + sizing est refusee a la validation
- **2026-09-12** — fix | Les plafonds etaient evalues ordre par ordre contre le portefeuille commite : un rebalancement transversal de dix ordres les franchissait tous ensemble | `max_positions=2` laissait detenir SIX instruments sur momentum_12_1 ; corrige par reservation de fournee, verifie en rejouant les fills. Lecon [[lessons]] L20

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
- [x] **P7 resolu (2026-09-12).** `sys.stdout` prenait l'encodage de la locale
      des qu'il etait redirige, donc du cp1252 sous Windows. Corrige a l'ENTREE
      (`cli.sortie_en_utf8`), pas dans `schema` : le defaut appartenait a toute
      commande qui ecrit.
      Trois choses apprises en le corrigeant. **Trois** commandes sur neuf
      etaient cassees, pas deux -- la premiere mesure avait oublie
      `schema --what spec` ; les six autres passaient parce que leur sortie
      etait ASCII par hasard. La prediction « la commande levera » etait
      EXACTE : verifie avant correction, un `→` donne
      `UnicodeEncodeError`, code 1, sortie tronquee. Et les tests ont ete
      valides en neutralisant le correctif -- sans quoi ils auraient pu etre
      verts sans rien garder.
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
- [x] **Contraintes de portefeuille : FAIT (2026-09-12).** Quatre plafonds sous
      `risk.limits` ([limites.py](../src/rsl/engine/limites.py)), normes en
      `docs/execution-model.md` §6.3. Deux choix de conception qui n'etaient pas
      evidents : un plafond ne refuse un ordre que s'il **aggrave** la mesure
      qu'il depasse - sinon une baisse d'equity enfermerait le portefeuille
      au-dessus de son plafond - et un bloc `limits` entierement nul est retire
      de la forme canonique, sans quoi les 7 `config_hash` archives changeaient
      pour un champ qui ne dit rien. Defaut trouve au passage et corrige :
      la contrainte ne contraignait rien sur un rebalancement transversal
      ([[lessons]] L20).
- [x] **Allocation : FAITE (2026-09-12).** `ranking@1` sait repartir -
      `equal_weight`, `inverse_volatility`, `signal`, plus `fixed` qui NOMME
      enfin le defaut historique ([allocation.py](../src/rsl/strategies/allocation.py),
      `docs/execution-model.md` §6.4). Deux points a retenir : la combinaison
      d'une allocation en argent et d'un `risk.sizing` est **refusee a la
      validation** - le dimensionnement passe en dernier et ecraserait la
      repartition en silence ; et la troncature en contrats entiers elimine les
      GROS contrats d'abord, ce qui a rendu trois essais sur six inexploitables
      avant qu'un compteur ne le dise ([[lessons]] L21).
- [x] **Granularites intra-journalieres : FAITES (2026-09-12), ancrees sur la
      SEANCE.** `5min` `10min` `15min` `30min` `1h` `2h` `4h`, refusees sans
      `data[].session` - `docs/execution-model.md` §1.3. L'arbitrage a ete rendu
      en faveur de la seance declaree contre l'epoque UTC ; le montage a gagne
      un champ SEANCE, pre-rempli par place mais a relire.
      Trois points a connaitre avant de s'en servir : la derniere tranche de
      chaque seance est plus COURTE (23 h en 4 h = cinq pleines et une de 3 h,
      conservee car c'est la cloture) ; le decoupage est MONO-INSTRUMENT, deux
      seances differentes n'ayant plus de frontiere commune ; et une
      declaration exacte ne decrit pas le fichier - 74 tranches d'ES sur 16 417
      auraient fuit sans le garde-fou ([[lessons]] L22).
- [x] **Panneau intra-journalier : GARDE POSE le meme jour.** Mesure avant de
      reporter : ES (CME) + FDAX (Eurex) en 4 h donnaient **18 653 lignes sur
      18 654 a un seul instrument**, soit 100 % - une strategie transversale
      n'y aurait rien a comparer et n'aurait leve aucune erreur. La combinaison
      est refusee a la validation ; tous les instruments d'un panneau agrege en
      intra-journalier doivent declarer la MEME seance.
- [ ] Obtenir et ingerer la source du Deflated Sharpe (independance des essais).
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
