"""Provenance d'un run : de quoi le rejouer, ou constater qu'on ne peut pas.

Un backtest sans manifeste est une anecdote. Six mois plus tard, un chiffre
dans un carnet ne dit ni quelles donnees il a vues, ni quel code l'a produit,
ni si le depot etait propre a ce moment-la.

Ce que le manifeste enregistre, et pourquoi
-------------------------------------------
- **empreinte des donnees** : le SHA-256 de chaque fichier source. Un
  fournisseur qui restate son historique produit un fichier different, et le
  manifeste le revele. C'est la seule defense contre la troisieme limite du
  contrat anti-look-ahead (`docs/no-lookahead.md` §7.3).
- **empreinte de la configuration** : le hash canonique de la specification
  complete. Deux runs de meme empreinte ont recu les memes instructions.
- **etat du depot** : commit, branche, et surtout `dirty`. Un run lance sur un
  arbre de travail modifie n'est PAS rejouable, et le manifeste doit le dire
  plutot que de laisser croire au commit affiche.
- **versions des dependances** : polars, numpy et pydantic changent leurs
  comportements de bord d'une version a l'autre.
- **graine** : le moteur n'utilise aucun hasard, mais une strategie peut en
  utiliser a tort. La graine est appliquee aux generateurs globaux avant le
  run pour que meme cette erreur soit reproductible.

Ce qu'il ne fait PAS partie
---------------------------
L'horodatage du run et l'etat de la machine ne participent pas a l'empreinte de
resultat. Deux runs identiques doivent donner le meme `result_fingerprint`
alors qu'ils ont ete lances a des instants differents ; melanger les deux
rendrait l'exigence de reproductibilite invérifiable.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Final

import numpy as np

SpecDict = dict[str, object]

TRACKED_DEPENDENCIES: Final[tuple[str, ...]] = (
    "polars",
    "numpy",
    "pydantic",
    "pyarrow",
)

GIT_TIMEOUT_SECONDS: Final[float] = 5.0


def canonical_hash(payload: object) -> str:
    """Empreinte SHA-256 d'une structure, insensible a l'ordre des cles.

    `sort_keys` est ce qui rend l'empreinte utilisable : sans lui, deux
    configurations identiques ecrites dans un ordre different auraient des
    empreintes differentes, et la comparaison ne voudrait rien dire.
    """
    encoded = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def apply_seed(seed: int) -> None:
    """Seme les generateurs globaux avant un run.

    Le moteur n'utilise aucun hasard : cette fonction n'existe que pour qu'une
    strategie qui en utiliserait - a tort - reste reproductible. Elle ne rend
    pas un backtest aleatoire acceptable, elle rend son erreur constatable.
    """
    random.seed(seed)
    np.random.seed(seed % (2**32))


@dataclass(frozen=True, slots=True)
class GitState:
    """Etat du depot au moment du run."""

    available: bool
    commit: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    detail: str = ""

    @property
    def is_reproducible(self) -> bool:
        """Un arbre de travail modifie ne se rejoue pas."""
        return self.available and self.dirty is False

    def describe(self) -> SpecDict:
        return {
            "available": self.available,
            "commit": self.commit,
            "branch": self.branch,
            "dirty": self.dirty,
            "is_reproducible": self.is_reproducible,
            "detail": self.detail,
        }


def capture_git_state(root: Path | None = None) -> GitState:
    """Interroge git, sans jamais faire echouer le run.

    L'absence de git, ou l'absence de depot, est une information a consigner -
    pas une raison de refuser de travailler.
    """
    cwd = root or Path.cwd()

    def run(*args: str) -> str | None:
        try:
            # Arguments litteraux : aucune entree utilisateur n'atteint cet appel.
            completed = subprocess.run(
                ["git", *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    commit = run("rev-parse", "HEAD")
    if commit is None:
        return GitState(available=False, detail="git indisponible ou hors depot")

    status = run("status", "--porcelain")
    return GitState(
        available=True,
        commit=commit,
        branch=run("rev-parse", "--abbrev-ref", "HEAD"),
        dirty=bool(status) if status is not None else None,
        detail="" if not status else f"{len(status.splitlines())} fichier(s) modifie(s)",
    )


def capture_dependencies(names: tuple[str, ...] = TRACKED_DEPENDENCIES) -> dict[str, str]:
    """Versions installees des dependances suivies, triees."""
    versions: dict[str, str] = {}
    for name in sorted(names):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "absent"
    return versions


@dataclass(frozen=True, slots=True)
class DataSource:
    """Un fichier de donnees tel qu'il a ete consomme."""

    symbol: str
    path: str
    source_hash: str
    n_bars: int
    granularity: str
    first_ts: str
    last_ts: str
    transformations: tuple[str, ...] = ()

    def describe(self) -> SpecDict:
        return {
            "symbol": self.symbol,
            "path": self.path,
            "source_hash": self.source_hash,
            "n_bars": self.n_bars,
            "granularity": self.granularity,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "transformations": list(self.transformations),
        }


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Provenance complete d'un run."""

    created_at: str
    config_hash: str
    seed: int
    git: GitState
    dependencies: dict[str, str]
    python_version: str
    platform_name: str
    data_sources: tuple[DataSource, ...] = ()
    primitives: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def capture(
        *,
        config: SpecDict,
        seed: int,
        data_sources: tuple[DataSource, ...] = (),
        primitives: tuple[str, ...] = (),
        repo_root: Path | None = None,
    ) -> RunManifest:
        git = capture_git_state(repo_root)
        warnings: list[str] = []
        if not git.available:
            warnings.append(
                "aucun depot git detecte : le code qui a produit ce run n'est pas identifie"
            )
        elif git.dirty:
            commit = git.commit[:8] if git.commit else "?"
            warnings.append(
                f"arbre de travail modifie ({git.detail}) : le commit {commit} "
                f"ne suffit PAS a rejouer ce run"
            )
        missing = [name for name, version in capture_dependencies().items() if version == "absent"]
        if missing:
            warnings.append(f"dependance(s) non installee(s) : {', '.join(missing)}")
        if not data_sources:
            warnings.append("aucune source de donnees enregistree : provenance incomplete")
        elif any(not source.source_hash for source in data_sources):
            warnings.append(
                "au moins une source sans empreinte : chargee avec `with_hash=False`, "
                "donc une restatement du fournisseur passerait inapercue"
            )

        return RunManifest(
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            config_hash=canonical_hash(config),
            seed=seed,
            git=git,
            dependencies=capture_dependencies(),
            python_version=sys.version.split()[0],
            platform_name=f"{platform.system()} {platform.release()} ({platform.machine()})",
            data_sources=data_sources,
            primitives=primitives,
            warnings=tuple(warnings),
        )

    @property
    def is_reproducible(self) -> bool:
        """Ce run peut-il etre rejoue a l'identique par un tiers ?"""
        return self.git.is_reproducible and all(s.source_hash for s in self.data_sources)

    def describe(self) -> SpecDict:
        return {
            "created_at": self.created_at,
            "config_hash": self.config_hash,
            "seed": self.seed,
            "git": self.git.describe(),
            "dependencies": dict(self.dependencies),
            "python_version": self.python_version,
            "platform": self.platform_name,
            "data_sources": [s.describe() for s in self.data_sources],
            "primitives": list(self.primitives),
            "is_reproducible": self.is_reproducible,
            "warnings": list(self.warnings),
        }

    def render(self) -> str:
        lines = [
            f"Horodatage   {self.created_at}",
            f"Config       {self.config_hash[:16]}   graine {self.seed}",
        ]
        if self.git.available:
            state = "propre" if self.git.dirty is False else "MODIFIE"
            lines.append(
                f"Depot        {self.git.commit[:12] if self.git.commit else '?'} "
                f"({self.git.branch}) - {state}"
            )
        else:
            lines.append("Depot        aucun")
        lines.append(
            f"Plateforme   Python {self.python_version}, {self.platform_name}"
        )
        lines.append(
            "Dependances  "
            + ", ".join(f"{n} {v}" for n, v in sorted(self.dependencies.items()))
        )
        for source in self.data_sources:
            marks = f" [{', '.join(source.transformations)}]" if source.transformations else ""
            lines.append(
                f"Donnees      {source.symbol}{marks} {source.n_bars} barres "
                f"{source.granularity}  {source.source_hash[:12] or 'SANS EMPREINTE'}"
            )
        lines.append(
            f"Rejouable    {'oui' if self.is_reproducible else 'NON'}"
        )
        lines.extend(f"Avertissement  {w}" for w in self.warnings)
        return "\n".join(lines)
