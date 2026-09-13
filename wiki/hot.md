---
type: hub
updated: 2026-09-13
generated: true
---

# hot — etat courant

> [!WARNING] FICHIER AUTO-GENERE — NE PAS EDITER A LA MAIN
> Produit par [`wiki/update_hot.py`](update_hot.py), relance par le hook
> `Stop` a chaque fin de session. Toute modification hors du bloc
> **Next Actions** sera ecrasee sans avertissement.
> Derniere generation : 2026-09-13.

## Current State

| Indicateur | Valeur |
|---|---|
| Pages de wiki | 26 |
| Entrees de log | 160 |
| Derniere activite | 2026-09-13 |
| Idees ecartees (ledger) | 20 |
| Idees en attente (ledger) | 4 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 7 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 71, fix × 34, feat × 25, decision × 19, essai × 4, experiment × 2, setup × 1, lint × 1, audit × 1, refactor × 1, perf × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/allocation-momentum-12-1-trois-regles]] | `termine` | `non-conclusif` | 6 | 2026-09-12 |
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/paire-es-nq-retour-a-la-moyenne]] | `termine` | `non-conclusif` | 1 | 2026-09-12 |
| [[experiments/pbo-grille-large-462-sma]] | `termine` | `negatif` | 462 | 2026-09-12 |
| [[experiments/pbo-grille-sma-es-quotidien]] | `termine` | `negatif` | 16 | 2026-09-12 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-12 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-13** — note | Effet sur la strategie Zarattini qui avait revele le defaut : 6,7 h estimees -> 3,05 h | le reste est le `rolling(stride=390)`, structurel : avec un pas de 390, les positions lues a deux barres consecutives sont DISJOINTES, donc rien ne se reutilise
- **2026-09-13** — note | Le diagnostic de depart etait FAUX : j'attribuais le cout a la somme recalculee, il venait de 400 creations de `BarContext` par barre | un accumulateur courant aurait ete plus rapide encore et aurait change les derniers bits - `np.sum` somme par paires, l'addition sequentielle non. Le tampon garde les valeurs et laisse numpy reduire. Lecon [[lessons]] L26
- **2026-09-13** — perf | `cumulative` : **1249 -> 36,5 us par barre**, soit 34 fois, et les 7 empreintes INCHANGEES | en deux etapes. (1) La memoire etait consultee APRES `ctx.shifted(lag)`, donc elle payait le cout qu'elle evitait ; sa cle se calcule pourtant sans reculer (`n_bars_seen - lag`). Gain profitant aussi a `rolling` et `bars_since` : 1249 -> 429. (2) Un tampon numpy par seance qui n'ajoute qu'une valeur par barre : 429 -> 36,5
- **2026-09-13** — fix | Ma garde contre un `risk.limits` ignore ne gardait rien : elle lisait `actives` sur la SPECIFICATION, ou il n'existe pas | chaine de `getattr` rendant `False` en silence. Remplacee par un acces type. Trouve par le test qui l'exerce
- **2026-09-13** — note | Mesure des agregations que le simulateur Nautilus EXECUTE : MINUTE, HOUR, DAY, WEEK oui ; MONTH non | fige dans `pont.AGREGATIONS_EXECUTABLES`, avec un reetiquetage du mensuel en quotidien. Les barres restent mensuelles - leurs horodatages le disent - et Nautilus ne les reagrege jamais puisqu'elles arrivent deja agregees
- **2026-09-13** — fix | Deux defauts SILENCIEUX dans le portage transversal, tous deux rendant capital intact et zero position | (1) declencher a la premiere barre d'un instant : les neuf autres instruments n'avaient pas de marche, 684 ordres emis et 684 rejetes ; (2) Nautilus ne remplit AUCUN ordre sur des barres etiquetees `MONTH` - mesure a la chaine de caracteres pres. Lecon [[lessons]] L25
- **2026-09-13** — feat | Le vocabulaire TRANSVERSAL tourne sur Nautilus : `panel_rules@1` et `ranking@1` par reconstitution de la coupe | la ligne de panneau est reconstituee en COMPTANT les barres attendues (`present_symbols`), et traitee a la derniere. `momentum_12_1` donne 97 positions et 273 fills la ou notre moteur fait 107 trades
- **2026-09-13** — fix | Mon test de concordance passait POUR LA MAUVAISE RAISON : il tolerait 0,5 % et portait sur le seul exemple qui negocie dix fois | remplace par `test_nautilus_coexistence.py`, qui NOMME l'ecart et le borne par le BAS. Et son temoin ne neutralisait rien - il remplacait une file que `on_bar` reassigne des la premiere barre

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

## Deux moteurs, et le contrat entre eux (2026-09-13)

Branche `migration-nautilus`. `main` est intact.

| | notre moteur | Nautilus |
|---|---|---|
| sert a | la RECHERCHE reproductible | la VALIDATION croisee, et le futur live |
| remplit a | `open[t+1]` | `close[t+1]` |
| porte | 7 empreintes, 493 essais, PBO, DSR | backtest et live partagent le meme noyau |

**Ce qu'on ne compare JAMAIS** : les equity des deux moteurs. Elles divergent de
0,5 % sur une strategie qui negocie dix fois et de 24 % sur une qui en negocie
dix-huit, parce que l'ecart de convention se COMPOSE a chaque trade. Ce n'est
pas une imprecision, c'est deux mesures differentes ([[lessons]] L24).

**Ce qui est partage, et qui doit le rester** : le vocabulaire JSON. Un meme
fichier decrit la meme strategie des deux cotes - c'est toute la valeur de la
coexistence, et `tests/test_nautilus_coexistence.py` la garde.

- [ ] **Alimenter Nautilus en TICKS plutot qu'en barres.** C'est le regime pour
      lequel son moteur est fait, et la seule voie qui rendrait les deux
      comparables : les fills retrouveraient un sens physique au lieu de tomber
      sur une cloture de barre. Cout a mesurer - 33 M de barres minute
      deviendraient des quotes.
- [x] **Transversal porte (2026-09-13).** `panel_rules@1` et `ranking@1`
      tournent sur Nautilus : la coupe est reconstituee en COMPTANT les barres
      attendues, et traitee a la derniere. `momentum_12_1` rend 97 positions et
      273 fills la ou notre moteur fait 107 trades.
      **Deux defauts silencieux trouves en chemin**, tous deux rendant capital
      intact et zero position : declencher a la premiere barre d'un instant
      (684 ordres, 684 rejets) et l'agregation `MONTH` que le simulateur
      n'execute pas. Un troisieme, dans ma propre garde, lisait `actives` sur la
      specification ou il n'existe pas. Lecon [[lessons]] L25.
      Ce que le pont transversal ne porte PAS, et qu'il refuse : le
      `RiskManager` - dimensionnement, plafonds de portefeuille, allocation.
- [x] **`cumulative` corrige (2026-09-13) : 1249 -> 36,5 us par barre, 34x.**
      Les 7 empreintes sont INCHANGEES, ce qui etait la condition.
      Le diagnostic de depart etait faux : le cout ne venait pas de la somme
      recalculee mais de 400 creations de `BarContext` par barre - la memoire
      etait consultee APRES la vue qu'elle devait eviter. Consulter d'abord
      profite aussi a `rolling` et `bars_since`.
      Et l'accumulateur courant envisage aurait CHANGE les derniers bits :
      `np.sum` somme par paires ([[lessons]] L26).
- [ ] **`rolling` a `stride` : le dernier segment lent.** 539 us/barre sur le
      z-score strie de la strategie Zarattini, et c'est STRUCTUREL - avec un pas
      de 390, les positions lues a deux barres consecutives sont disjointes,
      donc aucune reutilisation n'est possible. Zarattini passe de 6,7 h a
      3,05 h ; le reste est la. A trancher : un cas mesure justifie-t-il une
      primitive dediee, ou ce regime (minute + stride) est-il hors perimetre ?
- [ ] **Decider du sort de la branche.** Fusionner `migration-nautilus` dans
      `main` maintenant, ou attendre que le transversal passe ? Rien n'est
      supprime, donc la fusion est sans risque ; c'est une question de lisibilite
      de l'historique.

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
- [ ] **A-P2 : MESURE le 2026-09-12, et il reste beaucoup moins qu'annonce.**
      L'entree precedente decrivait un probleme deja resolu aux trois quarts
      par la memoisation du 2026-09-11. Mesure sur ES quotidien, panneau ES+NQ,
      400 barres, avec et sans `RSL_NO_MEMO` :

      | Sous-arbre sous `rolling(zscore,120)` | sans memo | avec memo | gain |
      |---|---|---|---|
      | `arith(sma/sma)` — memoisable | 2864 us | 352 us | **8x** |
      | `arith(close/peer)` — NON memoisable | 1461 us | 1358 us | **1,07x** |

      Les deux lignes ne comparent pas la meme expression - le sous-arbre a
      pair est plus simple - donc le rapport 4x entre 1358 et 352 mesure ce
      qu'on paie aujourd'hui, pas le cout du `peer` lui-meme. Le chiffre qui
      tranche est le **1,07x** : la memoisation n'apporte RIEN au segment a
      pair, et c'est le seul qui reste.
      Ordre de grandeur restant : 1,41 h pour un signal a pair sur les 3,7 M de
      barres minute d'ES, contre 0,37 h pour son equivalent memoisable.
      Ce qu'il faut trancher n'est donc plus « comment accelerer `rolling` »
      mais « un z-score de ratio ES/NQ a la minute est-il un cas qu'on veut
      vraiment traiter ». A l'echelle QUOTIDIENNE, ou vivent tous les exemples,
      le sujet n'existe pas : 2753 barres a 1358 us font 3,7 secondes.
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
- [x] **Archivage des essais : FAIT (2026-09-12).** `essais/registre.jsonl`,
      versionne, une ligne par essai, plus le rapport complet a cote
      ([essais.py](../src/rsl/essais.py)). `rsl run --archive` enregistre et
      calcule le DSR contre TOUS les essais du depot ; `rsl essais` montre ce
      que le compteur contient.
      **14 essais archives** : les 7 exemples du depot et les 7 de la journee.
      Ce que cela revele : `TrialLog` vivait dans un processus, donc chaque run
      se declarait « 1 essai » et son DSR se confondait avec son PSR. **Tous
      les DSR publies avant cette date sont des PSR deguises** - la paire ES/NQ
      passe de 0,9722 a 0,9546 une fois comptee au troisieme rang.
      `runs/` reste ignore : c'est la sortie de `--out`, un fichier qu'on
      regarde et qu'on jette. `essais/` est ce qu'on garde.
- [x] **Walk-forward archive : FAIT (2026-09-12).** L'arbitrage a ete rendu en
      faveur de « un walk-forward = UN essai » : un pli est la meme
      configuration sur d'autres donnees, pas une configuration de plus. C'est
      ce que `walkforward.py` disait en commentaire depuis sa premiere version
      ; c'est desormais executable.
      Trouve en l'ecrivant : il n'existait aucun Sharpe agrege LEGITIME a
      enregistrer. Le rapport ne publiait qu'une moyenne des Sharpe par pli,
      qui donne le meme poids a un pli ayant negocie une fois et a un pli ayant
      negocie tout du long. La serie GROUPEE - rendements hors echantillon des
      neuf plis bout a bout - donne 0,62 annualise contre 0,32 pour la moyenne.
      Les deux sont publies ; c'est la groupee qui entre au registre.
      **15 essais** au registre. Les deux experiences seminales y sont, run
      simple ET walk-forward.
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
- [x] **PBO / CSCV : IMPLEMENTEE ET APPLIQUEE (2026-09-12).** `rsl pbo`,
      [surapprentissage.py](../src/rsl/metrics/surapprentissage.py) pour le
      calcul, [pbo.py](../src/rsl/pbo.py) pour la matrice. Le protocole etait
      fige depuis le 2026-09-10 et attendait son implementation.
      **Le resultat est mauvais, et c'est ce qui le rend utile** : la grille SMA
      4x4 d'ES quotidien rend une PBO de 0,70 a 0,80, et le DSR de l'exemple
      phare tombe de 0,9719 SIGNIFICATIF a 0,0000 une fois les 31 essais du
      registre comptes. Voir [[experiments/pbo-grille-sma-es-quotidien]].
      Deux problemes de METHODE trouves en chemin : une grille de fenetres
      inegales ne partage pas son echantillon (quatre longueurs pour seize
      configurations), et quatre configurations ne negocient pas du tout sur une
      sous-periode.
- [x] **Grille elargie : FAIT (2026-09-12).** 462 configurations - rapide 2-40
      pas 2, lent 20-250 pas 10 - 1021 s de calcul, toutes archivees.
      **Elargir a EMPIRE le chiffre** : PBO 0,833 sur 462 contre 0,80 sur seize,
      exactement comme la theorie l'annonce. La demande du ledger est satisfaite
      et la reponse ne change pas de signe.
      Le tableau par S est a lire avec precaution : a partir de S=6 le retrait
      des inactives elimine SYSTEMATIQUEMENT les fenetres longues (357 sur 462 a
      S=8), donc la PBO y porte sur un sous-ensemble biaise. Seuls S=2 et S=4
      preservent la grille entiere.
      Voir [[experiments/pbo-grille-large-462-sma]].
- [ ] **Ce qui manque maintenant n'est plus une grille, c'est un ECHANTILLON.**
      2501 rendements quotidiens, dix ans, un instrument. Une grille plus dense
      sur les memes donnees ajoute des essais correles, pas de l'information.
      Trois voies : d'autres instruments (dix sont sur le disque), une
      granularite plus fine (les tranches intra-journalieres existent depuis ce
      matin), ou un echantillon plus long qu'on n'a pas.
- [ ] **Choisir une configuration pour une raison EXTERIEURE aux donnees.**
      C'est la conclusion de l'essai PBO, et ce n'est pas une tache de code : la
      CSCV qualifie le fait d'avoir pris le maximum d'une grille. Une
      configuration choisie sur une hypothese economique n'est pas concernee par
      ce chiffre - encore faut-il en formuler une.
- [ ] **Obtenir et ingerer la source du Deflated Sharpe (independance des
      essais). C'est devenu le point le plus important de cette liste.**
      Le balayage du 2026-09-12 a montre, en chiffres, que l'hypothese est
      violee et que la violation va dans le mauvais sens : ajouter 462 essais
      CORRELES a fait BAISSER le maximum attendu sous H0 de 0,1600 a 0,0663.
      Remplir le compteur d'essais quasi identiques AFFAIBLIT la correction au
      lieu de la durcir ([[lessons]] L23).
      Le garde existant n'y peut rien : `Registre.doublons` ne repere que les
      resultats bit-identiques, et 462 croisements voisins ont 462 empreintes.
      Ce qu'il faudrait : une notion de distance entre essais, ou un nombre
      d'essais EFFECTIF. Les deux demandent la source.
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
