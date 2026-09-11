---
type: reference
updated: 2026-09-11
autorite: schemas/signals.schema.json (engendre, ne pas editer a la main)
---

# Vocabulaire des signaux — routeur

> Page routeur. L'autorite est le **schema engendre**, pas ce tableau.
> `rsl schema` le produit depuis les registres ; les fichiers de `schemas/` sont
> compares au registre a chaque execution des tests, donc ils ne peuvent pas
> rouiller.

| Question | Reponse faisant autorite |
|---|---|
| Quels types de noeuds existent, avec quels champs ? | [schemas/signals.schema.json](../../schemas/signals.schema.json) — `$defs/node` enumere les types enregistres |
| Quelle est la forme d'une specification complete ? | [schemas/rsl.schema.json](../../schemas/rsl.schema.json) |
| Quelles primitives, quels noeuds, quelles strategies sont enregistres **maintenant** ? | `rsl catalogue` |
| Comment regenerer les schemas ? | `rsl schema --out schemas/signals.schema.json` |
| Comment un arbre est-il reconstruit depuis du JSON ? | `build_signal(spec)` dans [src/rsl/strategies/signals.py](../../src/rsl/strategies/signals.py) |
| Que peut-on mettre dans CHAQUE emplacement ? | [schemas/squelette.json](../../schemas/squelette.json) — engendre par `rsl squelette`. Chaque trou y est decrit par ses valeurs acceptees |
| Par quoi commencer pour ecrire une strategie ? | [examples/_moule.json](../../examples/_moule.json), a copier puis editer |
| A quoi ressemble CHAQUE type de noeud en JSON ? | [examples/_moule_universel.json](../../examples/_moule_universel.json) — les 20, dans un fichier qui tourne |
| Comment lire une grandeur de SEANCE ? | `session` et `cumulative` — exigent un calendrier declare, voir [[reference/seances]] |
| Comment lisser une EXPRESSION (pas un champ de prix) ? | `rolling` avec `stat: "ema"`. `primitive` est une feuille : elle ne lit que des champs de prix |
| Wilder ou moyenne simple ? | `atr@1` / `rsi@1` sont des moyennes ARITHMETIQUES ; `atr_wilder@1` / `rsi_wilder@1` sont les variantes de Wilder. Des noms distincts, jamais des versions — voir [[lessons]] L10 |
| Ou sont les moules de strategie descriptibles ? | [rules.py](../../src/rsl/strategies/rules.py) · [ranking.py](../../src/rsl/strategies/ranking.py) |
| Ou branchera le futur compilateur de specifications ? | [src/rsl/pipeline.py](../../src/rsl/pipeline.py) — decrit, sans implementation |

## Ou passe la frontiere du « sans code »

Mesure du 2026-09-11, et pas une impression : le vocabulaire sait desormais
**reconstruire une de ses propres primitives**. Un `rsi@1` recompose avec les
seuls noeuds (`arith`, `lag`, `max_of`, `math`, `rolling`) rend des valeurs
identiques a la primitive sur 240 points, ecart maximum `0.00e+00`. Ce qui
suit de plus important : la meme composition s'applique a une EXPRESSION, donc
le RSI d'un spread ES/NQ s'ecrit, alors qu'aucune primitive ne le calcule.

Deux murs sont tombes le 2026-09-11, deux restent, et ils ne sont pas de meme
nature :

| Mur | Etat |
|---|---|
| Deux granularites du MEME symbole | **leve** : `data[].alias` publie la serie sous un nom distinct, et `panel.allow_mixed_granularity` autorise le melange. Causalite verifiee par `tests/adversarial/test_multi_timeframe_closure.py` |
| Taille fonction d'un signal | **leve** : `sizing.kind: "signal"` prend un noeud quelconque, avec un `max_contracts` obligatoire |
| Ordres autres qu'au marche | **leve** : `entry_limit` et `entry_stop` dans `rules`. Lire la semantique ci-dessous AVANT de s'en servir |
| Optimisation de parametres | **debout, par decision** : hors perimetre declare du runner ([[Failed Ideas/ledger]]) |
| Noeud a memoire entre barres | **debout, par decision** : casserait la reproductibilite bit-a-bit |
| Primitive vraiment nouvelle | ~30 lignes de Python et un enregistrement `@1` |

La distinction compte : les deux murs restants ne sont pas des manques, ce sont
des garanties. Les lever couterait ce que le depot protege.

Astuce utile : `rolling` n'offre que l'EMA (`alpha = 2/(w+1)`), pas le lissage
de Wilder (`alpha = 1/n`). Les deux coincident pour `w = 2n - 1` - l'amorce
differe, les series convergent.

## Type d'ordre a l'entree : `entry_limit` et `entry_stop`

Deux cles de plus dans `rules`, chacune un noeud qui donne un PRIX :

```json
"entry_limit": { "type": "arith", "op": "-",
                 "left":  { "type": "price", "field": "close" },
                 "right": { "type": "primitive", "ref": "atr@1", "params": { "window": 20 } } }
```

Les deux sont exclusives - un ordre a un seul type. Aucune des deux : ordre au
marche, comme avant, donc aucune specification existante ne change de sens.

### La semantique surprend, et il faut la connaitre

**Un ordre a limite vaut pour la SEULE barre d'execution.** S'il n'est pas
touche, l'entree est abandonnee. Ce n'est PAS un ordre au carnet qui attendrait
plusieurs barres.

Mesure sur ES quotidien, limite posee a une ATR sous la cloture :

| Type d'entree | Trades |
|---|---|
| marche | 18 |
| limite a 1 ATR sous la cloture | **1** |
| stop a 1 ATR au-dessus | **0** |

Dix-sept entrees sur dix-neuf sont abandonnees, et cela se lit :
`n_orders_cancelled_unfilled: 17` pour `n_orders_submitted: 19` dans les
compteurs du rapport. Rien n'est silencieux, mais rien ne previent non plus -
d'ou ce paragraphe.

Deuxieme regle a connaitre : **un gap remplit a l'OUVERTURE, jamais au niveau
demande** (`execution.py`). C'est la direction defavorable, et la seule
realiste.

Troisieme : si le signal de prix est **indefini** a cette barre, l'entree est
abandonnee - elle ne retombe pas sur un ordre au marche. Retomber changerait
silencieusement le type d'ordre au moment ou l'on en sait le moins.

La SORTIE reste au marche : `stop_loss` et `take_profit`, attaches a l'ordre
d'entree, couvrent deja le besoin.

## Multi-timeframe : comment le declarer

Le meme instrument, deux granularites, deux noms - rien n'est devine :

```json
"data": [
  { "root": "ES", "path": "indices/ES_v0_1m.parquet", "resample": "day" },
  { "root": "ES", "path": "indices/ES_v0_1m.parquet", "resample": "week",
    "alias": "ES.week" }
],
"panel": { "align_policy": "ffill", "max_ffill_bars": 7,
           "allow_mixed_granularity": true }
```

La serie grossiere se lit ensuite par `peer` : `peer("ES.week", sma@1(10))`.

Trois garde-fous restent actifs, et ce sont eux qui rendent la chose sure :

- **l'unicite est verifiee sur le NOM publie**, pas sur le contrat. Declarer
  deux fois la meme serie reste une erreur ; un alias rend la duplication
  voulue impossible a confondre avec une duplication accidentelle ;
- **le melange de granularites doit etre declare**. Par defaut il leve, parce
  qu'il rend un classement transversal incomparable - un rendement hebdomadaire
  et un rendement quotidien ne sont pas de meme nature ;
- **le report est borne et marque** `is_stale`. Le panneau s'aligne sur l'union
  des CLOTURES : une ligne ne peut voir qu'une barre grossiere deja close.

Ce dernier point est le piege classique du backtest, et il est teste plutot
qu'affirme : aucune ligne ne voit une cloture posterieure a la sienne, la barre
vue est la plus recente close, et corrompre le futur ne change rien avant la
coupure.

## Trois documents, trois usages

| Document | Sert a | Engendre ? |
|---|---|---|
| [schemas/squelette.json](../../schemas/squelette.json) | **ecrire** : chaque emplacement avec ses valeurs acceptees, les 10 instruments, les 22 primitives, les 20 noeuds, les 6 strategies | oui, `rsl squelette` |
| [schemas/signals.schema.json](../../schemas/signals.schema.json) | **valider** : JSON Schema exact | oui, `rsl schema` |
| [examples/_moule_universel.json](../../examples/_moule_universel.json) | **imiter** : un fichier qui tourne et exerce les 20 noeuds | non, teste |

Le squelette est en **ASCII pur** et se redirige donc sans risque (`rsl schema`
en sortie standard, lui, sort en CP1252 sur Windows).

Suffisance verifiee : un lecteur qui n'a QUE le squelette peut en tirer une
specification valide - trois tests de `tests/unit/test_skeleton.py` construisent
une specification, chaque type de noeud et chaque primitive a partir du seul
document.

## Exemples executables

| Fichier | Ce qu'il montre |
|---|---|
| [examples/_moule_universel.json](../../examples/_moule_universel.json) | **la reference exhaustive** : les **20** types de noeuds, long ET short, stop adaptatif, objectif borne. Un test echoue si un type de noeud enregistre n'y figure pas |
| [examples/_moule.json](../../examples/_moule.json) | **le gabarit de demarrage**, plus court : tous les blocs d'une specification et une strategie `rules@1` complete. Tourne tel quel |
| [examples/sma_es_daily.json](../../examples/sma_es_daily.json) | croisement de moyennes, mono-instrument |
| [examples/retour_moyenne_dans_tendance.json](../../examples/retour_moyenne_dans_tendance.json) | `rules@1` — strategie ecrite nulle part dans le code |
| [examples/paire_es_nq.json](../../examples/paire_es_nq.json) | `peer` + `rolling` — paire ES/NQ sur donnees reelles |
| [examples/momentum_12_1_mensuel.json](../../examples/momentum_12_1_mensuel.json) | transversal, classement |

## A savoir avant d'etendre

- `peer` et `rolling` vont ensemble : acces a un autre instrument au meme
  instant, et elevation de n'importe quelle expression en statistique glissante.
  L'un sans l'autre ne sert a rien.
- `rolling` a un **cout assume** : il reevalue son sous-arbre `window` fois par
  barre. Voir les idees en attente du [[Failed Ideas/ledger]].
- Ajouter un type de noeud **sans regenerer les schemas** fait echouer la suite
  de tests, avec la commande a lancer.

## Liens wiki

[[concepts/registre-versionne]] · [[reference/cli]] ·
[[Failed Ideas/ledger]]
