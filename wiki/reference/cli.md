---
type: reference
updated: 2026-09-11
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
| `rsl schema [--what signals\|strategies\|spec\|all]` | JSON Schema du vocabulaire |
| `rsl example` | specification d'exemple, a rediriger dans un fichier |
| `rsl run CONFIG` | execute un backtest, affiche le rapport, ecrit le JSON |
| `rsl walkforward CONFIG --train N --test N` | fenetres successives |
| `rsl verify CONFIG` | execute DEUX fois et compare les empreintes |
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

## Ce que chaque run enregistre

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
