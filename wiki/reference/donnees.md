---
type: reference
updated: 2026-09-10
autorite: docs/no-lookahead.md §4 + src/rsl/data/
---

# Donnees — routeur

> Page routeur. Le repertoire de donnees **n'est pas versionne** (`data/` est
> dans `.gitignore`). Les tests d'integration le cherchent via la variable
> d'environnement `RSL_DATA_DIR` et se sautent s'il est absent.

> [!WARNING] Le paquet `rsl.data` est absent du depot (2026-09-10)
> `.gitignore:1` contient `data/`, motif qui en git s'applique a **n'importe
> quel** repertoire nomme `data`, a n'importe quelle profondeur — donc aussi a
> `src/rsl/data/`. Consequence verifiee : le paquet de la couche donnees n'a
> jamais ete commite (`git log --all -- src/rsl/data` est vide, aucune stash),
> et il est absent de cette copie de travail. `import rsl.data` leve
> `ModuleNotFoundError`, alors que dix modules de `src/rsl/` l'importent.
> Voir [[hot]] § Next Actions. Les chemins `src/rsl/data/*` cites ci-dessous
> sont ceux qu'attendent les imports, pas des fichiers existants.

## Le jeu de donnees

| Dimension | Valeur |
|---|---|
| Contrats | dix futures continus `.v.0`, roulement au volume |
| Granularite source | 1 minute |
| Volume | 33,4 M barres, 2016-2026 (FDAX depuis mars 2025) |
| Source | Databento, format Parquet, `ts_event` en UTC |

## Deux caracteristiques a connaitre avant d'interpreter un resultat

- **Les series ne sont pas ajustees au roulement.** Discontinuites de ~1,1-1,3 %
  groupees sur les dates de roulement trimestrielles, contre un p95 des ecarts
  quotidiens de 0,29 %. Une serie continue `.v.0` n'est donc **pas une serie de
  prix detenable** — ce qui affecte directement l'interpretation d'un buy & hold
  sur donnees reelles.
- **Les trous sont la norme**, pas l'exception : coupure de maintenance
  quotidienne d'une heure, week-ends de 49 heures, feries. Le moteur ne
  reconstruit aucune barre : **toute fenetre est en nombre de barres, jamais en
  duree** (voir [[Failed Ideas/ledger]]).

## Ou est quoi

| Question | Reponse faisant autorite |
|---|---|
| Schema de barre, granularites | `src/rsl/data/schema.py` |
| Chargement et validation | `src/rsl/data/loader.py` — `load_bar_store` rend aussi un rapport |
| Iteration a curseur | `src/rsl/data/feed.py` — voir [[concepts/context-curseur]] |
| Politique de donnees manquantes | [docs/no-lookahead.md](../../docs/no-lookahead.md) §4 |
| Valider des fichiers en ligne de commande | `rsl validate FICHIER...` — la racine est deduite du nom (`ES_v0_1m` → `ES`) |
| Table des contrats | `rsl instruments` — multiplicateur, tick, valeur du tick, frais, marge |
| Reechantillonnage causal | couche donnees + `rsl run` (champ `resample` de la config) |

## Liens wiki

[[reference/contrat-anti-lookahead]] · [[concepts/context-curseur]] ·
[[reference/cli]]
