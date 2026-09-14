---
type: hub
updated: 2026-09-14
generated: true
---

# hot — etat courant

> [!WARNING] FICHIER AUTO-GENERE — NE PAS EDITER A LA MAIN
> Produit par [`wiki/update_hot.py`](update_hot.py), relance par le hook
> `Stop` a chaque fin de session. Toute modification hors du bloc
> **Next Actions** sera ecrasee sans avertissement.
> Derniere generation : 2026-09-14.

## Current State

| Indicateur | Valeur |
|---|---|
| Pages de wiki | 27 |
| Entrees de log | 193 |
| Derniere activite | 2026-09-14 |
| Idees ecartees (ledger) | 22 |
| Idees en attente (ledger) | 4 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 8 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 80, fix × 41, feat × 32, decision × 20, mesure × 8, essai × 4, experiment × 2, setup × 1, lint × 1, audit × 1, refactor × 1, perf × 1, bug × 1

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
| [[experiments/zarattini-nq-intraday-60-30]] | `termine` | `negatif` | 3 | 2026-09-13 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-14** — note | L'attribution horaire n'est PAS un outil d'optimisation | retenir les heures qui gagnent est du sur-ajustement, et les tranches ne sont pas des essais independants - memes seances, memes regimes, meme strategie. L'usage legitime est de constater une MECANIQUE, pas de choisir un seuil
- **2026-09-14** — feat | **Attribution horaire** dans le rapport : trades, P&L net et hit par heure depuis l'ouverture declaree | premier diagnostic d'une strategie intraday, jusqu'ici inaccessible. Sur `intraday_opening_range` : -55 987 sur la tranche +2 h et -32 877 sur +4 h, gains partout ailleurs. Un garde-fou REFUSE un tableau dont les lignes ne totalisent pas les trades fermes - incomplet, il se lirait comme complet
- **2026-09-14** — fix | **`is_last` marquait 71,9 % des barres** au lieu d'une par seance : 90 515 sur 125 806 sur ES en 30 minutes | l'ecriture etait `ts >= cloture`, vraie pour toutes les barres d'apres-cloture, qui appartiennent encore a la seance. Aucune des 7 empreintes ne bouge : elles sont toutes quotidiennes, regime ou une seance contient une barre et ou le defaut est invisible. Lecon [[lessons]] L31
- **2026-09-14** — fix | **`bars_held` et `entry_price` decrivaient deux trades differents** ; le suivi recopie desormais la frontiere du portefeuille | `paire_es_nq` : 149 -> 33 trades, dont **121 sur 149 etaient des artefacts** d'une boucle sortie/re-entree. Empreinte de resultat changee, `config_hash` INCHANGE - la specification n'a pas bouge. Lecon [[lessons]] L32
- **2026-09-14** — feat | **Marge de JOUR** : `execution.intraday_margin_ratio` allege la marge immobilisee | la table porte des marges OVERNIGHT (ES 17 000, NQ 27 000) qu'un intraday ne paie pas. Un RATIO declare plutot qu'une table de marges de jour : celle-ci est fixee par le COURTIER, aucun chiffre publie a recopier. Laisse a `null`, le champ est retire de la forme canonique - sans quoi les 7 `config_hash` changeaient
- **2026-09-14** — note | Les marges declarees sont des marges OVERNIGHT (ES 17 000, NQ 27 000) | une strategie intraday paie chez un courtier une marge de jour, d'un ordre de grandeur plus faible. Tout dimensionnement intraday du depot est donc trop contraint - c'est ce qui a fait lire le run Zarattini comme une strategie perdante
- **2026-09-14** — mesure | Consequence : « arreter apres N pertes dans la seance » n'est PAS exprimable, alors que « un seul trade par seance » l'est | le second ne demande que de compter des entrees - verifie, 12,54 -> 0,89 trade par seance. Le premier demande l'ISSUE d'un trade passe, donc sa frontiere. Deux formulations essayees (`position == 0`, puis remise a zero de `bars_held`) : aucune ne mord
- **2026-09-14** — mesure | Ce n'est pas un cas de bord : sur un momentum ES 30 min, **30 119 barres sur 37 615 portent DEUX fills** - sortie et re-entree immediates | la position n'est observee a plat que 3 748 fois pour 33 867 trades fermes. Le portefeuille connait la frontiere entre trades ; le vocabulaire de signaux ne la voit pas

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
- [x] **`rolling` a `stride` : le probleme n'existait pas (2026-09-13).**
      Les 539 us/barre etaient un artefact - mesure sur un noeud fraichement
      construit, donc une memoisation VIDE. A chaud : **52,1 us**, douze fois
      moins. Le run Zarattini a ete MESURE de bout en bout : **15 min 55 s**,
      contre 6,7 h puis 3,05 h puis 22 min estimees. Les trois se trompaient par
      la meme faute ([[lessons]] L27).
      Consequence : la question « ce regime est-il hors perimetre » ne se pose
      plus, et la reecriture en C# envisagee sur la foi des 3 h est ECARTEE,
      motif chiffre au [[Failed Ideas/ledger]].
## Intraday : les trois points faits, et le bug trouve en chemin (2026-09-14)

- [x] **Marge de JOUR** (`execution.intraday_margin_ratio`). La table porte des
      marges OVERNIGHT qu'un intraday ne paie pas. Un RATIO declare, parce que
      la marge de jour est fixee par le COURTIER et qu'aucun chiffre publie
      n'existe a recopier.
- [x] **Frontiere de trade.** `bars_held` et `entry_price` decrivaient deux
      trades differents quand la sortie et la re-entree partageaient une barre.
      `paire_es_nq` : 149 -> 33 trades, dont **121 sur 149 etaient des
      artefacts**. Empreinte changee, `config_hash` inchange ([[lessons]] L32).
- [x] **Attribution horaire** dans le rapport. Sur `intraday_opening_range` :
      -55 987 sur la tranche +2 h, -32 877 sur +4 h, gains partout ailleurs.
      Ce n'est PAS un outil d'optimisation - voir l'en-tete du module.
- [x] **`is_last` marquait 71,9 % des barres** au lieu d'une par seance.
      Trouve en cherchant pourquoi une garde ne mordait pas. Invisible aux 7
      empreintes parce qu'elles sont toutes quotidiennes, regime ou une seance
      contient une barre ([[lessons]] L31).

- [ ] **« Arreter apres N pertes dans la seance » n'est TOUJOURS pas
      exprimable.** C'etait la motivation du point 2, et le correctif n'a pas
      suffi. Deux formulations essayees, aucune ne mord. Ce qui reste a
      elucider : `cumulative` sur un sous-arbre qui lit `position` est-il juste ?
      Son tampon de seance n'a jamais ete conditionne a la memoisabilite, et
      l'historique de position est BORNE par le `warmup_bars` declare - deux
      pistes, aucune verifiee.
- [ ] **Les trois exemples intraday n'ont pas ete rejoues** depuis les deux
      correctifs. Leurs chiffres publies au log du 2026-09-14 sont ceux d'AVANT.

## Intraday : inventaire d'expressivite (2026-09-14)

**Inventaire MESURE**, pas suppose : 13 familles canoniques ecrites en JSON,
construites et evaluees. **12 sur 13 s'ecrivaient deja.**

| Famille | Etat |
|---|---|
| momentum depuis l'ouverture, VWAP ancre, plus haut de la veille, gap, plus haut de seance, cloture forcee, fenetre horaire, stop temporel | deja couvert |
| volume relatif et volatilite AU MEME MOMENT des seances passees | couvert depuis le 2026-09-13 (`rolling.across`, `session_lag`) |
| opening range, etendue de la premiere heure | n'etaient possibles que par un ARTIFICE - voir ci-dessous |
| grille horaire periodique | etait IMPOSSIBLE, faute de modulo |
| multi-horizon (5 min filtre par le quotidien) | deja couvert : `alias` + `panel.allow_mixed_granularity`. Mesure : ES 15 min + ES quotidien, **100 %** des lignes portent les deux series |

Deux ajouts ont ferme les deux trous :

- **`arith %`** - une grille horaire en trois noeuds au lieu de douze
  comparaisons ;
- **`cumulative.mask`** - agreger sur une TRANCHE de seance. Il remplace une
  sentinelle `if_then_else(..., -1e18)` qui rendait **-1e+18** sur une tranche
  vide, faisant declencher la regle a chaque barre. Quatrieme occurrence de la
  famille L18 / L25 / L28, et la pire : les trois premieres faisaient trop PEU
  negocier, celle-ci fait negocier TROP ([[lessons]] L30).

Trois exemples executables : `intraday_opening_range`,
`intraday_vwap_reversion`, `intraday_momentum_filtre_quotidien`. **Aucun n'a
d'essai archive** - ce sont des FORMES, pas des resultats.

- [ ] **Le cout d'un balayage intraday n'est pas mesure.** `construire_grille`
      prend n'importe quelles `BacktestSpec`, donc il marche deja. Mais un run
      d'ES en 5 minutes porte 742 395 barres et prend plusieurs minutes ; une
      grille de cinquante configurations se compte en heures. Avant de lancer un
      balayage intraday, mesurer UN run et multiplier - c'est exactement
      l'erreur que [[lessons]] L27 consigne pour n'avoir pas ete faite.
- [ ] **Aucune des trois formes intraday n'a ete evaluee.** Les seuils - 30
      minutes d'opening range, deux ecarts-types au VWAP, SMA 50 quotidienne -
      sont ceux de la litterature, pas un choix mesure. Les archiver comme
      essais AVANT d'en regarder les resultats est ce qui evite que le premier
      chiffre satisfaisant devienne la conclusion.
- [ ] **Rien ne borne le nombre de decisions par seance.** Une grille horaire
      mal ecrite - `%` sur une granularite de 5 minutes avec un pas de 1 -
      decide a chaque barre. Le taux d'execution le montrerait, le nombre de
      trades aussi, mais aucune garde ne le refuse.

- [x] **Taux de rejet affiche a cote du rendement (2026-09-14).** La ligne
      `Execution` parait TOUJOURS des qu'un ordre a ete emis - y compris a
      100 %, un taux plein etant une information et une ligne absente ne se
      distinguant pas d'une fonctionnalite oubliee. Sous 90 %, un
      AVERTISSEMENT dit que « le rendement ci-dessus ne mesure PAS la strategie
      declaree ». Sur le run Zarattini :
      `Execution 4 fill(s) sur 5084 ordre(s) emis taux 0.1 % / Refus margin 5080`.
      L'ancienne ligne `Refus` ne couvrait que les quatre motifs de
      `risk.limits` et n'etait emise que si un plafond etait DECLARE : elle
      serait restee muette sur le cas qui comptait, `margin` ne relevant
      d'aucun plafond.
- [x] **`sigma` reecrit sur un ancrage de seance REEL (2026-09-13).**
      Deux formes neuves, adossees au calendrier declare :
      `rolling.across: "sessions"` compte `window` en SEANCES au meme rang, et
      le noeud `session_lag` recule d'une seance. Reprise de la ligne du
      [[Failed Ideas/ledger]] du 2026-09-11, dont les deux conditions etaient
      remplies. 24 types de noeuds, 4190 tests, les 7 empreintes verifiees sur
      donnees reelles.
      **Ce n'etait pas une approximation** : reecrit, `sigma[tau]` differe de
      l'ancien a **100 %** des points de controle ou tous deux sont definis, de
      **28,3 % en mediane**. La note « 3,4 % » de la specification etait fausse
      sur ses trois affirmations - les seances courtes ne sont pas 94 accidents
      mais LES VENDREDIS, une semaine sur une ([[lessons]] L29).
      Empreinte de `_moule_universel` changee A DESSEIN : il doit montrer chaque
      type de noeud. Verifie terme a terme - equity, trades et portefeuille
      bit-identiques, seuls les `order_id` et deux compteurs bougent.
- [ ] **Rangs manquants : une politique DECLAREE plutot que `None`.**
      Aujourd'hui une seance ecourtee fait tomber toute la fenetre : 88 % des
      points de controle restent servis sur NQ, 12 % ne declenchent pas. Le
      papier, lui, moyennerait sur les seances disponibles. Non fait faute d'un
      cas ou ces 12 % changent une conclusion - et parce qu'un moyennage
      silencieux sur un nombre variable d'observations est exactement ce que le
      socle refuse. A trancher si un essai le rend genant.
- [x] **Aucune autre specification du depot n'est touchee (verifie 2026-09-13).**
      `grep stride examples/**/*.json` ne rend aucune declaration de pas : les
      sept exemples utilisent tous le defaut `stride: 1`. La premisse fausse
      etait propre a la specification Zarattini, qui vit hors du depot. Toute
      spec EXTERIEURE qui declare un `stride` cense valoir « une seance » porte
      la meme erreur.
- [x] **Branche fusionnee (2026-09-14).** `migration-nautilus` est dans `main`
      par un commit de fusion qui porte ce que la branche a fait et pourquoi
      elle ne supprime rien. La branche est CONSERVEE, pas effacee.

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
