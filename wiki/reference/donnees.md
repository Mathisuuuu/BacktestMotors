---
type: reference
updated: 2026-09-11
autorite: docs/no-lookahead.md §4 + src/rsl/data/
---

# Donnees — routeur

> Page routeur. Le repertoire de donnees **n'est pas versionne** (`data/` est
> dans `.gitignore`). Les tests d'integration le cherchent via la variable
> d'environnement `RSL_DATA_DIR` et se sautent s'il est absent.

> [!WARNING] Le paquet `rsl.data` existe sur le disque mais n'est **pas versionne** (2026-09-11)
> Etat au 2026-09-11 : les 6 modules sont **revenus** dans la copie de travail
> -- `schema`, `feed`, `loader`, `resample`, `validation`, `instruments`, soit
> 7 fichiers et 2063 lignes. `import rsl.data` fonctionne, la suite de tests
> passe et `rsl run` produit un rapport. **Mais la cause racine n'est pas
> corrigee** : `.gitignore:1` contient toujours `data/`, motif non ancre qui en
> git s'applique a n'importe quel repertoire nomme `data` a n'importe quelle
> profondeur -- donc encore a `src/rsl/data/`.
>
> Consequence mesuree : `git ls-files src/` rend **36** fichiers quand le disque
> en porte **43**. `git check-ignore -v src/rsl/data/feed.py` repond
> `.gitignore:1:data/`. Le paquet reste donc invisible de git, et `git status`
> affiche **« propre »** pendant que le tiers du moteur n'est suivi par rien.
> Un clone frais, un `git clean -xfd` ou un changement de machine reperd la
> couche donnees exactement comme le 2026-09-10.
>
> **Correctif restant** : ancrer le motif en `/data/`, puis committer
> `src/rsl/data/`. Tant que ce n'est pas fait, la reconstruction n'est sauvee
> nulle part. Voir [[hot]] § Next Actions.

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
