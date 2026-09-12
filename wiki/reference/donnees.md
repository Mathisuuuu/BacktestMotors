---
type: reference
updated: 2026-09-12
autorite: docs/no-lookahead.md §4 + src/rsl/data/
---

# Donnees — routeur

> Page routeur. Le repertoire de donnees **n'est pas versionne** (`data/` est
> dans `.gitignore`). Autorite : [src/rsl/env.py](../../src/rsl/env.py).

## Ou vit le fichier d'un instrument

`InstrumentSpec.category` porte la classe d'actif - une propriete du CONTRAT,
pas du disque - et `InstrumentSpec.data_path` en derive le chemin RELATIF :
`indices/ES_v0_1m.parquet`, `metaux/GC_v0_1m.parquet`.

Une seule convention, ecrite une seule fois : la classe donne le dossier, le
nom de fichier suit `{root}_v0_1m` (`v0` pour la serie continue non ajustee,
`1m` pour la granularite native). Elle vivait en DOUBLE jusqu'au 2026-09-12 -
`gui/montage.py` en portait une copie, qu'un instrument range ailleurs aurait
fait mentir sans prevenir.

Un instrument sans classe - ceux que construisent les tests - n'a pas de
chemin et le dit en levant : il n'existe sur aucun disque, et rendre un chemin
plausible serait pire qu'un refus.

## Ou sont les cotations — `RSL_DATA_DIR`

Les cotations ne vivent pas au meme endroit chez deux personnes. Une
specification de backtest ne porte donc **jamais** de chemin absolu : elle porte
un chemin **relatif a une racine**, et la racine est une propriete de la
machine, pas du run.

| | |
|---|---|
| Declaration | `RSL_DATA_DIR` dans un fichier `.env` a la racine du depot |
| Modele versionne | [.env.example](../../.env.example) — a copier en `.env` |
| Surcharge ponctuelle | la variable d'environnement l'emporte sur le fichier |
| `.env` versionne ? | non : `/.env` dans `.gitignore`, motif **ancre** (lecon L5) |

```bash
cp .env.example .env
```

Une specification ecrit alors `"path": "indices/ES_v0_1m.parquet"`. Un chemin
absolu reste accepte — les specifications anciennes ne changent pas de sens —
mais il n'est pas portable, et il entre tel quel dans le `config_hash`.

Trois garde-fous, tous couverts par `tests/unit/test_env.py` :

- **Pas de repli silencieux.** Un chemin relatif sans racine declaree leve une
  `ConfigurationError` qui nomme le remede. Resoudre contre le repertoire
  courant ferait dependre le run de l'endroit d'ou la commande est lancee.
- **La recherche du `.env` ne sort pas du depot.** Elle s'arrete au premier
  repertoire portant `.git` ou `pyproject.toml`. Sans cette borne, le `.env`
  d'un projet voisin — ou celui du repertoire personnel — imposerait sa racine.
- **L'encodage est tolere.** PowerShell 5.1 ecrit ses redirections en UTF-16 :
  un `.env` cree avec `"CLE=valeur" > .env` depuis une console Windows n'est pas
  de l'UTF-8. UTF-8, UTF-16 et CP1252 sont lus.

Le `config_hash` porte la forme **relative et normalisee en `/`** : deux
machines produisent le meme hash pour le meme run. Voir [[lessons]] L7.

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
| Racine des cotations, `.env` | `src/rsl/env.py` |
| Frontieres de seance | `src/rsl/data/session.py` — **declarees**, voir [[reference/seances]] |
| Valider des fichiers en ligne de commande | `rsl validate FICHIER...` — la racine est deduite du nom (`ES_v0_1m` → `ES`) |
| Table des contrats | `rsl instruments` — multiplicateur, tick, valeur du tick, frais, marge |
| Reechantillonnage causal | couche donnees + `rsl run` (champ `resample` de la config) |
| Granularites disponibles | [docs/execution-model.md](../../docs/execution-model.md) §1.3 — 1 min brut, `5min` a `4h` **ancrees sur la seance declaree**, puis `day` a `year` |

## Liens wiki

[[reference/contrat-anti-lookahead]] · [[concepts/context-curseur]] ·
[[reference/cli]]
