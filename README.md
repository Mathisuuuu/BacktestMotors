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
| CLI et manifeste de run | a venir |

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

Marqueurs pytest : `adversarial` (tests qui attaquent une garantie du socle),
`slow` (tests qui touchent aux donnees reelles).

Stack : Python 3.11+, polars (couche donnees), numpy (magasin et primitives),
pydantic (configs et parametres), pytest + hypothesis, ruff, mypy strict.

polars plutot que pandas pour la couche donnees : pas d'index implicite, donc
pas d'alignement ni de forward-fill silencieux sur les jointures
multi-instruments - les deux mecanismes par lesquels le look-ahead entre dans
une couche de donnees.
