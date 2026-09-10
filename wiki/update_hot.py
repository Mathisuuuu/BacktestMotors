#!/usr/bin/env python3
"""Regenere wiki/hot.md depuis wiki/log.md et l'arborescence du wiki.

Contrat de ce script :

- bibliotheque standard uniquement, aucune dependance ;
- il ne plante jamais la session : toute erreur est rattrapee, signalee sur
  stderr, et le code de sortie reste 0 ;
- il preserve le bloc `Next Actions` entre les deux marqueurs HTML, qui est le
  SEUL endroit de hot.md editable a la main ;
- il n'ecrit le fichier que si le contenu change vraiment, pour ne pas salir
  l'arbre git a chaque fin de session.

Usage : python wiki/update_hot.py [--wiki CHEMIN] [--entries N]
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections import Counter
from pathlib import Path

# --- Marqueurs du bloc preserve. Ne pas changer : c'est un contrat avec le
# --- fichier deja sur le disque.
NA_START = "<!-- NEXT-ACTIONS:START -->"
NA_END = "<!-- NEXT-ACTIONS:END -->"

LOG_ENTRY = re.compile(r"^##\s+\[(\d{4}-\d{2}-\d{2})\]\s*(.*)$")

DEFAULT_NEXT_ACTIONS = """\
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

- [ ] **Bloquant** — `src/rsl/data/` est ignore par `.gitignore:1` (`data/`
      attrape tous les repertoires `data` a toute profondeur). Le paquet n'a
      jamais ete commite et `import rsl.data` leve. Decider : recuperer la
      couche donnees depuis une autre machine, ou la reecrire. Puis ancrer le
      motif (`/data/`) pour que ca ne se reproduise pas.
- [ ] Relancer les deux experiences seminales depuis ce wiki, avec manifeste et
      empreinte archives, pour qu'elles cessent d'etre des releves du README.
- [ ] Obtenir et ingerer la source du Deflated Sharpe, et trancher la question
      de l'independance des essais d'une grille de parametres voisins.
"""


def read(path: Path) -> str:
    """Contenu d'un fichier, chaine vide s'il est absent ou illisible."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def frontmatter(text: str) -> dict[str, str]:
    """Champs scalaires du frontmatter YAML. Volontairement naif : pas de
    parseur YAML dans la stdlib, et on ne lit que des `cle: valeur`."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def log_entries(wiki: Path) -> list[tuple[str, str]]:
    """Entrees de log, dans l'ordre du fichier : (date, reste de la ligne)."""
    out: list[tuple[str, str]] = []
    for line in read(wiki / "log.md").splitlines():
        match = LOG_ENTRY.match(line.strip())
        if match:
            out.append((match.group(1), match.group(2).strip()))
    return out


def entry_type(rest: str) -> str:
    return (rest.split("|", 1)[0] or "?").strip() or "?"


def pages(wiki: Path) -> list[Path]:
    """Pages du wiki, hors hot.md lui-meme."""
    try:
        found = sorted(p for p in wiki.rglob("*.md") if p.is_file())
    except OSError:
        return []
    return [p for p in found if p.name != "hot.md"]


def experiments_table(wiki: Path) -> list[str]:
    rows: list[str] = []
    for path in sorted((wiki / "experiments").glob("*.md")):
        meta = frontmatter(read(path))
        if meta.get("type") != "experiment":
            continue
        rows.append(
            "| [[experiments/{slug}]] | `{statut}` | `{verdict}` | {essais} | {updated} |".format(
                slug=path.stem,
                statut=meta.get("statut", "?"),
                verdict=meta.get("verdict", "?"),
                essais=meta.get("essais", "?"),
                updated=meta.get("updated", "?"),
            )
        )
    return rows


def ledger_counts(wiki: Path) -> tuple[int, int]:
    """(idees ecartees, idees en attente) — compte les lignes de tableau qui
    commencent par une date, section par section."""
    text = read(wiki / "Failed Ideas" / "ledger.md")
    if not text:
        return (0, 0)
    dead = waiting = 0
    in_waiting = False
    for line in text.splitlines():
        low = line.lower()
        if low.startswith("## ") and "attente" in low:
            in_waiting = True
        elif low.startswith("## "):
            in_waiting = False
        elif re.match(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|", line):
            if in_waiting:
                waiting += 1
            else:
                dead += 1
    return (dead, waiting)


def preserved_next_actions(hot: Path) -> str:
    """Bloc Next Actions deja present, ou le bloc par defaut au premier passage."""
    text = read(hot)
    start = text.find(NA_START)
    end = text.find(NA_END)
    if start != -1 and end > start:
        block = text[start + len(NA_START) : end].strip("\n")
        if block.strip():
            return block
    return DEFAULT_NEXT_ACTIONS.rstrip("\n")


def build(wiki: Path, keep: int) -> str:
    entries = log_entries(wiki)
    all_pages = pages(wiki)
    by_type = Counter(entry_type(rest) for _, rest in entries)
    dead, waiting = ledger_counts(wiki)
    last_date = entries[-1][0] if entries else "—"
    today = dt.date.today().isoformat()

    counts: Counter[str] = Counter()
    for path in all_pages:
        try:
            rel = path.relative_to(wiki)
        except ValueError:
            continue
        counts["hub" if len(rel.parts) == 1 else rel.parts[0]] += 1

    lines: list[str] = [
        "---",
        "type: hub",
        f"updated: {today}",
        "generated: true",
        "---",
        "",
        "# hot — etat courant",
        "",
        "> [!WARNING] FICHIER AUTO-GENERE — NE PAS EDITER A LA MAIN",
        "> Produit par [`wiki/update_hot.py`](update_hot.py), relance par le hook",
        "> `Stop` a chaque fin de session. Toute modification hors du bloc",
        "> **Next Actions** sera ecrasee sans avertissement.",
        f"> Derniere generation : {today}.",
        "",
        "## Current State",
        "",
        "| Indicateur | Valeur |",
        "|---|---|",
        f"| Pages de wiki | {len(all_pages)} |",
        f"| Entrees de log | {len(entries)} |",
        f"| Derniere activite | {last_date} |",
        f"| Idees ecartees (ledger) | {dead} |",
        f"| Idees en attente (ledger) | {waiting} |",
    ]

    for folder in sorted(counts):
        if folder != "hub":
            lines.append(f"| Pages `{folder}/` | {counts[folder]} |")

    if by_type:
        kinds = ", ".join(f"{k} × {n}" for k, n in by_type.most_common())
        lines += ["", f"**Activite par type :** {kinds}"]

    rows = experiments_table(wiki)
    lines += ["", "## Experiences", ""]
    if rows:
        lines += [
            "| Experience | Statut | Verdict | Essais | Maj |",
            "|---|---|---|---|---|",
            *rows,
        ]
        lines += [
            "",
            "Le total des essais alimente le Deflated Sharpe : un essai non "
            "enregistre gonfle le DSR de tous les autres.",
        ]
    else:
        lines.append("_Aucune page d'experience._")

    lines += ["", f"## Derniere activite — {min(keep, len(entries))} entree(s)", ""]
    if entries:
        for date, rest in entries[-keep:][::-1]:
            lines.append(f"- **{date}** — {rest}")
    else:
        lines.append("_`log.md` est vide ou absent._")

    lines += [
        "",
        "## Next Actions",
        "",
        NA_START,
        preserved_next_actions(wiki / "hot.md"),
        NA_END,
        "",
        "---",
        "",
        "Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · "
        "[[Failed Ideas/ledger]]",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenere wiki/hot.md.")
    parser.add_argument("--wiki", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--entries", type=int, default=8)
    args = parser.parse_args(argv)

    wiki = Path(args.wiki)
    if not wiki.is_dir():
        print(f"update_hot: repertoire wiki absent ({wiki}), rien a faire", file=sys.stderr)
        return 0

    hot = wiki / "hot.md"
    content = build(wiki, max(1, args.entries))
    if read(hot) == content:
        return 0
    hot.write_text(content, encoding="utf-8", newline="\n")
    print(f"update_hot: {hot} regenere")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — un hook ne doit jamais casser la session
        print(f"update_hot: ignore ({type(exc).__name__}: {exc})", file=sys.stderr)
        raise SystemExit(0) from None
