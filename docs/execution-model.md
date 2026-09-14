# Modèle d'exécution

Ce document fixe la sémantique d'exécution du moteur `rsl`. Il est normatif :
tout comportement du code qui contredit ce document est un bug du code, pas du
document. Le contrat anti-look-ahead qui en découle est dans
[`no-lookahead.md`](./no-lookahead.md).

Statut : **décisions de design, avant implémentation.** Les points marqués
`[À ARBITRER]` attendent une décision explicite et bloquent l'implémentation de
la brique concernée.

---

## 1. Sémantique de la barre

### 1.1 Convention d'horodatage

Les données sources (Databento `ohlcv-1m`) horodatent chaque barre par
**`ts_event` = début de l'intervalle**, en UTC. Une barre étiquetée
`2024-03-14 13:30:00Z` couvre `[13:30:00, 13:31:00)` et **n'est close qu'à
13:31:00**.

C'est le premier piège de look-ahead du projet, et il est silencieux : croire
que la barre `t` est connue à l'instant `t` avance toute la stratégie d'une
minute.

**Décision.** Le format canonique interne conserve `ts_event` (ouverture) comme
clé, et expose en plus `ts_close = ts_event + granularité`. Toute logique du
moteur qui parle de « l'instant où l'information devient disponible » utilise
`ts_close`, jamais `ts_event`. La barre `t` entre dans le `Context` à
`ts_close(t)`.

Corollaire : `ts_close(t)` peut être très antérieur à `ts_event(t+1)` (voir §5,
trous de session). Les deux ne doivent jamais être confondus.

### 1.2 Intervalle intra-barre

À l'intérieur d'une barre, l'ordre chronologique de `open`, `high`, `low`,
`close` est **inconnu**. Le moteur ne le suppose jamais. Toute situation où le
résultat dépend de cet ordre est traitée par la règle du §4.4 (priorité
intra-barre pessimiste).

### 1.3 Rééchantillonnage : deux familles de périodes

Les données sont à la **minute**. Toute autre granularité est produite par
agrégation causale en amont du run (`rsl.data.resample`) : une période
partielle n'est jamais visible comme si elle était complète.

Les périodes se répartissent en deux familles qui ne s'ancrent pas de la même
façon.

| Famille | Périodes | Ancrage |
|---|---|---|
| Calendaire | `day` `week` `month` `quarter` `year` | l'horodatage seul |
| Intra-journalière | `5min` `10min` `15min` `30min` `1h` `2h` `4h` | l'**ouverture de séance déclarée** |

Le mois d'une barre se lit dans sa date. « Une barre de 4 h » ne dit pas où
elle commence : c'est une convention, et le socle n'en invente aucune. La
réponse est prise dans `data[].session`, **déclarée** — la même décision que
celle qui a tenu le nœud `session` écarté jusqu'à ce qu'un calendrier existe.

Une période intra-journalière sans `session` est donc **refusée à la
validation**, et une `session` fournie pour une période calendaire l'est aussi :
elle n'y changerait rien, et l'accepter laisserait croire le contraire.

#### La dernière tranche d'une séance est plus courte

Dès que la durée de séance n'est pas un multiple de la période. Une séance ES
de 23 h découpée en 4 h donne cinq tranches pleines et une de 3 h. Cette
tranche est **conservée** : c'est la clôture, la partie la plus liquide de la
séance. `granularity_of` reste donc une durée *nominale*, exactement comme pour
`month` — c'est `ts_close` qui fait foi.

#### Instant de disponibilité

Trois termes, dans cet ordre :

1. la fin nominale, `début + durée` ;
2. bornée par la **fermeture de séance** — dater la tranche courte une heure
   après la clôture retarderait le signal sans rien y gagner ;
3. **jamais avant la dernière clôture réellement observée**.

Le troisième terme n'est pas une précaution théorique. Sur les données ES avec
la déclaration usuelle `17:00-16:00@America/Chicago`, il mord **74 fois sur
16 417** tranches de 4 h : des barres d'une minute horodatées 16:00 clôturent à
16:01, après la fermeture déclarée. Sans lui, ces 74 barres agrégées seraient
réputées disponibles avant la clôture d'une de leurs composantes — une fuite.

#### Fenêtres comptées en séances, et non en barres

Même problème, un cran plus loin : `rolling` peut vouloir comparer une barre à
**celles de même rang dans les séances précédentes** — la 30ᵉ minute d'hier et
d'avant-hier. Jusqu'au 2026-09-13, la seule façon de l'écrire était
`rolling.stride`, qui compte des **barres** : « une barre sur 390 ».

Cela ne retrouve le même rang que si toutes les séances ont la même longueur.
**Les données réelles ne le vérifient pas.** Mesure sur `NQ_v0_1m.parquet` avec
la déclaration `09:30-16:00@America/New_York` :

| | barres par séance |
|---|---|
| jour plein | **1 362** |
| vendredi | **435** |

La séance ouverte le vendredi à 9 h 30 se ferme avant le week-end : elle est
structurellement courte, une semaine sur une, sur les dix ans de l'échantillon.
Un `stride` de 390 n'échantillonne donc pas « le même rang la veille » mais une
heure arbitraire, différente chaque jour.

Deux formes s'appuient sur le calendrier **déclaré** plutôt que sur une
longueur supposée :

| Forme | Sens |
|---|---|
| `rolling.across: "sessions"` | `window` compte des **séances** : la barre courante, puis celles de même rang dans les séances précédentes |
| `session_lag` | recule de N **séances**, au même rang |

Les deux exigent `data[].session` et **lèvent** sans lui. `across: "sessions"`
et `stride` ensemble sont refusés : ils disent la même chose de deux façons qui
se contredisent.

`across: "bars"` reste le défaut, et le champ n'est publié dans la forme
canonique que lorsqu'il s'en écarte — une spécification écrite avant cet ajout
garde donc son `config_hash` au bit près.

##### Ce que ces formes refusent

Une séance **écourtée** n'a pas de barre au rang demandé. La fenêtre rend alors
`None`, et ne substitue pas la dernière barre disponible : cela comparerait
15 h 59 d'un jour plein à 13 h 00 d'un demi-jour, c'est-à-dire exactement le
désalignement silencieux que ces formes existent pour supprimer.

Conséquence mesurée, à connaître avant de s'en servir — sur NQ, `window: 60` :

| | fenêtre définie |
|---|---|
| toutes les barres | **33 %** |
| aux douze points de contrôle semi-horaires (10:00-15:30) | **88 %** |

Les 67 % perdus sont les barres de nuit, dont le rang n'existe simplement pas
un vendredi. Ce n'est pas une perte d'information : c'est le refus de comparer
une barre à un marché fermé.

##### Le warmup ne peut pas être déclaré en barres

`warmup_bars` est une propriété statique de l'arbre de signaux. Combien de
barres font soixante séances dépend des **données** : ~81 700 sur NQ à la
minute, 60 sur du quotidien. Ces deux nœuds ne déclarent donc que le warmup de
leur sous-arbre, et l'insuffisance réelle est signalée à l'évaluation —
`None`, jamais une valeur prise au mauvais rang. Déclarer `min_warmup_bars` au
niveau du run reste le moyen de faire réellement sauter ces barres au runner.

#### Agréger sur une TRANCHE de séance

`cumulative` agrège depuis l'ouverture jusqu'à maintenant. Toute la famille
« opening range » demande moins : un agrégat sur une **partie** de la séance —
le plus haut des trente premières minutes, l'étendue de la première heure, le
VWAP de l'ouverture.

`cumulative.mask` restreint l'agrégation aux barres de la séance où un
sous-signal est vrai :

```json
{"type": "cumulative", "stat": "max", "inner": {"type": "price", "field": "high"},
 "mask": {"type": "compare", "op": "<=",
          "left": {"type": "session", "field": "minutes_from_open"},
          "right": {"type": "constant", "value": 30}}}
```

Vérité du masque : `> 0`, comme `count_true`. Le champ n'est publié dans la
forme canonique que lorsqu'il existe, donc une spécification écrite avant cet
ajout garde son `config_hash` au bit près.

##### Pourquoi ce n'est pas un confort

Sans `mask`, cela s'écrivait par une **sentinelle** :

```json
{"type": "cumulative", "stat": "max",
 "inner": {"type": "if_then_else", "condition": "...",
           "then": {"type": "price", "field": "high"},
           "otherwise": {"type": "constant", "value": -1e18}}}
```

Cet artifice est juste tant que la tranche contient au moins une barre, et
produit un **nombre** quand elle est vide. Mesuré le 2026-09-14 : une tranche
vide rendait `-1e+18`, et la règle « cours > cette borne » valait vrai à chaque
barre. Le backtest ouvrait des positions partout, sans une erreur ni un
avertissement.

Avec `mask`, une tranche vide rend `None`, et une règle qui vaut `None` ne
déclenche pas. Le pire cas devient une stratégie qui ne négocie pas, au lieu
d'une qui négocie partout — la différence entre un défaut visible et un défaut
qui se lit comme un résultat.

L'équivalence est vérifiée : là où la sentinelle est juste, le masque rend
exactement la même chose, au bit près
(`tests/unit/test_tranche_de_seance.py`).

#### Grilles horaires périodiques

`arith` accepte `%`. « Décider toutes les trente minutes » s'écrit en trois
nœuds au lieu de douze comparaisons `any_of` :

```json
{"type": "all_of", "operands": [
  {"...": "minutes_from_open >= 30"},
  {"...": "minutes_from_open <= 360"},
  {"type": "compare", "op": "==",
   "left": {"type": "arith", "op": "%",
            "left": {"type": "session", "field": "minutes_from_open"},
            "right": {"type": "constant", "value": 30}},
   "right": {"type": "constant", "value": 0}}]}
```

Ce n'est **pas** une fenêtre en durée — l'idée que le ledger écarte le
2026-09-10. Rien n'est reconstruit et aucune barre absente n'est inventée : le
nœud lit une grandeur déjà calculée par le calendrier déclaré, et si la barre
de la minute 30 n'existe pas, la condition est simplement fausse ce jour-là.

Deux conventions, fixées explicitement :

- **le signe suit le diviseur** (sémantique Python) : `-10 % 30` vaut 20. Sur
  des grandeurs de séance, qui sont positives, la question ne se pose pas ;
- **un modulo par zéro rend `None`**, comme la division, et pour la même
  raison : il n'y a pas de réponse, et `nan` en serait une fausse.

Piège à connaître, et il n'est pas propre au modulo : une barre est horodatée à
sa **clôture**, donc `minutes_from_open` parcourt `1..N` et jamais `0`. Le point
de contrôle « 30 minutes après l'ouverture » est la barre qui *se ferme* à cette
minute — le choix causal correct, celle qui s'ouvre avec elle n'étant pas encore
connue.

#### Calendriers d'événements déclarés

Une entrée `data` est un parquet OHLCV. Les stratégies qui se positionnent
autour d'une annonce macro exigent un autre canal : la section `events`.

```json
"events": [{"name": "fomc", "path": "calendriers/fomc.parquet",
            "known_in_advance": true}]
```

Le fichier porte une colonne `ts_event` en nanosecondes UTC. Son contenu est
**haché** et entre au manifeste, comme les cotations. Une liste `events` vide
est retirée de la forme canonique, donc n'altère pas les `config_hash`
antérieurs.

Le nœud `event` expose trois champs :

| Champ | Sens | Disponible |
|---|---|---|
| `minutes_since` | depuis la dernière annonce | **toujours** |
| `minutes_until` | avant la prochaine | si `known_in_advance` |
| `is_now` | une annonce tombe sur cette barre | toujours |

##### Pourquoi `minutes_until` est conditionné

Il lit un instant **futur**. Ce n'est pas du look-ahead pour autant : un
calendrier économique est publié à l'avance, et savoir que le FOMC parle à 14 h
ne dit rien du prix qu'il fera.

Mais cette propriété dépend du **fichier**, pas du socle. Un calendrier
reconstruit après coup — dates révisées, événements ajoutés rétrospectivement —
ferait entrer du futur sans qu'aucune inspection du code ne le voie. La source
doit donc déclarer `known_in_advance: true`, ce qui n'est pas une garantie mais
une **affirmation signée** : elle entre dans le `config_hash`.

Convention : une annonce tombant exactement sur la clôture d'une barre
appartient au **passé** de cette barre. La barre est close, son prix est connu,
l'annonce a eu lieu pendant qu'elle se formait.

#### Conséquence sur les panneaux

Deux instruments dont les séances diffèrent n'ont **plus aucune frontière
commune** en intra-journalier. Le calendrier d'union du panneau (§7.2) produit
alors une ligne par instrument et par tranche, avec un univers amputé à chaque
fois. Mesuré sur ES (CME) + FDAX (Eurex) en tranches de 4 h : **18 653 lignes
sur 18 654 ne portaient qu'un seul instrument**, soit 100 %. Une stratégie
transversale n'y aurait rien à comparer, et n'aurait levé aucune erreur — elle
aurait sauté tous ses rééquilibrages en silence.

La combinaison est donc **refusée à la validation** : tous les instruments d'un
panneau agrégé en intra-journalier doivent déclarer la **même** séance.
`allow_mixed_granularity` ne voit pas ce cas — les deux séries sont bien en
`4h`, c'est leur ancrage qui diffère.

Le découpage intra-journalier est ainsi un outil **mono-instrument**, ou réservé
à des instruments partageant le même calendrier. Pour un panneau hétérogène,
`day` et au-delà restent les seules périodes qui alignent.

---

## 2. Chaîne de décision

```
 fin de la barre t              début de la barre t+lag
        |                                  |
        v                                  v
  +-----------+   +----------+   +--------------+   +-----------+
  | Context   |-->| Strategy |-->| Risk /Sizing |-->| Execution |
  |  a t      |   | on_bar   |   |              |   |   fill    |
  +-----------+   +----------+   +--------------+   +-----------+
   barres <= t     list[Order]    Order dimensionne   Fill a t+lag
```

1. Le runner clôt la barre `t` et avance le curseur du `Context` à `t`.
2. La stratégie reçoit le `Context` et retourne `list[Order]`. Elle ne voit que
   des barres closes (`<= t`). Elle ne connaît pas `t+1`.
3. La couche risque dimensionne et attache stops / take-profits, à partir de la
   même information (`<= t`).
4. Les ordres entrent dans le carnet interne, **datés de leur soumission**.
5. Le runner avance à la barre `t+lag` et tente les fills contre l'OHLC de
   **cette** barre uniquement.

### 2.1 Le lag

`execution_lag` est exprimé **en barres**, entier, `>= 1`, **sans valeur par
défaut nulle**. La validation pydantic impose `ge=1` : `execution_lag=0` est un
`ValidationError`, pas un avertissement.

Valeur par défaut : `1`. Signal calculé à la clôture de `t`, ordre exécuté à
l'ouverture de `t+1`.

Il n'existe aucun mode, aucun flag, aucun chemin de code permettant d'exécuter
à la clôture de la barre qui a produit le signal. Cette exécution-là est le
mode de fuite le plus courant des backtests naïfs ; elle est absente du moteur,
pas désactivée par défaut.

### 2.2 Portée du lag

Le lag s'applique à **tous** les ordres issus de `on_bar`, y compris les
sorties. Un stop-loss placé à la clôture de `t` n'est pas armé pendant `t` ; il
devient actif à partir de `t+1`. Une stratégie ne peut donc pas être protégée
par un stop sur la barre qui l'a fait entrer.

Les stops déjà armés (posés à une barre antérieure) sont évalués sur chaque
barre sans lag supplémentaire : le lag modélise le délai décision → marché, pas
le délai marché → déclenchement d'un ordre déjà au carnet.

---

## 3. Types d'ordres

| Type | Déclenchement | Prix de fill |
|---|---|---|
| `MARKET` | immédiat à la barre de fill | `open` de la barre de fill, + slippage |
| `LIMIT` | si le prix limite est atteint dans `[low, high]` | `min(limit, open)` à l'achat, `max(limit, open)` à la vente |
| `STOP` | si le prix stop est atteint dans `[low, high]` | `max(stop, open)` à l'achat, `min(stop, open)` à la vente, + slippage |
| `STOP_LIMIT` | hors périmètre phase 1 | — |

Lecture des règles `LIMIT` / `STOP` : elles encodent le **gap**. Si la barre
ouvre déjà au-delà du niveau, le fill se fait à l'ouverture, jamais au niveau
demandé. Un stop de vente à 4000 sur une barre qui ouvre à 3950 remplit à 3950.
C'est la direction défavorable, et c'est la seule réaliste.

`LIMIT` est **optimiste** : on suppose qu'être dans `[low, high]` suffit à être
exécuté, ce qui ignore la file d'attente du carnet. Documenté comme tel ; à ne
pas utiliser pour des stratégies dont le P&L dépend de la capture du spread.
Les stratégies de référence de la phase 1 n'utilisent que `MARKET` et `STOP`.

### 3.1 Invariant de fill

```
low(barre_de_fill) <= fill_price <= high(barre_de_fill)
```

Vérifié par assertion **dans** `execution.py` à chaque fill, en plus du test
property-based. Un slippage qui pousserait le prix hors de la barre est
**écrêté à la borne** (`high` à l'achat, `low` à la vente) et l'écrêtage est
compté dans le rapport de run (`n_slippage_clamped`). On ne remplit jamais à un
prix qui n'a pas existé, quitte à sous-estimer le slippage.

### 3.2 Durée de vie et annulation

- Les ordres issus de `on_bar` visent **une barre précise**. Un `MARKET` est
  toujours exécuté à sa barre cible ; un `LIMIT` non touché à cette barre est
  **annulé**, pas reporté.
- Les stops et take-profits attachés à une position sont **persistants** :
  actifs jusqu'à exécution ou fermeture de la position.

---

## 4. Modèle de coûts

### 4.1 Aucun défaut à zéro

`fees` et `slippage` sont des champs **obligatoires** de la config d'exécution.
Pas de `= 0.0` dans les signatures, pas de `Optional`. Une config sans coûts ne
se construit pas. Pour tester explicitement le cas sans friction (test
« stratégie plate », test analytique buy & hold), on écrit `ZeroCostModel()` —
un objet nommé, qui apparaît dans le manifeste du run.

### 4.2 Frais

Futures : frais **par contrat et par côté**, en devise du contrat.

```
fee = n_contrats * (commission_par_contrat + frais_exchange_par_contrat)
```

Pas de frais en pourcentage du notionnel : ce n'est pas ainsi que les futures
sont facturés, et un modèle en bps produirait des ordres de grandeur faux sur
ES (notionnel ~250 k$ pour ~2 $ de frais aller-retour).

### 4.3 Slippage

Trois modèles, choix explicite :

- `TickSlippage(n_ticks)` — `n_ticks * tick_size`, dans le sens défavorable.
  **Modèle recommandé pour les futures** : le slippage y est une affaire de
  ticks, pas de pourcentage.
- `BpsSlippage(bps)` — proportionnel au prix.
- `ZeroCostModel()` — uniquement pour les tests analytiques.

Le slippage s'applique aux `MARKET` et aux `STOP` (qui deviennent des marchés
au déclenchement). Pas aux `LIMIT`.

### 4.4 Priorité intra-barre

Quand un stop-loss et un take-profit sont tous deux atteignables dans la même
barre (`low <= stop` et `high >= take_profit`), l'ordre chronologique réel est
inconnu.

**Décision : pessimisme par défaut.** Le stop est réputé toucher en premier.
Configurable par `intrabar_priority: "pessimistic" | "optimistic"`, défaut
`"pessimistic"`. Le compteur `n_intrabar_ambiguous` remonte dans le rapport :
si une stratégie affiche 40 % de barres ambiguës, son résultat dépend d'une
hypothèse, et le rapport doit le dire.

---

## 5. Trous de session

Les données 1 minute de futures ne sont pas un flux continu. Mesuré sur ES
(3 744 976 barres, 2016-2026) :

| Écart entre barres consécutives | Occurrences | Nature |
|---|---|---|
| 1 min | 3 733 215 | normal |
| 2-6 min | ~7 600 | micro-trous intra-session |
| 60-61 min | ~2 100 | coupure de maintenance quotidienne (22:00-23:00 UTC) |
| ~2 941 min | 485 | week-end |
| > 4 320 min | 19 | fériés (Noël, Nouvel An, Vendredi saint) |

Conséquence directe : « la barre suivante » peut être **49 heures plus tard**.
Un ordre soumis à la clôture du vendredi s'exécute à l'ouverture du dimanche
soir, après un gap de week-end. C'est réaliste — mais il faut que ce soit un
choix, pas un accident.

**Décision.** `max_fill_gap` : durée maximale tolérée entre `ts_close` de la
barre de soumission et `ts_event` de la barre de fill. Au-delà, l'ordre est
**annulé** et compté (`n_orders_expired_gap`). Défaut : `None` (aucune
annulation — comportement réaliste : l'ordre survit au week-end).

`[À ARBITRER]` Le défaut `None` est réaliste mais expose les stratégies
intraday à des fills de gap de week-end qui n'ont rien à voir avec leur
horizon. L'alternative serait un défaut à `timedelta(minutes=5)`, qui
annulerait ~2 700 ordres sur ES et rendrait le moteur silencieusement
« intraday-only ». Je pars sur `None` (explicite, réaliste, et le compteur rend
le phénomène visible) sauf indication contraire.

### 5.1 Ce que le moteur ne fait pas

Le moteur **ne reconstruit aucune barre manquante**. Il n'y a pas de grille
temporelle régulière : l'itérateur avance sur les barres qui existent. « la
barre `t+1` » signifie « la barre suivante présente dans les données », pas
« la minute suivante ». Toute fenêtre glissante est donc en **nombre de
barres**, jamais en durée — un `SMA(20)` traverse un week-end sans le savoir.

C'est une limite assumée et documentée, pas un oubli. La convertir en fenêtres
temporelles exigerait un calendrier de sessions par place (CME, EUREX), hors
périmètre phase 1.

---

## 6. Comptabilité futures

C'est le point où la spécification initiale est **inapplicable telle quelle**.

L'invariante demandée était `equity == cash + Σ(position × prix)`. Elle décrit
un instrument au comptant, acheté avec du cash. Un future ne s'achète pas : on
dépose une marge et on encaisse ou on paie la variation. `position × prix` d'un
contrat ES vaut ~250 000 $ pour une position dont la valeur économique est
nulle à l'instant de l'entrée.

**Invariante retenue :**

```
equity(t) == cash(t) + Σ_i  qty_i * multiplier_i * (mark_i(t) - avg_entry_i)
             --------        --------------------------------------------
             réalisé          P&L non réalisé, marked-to-market
```

avec :

- `cash` mouvementé **uniquement** par le P&L réalisé (à la fermeture) et les
  frais. Pas de sweep de marge de variation quotidien.
- `mark_i(t) = close_i(t)`, la barre courante close.
- `avg_entry_i` : prix moyen pondéré des lots ouverts, recalculé à chaque
  ajout. Les fermetures partielles réalisent au prix moyen (pas de FIFO fiscal
  — hors périmètre, documenté).

Cette invariante est vérifiée **à chaque barre, pour chaque stratégie**, avec
une tolérance relative de `1e-9`. C'est le test n° 5 de la suite.

**Équivalence.** Ne pas balayer la marge de variation dans le cash à chaque
barre change la trajectoire de `cash` mais pas celle de `equity`. Comme aucun
intérêt n'est modélisé sur le cash en phase 1, les deux conventions donnent le
même `equity` bit à bit. La convention retenue est la plus simple à tester.

### 6.1 Marge

`initial_margin` et `maintenance_margin` par contrat sont des champs de la spec
d'instrument. En phase 1 :

- la marge requise est **calculée et rapportée** (`max_margin_utilization`) ;
- son dépassement est **rejeté ou signalé** selon
  `margin_policy: "reject" | "warn"`, défaut `"reject"` ;
- **aucun appel de marge, aucune liquidation forcée** n'est modélisé.

`[À ARBITRER]` Les marges réelles par contrat (ES, NQ, GC, CL, 6E…) ne sont pas
dans le jeu de données et varient dans le temps. Il faut soit les fournir en
config statique (valeurs actuelles, anachroniques sur 2016), soit régler
`margin_policy="warn"` et ne rien contraindre. Je propose une table statique en
config, avec un avertissement explicite dans le manifeste sur son caractère
anachronique.

### 6.2 Dimensionnement

Les futures se traitent en contrats entiers. Tout sizing est arrondi par
troncature **vers zéro** (jamais `round`, qui peut faire passer de 0 à 1
contrat et créer des positions non voulues). Un sizing qui donne `0.7` contrat
donne `0` contrat, l'ordre n'est **pas** émis, et le compteur
`n_orders_dropped_sizing` le remonte.

Conséquence : sur un capital modeste, une stratégie sur ES (multiplicateur 50)
est grumeleuse. C'est la réalité de l'instrument, pas un artefact.

### 6.3 Contraintes de portefeuille

Le dimensionnement (§6.2) regarde **un instrument**. Une contrainte de
portefeuille regarde **toutes les positions à la fois**. Les deux peuvent être
justes séparément et donner ensemble un portefeuille inacceptable : dix règles
qui prennent chacune une position raisonnable font une exposition qui ne l'est
pas.

Quatre plafonds, tous facultatifs et `null` par défaut, déclarés sous
`risk.limits` :

| Plafond | Mesure |
|---|---|
| `max_gross_exposure` | `Σ abs(quantité × multiplicateur × marque) / equity` |
| `max_net_exposure` | `abs(Σ quantité × multiplicateur × marque) / equity` |
| `max_positions` | nombre d'instruments détenus |
| `max_per_category` | nombre d'instruments détenus par classe d'actif |

Les deux premiers se mesurent **en argent**, pas en contrats : dix ES et dix CL
ne représentent pas le même risque, donc un plafond en contrats ne peut pas
répondre à cette question. `max_gross_contracts`, qui existe par ailleurs,
borne `abs(position)` **pour un instrument** — son nom dit « gross » mais il ne
regarde pas le portefeuille.

Brut et net ne disent pas la même chose : un portefeuille long 5 ES / court
5 ES a un net de zéro et un brut de dix. Borner l'un sans l'autre laisse passer
exactement l'un des deux risques.

#### Règle de non-aggravation

Un ordre est refusé s'il dépasse le plafond **et** aggrave la mesure qu'il
dépasse. Un ordre qui la laisse égale ou la diminue passe toujours.

Cette règle n'est pas une commodité : les plafonds en argent se comparent à une
equity qui bouge seule. Un portefeuille conforme à 1,9 le matin est à 2,1 le
soir sans qu'aucun ordre ne soit passé. Un contrôle portant sur le **niveau**
enfermerait alors le portefeuille au-dessus de son plafond — il ne pourrait
plus se réduire. Un plafond qui peut piéger un portefeuille n'est pas une
contrainte, c'est une panne.

Conséquence à connaître : sous une equity nulle ou négative, les quatre mesures
valent l'infini, `inf > inf` est faux, et les plafonds deviennent **inertes**
dans les deux sens. C'est voulu pour la liquidation ; sous `margin_policy:
"reject"`, la marge refuse déjà tout ordre qui ajoute du risque dans cet état.

#### Portée d'un contrôle : la fournée

Les ordres d'une même soumission sont évalués **les uns contre les autres**.
Sans cela, un rebalancement transversal qui émet dix ordres d'un coup les
évaluerait tous contre le portefeuille d'avant : chacun lirait « aucune
position détenue », chacun passerait, et un plafond de deux instruments en
laisserait ouvrir dix. Une réservation vaut le temps d'une fournée, pas
davantage — le runner remplit les ordres dus **avant** de soumettre les
suivants.

Les réductions sont réservées comme les entrées. `ranking@1` émet ses sorties
avant ses entrées ; un plafond qui ne créditerait pas les sorties refuserait
toute rotation.

#### Ce que ces plafonds ne garantissent pas

- Ils sont évalués **à la soumission**, sur les marques de la barre courante,
  alors que le fill a lieu à `t+lag`, à un autre prix. L'exposition réalisée
  peut donc dépasser légèrement un plafond **en argent**. C'est structurel : le
  plafond exact demanderait de connaître le prix de fill avant de le connaître,
  ce que §2 interdit. `max_positions` et `max_per_category`, qui comptent et ne
  valorisent pas, sont en revanche **exacts**.
- Un ordre à cours limité resté en attente n'est ni rempli ni réservé : le
  plafond l'ignore jusqu'à ce qu'il touche.
- Un ordre `reduce_only` — y compris un stop ou un objectif — n'est pas soumis
  à ces plafonds. Il ne peut que réduire.
- Un instrument sans marque à cet instant compte dans `max_positions` mais pas
  dans les expositions en argent : il est détenu, il n'est pas valorisable, et
  lui inventer une valeur serait la seule façon de se tromper en silence.

Chaque refus est compté sous son propre motif, publié dans `run.risk_stats` du
rapport : `n_rejected_gross_exposure`, `n_rejected_net_exposure`,
`n_rejected_positions`, `n_rejected_per_category`. Un ordre disparu sans
compteur donnerait « la stratégie ne trade pas » sans explication.

#### Hachage

Un bloc `risk.limits` entièrement `null` est **retiré de la forme canonique**,
donc du `config_hash` : il ne dit rien de plus que son absence, et deux runs
qui n'ont déclaré aucun plafond ont reçu les mêmes instructions. Un plafond
réellement déclaré, lui, est haché — c'est une instruction.

### 6.4 Allocation transversale

§6.2 dit combien de contrats sur **un** instrument ; §6.3 dit ce que le
portefeuille s'**interdit**. Ni l'un ni l'autre ne dit comment **répartir** un
budget entre plusieurs noms retenus. C'est ce que fait l'allocation de
`ranking@1`, déclarée sous `strategy.params.allocation`.

#### « Un contrat chacun » est une répartition, pas son absence

Le défaut historique donne `quantity` contrats à chaque nom. Un contrat ES vaut
environ 50 × 5 000 = 250 000 $ ; un contrat 6J environ 81 000 $. « Un contrat
chacun » met donc trois fois plus d'argent sur ES, et le résultat du
portefeuille est dominé par l'instrument dont le contrat est gros — pour une
raison sans rapport avec la stratégie. La règle porte désormais un nom
(`fixed`) : un défaut invisible ne se discute pas.

| `kind` | Poids |
|---|---|
| `fixed` | `contracts` contrats par nom. Défaut, identique au comportement antérieur |
| `equal_weight` | `1/N` du budget à chaque nom |
| `inverse_volatility` | proportionnel à `1/volatilité`, puis normalisé |
| `signal` | une expression du vocabulaire, puis normalisée |

    budget     = equity × gross_target
    contrats_i = trunc(budget × poids_i / (prix_i × multiplicateur_i))

#### Ce qui exige de voir la coupe

Beaucoup de besoins sont déjà couverts par une règle de dimensionnement (§6.2),
qui ne voit qu'un instrument — s'ils suffisent, les préférer. Une allocation ne
se justifie que pour ce qu'une règle par instrument ne peut pas faire :
**normaliser**. `vol_target` appliqué à six noms déploie six fois son budget ;
`inverse_volatility` en déploie un, quel que soit le nombre de noms retenus et
quelles que soient leurs volatilités.

#### Exclusion mutuelle avec le dimensionnement

`RiskManager._size` **remplace** la quantité de l'ordre. Une allocation qui
répartit un budget verrait donc ses tailles écrasées par une valeur unique,
sans erreur et sans compteur. La combinaison d'une allocation en argent et d'un
`risk.sizing.kind` autre que `"none"` est donc **refusée à la validation**, pas
au run. `fixed` reste autorisé : il ne répartit rien.

#### Troncature : la première cause de « la stratégie ne trade pas »

Le nombre de contrats est tronqué vers zéro (§6.2). Avec un budget modeste
réparti sur plusieurs noms, `trunc` peut rendre zéro — et ce sont les
**gros contrats qui disparaissent en premier**, ce qui transforme silencieusement
la répartition demandée en une autre.

Mesuré le 2026-09-12 sur `momentum_12_1` (dix instruments, six noms retenus) :
à 1 M$ de capital et `gross_target: 1.0`, `equal_weight` tronque **190** noms à
zéro et `inverse_volatility` **294**, sur ~690 emplacements. Les Sharpe obtenus
ne décrivaient alors pas les règles déclarées. À 20 M$, la troncature tombe à
zéro pour les trois règles.

Le compteur `n_noms_tronques`, publié dans `run.strategy.allocation.stats`, est
donc à **lire avant** tout chiffre de performance issu d'une allocation.

#### Ce que l'allocation ne garantit pas

- Les poids sont calculés sur les barres closes de la coupe ; l'ordre est
  rempli à `t+lag`, à un autre prix. La répartition réalisée s'écarte un peu de
  la répartition voulue — même approximation structurelle qu'en §6.3.
- Un nom dont le poids n'est pas calculable (volatilité indéfinie ou nulle,
  signal `None` ou négatif) est **écarté**, jamais doté d'un poids par défaut,
  et compté sous `n_noms_sans_poids`. La normalisation porte alors sur les noms
  restants : la cible brute est tenue, au prix d'une concentration.
- Les **sorties** ne consultent jamais l'allocation. Fermer une position n'est
  pas la dimensionner, et un nom dont le poids devient incalculable doit
  pouvoir être fermé.
- `gross_target: 1.0` n'est pas « sans levier » sur des futures : la marge
  initiale d'ES avoisine 6 % du notionnel, donc environ seize fois la marge.

---

## 7. Deux modes de runner

Les deux familles de stratégies demandées ont des besoins d'exécution
différents. Plutôt qu'une abstraction unique qui servirait mal les deux, deux
runners partagent le même portefeuille, le même modèle d'exécution et le même
`Context`.

### 7.1 `SingleAssetRunner`

Boucle barre par barre sur un instrument. `on_bar(ctx)` appelé à chaque barre
close. Utilisé par buy & hold et SMA crossover.

### 7.2 `CrossSectionalRunner`

- Calendrier commun : **union** des horodatages des instruments du panier, pas
  intersection (une intersection sur 10 futures de places différentes réduit
  l'échantillon et introduit un biais de sélection).
- À un horodatage `t`, un instrument est **présent ou absent**. Absent ≠ prix
  précédent. Aucun forward-fill implicite (voir `no-lookahead.md` §4).
- `on_rebalance(ctx_multi)` appelé aux dates de rebalancement uniquement. Entre
  deux rebalancements, seuls les stops persistants sont évalués.
- Timing : signal calculé sur la **dernière barre close de la période P**,
  ordres exécutés à l'**ouverture de la première barre de la période P+1**. Le
  lag §2.1 s'applique identiquement.

### 7.3 Granularité du momentum 12-1

`[À ARBITRER]` Un momentum 12-1 est une stratégie mensuelle ; le jeu de données
est à la minute. Le runner cross-sectionnel travaillera sur une **vue
rééchantillonnée mensuelle (dernière barre close du mois)** construite par
agrégation causale, pas sur les 37 millions de barres minute. La règle
d'agrégation est elle-même soumise au contrat anti-look-ahead : une barre
mensuelle n'existe qu'une fois le mois terminé.

---

## 8. Annualisation

À la minute, l'annualisation est un piège : `sqrt(252 * 1440)` suppose un
marché ouvert 24/7/365, ce qui gonfle le Sharpe.

**Décision.** La courbe d'equity est **rééchantillonnée en pas quotidien**
(dernière valeur de chaque journée UTC) avant tout calcul de Sharpe, Sortino,
volatilité ou CAGR. Le facteur d'annualisation est
`sqrt(jours_de_bourse_observés_par_an)`, **mesuré sur l'échantillon**, pas
codé en dur à 252. Le facteur retenu est écrit dans le rapport de run.

Le max drawdown et sa durée sont calculés sur la courbe **à pleine
granularité** (le drawdown intraday est réel), et les deux valeurs — pleine
granularité et quotidienne — sont rapportées, car elles diffèrent.

---

## 9. Points à arbitrer

1. **§5** — `max_fill_gap` par défaut : `None` (proposé) ou une durée courte.
2. **§6.1** — Marges : table statique anachronique (proposé) ou
   `margin_policy="warn"` sans contrainte.
3. **§7.3** — Granularité du runner cross-sectionnel : mensuel rééchantillonné
   (proposé).
4. **Hors doc, bloquant pour le test analytique buy & hold** — les séries
   continues `.v.0` ne sont pas ajustées au roulement : on mesure des
   discontinuités de ~1,1-1,3 % groupées sur les dates de roulement
   trimestrielles, contre un p95 quotidien de 0,29 %. Le manifeste des données
   ne fournit pas les dates de roulement. Conséquence : sur données réelles,
   « buy & hold » ne correspond à aucune position détenable. Le test analytique
   se fera sur fixtures synthétiques (déjà exigé par la spec) ; sur données
   réelles, le buy & hold sera documenté comme « rendement de la série
   continue », pas comme un rendement réalisable.
