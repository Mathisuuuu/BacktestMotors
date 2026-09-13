---
type: reference
updated: 2026-09-13
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
| Par quoi commencer pour ecrire une strategie ? | [examples/strategies/_moule.json](../../examples/strategies/_moule.json), a copier puis editer |
| A quoi ressemble CHAQUE type de noeud en JSON ? | [examples/strategies/_moule_universel.json](../../examples/strategies/_moule_universel.json) — les 20, dans un fichier qui tourne |
| Comment lire une grandeur de SEANCE ? | `session` et `cumulative` — exigent un calendrier declare, voir [[reference/seances]] |
| Comment lisser une EXPRESSION (pas un champ de prix) ? | `rolling` avec `stat: "ema"`. `primitive` est une feuille : elle ne lit que des champs de prix |
| Comment comparer une barre a celle de MEME RANG les jours precedents ? | `rolling` avec `across: "sessions"`, pas `stride`. Un pas fixe suppose des seances de longueur egale ; sur NQ elles font 1 362 barres, 435 le vendredi. Voir [[reference/seances]] |
| Comment reculer d'UNE SEANCE plutot que de N barres ? | `session_lag`. `lag` compte des barres et ne peut pas suivre une longueur de seance qui change |
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
| Un seul instrument par strategie a regles | **leve** : `multi_rules@1` prend un jeu de regles PAR instrument, dans un portefeuille commun |
| Sorties tout ou rien | **leve** : `exit_quantity` dans `rules` alleger au lieu de tout fermer |
| Optimisation de parametres | **debout, par decision** : hors perimetre declare du runner ([[Failed Ideas/ledger]]) |
| Noeud a memoire entre barres | **debout, par decision** : casserait la reproductibilite bit-a-bit |
| Primitive vraiment nouvelle | ~30 lignes de Python et un enregistrement `@1` |

La distinction compte : les deux murs restants ne sont pas des manques, ce sont
des garanties. Les lever couterait ce que le depot protege.

Astuce utile : `rolling` n'offre que l'EMA (`alpha = 2/(w+1)`), pas le lissage
de Wilder (`alpha = 1/n`). Les deux coincident pour `w = 2n - 1` - l'amorce
differe, les series convergent.

## Alleger une position : `exit_quantity`

Une cle de plus dans `rules`, un noeud qui donne un NOMBRE DE CONTRATS.
Absente, la sortie ferme tout - le comportement d'avant.

```json
"exit_quantity": { "type": "arith", "op": "*",
                   "left":  { "type": "position", "field": "quantity" },
                   "right": { "type": "constant", "value": 0.5 } }
```

La valeur est une **magnitude** : son signe est ignore. C'est ce qui permet
d'ecrire l'exemple ci-dessus sans `abs` et d'alleger de moitie qu'on soit long
ou court, `position.quantity` etant signee.

> Cela DIFFERE de `sizing.kind: "signal"`, ou une valeur negative annule la
> taille. La, le sens vient des regles d'entree et un negatif n'a pas de
> lecture ; ici la position existe deja, donc le sens est connu.

Trois cas n'emettent aucun ordre, et l'ordre manquant se lit dans les
compteurs :

| Cas | Pourquoi |
|---|---|
| signal indefini | « je ne sais pas » n'est pas une raison d'agir |
| moins d'un contrat apres troncature | on ne ferme pas une fraction de contrat, et arrondir a 1 trahirait l'intention |
| valeur nulle ou negative | rien a fermer |

Une demande superieure a la position est **bornee** a ce qui est detenu.
L'ordre reste `reduce_only`, comme toute sortie.

Mesure sur ES quotidien, quatre contrats par position :

| Sortie | Trades | Profit factor |
|---|---|---|
| totale | 8 | 0.68 |
| moitie | 9 | 0.52 |
| un contrat | 9 | 0.50 |

## Plusieurs instruments, chacun ses regles : `multi_rules@1`

`rules@1` et `panel_rules@1` ne negocient qu'UN symbole - le second voit les
autres par `peer`, mais n'y prend pas position. Tenir ES sur une logique et NQ
sur une autre demandait donc deux runs : deux equity separees, deux drawdowns
sans rapport, aucune contrainte de risque commune.

```json
"strategy": {
  "ref": "multi_rules@1",
  "params": { "books": {
    "ES.v.0": { "quantity": 1, "rules": { "entry_long": {...}, "exit_long": {...} } },
    "NQ.v.0": { "quantity": 2, "rules": { "entry_long": {...}, "exit_long": {...} } }
  } }
}
```

Un **livre** est un jeu de parametres `rules@1` moins le symbole, qui est deja
la cle - il est d'ailleurs valide par le meme modele, donc memes defauts et
meme refus d'un champ inconnu. Declarer un `symbol` dans un livre leve : deux
sources pour la meme information finiraient par diverger.

Trois proprietes a connaitre :

- **l'ordre des livres est TRIE par symbole**, jamais celui des cles JSON. Deux
  specifications identiques a l'ordre pres doivent donner la meme suite
  d'ordres, donc la meme empreinte ;
- **`peer` fonctionne a l'interieur d'un livre** : chacun recoit `ctx[symbole]`.
  On peut negocier ES en regardant NQ, tout en negociant NQ separement ;
- **un instrument absent de la coupe ne produit rien** - on ne decide pas sans
  barre, meme regle que `panel_rules@1`.

Le warmup retenu est celui du livre le plus exigeant : le runner transversal
n'en expose qu'un, et mieux vaut attendre trop que decider sur un indicateur
pas encore defini.

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
| [schemas/squelette.json](../../schemas/squelette.json) | **ecrire** : chaque emplacement avec ses valeurs acceptees, les 10 instruments, les 136 primitives, les 23 noeuds, les 7 strategies | oui, `rsl squelette` |
| [schemas/signals.schema.json](../../schemas/signals.schema.json) | **valider** : JSON Schema exact | oui, `rsl schema` |
| [examples/strategies/_moule_universel.json](../../examples/strategies/_moule_universel.json) | **imiter** : un fichier qui tourne et exerce les 20 noeuds | non, teste |

Le squelette est en **ASCII pur** et se redirige donc sans risque (`rsl schema`
en sortie standard, lui, sort en CP1252 sur Windows).

Suffisance verifiee : un lecteur qui n'a QUE le squelette peut en tirer une
specification valide - trois tests de `tests/unit/test_skeleton.py` construisent
une specification, chaque type de noeud et chaque primitive a partir du seul
document.

## Exemples executables

| Fichier | Ce qu'il montre |
|---|---|
| [examples/strategies/_moule_universel.json](../../examples/strategies/_moule_universel.json) | **la reference exhaustive** : les **20** types de noeuds, long ET short, stop adaptatif, objectif borne. Un test echoue si un type de noeud enregistre n'y figure pas |
| [examples/strategies/_moule.json](../../examples/strategies/_moule.json) | **le gabarit de demarrage**, plus court : tous les blocs d'une specification et une strategie `rules@1` complete. Tourne tel quel |
| [examples/strategies/sma_es_daily.json](../../examples/strategies/sma_es_daily.json) | croisement de moyennes, mono-instrument |
| [examples/strategies/retour_moyenne_dans_tendance.json](../../examples/strategies/retour_moyenne_dans_tendance.json) | `rules@1` — strategie ecrite nulle part dans le code |
| [examples/strategies/paire_es_nq.json](../../examples/strategies/paire_es_nq.json) | `peer` + `rolling` — paire ES/NQ sur donnees reelles |
| [examples/strategies/momentum_12_1_mensuel.json](../../examples/strategies/momentum_12_1_mensuel.json) | transversal, classement |

## Combien d'indicateurs, et comment ils sont verifies

**136 primitives** au 2026-09-11, soit **209 sorties nommees** - `adx@1`,
`macd@1`, `bollinger@1` et les autres portent plusieurs lignes sous un seul
nom, parce que deux lignes d'un meme indicateur doivent etre calculees avec les
memes reglages pour que leur croisement veuille dire quelque chose.

Ce chiffre n'est pas le bon indicateur de couverture, et il ne faut pas le
lire comme tel. `rolling@1` eleve **n'importe quelle expression** en
statistique glissante avec douze statistiques au choix, et 16 primitives
acceptent un champ OHLCV libre. Le nombre de mesures exprimables n'a pas de
borne ; ce qui en a une, c'est leur COUT (voir [[hot]], A-P2).

Ce qui rend le chiffre credible n'est pas sa taille mais le fait qu'une
bibliotheque de cette taille se verifie **d'un seul tenant** :

| Ou | Ce qui est verifie | Pour qui |
|---|---|---|
| [tests/adversarial/test_registre_primitives.py](../../tests/adversarial/test_registre_primitives.py) | futur corrompu sans effet, warmup honnete, ni NaN ni infini, determinisme, serie plate sans erreur, et **jamais `None` partout** | TOUTES, par parcours du registre |
| [tests/unit/test_indicateurs.py](../../tests/unit/test_indicateurs.py) | la valeur : formes fermees sur rampe et constante, equivalences avec du code deja eprouve | les formules, une a une |

Le premier fichier est le seul qui passe a l'echelle : une primitive ajoutee
demain y est couverte sans qu'une ligne soit ecrite. Il a trouve trois defauts
reels le jour de sa mise en place, dont deux qu'aucune relecture n'aurait vus
([[lessons]] L16).

## Reagir a sa propre performance : le noeud `account`

Ajoute le 2026-09-12. C'etait le seul grand absent du vocabulaire, identifie
en repondant a « peut-on tout ecrire en JSON ». La couche risque voyait
l'equity - `RiskManager.contracts` la recoit - mais aucune REGLE ne pouvait y
reagir : le dimensionnement composait avec le capital, la decision l'ignorait.

```json
{ "type": "compare", "op": "<",
  "left":  { "type": "account", "field": "drawdown" },
  "right": { "type": "constant", "value": -0.12 } }
```

Six champs : `equity`, `cash`, `peak_equity`, `initial_equity`, `drawdown`
(fraction negative ou nulle) et `total_return`.

**Trois differences avec `position`**, chacune pour un motif :

| | `position` | `account` |
|---|---|---|
| Hors runner | plat, **par deduction** | **leve** : une equity est inconnue, pas nulle |
| Forme | propriete | **methode**, comme `session_value` - une propriete qui leve rend `isinstance(ctx, Context)` impossible |
| Portee | un par instrument | **un par portefeuille** |

**Le piege a connaitre.** Une regle qui lit son propre drawdown se referme sur
elle-meme : couper a -10 % change l'equity, donc le drawdown, donc les coupes
suivantes. Le backtest reste juste - il simule exactement cela - mais la
sensibilite au seuil est bien plus forte qu'elle n'en a l'air, et un seuil
ajuste sur l'echantillon est du sur-ajustement particulierement difficile a
voir.

## Dire POURQUOI : le champ `note`

JSON n'a pas de commentaires. Depuis le 2026-09-12, **tout bloc de
specification et tout noeud de signal** accepte un champ `note` - un texte, ou
une liste de textes pour plusieurs lignes.

```json
{ "type": "rolling", "stat": "zscore", "window": 120,
  "note": "120 jours ~ six mois de seances",
  "inner": { "type": "price", "field": "close" } }
```

Trois proprietes, toutes verifiees par
[tests/unit/test_notes.py](../../tests/unit/test_notes.py) :

- **elle ne change aucun chiffre** - ni le `config_hash`, ni l'empreinte de
  resultat. Reformuler un commentaire ne rend pas un run incomparable a un run
  archive ;
- **elle n'ouvre rien** : `extra="forbid"` reste entier, une coquille est
  toujours une erreur, et la FORME de la note est verifiee (texte ou liste de
  textes, pas un objet) ;
- **elle ne survit pas a `describe()`** : un commentaire decrit l'INTENTION de
  qui a ecrit la specification, le rapport decrit ce qui a TOURNE.

Consequence : `note` est un mot **reserve**. Une cle de ce nom dans une
specification est un commentaire, jamais une donnee.

Le squelette ne le repete pas sur chacun des 22 noeuds - la regle vaut pour
tous, elle est dite une fois dans ses `contraintes`.

Pourquoi ce champ plutot qu'un changement de format : YAML a ete envisage et
mesure le meme jour, puis ecarte ([[Failed Ideas/ledger]]). Cinq des dix
operateurs du vocabulaire cassent quand on les ecrit a la main en YAML, et
`>` - le plus courant - y devient la chaine vide sans une erreur.

## Les cles de `rules` : une liste, et elle est fermee

Les neuf cles acceptees sont `entry_long`, `exit_long`, `entry_short`,
`exit_short`, `stop_loss`, `take_profit`, `entry_limit`, `entry_stop`,
`exit_quantity`. Cette liste n'est pas maintenue ici : elle est **derivee** des
champs de `RuleStrategy` (`RULE_KEYS`), publiee par `rsl squelette` sous
`cles_de_rules`, et par `rsl schema --what strategies` sous `propertyNames`.
La lire ailleurs qu'a ces deux endroits, c'est risquer une copie perimee.

Depuis le 2026-09-11, une cle **inconnue est refusee**. Avant, elle etait
ignoree : `exit_lng` au lieu de `exit_long` donnait une strategie qui entre et
ne sort jamais, sans un mot -- un backtest faux, pas un backtest en erreur.
`rules` est un `dict[str, object]`, donc le `extra="forbid"` de pydantic ne
s'y applique pas ; le refus est fait par `RuleStrategy.from_spec`, et le schema
publie porte desormais la meme contrainte. Meme regle que pour les champs d'un
noeud, ou `build_signal` refuse deja `oprands` au lieu de `operands`.

## `peer` et `position` sous une fenetre : ce que voit une vue reculee

`rolling`, `lag`, `bars_since`, `cumulative` et les deux `crosses_*` evaluent
leur sous-arbre sur `ctx.shifted(k)`. Deux noeuds se comportent alors
differemment, et il faut le savoir avant d'ecrire un signal :

Les deux portaient le meme defaut, corrige le meme jour : ils rendaient la
valeur COURANTE quel que soit le decalage.

| Noeud | Ce que voit `shifted(k)` | Comment |
|---|---|---|
| `peer` | l'autre instrument **a l'instant recule** | le panneau porte tout l'historique ; la lecture passe par ses REGLES, donc un absent le reste |
| `position` | l'etat **de la barre `i-k`** | le runner enregistre l'etat a chaque barre dans un historique BORNE porte par le feed |

La borne de l'historique de positions est le `warmup_bars` que la strategie
**declare** - le budget de lecture en arriere qu'elle a elle-meme annonce.
Au-dela, le socle leve plutot que de rendre un etat plat qui passerait pour
une mesure. Une strategie a regles derive ce budget de son arbre de noeuds :
le cas declaratif n'a donc rien a regler a la main.

Avant la premiere barre enregistree, « a plat » est une **deduction** et non
un defaut : le runner n'appelle pas la strategie pendant le prechauffage, donc
aucun ordre n'a pu etre emis.

Le cas `peer`, lui, **etait** un bug. Le terme distant restait a l'instant
courant, donc constant sur toute la fenetre ; un z-score etant invariant
d'echelle, il n'avait aucun effet - ecart 2,08e-14 avec un z-score du seul
numerateur. L'empreinte de [examples/strategies/paire_es_nq.json](../../examples/strategies/paire_es_nq.json)
change avec la correction, et son `config_hash` non : le moteur a change, pas
la specification. Voir [[lessons]] L18 et
[[experiments/paire-es-nq-retour-a-la-moyenne]].

## Ou vit le code

`rsl/strategies/signals.py` est une **facade** depuis le 2026-09-11 : elle ne
fait que reexporter. Le code est dans
[src/rsl/strategies/noeuds/](../../src/rsl/strategies/noeuds/), range par
famille.

| Module | Ce qu'il contient |
|---|---|
| `contrat` | ce qu'EST un noeud : protocole `Signal`, `NodeField`, registre, `build_signal` |
| `feuilles` | ce qui lit le monde : `price`, `primitive`, `position`, `time`, `session`, `peer`, `constant` |
| `fenetres` | ce qui regarde plusieurs barres : `rolling`, `lag`, `session_lag`, `bars_since`, `cumulative` |
| `operateurs` | ce qui combine : `compare`, `arith`, `all_of`, `not`, `crosses_*`, `if_then_else`, `math`, `min_of`, `max_of` |
| `raccourcis` | abreviations Python (`prim`, `const`, `price`) - pas utilisees par le chemin declaratif |

Les quatre familles importent `contrat`, jamais l'inverse
([tests/unit/test_couches.py](../../tests/unit/test_couches.py) le verifie par
analyse d'AST). Un noeud AJOUTE dans une famille doit apparaitre dans la
facade : le meme fichier de test le verifie, sans liste a tenir a jour.

## A savoir avant d'etendre

- `peer` et `rolling` vont ensemble : acces a un autre instrument au meme
  instant, et elevation de n'importe quelle expression en statistique glissante.
  L'un sans l'autre ne sert a rien.
- `rolling` reevalue son sous-arbre `window` fois par barre, mais la
  redondance ENTRE barres est supprimee depuis le 2026-09-11 par une
  memoisation ([src/rsl/strategies/memoire.py](../../src/rsl/strategies/memoire.py)) :
  **1 381 -> 116 us** sur une fenetre de 120, empreintes inchangees.
  **Sauf si le sous-arbre contient `peer` ou `position`** - leur valeur ne
  depend pas que de la serie et de la barre, et les memoiser a reellement
  change une empreinte avant que la garde n'existe. Le z-score d'un ratio
  ES/NQ garde donc son cout entier.
- Ajouter un type de noeud **sans regenerer les schemas** fait echouer la suite
  de tests, avec la commande a lancer.
- Ajouter une **regle** a `RuleStrategy` ne demande qu'un champ `Signal | None` :
  `warmup_bars`, `describe()`, `from_spec`, le squelette et le schema la
  reprennent seuls. Il reste a regenerer les schemas et a l'ajouter a la liste
  attendue par `tests/unit/test_rules_keys.py` ([[lessons]] L15).

## Liens wiki

[[concepts/registre-versionne]] · [[reference/cli]] ·
[[Failed Ideas/ledger]]
