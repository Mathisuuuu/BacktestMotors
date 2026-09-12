# research-strategy-lab

Socle de backtest event-driven, deterministe, dans lequel le look-ahead bias est
structurellement impossible.

Ce depot est la **verite terrain** d'un systeme plus large : lire des papers de
recherche, en extraire une specification de strategie, la compiler en code
backtestable. Aucune de ces briques n'est construite ici. Si le socle est faux,
tout ce qui sera bati dessus sera faux - d'ou l'ordre de construction.

## Les deux documents a lire en premier

| Document | Contenu |
|---|---|
| [`docs/no-lookahead.md`](docs/no-lookahead.md) | **Le contrat anti-look-ahead.** Modele de menace en sept voies, garanties du `Context`, politique de donnees manquantes, et - explicitement - ce que le socle NE garantit pas. |
| [`docs/execution-model.md`](docs/execution-model.md) | Semantique de barre, lag d'execution, types d'ordres et bornes de fill, modele de couts, comptabilite futures, trous de session. |

Ils sont normatifs : un comportement du code qui les contredit est un bug du
code.

## L'idee en une phrase

Une strategie ne recoit jamais un DataFrame. Elle recoit un `Context` : une
reference vers un magasin de barres immuable, plus un entier. Rien dans sa
surface publique ne permet de lire au-dela de cet entier, ni de savoir combien
de barres restent.

```python
from rsl.data.loader import load_bar_store
from rsl.data.feed import BarFeed
from rsl.data.schema import Granularity
from rsl.strategies.signals import prim, CrossesAbove

store, report = load_bar_store(path, symbol="ES.v.0", granularity=Granularity.minutes(1))
signal = CrossesAbove(prim("sma@1", window=20), prim("sma@1", window=100))

for ctx in BarFeed(store, warmup_bars=signal.warmup_bars):
    ctx.value(Field.CLOSE, lag=5)     # une barre close : OK
    ctx.value(Field.CLOSE, lag=-1)    # LookAheadError
    ctx.history(10_000)               # InsufficientHistoryError, jamais des NaN
    len(ctx)                          # n'existe pas
```

## Etat d'avancement

| Etape | Etat |
|---|---|
| Documents de design | fait |
| Couche donnees (schema, validation, loader, feed) | fait |
| Registres versionnes, primitives, signaux composables | fait |
| Moteur (portefeuille, execution, risque, runner mono-instrument) | fait |
| Buy & hold + test analytique | fait |
| Reechantillonnage causal, runner transversal | fait |
| SMA crossover, momentum 12-1 | fait |
| Metriques, Deflated Sharpe | fait |
| CLI, manifeste et rapport | fait |
| Runner walk-forward | fait |
| PBO / CSCV | protocole seulement |

## Les trois strategies de reference

| Strategie | Famille | Ce qu'elle valide |
|---|---|---|
| `buy_and_hold@1` | triviale | Le P&L doit egaler une formule fermee calculee hors du moteur. Verifie a 0,00e+00 sur cinq series synthetiques et sur 500 000 barres reelles d'ES. |
| `sma_crossover@1` | time-series | Entree, sortie, stop persistant, dimensionnement. Ecrite en code explicite, puis verifiee ordre par ordre contre sa traduction en noeuds de signaux : deux implementations independantes qui concordent. |
| `cross_sectional_momentum@1` | transversale | Tri, rebalancement periodique, long-short. Univers recalcule a chaque date, sans biais de survie : un instrument entre quand il a assez d'historique, pas avant. |

Les trois passent le test de corruption du futur : bruiter toutes les barres
apres l'index `k` ne change rien a un backtest arrete a `k`, empreinte
exhaustive comparee (courbe, fills, compteurs, trades, rapport JSON).

## Ce qu'un run rapporte

```
Echantillon  2753 barres, 10.65 an(s), 258.6 periodes/an (mesure)
Rendement    total +57.12 %   CAGR +4.33 %
Risque       vol +5.61 %   Sharpe 0.78   Sortino 1.12
Drawdown     quotidien -10.01 % (720 j sous l'eau)
             pleine granularite -10.01 %
Activite     0 trades   hit n/d   profit factor n/d   exposition +99.96 %
```

Le pas d'annualisation est **mesure sur l'echantillon**, jamais suppose : a la
minute, `sqrt(252 * 1440)` supposerait un marche ouvert 24/7/365 et gonflerait
le Sharpe d'un facteur deux. Le drawdown est rapporte deux fois, a pleine
granularite et au pas quotidien, parce que les deux valeurs different et que
n'en montrer qu'une serait un choix.

## Le compteur d'essais

Un Sharpe ne dit pas s'il vaut quelque chose. Essayer assez de configurations
sur un echantillon fixe finit toujours par en produire une qui brille : le
maximum d'un ensemble de tirages n'est pas un tirage.

`TrialLog` enregistre chaque essai au moment ou il est fait, et fournit au
Deflated Sharpe Ratio les deux entrees qu'aucun backtest isole ne connait - le
nombre d'essais et leur dispersion.

```
=== DEFLATED SHARPE du meilleur essai (SMA 5/20 sur ES quotidien) ===
Sharpe observe (par periode)  0.0560
Maximum attendu sous H0       0.0158 (8 essai(s), variance 0.00012)
PSR (contre zero)             0.9981
DSR (contre le maximum)       0.9810  SIGNIFICATIF
Moments                       asymetrie -0.258, kurtosis 11.712, 2731 observations
```

Huit essais est une grille minuscule. Une vraie recherche en compte des
centaines, et le meme Sharpe n'y survivrait pas - c'est precisement ce que le
DSR sert a montrer.

## Utilisation

```bash
rsl catalogue
```

```bash
rsl example > ma-config.json
```

```bash
rsl run ma-config.json --out runs/mon-run.json
```

```bash
rsl verify ma-config.json
```

| Commande | Role |
|---|---|
| `rsl validate FICHIER...` | valide des fichiers de donnees ; la racine est deduite du nom (`ES_v0_1m` -> `ES`) |
| `rsl instruments` | table des contrats : multiplicateur, tick, valeur du tick, frais, marge |
| `rsl catalogue` | primitives, noeuds de signaux et strategies enregistres |
| `rsl schema [--what signals\|strategies\|spec\|all]` | JSON Schema du vocabulaire |
| `rsl example` | specification d'exemple, a rediriger dans un fichier |
| `rsl run CONFIG` | execute un backtest, affiche le rapport, ecrit le JSON |
| `rsl walkforward CONFIG --train N --test N` | evalue la strategie sur des fenetres successives |
| `rsl verify CONFIG` | execute DEUX fois et compare les empreintes |

Codes de sortie : `0` succes, `1` erreur d'usage ou d'execution, `2` verification
echouee - donnees rejetees, empreintes divergentes, run non rejouable. Un script
d'integration peut donc distinguer "je n'ai pas pu" de "j'ai pu, et c'est faux".

`verify` existe comme commande a part entiere parce que l'exigence "deux runs
identiques produisent des resultats bit-a-bit identiques" est facile a ecrire
dans un document et facile a perdre dans le code.

## Provenance : ce que chaque run enregistre

```
Horodatage   2026-09-10T13:32:30+00:00
Config       5dfdefe68f787a59   graine 0
Depot        d5df68836256 (master) - MODIFIE
Plateforme   Python 3.11.9, Windows 10 (AMD64)
Dependances  numpy 2.4.6, polars 1.44.2, pyarrow 25.0.1, pydantic 2.13.5
Donnees      ES.v.0 [resample:day(2753 periodes, 564 ecartee(s))] 2753 barres 1d  17bdf284b5b8
Rejouable    NON
Avertissement  arbre de travail modifie (6 fichier(s) modifie(s)) : le commit
               d5df6883 ne suffit PAS a rejouer ce run
```

Un backtest sans manifeste est une anecdote : six mois plus tard, un chiffre
dans un carnet ne dit ni quelles donnees il a vues, ni quel code l'a produit.

Le champ **Rejouable** est le seul qui compte vraiment. Il vaut `NON` des qu'une
piece manque - arbre de travail modifie, fichier source sans empreinte, absence
de depot - plutot que d'afficher un numero de commit qui laisserait croire a une
tracabilite qui n'existe pas.

L'**empreinte de resultat** est calculee separement, sur la courbe d'equity, les
fills, les compteurs et la comptabilite. Jamais sur l'horodatage : deux runs
identiques lances a dix minutes d'intervalle doivent avoir la meme empreinte,
sinon l'exigence de reproductibilite serait inverifiable.

## Walk-forward : la performance tient-elle sur toute la periode ?

```bash
rsl walkforward examples/strategies/sma_es_daily.json --settings examples/reglages/sma_es_daily.json --symbol ES.v.0 --train 500 --test 250
```

```
  pli  0  barres    500-750    rendement   -0.54 %  Sharpe -0.26  DD -2.8 %  1 trades  expo 41.2 %
  pli  1  barres    750-1000   rendement   -0.05 %  Sharpe +0.00  DD -2.8 %  2 trades  expo 59.6 %
  pli  2  barres   1000-1250   rendement   -1.12 %  Sharpe -0.62  DD -2.1 %  1 trades  expo  2.0 %
  pli  3  barres   1250-1500   rendement   +0.00 %  Sharpe   n/d  DD +0.0 %  0 trades  expo  0.0 %
  pli  4  barres   1500-1750   rendement   -1.38 %  Sharpe -1.39  DD -1.5 %  1 trades  expo  1.6 %
  pli  5  barres   1750-2000   rendement   +0.86 %  Sharpe +0.27  DD -2.8 %  2 trades  expo 51.6 %
  pli  6  barres   2000-2250   rendement  +10.80 %  Sharpe +1.90  DD -4.6 %  1 trades  expo 82.8 %
  pli  7  barres   2250-2500   rendement   +5.51 %  Sharpe +1.68  DD -1.7 %  1 trades  expo 28.8 %
  pli  8  barres   2500-2750   rendement   +5.03 %  Sharpe +0.95  DD -3.6 %  1 trades  expo 34.4 %
------------------------------------------------------------------------------
Sharpe       moyen 0.32   median 0.13   dispersion 1.13
Plis         9 au total, +44.44 % positifs
Concentration 57 % du resultat vient d'un seul pli
```

La meme strategie mesuree sur l'echantillon entier affiche un Sharpe de 0,60.
Decoupee en neuf fenetres, elle est positive dans quatre, et **57 % de son
resultat vient d'un seul pli**. Un chiffre agrege ne distingue pas une
performance repartie d'une performance concentree ; c'est ce que ce decoupage
sert a voir.

**Ce runner n'optimise rien.** L'optimisation de parametres est hors du
perimetre de cette phase. La fenetre d'apprentissage sert d'HISTORIQUE - la
strategie la traverse pour remplir ses fenetres glissantes, sans negocier.

Consequence a ne pas masquer : tant que rien n'est optimise, un decoupage ancre
et un decoupage glissant produisent exactement les memes plis. Les deux existent
parce que le jour ou une selection de parametres s'inserera entre les deux
fenetres, le choix comptera. Un test verifie cette egalite plutot que de laisser
croire a deux mesures independantes.

Chaque pli repart du capital initial et est liquide a sa derniere barre. Sans
cela, le rendement d'un pli contiendrait un profit latent que le pli suivant
n'herite pas.

## Une strategie sans ecrire de code

`rules@1` construit une strategie a partir de ses seuls parametres. Celle-ci -
retour a la moyenne a l'interieur d'une tendance - n'est ecrite nulle part dans
le depot :

```json
"strategy": {
  "ref": "rules@1",
  "params": {
    "symbol": "ES.v.0", "quantity": 1,
    "rules": {
      "entry_long": {"type": "all_of", "operands": [
        {"type": "compare", "op": ">",
         "left":  {"type": "price", "field": "close"},
         "right": {"type": "primitive", "ref": "sma@1", "params": {"window": 200}}},
        {"type": "compare", "op": "<",
         "left":  {"type": "primitive", "ref": "zscore@1", "params": {"window": 100}},
         "right": {"type": "constant", "value": -1.5}}]},
      "exit_long": {"type": "compare", "op": ">", "...": "..."},
      "stop_loss": {"type": "arith", "op": "-", "...": "..."}
    }
  }
}
```

```bash
rsl run examples/strategies/retour_moyenne_dans_tendance.json --settings examples/reglages/retour_moyenne_dans_tendance.json --symbol ES.v.0
```

Aucune ligne de Python n'est ecrite NI GENEREE. C'est ce qui rend la phase
suivante sure : du code qui n'est pas genere ne peut pas etre faux.

## Le vocabulaire publie son contrat

```bash
rsl schema --out schemas/signals.schema.json
```

Le document est un JSON Schema recursif : un `$defs/node` enumere les onze
types enregistres, et chaque champ de sous-noeud y pointe. Un validateur
ordinaire verifie donc un arbre ENTIER, a n'importe quelle profondeur - avant
d'ouvrir le moindre fichier de donnees.

```json
{
  "title": "compare@1",
  "type": "object",
  "properties": {
    "type":  {"const": "compare"},
    "op":    {"type": "string", "enum": [">", ">=", "<", "<=", "==", "!="]},
    "left":  {"$ref": "#/$defs/node"},
    "right": {"$ref": "#/$defs/node"}
  },
  "required": ["type", "op", "left", "right"],
  "additionalProperties": false
}
```

Trois proprietes le rendent digne de confiance :

**Il est engendre, pas saisi.** Chaque type de noeud declare ses champs une
fois ; le schema en derive, et `build_signal` refuse tout champ non declare a
partir de la meme declaration. Leur divergence est impossible par construction.

**Il est verifie contre le constructeur.** Onze cas malformes - type inconnu,
operateur invalide, champ en trop, champ manquant, lag negatif, operandes
vides, erreur en profondeur - sont testes deux fois : le schema doit refuser,
et `build_signal` aussi. Un schema plus permissif que le code laisserait passer
ce qu'il pretend interdire ; un schema plus strict rejetterait du valide.

**Il ne peut pas rouiller.** Les fichiers de `schemas/` sont compares au
registre a chaque execution des tests. Un noeud ajoute sans regenerer le
fichier fait echouer la suite, avec la commande a lancer.

Ce contrat est ce qui manquait pour qu'une machine produise une specification
valide du premier coup, au lieu d'iterer sur des messages d'erreur.

## Ce que le vocabulaire couvre

Mesure sur un echantillon volontairement melange de seize idees de strategie :
**quatorze s'expriment en JSON, deux non.**

```
OK   Donchian : cassure du plus haut 20
OK   Bollinger : retour a la moyenne a -2 ecarts
OK   Filtre de volume relatif (> 2x la moyenne)
OK   Momentum 60 barres positif ET au-dessus de la SMA 200
OK   Croisement MACD-like (EMA 12 croise EMA 26)
OK   Compression de volatilite (ATR sous sa moyenne)
OK   Stop a 2 ATR sous la cloture
OK   Sortie si la cloture repasse sous le plus bas 10
OK   Sortie apres 10 barres en position
OK   Stop suiveur sur le plus haut atteint
OK   Momentum ajuste de la volatilite (score de classement)
OK   RSI sous 30
OK   Bande de Bollinger haute
OK   Pente de tendance positive

OK   Spread ES/NQ (deux instruments)
OK   Z-score du spread sur 120 barres
OK   Ne trader que du lundi au vendredi
OK   Couverture en ratio : 2 ES contre 1 NQ
OK   Force relative contre un indice de reference
```

Treize primitives, seize types de noeuds, trois moules descriptibles :
`rules@1` pour les regles mono-instrument, `panel_rules@1` pour les regles qui
lisent PLUSIEURS instruments, `ranking@1` pour le classement transversal.

**`peer` et `rolling` vont ensemble.** Le premier donne acces a un autre
instrument au meme instant ; le second eleve n'importe quelle expression en
statistique glissante. L'un sans l'autre ne sert a rien : on saurait calculer
un spread sans pouvoir le normaliser, et un niveau de spread brut ne se trade
pas. Ensemble, une strategie de paires s'ecrit en JSON - voir
`examples/strategies/paire_es_nq.json`, qui tourne sur ES/NQ reels.

**`rolling` a un cout assume** : il reevalue son sous-arbre `window` fois par
barre, via `ctx.shifted(k)`. Sur une fenetre de 120 et un sous-arbre de trois
noeuds, cela fait 360 evaluations la ou une primitive dediee en ferait une. La
correction prime sur la vitesse, et une primitive dediee reste possible quand
un cas precis devient couteux.

**`ranking@1` merite un mot.** `cross_sectional_momentum@1` etait
parametrable mais pas descriptible : on pouvait changer `lookback`, pas le
CRITERE de tri, ecrit en dur dans la classe. Avec `ranking@1` le critere est un
signal, donc du JSON - « classe par momentum ajuste de la volatilite » s'ecrit
sans toucher au code. Un test verifie que le moule reproduit exactement le
momentum ecrit a la main, ordre par ordre, sur quatre jeux de parametres.

**L'etat de position** est expose par le `Context` : quantite, barres depuis
l'entree, prix d'entree, extremes atteints. C'est le runner qui le calcule, pas
un noeud a memoire - un noeud a etat survivrait d'un run a l'autre et casserait
le determinisme. Voir [`docs/no-lookahead.md`](docs/no-lookahead.md) §2.5, et le
test de corruption du futur rejoue sur une strategie qui lit `bars_held`.

## Extension par ajout uniquement

Le socle est ferme a la modification, ouvert a l'extension. Chaque registre est
statique et **versionne** : la cle est `(nom, version)`, et reenregistrer une
cle existante leve une erreur.

| Besoin | Geste |
|---|---|
| Un indicateur nouveau | `@primitive("mon_indic", version=1, ...)` |
| Corriger un indicateur publie | `@primitive("mon_indic", version=2, ...)` - la v1 reste, et reste rejouable |
| Une regle nouvelle | composer des noeuds existants, aucun code |
| Un type de noeud nouveau | `@signal_node("mon_noeud", version=1)` |
| Une famille de strategies nouvelle | `@strategy("ma_famille", version=1, ...)` |

Raison : un rapport de run archive epingle `sma@1`. Si `sma@1` changeait de sens
un jour, le run cesserait d'etre rejouable et la verite terrain serait perdue.

Une strategie a regles se decrit entierement en JSON, sans ecrire de classe :

```json
{
  "type": "all_of",
  "operands": [
    {"type": "crosses_above",
     "fast": {"type": "primitive", "ref": "sma@1", "params": {"window": 20}},
     "slow": {"type": "primitive", "ref": "sma@1", "params": {"window": 100}}},
    {"type": "compare", "op": "<",
     "left": {"type": "primitive", "ref": "zscore@1", "params": {"window": 500}},
     "right": {"type": "constant", "value": 2.0}}
  ]
}
```

`build_signal(spec)` la reconstruit ; `signal.describe()` la reproduit, versions
epinglees. C'est le point de branchement du futur compilateur de
specifications - decrit, sans implementation, dans
[`src/rsl/pipeline.py`](src/rsl/pipeline.py).

## Donnees

Dix contrats futures continus (`.v.0`, roulement au volume), granularite 1
minute, 33,4 M barres, 2016-2026 (FDAX depuis mars 2025). Source Databento,
format Parquet, `ts_event` en UTC.

Le repertoire de donnees n'est pas versionne. Les tests d'integration le
cherchent via `RSL_DATA_DIR` et se sautent s'il est absent.

Deux caracteristiques a connaitre avant d'interpreter un resultat :

- **Les series ne sont pas ajustees au roulement.** Discontinuites de ~1,1-1,3 %
  groupees sur les dates de roulement trimestrielles, contre un p95 des ecarts
  quotidiens de 0,29 %. Une serie continue `.v.0` n'est donc pas une serie de
  prix detenable, ce qui affecte directement l'interpretation d'un buy & hold
  sur donnees reelles.
- **Les trous sont la norme**, pas l'exception : coupure de maintenance
  quotidienne d'une heure, week-ends de 49 heures, feries. Le moteur ne
  reconstruit aucune barre : toute fenetre est en nombre de barres, jamais en
  duree.

## Developpement

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

```bash
.venv/Scripts/python.exe -m pytest
```

```bash
.venv/Scripts/python.exe -m ruff check src tests && .venv/Scripts/python.exe -m mypy
```

1 134 tests, `ruff` et `mypy --strict` sans exception.

Marqueurs pytest : `adversarial` (tests qui attaquent une garantie du socle),
`slow` (tests qui touchent aux donnees reelles).

Stack : Python 3.11+, polars (couche donnees), numpy (magasin et primitives),
pydantic (configs et parametres), pytest + hypothesis, ruff, mypy strict.

polars plutot que pandas pour la couche donnees : pas d'index implicite, donc
pas d'alignement ni de forward-fill silencieux sur les jointures
multi-instruments - les deux mecanismes par lesquels le look-ahead entre dans
une couche de donnees.
