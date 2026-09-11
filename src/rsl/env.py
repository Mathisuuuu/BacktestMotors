"""Racine des donnees, resolue par l'environnement.

Les fichiers de cotations ne sont pas versionnes et ne vivent pas au meme
endroit chez deux personnes. Une specification de backtest ne peut donc pas
porter un chemin absolu : elle porte un chemin **relatif a une racine**, et la
racine est une propriete de la machine, pas du run.

La racine est cherchee dans cet ordre, le premier qui repond gagne :

1. la variable d'environnement `RSL_DATA_DIR` ;
2. la cle `RSL_DATA_DIR` d'un fichier `.env`, cherche depuis le repertoire
   courant puis dans chaque parent, SANS jamais sortir du depot.

L'environnement l'emporte sur le fichier : c'est la precedence habituelle, et
elle permet de surcharger le temps d'une commande sans editer quoi que ce soit.

Aucune dependance : le format `.env` utile ici tient en quelques lignes, et le
manifeste de run enregistre les versions des dependances - en ajouter une pour
lire six lignes de `CLE=valeur` se paierait sur chaque rapport archive.
"""

from __future__ import annotations

import os
from pathlib import Path

from rsl.errors import ConfigurationError

DATA_ROOT_VAR = "RSL_DATA_DIR"
DOTENV_NAME = ".env"
ROOT_MARKERS = (".git", "pyproject.toml")


def parse_dotenv(text: str) -> dict[str, str]:
    """Lit un `.env` minimal : `CLE=valeur`, `#` en commentaire.

    Tolere le prefixe `export` et les guillemets autour de la valeur, parce que
    les deux se retrouvent dans a peu pres tous les `.env` existants. Une ligne
    qui ne contient pas `=` est ignoree plutot que fatale : un `.env` est un
    fichier de confort, il ne doit pas pouvoir casser un run.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def read_dotenv(path: Path) -> dict[str, str]:
    """Lit un `.env` en tolerant son encodage.

    PowerShell 5.1 ecrit ses redirections en UTF-16 : un `.env` cree avec
    `"CLE=valeur" > .env` depuis une console Windows n'est PAS de l'UTF-8. Le
    lire avec le seul UTF-8 leverait une `UnicodeDecodeError` que rien dans le
    message ne relierait a la cause.
    """
    raw = path.read_bytes()
    for encodage in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return parse_dotenv(raw.decode(encodage))
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ConfigurationError(
        f"fichier {path} illisible : ni UTF-8, ni UTF-16, ni CP1252."
    )


def find_dotenv(start: Path | None = None) -> Path | None:
    """Cherche un `.env`, SANS jamais sortir du depot.

    La remontee s'arrete au premier repertoire portant un marqueur de racine de
    projet (`.git` ou `pyproject.toml`), ce repertoire inclus. Remonter
    au-dela, jusqu'a la racine du disque, ferait ramasser le `.env` d'un projet
    voisin ou celui du repertoire personnel de l'utilisateur - une racine de
    donnees silencieusement heritee d'ailleurs serait pire que pas de racine
    du tout.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        path = candidate / DOTENV_NAME
        if path.is_file():
            return path
        if any((candidate / marqueur).exists() for marqueur in ROOT_MARKERS):
            return None
    return None


def data_root(start: Path | None = None) -> Path | None:
    """Racine des cotations, ou `None` si la machine n'en declare aucune."""
    from_environment = os.environ.get(DATA_ROOT_VAR)
    if from_environment and from_environment.strip():
        return Path(from_environment.strip()).expanduser()

    dotenv = find_dotenv(start)
    if dotenv is None:
        return None
    value = read_dotenv(dotenv).get(DATA_ROOT_VAR, "")
    if not value.strip():
        return None
    return Path(value.strip()).expanduser()


def resolve_data_path(path: Path, start: Path | None = None) -> Path:
    """Rend le chemin absolu d'un fichier de cotations.

    Un chemin deja absolu est rendu tel quel : les specifications anciennes
    continuent de fonctionner. Un chemin relatif exige une racine, et son
    absence est une erreur explicite - pas un chemin resolu contre le
    repertoire courant, qui dependrait de l'endroit d'ou la commande est lancee.
    """
    if path.is_absolute():
        return path
    root = data_root(start)
    if root is None:
        raise ConfigurationError(
            f"chemin de donnees relatif '{path.as_posix()}' mais aucune racine declaree. "
            f"Definir {DATA_ROOT_VAR} dans un fichier {DOTENV_NAME} a la racine du depot "
            f"(voir {DOTENV_NAME}.example), ou dans l'environnement."
        )
    return root / path
