"""Calendrier de seance DECLARE, et index derive.

Le socle ne connaissait aucune notion de seance, et refusait de l'inventer :
les series continues `.v.0` sont trouees, et inferer une frontiere d'un trou
serait une supposition (voir le ledger). Ce module ne devine rien non plus - il
prend une **declaration** et en tire des faits.

La declaration tient en trois champs : l'heure d'ouverture, l'heure de
fermeture, et le fuseau dans lequel les lire. Elle vit dans la specification du
run, donc elle entre dans le `config_hash` : deux personnes qui declarent des
seances differentes ne peuvent pas croire avoir fait le meme run.

Comment une barre est rattachee a une seance
--------------------------------------------
Une barre appartient a la seance ouverte a la DERNIERE occurrence de l'heure
d'ouverture qui precede son horodatage de cloture. Cette regle a deux
proprietes qui comptent :

- elle traite les seances a cheval sur minuit sans cas particulier - la seance
  ES court de 17 h a 16 h heure de Chicago, et une frontiere a minuit UTC la
  couperait en deux ;
- elle est **causale** : elle ne regarde que le passe de la barre, jamais la
  barre suivante.

`is_last` decoule de l'heure de FERMETURE declaree, pas de l'existence d'une
barre suivante. Sans declaration, on ne saurait qu'une barre etait la derniere
qu'en voyant la suivante - c'est-a-dire trop tard. Consequence assumee : si les
dernieres barres d'une seance manquent des donnees, aucune barre n'est marquee
derniere ce jour-la. C'est correct : le socle prefere ne rien dire a inventer.

Cout : la conversion de fuseau se fait par JOUR, pas par barre. Sur dix ans,
cela fait quelques milliers de conversions au lieu de plusieurs millions, et le
rattachement des barres se fait ensuite par recherche dichotomique.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import numpy.typing as npt

from rsl.errors import ConfigurationError, InsufficientHistoryError, LookAheadError

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]

NS_PER_SECOND = 1_000_000_000
NS_PER_MINUTE = 60 * NS_PER_SECOND
NS_PER_DAY = 24 * 60 * NS_PER_MINUTE


def parse_heure(texte: str, champ: str) -> dt.time:
    """`"HH:MM"` -> `time`. Tout le reste leve, plutot que d'etre devine."""
    morceaux = texte.split(":")
    if len(morceaux) != 2 or not all(m.isdigit() for m in morceaux):
        raise ConfigurationError(
            f"{champ} : format attendu 'HH:MM', recu {texte!r}"
        )
    heures, minutes = int(morceaux[0]), int(morceaux[1])
    if not (0 <= heures <= 23 and 0 <= minutes <= 59):
        raise ConfigurationError(f"{champ} : heure hors bornes, recu {texte!r}")
    return dt.time(heures, minutes)


@dataclass(frozen=True, slots=True)
class SessionCalendar:
    """Declaration d'une seance. Rien n'est deduit des donnees."""

    start: str
    end: str
    timezone: str

    def __post_init__(self) -> None:
        debut = parse_heure(self.start, "session.start")
        fin = parse_heure(self.end, "session.end")
        if debut == fin:
            raise ConfigurationError(
                f"session : start et end sont identiques ({self.start}). Une seance "
                f"de duree nulle ou de 24 h exactes est trop ambigue pour etre devinee ; "
                f"declarer des bornes distinctes"
            )
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as erreur:
            raise ConfigurationError(
                f"session.timezone : fuseau inconnu {self.timezone!r} ({erreur})"
            ) from erreur

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def heure_ouverture(self) -> dt.time:
        return parse_heure(self.start, "session.start")

    @property
    def heure_fermeture(self) -> dt.time:
        return parse_heure(self.end, "session.end")

    @property
    def traverse_minuit(self) -> bool:
        """Vrai quand la fermeture tombe le lendemain de l'ouverture."""
        return self.heure_fermeture <= self.heure_ouverture

    def describe(self) -> dict[str, str]:
        return {"start": self.start, "end": self.end, "timezone": self.timezone}


@dataclass(frozen=True, slots=True)
class SessionIndex:
    """Faits derives, alignes barre par barre sur un magasin.

    `session_number` identifie la seance ; il croit avec le temps mais n'est pas
    forcement contigu, les jours sans barre n'apparaissant pas.
    """

    calendar: SessionCalendar
    session_number: IntArray
    bar_in_session: IntArray
    minutes_from_open: FloatArray
    is_first: BoolArray
    is_last: BoolArray
    session_open: FloatArray
    session_high: FloatArray
    session_low: FloatArray
    session_close: FloatArray
    session_volume: FloatArray

    @property
    def n_sessions(self) -> int:
        return int(self.session_open.size)

    def slice(self, start: int, stop: int) -> SessionIndex:
        """Restreint aux barres `[start, stop)`.

        Les agregats par seance ne sont PAS recalcules : ils decrivent la
        seance entiere telle qu'elle a eu lieu, et une tranche de l'echantillon
        ne change pas ce qui s'est passe ce jour-la.
        """
        numeros = self.session_number[start:stop]
        return SessionIndex(
            calendar=self.calendar,
            session_number=numeros,
            bar_in_session=self.bar_in_session[start:stop],
            minutes_from_open=self.minutes_from_open[start:stop],
            is_first=self.is_first[start:stop],
            is_last=self.is_last[start:stop],
            session_open=self.session_open,
            session_high=self.session_high,
            session_low=self.session_low,
            session_close=self.session_close,
            session_volume=self.session_volume,
        )


def bornes_de_seances(
    ts_ns: IntArray, calendar: SessionCalendar
) -> tuple[IntArray, IntArray]:
    """Instants UTC d'ouverture et de fermeture de chaque seance couvrant la serie.

    PUBLIQUE, et c'est delibere : `resample` s'en sert pour ancrer ses tranches
    intra-journalieres. Deux definitions de « a quelle seance appartient cette
    barre » finiraient par diverger ; il n'y en a qu'une, et elle est ici.

    Une conversion de fuseau par jour local, pas par barre : c'est ce qui rend
    la construction utilisable sur des series de plusieurs millions de barres.
    """
    zone = calendar.zone
    debut = dt.datetime.fromtimestamp(int(ts_ns[0]) / NS_PER_SECOND, tz=zone).date()
    fin = dt.datetime.fromtimestamp(int(ts_ns[-1]) / NS_PER_SECOND, tz=zone).date()

    ouverture = calendar.heure_ouverture
    fermeture = calendar.heure_fermeture
    decalage_fin = dt.timedelta(days=1 if calendar.traverse_minuit else 0)

    # Une journee de marge de chaque cote : une barre peut appartenir a une
    # seance ouverte la veille du premier jour observe.
    jour = debut - dt.timedelta(days=2)
    dernier = fin + dt.timedelta(days=1)
    ouverts: list[int] = []
    fermes: list[int] = []
    while jour <= dernier:
        ouvre = dt.datetime.combine(jour, ouverture, tzinfo=zone)
        ferme = dt.datetime.combine(jour + decalage_fin, fermeture, tzinfo=zone)
        ouverts.append(int(ouvre.timestamp()) * NS_PER_SECOND)
        fermes.append(int(ferme.timestamp()) * NS_PER_SECOND)
        jour += dt.timedelta(days=1)

    return (
        np.asarray(ouverts, dtype=np.int64),
        np.asarray(fermes, dtype=np.int64),
    )


def build_session_index(
    ts_ns: IntArray,
    open_: FloatArray,
    high: FloatArray,
    low: FloatArray,
    close: FloatArray,
    volume: FloatArray,
    calendar: SessionCalendar,
) -> SessionIndex:
    """Construit l'index de seance d'un magasin.

    Les agregats par seance (`session_high` et les autres) decrivent la seance
    COMPLETE. Ils ne sont lisibles qu'a `lag >= 1` : la vue de contexte refuse
    de les rendre pour la seance en cours, qui n'est pas finie.
    """
    if ts_ns.size == 0:
        vide_i: IntArray = np.zeros(0, dtype=np.int64)
        vide_f: FloatArray = np.zeros(0, dtype=np.float64)
        vide_b: BoolArray = np.zeros(0, dtype=np.bool_)
        return SessionIndex(calendar, vide_i, vide_i, vide_f, vide_b, vide_b,
                            vide_f, vide_f, vide_f, vide_f, vide_f)

    ouverts, fermes = bornes_de_seances(ts_ns, calendar)
    rang = np.searchsorted(ouverts, ts_ns, side="right") - 1
    if bool(np.any(rang < 0)):  # pragma: no cover - la marge de deux jours l'evite
        raise ConfigurationError(
            "session : une barre precede la premiere ouverture calculee"
        )

    # Renumerotation compacte : seules les seances effectivement observees
    # portent un numero, et les numeros restent croissants dans le temps.
    presents, numeros = np.unique(rang, return_inverse=True)
    numeros = numeros.astype(np.int64)

    debut_de_seance = np.searchsorted(numeros, np.arange(presents.size), side="left")
    bar_in_session = np.arange(numeros.size, dtype=np.int64) - debut_de_seance[numeros]

    ouverture_de_barre = ouverts[presents][numeros]
    minutes = (ts_ns - ouverture_de_barre).astype(np.float64) / NS_PER_MINUTE

    is_first = bar_in_session == 0
    is_last = ts_ns >= fermes[presents][numeros]

    # Agregats par seance. `reduceat` decoupe sur les debuts de seance : une
    # boucle Python ferait le meme calcul en beaucoup plus de temps.
    coupes = debut_de_seance
    return SessionIndex(
        calendar=calendar,
        session_number=numeros,
        bar_in_session=bar_in_session,
        minutes_from_open=minutes,
        is_first=is_first,
        is_last=is_last,
        session_open=open_[coupes],
        session_high=np.maximum.reduceat(high, coupes),
        session_low=np.minimum.reduceat(low, coupes),
        session_close=np.append(close[coupes[1:] - 1], close[-1]),
        session_volume=np.add.reduceat(volume, coupes),
    )


class SessionField(StrEnum):
    """Ce qu'une feuille `session` peut lire."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"
    BAR_INDEX = "bar_index"
    MINUTES_FROM_OPEN = "minutes_from_open"
    IS_FIRST = "is_first"
    IS_LAST = "is_last"


POSITIONNELS = (
    SessionField.BAR_INDEX,
    SessionField.MINUTES_FROM_OPEN,
    SessionField.IS_FIRST,
    SessionField.IS_LAST,
)
"""Champs qui decrivent la BARRE courante dans sa seance, pas la seance."""

NON_CLOS = (SessionField.HIGH, SessionField.LOW, SessionField.CLOSE, SessionField.VOLUME)
"""Agregats que la seance en cours n'a pas encore : les lire a `lag` 0 serait
lire le futur de la seance. `open`, lui, est connu des sa premiere barre."""


def read_session(
    index: SessionIndex, bar: int, field: SessionField, lag: int
) -> float:
    """Valeur d'un champ de seance pour la barre `bar`, `lag` seances en arriere.

    Trois refus, tous causaux :

    - `lag` negatif : meme garde que partout ailleurs dans le socle ;
    - un agregat non clos (`high`, `low`, `close`, `volume`) a `lag` 0 : la
      seance n'est pas finie, le rendre serait lire son futur ;
    - un champ positionnel a `lag` non nul : `bar_index` ou `is_first`
      decrivent la barre COURANTE, ils n'ont pas de sens pour une seance
      passee prise en bloc. Rendre zero serait inventer une reponse.
    """
    if lag < 0:
        raise LookAheadError(
            f"session : lag negatif ({lag}) - le futur n'est pas lisible"
        )
    if field in POSITIONNELS and lag != 0:
        raise ConfigurationError(
            f"session : '{field.value}' decrit la barre courante dans sa seance ; "
            f"il n'a pas de sens avec lag={lag}. Utiliser lag=0."
        )
    if field in NON_CLOS and lag == 0:
        raise LookAheadError(
            f"session : '{field.value}' de la seance EN COURS n'est pas connu - "
            f"elle n'est pas finie. Utiliser lag>=1 pour une seance close, ou le "
            f"noeud `cumulative` pour un cumul depuis l'ouverture."
        )

    if field is SessionField.BAR_INDEX:
        return float(index.bar_in_session[bar])
    if field is SessionField.MINUTES_FROM_OPEN:
        return float(index.minutes_from_open[bar])
    if field is SessionField.IS_FIRST:
        return 1.0 if bool(index.is_first[bar]) else 0.0
    if field is SessionField.IS_LAST:
        return 1.0 if bool(index.is_last[bar]) else 0.0

    numero = int(index.session_number[bar]) - lag
    if numero < 0:
        raise InsufficientHistoryError(
            f"session : {lag} seance(s) demandee(s), seulement "
            f"{int(index.session_number[bar])} close(s) avant celle-ci"
        )
    match field:
        case SessionField.OPEN:
            return float(index.session_open[numero])
        case SessionField.HIGH:
            return float(index.session_high[numero])
        case SessionField.LOW:
            return float(index.session_low[numero])
        case SessionField.CLOSE:
            return float(index.session_close[numero])
        case SessionField.VOLUME:
            return float(index.session_volume[numero])
