---
type: reference
updated: 2026-09-12
autorite: src/rsl/cli.py + README.md
---

# CLI `rsl` — routeur

> Page routeur. L'autorite est [src/rsl/cli.py](../../src/rsl/cli.py) ;
> [README.md](../../README.md) en donne la table complete.

| Commande | Role |
|---|---|
| `rsl validate FICHIER...` | valide des fichiers de donnees |
| `rsl instruments` | table des contrats |
| `rsl catalogue` | primitives, noeuds et strategies enregistres |
| `rsl schema [--what signals\|strategies\|spec\|all]` | JSON Schema du vocabulaire. **Le defaut est `signals`** : regenerer `schemas/rsl.schema.json` exige `--what all`, sinon le fichier complet est ecrase par le seul schema des signaux |
| `rsl example [--what strategy\|settings]` | **strategie** d'exemple par defaut, ou reglages de run. Ce qu'on ecrit est une strategie |
| `rsl run CONFIG` | execute un backtest, affiche le rapport, ecrit le JSON |
| `rsl run STRATEGIE --settings MONTAGE [--symbol ES.v.0]` | forme NORMALE depuis le 2026-09-12 : `examples/` ne contient plus de specification complete. `walkforward` et `verify` prennent les memes options |
| `rsl walkforward CONFIG --train N --test N` | fenetres successives |
| `rsl verify CONFIG` | execute DEUX fois et compare les empreintes |
| `rsl squelette [--out F]` | squelette a trous : tout ce qu'on peut ecrire, engendre depuis les registres |
| `rsl run CONFIG --archive [--note T]` | execute ET enregistre l'essai dans `essais/`. Le Deflated Sharpe est alors calcule contre TOUS les essais du depot, pas contre celui-la seul |
| `rsl walkforward CONFIG --archive [--note T]` | evalue par fenetres ET enregistre **UN** essai. Un pli n'est pas un essai : c'est la meme configuration sur d'autres donnees. Le Sharpe retenu est celui de la serie GROUPEE, pas la moyenne des plis |
| `rsl essais [--json]` | ce que le compteur du DSR contient : lignes, configurations distinctes, variance, divergences et doublons |

> **Redirection et `--out` sont equivalents depuis le 2026-09-12.** Ils ne l'etaient pas : `> fichier` ecrivait dans l'encodage de la LOCALE, donc du cp1252 sous Windows, et trois commandes sur neuf produisaient un fichier qu'aucun lecteur JSON n'ouvrait en UTF-8. Corrige a l'entree de la CLI ([cli.py](../../src/rsl/cli.py), `sortie_en_utf8`). Seul ecart restant : `print` ajoute un saut de ligne final.
| `rsl gui [CONFIG]` | tableau de bord graphique — voir [[reference/tableau-de-bord]] |
| `rsl run CONFIG --gui` | run ordinaire, puis ouverture du tableau de bord |

## Codes de sortie — a lire avant de scripter

| Code | Sens |
|---|---|
| `0` | succes |
| `1` | erreur d'usage ou d'execution — « je n'ai pas pu » |
| `2` | verification echouee — « j'ai pu, et c'est faux » : donnees rejetees, empreintes divergentes, run non rejouable |

La distinction entre `1` et `2` est deliberee : un script d'integration doit
pouvoir traiter differemment une panne et un resultat invalide.

## Ordre des etapes d'un run

La strategie est construite **avant** que les donnees soient lues : c'est elle
qui valide tout l'arbre de signaux, et une specification fausse doit etre
refusee sans qu'un octet de parquet ait ete lu. Mesure sur un univers de dix
instruments, avant et apres correction : **6,1 s contre 0,1 ms**.

`tests/unit/test_fail_fast.py` garde cet ordre sans avoir besoin de donnees :
la specification de test pointe vers un fichier inexistant, si bien que l'ordre
des deux etapes se lit dans le message d'erreur.

## Ce que chaque run enregistre

Le rapport JSON porte deux blocs de compteurs distincts :

| Bloc | Contenu | Dans l'empreinte ? |
|---|---|---|
| `counters` | ce que la DECISION a produit : ordres soumis, rejetes, annules | **oui** |
| `execution_stats` | ce que le MOTEUR a fait : fills, slippage borne, limites non touchees, stops non declenches | non |

La separation n'est pas cosmetique. `counters` entre dans l'empreinte de
resultat ; y fusionner les statistiques d'execution changerait l'empreinte de
tous les runs deja archives, pour une information qui decrit le moteur et non
la decision. Un test garde cette frontiere.

Un manifeste : horodatage, empreinte de config, graine, commit + proprete de
l'arbre, plateforme, versions des dependances, empreintes des fichiers de
donnees, et le champ **Rejouable**. Ce dernier est le seul qui compte vraiment —
voir [[concepts/determinisme]].

## Developpement

Premiere etape sur une machine neuve : declarer ou sont les cotations. Sans
`.env`, toute specification a chemin relatif leve. Voir [[reference/donnees]].

```bash
cp .env.example .env
```

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

L'interface graphique est un extra distinct — le moteur n'en depend pas :

```bash
.venv/Scripts/python.exe -m pip install -e ".[gui]"
```

```bash
.venv/Scripts/python.exe -m pytest
```

```bash
.venv/Scripts/python.exe -m ruff check src tests
```

```bash
.venv/Scripts/python.exe -m mypy
```

Marqueurs pytest : `adversarial` (tests qui attaquent une garantie du socle),
`slow` (tests qui touchent aux donnees reelles).

## Liens wiki

[[concepts/determinisme]] · [[reference/donnees]] ·
[[reference/vocabulaire-signaux]]
