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
