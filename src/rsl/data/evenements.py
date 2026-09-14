"""Calendrier d'EVENEMENTS declare : FOMC, NFP, publications.

Pourquoi ce module existe
--------------------------
Une entree `data` est un parquet OHLCV. Sur futures intraday, cela laisse hors
d'atteinte toute une famille de strategies : celles qui se positionnent autour
d'une annonce macro. Le recensement du 2026-09-14 la comptait parmi les quatre
familles bloquees, et c'etait la seule des quatre que le perimetre declare -
intraday, futures, une position a la fois - ne rendait pas sans objet.

Ce que le socle exige, et qui vaut ici aussi
---------------------------------------------
Le calendrier est **declare**, jamais deduit. Son fichier est hache et entre au
manifeste de run, exactement comme les cotations : deux runs qui s'appuient sur
des calendriers differents ne peuvent pas se confondre.

La question de causalite, et comment elle est tranchee
-------------------------------------------------------
« Combien de minutes avant la prochaine annonce » lit un instant FUTUR. Ce n'est
pas pour autant du look-ahead : un calendrier economique est **publie a
l'avance**, et savoir que le FOMC parle a 14 h ne dit rien du prix qu'il fera.

Mais cette propriete depend du FICHIER, pas du socle. Un calendrier reconstruit
apres coup - dates revisees, evenements ajoutes retrospectivement - ferait
entrer du futur par la porte de derriere, et aucune inspection du code ne le
verrait.

D'ou le choix : `minutes_since` est toujours disponible, parce qu'il ne regarde
que le passe. `minutes_until` **exige** que la source declare
`known_in_advance: true`. Ce n'est pas une garantie - c'est une AFFIRMATION
signee, qui entre dans le `config_hash` et engage celui qui l'ecrit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

from rsl.errors import ConfigurationError, DataValidationError

IntArray = npt.NDArray[np.int64]

COLONNE_INSTANT: Final[str] = "ts_event"
NS_PER_MINUTE: Final[int] = 60 * 1_000_000_000


class EventField(StrEnum):
    """Ce qu'une feuille `event` peut lire."""

    MINUTES_SINCE = "minutes_since"
    """Minutes ecoulees depuis le dernier evenement a ou avant cette barre.

    Toujours disponible : ne regarde que le passe."""

    MINUTES_UNTIL = "minutes_until"
    """Minutes restantes avant le prochain evenement a ou apres cette barre.

    Exige `known_in_advance: true` sur la source."""

    IS_NOW = "is_now"
    """1.0 si un evenement tombe exactement sur cette barre, 0.0 sinon."""


EXIGENT_L_AVANCE: Final[tuple[EventField, ...]] = (EventField.MINUTES_UNTIL,)


@dataclass(frozen=True, slots=True)
class EventCalendar:
    """Les instants d'un calendrier, tries, plus ce qu'on affirme d'eux."""

    name: str
    instants: IntArray
    known_in_advance: bool
    source_hash: str

    def __post_init__(self) -> None:
        if self.instants.size == 0:
            raise ConfigurationError(
                f"calendrier '{self.name}' : aucun evenement. Un calendrier vide "
                f"rendrait `None` partout, ce qui se lit comme « la strategie n'a "
                f"pas declenche » plutot que comme « le fichier est vide »."
            )
        if bool(np.any(np.diff(self.instants) < 0)):
            raise DataValidationError(
                f"calendrier '{self.name}' : instants non tries. Le loader ne trie "
                f"pas - un fichier desordonne est une source douteuse, pas une "
                f"source a reparer.",
                None,
            )

    def valeur(self, ts_close_ns: int, field: EventField) -> float | None:
        """La grandeur demandee a l'instant de cloture d'une barre.

        Rend `None` quand il n'y a rien a dire - aucun evenement avant, ou
        aucun apres - et jamais une sentinelle : « pas d'annonce en vue » et
        « annonce dans zero minute » ne doivent pas se confondre.
        """
        if field in EXIGENT_L_AVANCE and not self.known_in_advance:
            raise ConfigurationError(
                f"calendrier '{self.name}' : '{field.value}' lit un instant FUTUR. "
                f"Il n'est disponible que si la source declare "
                f"`known_in_advance: true`, ce qui AFFIRME que ces dates etaient "
                f"publiees a l'avance. Sans cette affirmation, seul "
                f"'{EventField.MINUTES_SINCE.value}' est lisible."
            )

        # `side="right"` : un evenement tombant EXACTEMENT sur la cloture de la
        # barre appartient au passe de cette barre. La barre est close, son prix
        # est connu, l'annonce a eu lieu pendant qu'elle se formait.
        apres = int(np.searchsorted(self.instants, ts_close_ns, side="right"))

        match field:
            case EventField.MINUTES_SINCE:
                if apres == 0:
                    return None
                return (ts_close_ns - int(self.instants[apres - 1])) / NS_PER_MINUTE
            case EventField.MINUTES_UNTIL:
                if apres >= self.instants.size:
                    return None
                return (int(self.instants[apres]) - ts_close_ns) / NS_PER_MINUTE
            case EventField.IS_NOW:
                if apres == 0:
                    return 0.0
                return 1.0 if int(self.instants[apres - 1]) == ts_close_ns else 0.0

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "n_events": int(self.instants.size),
            "known_in_advance": self.known_in_advance,
            "source_hash": self.source_hash,
            "premier": int(self.instants[0]),
            "dernier": int(self.instants[-1]),
        }


def charger_calendrier(
    path: Path, *, name: str, known_in_advance: bool, with_hash: bool = True
) -> EventCalendar:
    """Lit un parquet d'instants et le gele.

    Le fichier porte une colonne `ts_event` en nanosecondes UTC. Les autres
    colonnes sont IGNOREES : ce module ne sait rien dire d'un libelle ou d'une
    surprise chiffree, et pretendre le contraire ouvrirait un canal dont
    personne n'aurait verifie la causalite.
    """
    if not path.exists():
        raise ConfigurationError(
            f"calendrier '{name}' : fichier introuvable - {path}"
        )
    frame = pl.read_parquet(path)
    if COLONNE_INSTANT not in frame.columns:
        raise ConfigurationError(
            f"calendrier '{name}' : colonne '{COLONNE_INSTANT}' absente. "
            f"Colonnes lues : {frame.columns}"
        )
    serie = frame.get_column(COLONNE_INSTANT)
    instants = np.asarray(serie.cast(pl.Int64).to_numpy(), dtype=np.int64)
    empreinte = (
        hashlib.sha256(path.read_bytes()).hexdigest() if with_hash else "non-hache"
    )
    return EventCalendar(
        name=name,
        instants=instants,
        known_in_advance=known_in_advance,
        source_hash=empreinte,
    )
