"""Serie EXOGENE declaree : fondamentaux, sentiment, positionnement.

Pourquoi ce module existe
--------------------------
Une entree `data` est un parquet OHLCV ; `evenements.py` y a ajoute des
INSTANTS. Restait le dernier canal ferme du recensement : une grandeur
CHIFFREE qui ne vienne pas du prix - positionnement COT, open interest publie,
indice de sentiment, surprise macro, estimation de benefices.

Le module `evenements.py` nomme lui-meme ce manque :

    « ce module ne sait rien dire d'un libelle ou d'une surprise chiffree, et
      pretendre le contraire ouvrirait un canal dont personne n'aurait verifie
      la causalite »

Le voici ouvert, avec la verification qui manquait.

Le piege, et comment il est tranche
------------------------------------
Il ne ressemble PAS a celui des evenements. Lire « la derniere valeur connue »
ne regarde jamais l'avenir : c'est un `searchsorted` vers la gauche, aussi
causal qu'un `lag`. Le danger est ailleurs, et il est pire parce qu'il est
invisible dans le code.

**Une donnee fondamentale porte deux dates** : celle de ce qu'elle MESURE, et
celle ou elle a ete PUBLIEE. Le rapport COT du mardi parait le vendredi ; un
resultat trimestriel arrete au 31 mars sort fin avril. Un fichier horodate a la
date de MESURE fait donc entrer trois jours - ou trois semaines - de futur,
sans qu'aucune inspection du socle ne puisse le voir. Le tableau est trie, les
valeurs sont justes, la lecture est causale, et le backtest est faux.

D'ou la meme reponse que pour `minutes_until` : le socle ne peut ni verifier ni
refuser sans amputer la famille entiere, alors **il fait signer**. La source
declare `horodatee_a_la_publication: true`, ce qui AFFIRME que `ts_event` est
l'instant ou la donnee est devenue connaissable. Ce n'est pas une garantie,
c'est un engagement, et il entre dans le `config_hash`.

Sans cette affirmation, la serie se charge quand meme - mais elle n'est
lisible qu'a travers un DECALAGE declare, `publication_lag_minutes`, qui
repousse chaque valeur d'autant. Mieux vaut un retard trop prudent qu'une
avance invisible.
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
FloatArray = npt.NDArray[np.float64]

COLONNE_INSTANT: Final[str] = "ts_event"
COLONNE_VALEUR: Final[str] = "value"
NS_PER_MINUTE: Final[int] = 60 * 1_000_000_000


class ChampExogene(StrEnum):
    """Ce qu'une feuille `exogenous` peut lire."""

    VALUE = "value"
    """Derniere valeur publiee a ou avant la cloture de la barre.

    `None` tant qu'aucune publication n'a eu lieu - et jamais zero, qui se
    lirait comme une mesure nulle."""

    AGE_MINUTES = "age_minutes"
    """Minutes ecoulees depuis cette publication.

    Sert a REFUSER une donnee perimee : un sentiment vieux de six semaines
    n'est pas un sentiment. Sans ce champ, une serie qui cesse d'etre
    alimentee continuerait de rendre sa derniere valeur indefiniment, et la
    strategie tournerait sur un fossile sans que rien ne le signale."""


@dataclass(frozen=True, slots=True)
class SerieExogene:
    """Des couples (instant, valeur) tries, plus ce qu'on affirme d'eux."""

    name: str
    instants: IntArray
    valeurs: FloatArray
    horodatee_a_la_publication: bool
    publication_lag_minutes: int
    source_hash: str

    def __post_init__(self) -> None:
        if self.instants.size == 0:
            raise ConfigurationError(
                f"serie exogene '{self.name}' : aucune valeur. Elle rendrait "
                f"`None` partout, ce qui se lit comme « la strategie n'a pas "
                f"declenche » plutot que comme « le fichier est vide »."
            )
        if self.instants.size != self.valeurs.size:
            raise DataValidationError(
                f"serie exogene '{self.name}' : {self.instants.size} instants pour "
                f"{self.valeurs.size} valeurs.",
                None,
            )
        if bool(np.any(np.diff(self.instants) < 0)):
            raise DataValidationError(
                f"serie exogene '{self.name}' : instants non tries. Le loader ne "
                f"trie pas - un fichier desordonne est une source douteuse, pas "
                f"une source a reparer.",
                None,
            )
        if not self.horodatee_a_la_publication and self.publication_lag_minutes <= 0:
            raise ConfigurationError(
                f"serie exogene '{self.name}' : sans "
                f"`horodatee_a_la_publication: true`, un "
                f"`publication_lag_minutes` STRICTEMENT POSITIF est obligatoire. "
                f"Une donnee horodatee a sa date de MESURE est connue plus tard "
                f"qu'elle ne le pretend - le rapport COT du mardi parait le "
                f"vendredi - et la lire sans decalage fait entrer du futur que "
                f"rien dans le code ne peut voir."
            )
        if self.horodatee_a_la_publication and self.publication_lag_minutes != 0:
            raise ConfigurationError(
                f"serie exogene '{self.name}' : "
                f"`horodatee_a_la_publication: true` AFFIRME que `ts_event` est "
                f"deja l'instant de publication. Y ajouter un decalage de "
                f"{self.publication_lag_minutes} min contredirait l'affirmation ; "
                f"choisir l'une des deux."
            )

    @property
    def _decalage_ns(self) -> int:
        return self.publication_lag_minutes * NS_PER_MINUTE

    def valeur(self, ts_close_ns: int, field: ChampExogene) -> float | None:
        """La grandeur demandee a l'instant de cloture d'une barre.

        `side="right"` : une publication tombant EXACTEMENT sur la cloture
        appartient au passe de cette barre - la barre est close, son prix est
        connu, la publication a eu lieu pendant qu'elle se formait. C'est la
        meme convention que `evenements.py`, et il n'y en a qu'une.
        """
        seuil = ts_close_ns - self._decalage_ns
        connues = int(np.searchsorted(self.instants, seuil, side="right"))
        if connues == 0:
            return None
        dernier = connues - 1
        match field:
            case ChampExogene.VALUE:
                valeur = float(self.valeurs[dernier])
                return None if not np.isfinite(valeur) else valeur
            case ChampExogene.AGE_MINUTES:
                publiee_a = int(self.instants[dernier]) + self._decalage_ns
                return (ts_close_ns - publiee_a) / NS_PER_MINUTE

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "n_valeurs": int(self.instants.size),
            "horodatee_a_la_publication": self.horodatee_a_la_publication,
            "publication_lag_minutes": self.publication_lag_minutes,
            "source_hash": self.source_hash,
        }


def charger_serie_exogene(
    path: Path,
    *,
    name: str,
    horodatee_a_la_publication: bool,
    publication_lag_minutes: int = 0,
    with_hash: bool = True,
) -> SerieExogene:
    """Lit un parquet de couples (instant, valeur) et le gele.

    Le fichier porte `ts_event` en nanosecondes UTC et `value` en flottant.
    Les autres colonnes sont IGNOREES : une serie porte UNE grandeur, et en
    laisser passer plusieurs sous un seul nom rendrait indecidable laquelle la
    strategie a lue.
    """
    if not path.exists():
        raise ConfigurationError(f"serie exogene '{name}' : fichier introuvable - {path}")
    frame = pl.read_parquet(path)
    for colonne in (COLONNE_INSTANT, COLONNE_VALEUR):
        if colonne not in frame.columns:
            raise ConfigurationError(
                f"serie exogene '{name}' : colonne '{colonne}' absente. "
                f"Colonnes lues : {frame.columns}"
            )
    instants = np.asarray(
        frame.get_column(COLONNE_INSTANT).cast(pl.Int64).to_numpy(), dtype=np.int64
    )
    valeurs = np.asarray(
        frame.get_column(COLONNE_VALEUR).cast(pl.Float64).to_numpy(), dtype=np.float64
    )
    empreinte = (
        hashlib.sha256(path.read_bytes()).hexdigest() if with_hash else "non-hache"
    )
    return SerieExogene(
        name=name,
        instants=instants,
        valeurs=valeurs,
        horodatee_a_la_publication=horodatee_a_la_publication,
        publication_lag_minutes=publication_lag_minutes,
        source_hash=empreinte,
    )
