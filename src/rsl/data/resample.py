"""Reechantillonnage causal vers un calendrier plus large.

Une strategie mensuelle sur des donnees a la minute ne se traite pas en
parcourant 3,7 millions de barres par instrument : elle se traite sur des
barres mensuelles construites en amont.

Regle causale (`docs/no-lookahead.md` §4.3) : une barre agregee n'existe
qu'une fois sa periode terminee. Une periode partielle n'est jamais visible
comme si elle etait complete.

Quand la periode devient-elle disponible
----------------------------------------
Par defaut, `ts_close` est la FRONTIERE DE PERIODE - le premier instant de la
periode suivante - et non la cloture de la derniere barre constituante.

Ce n'est pas un detail. Sur un panneau multi-instruments, dater chaque barre
mensuelle a sa derniere cotation fragmente la coupe transversale sur une
technicite : mesure sur les dix contrats du jeu de donnees, un mois ou 6B
imprime a 23:56 et les autres a 00:00 produit DEUX lignes de panneau au lieu
d'une, chacune avec un univers ampute. Le panneau comptait 181 lignes pour 128
mois, dont 47 lignes a un seul instrument.

La frontiere de periode est posterieure ou egale a toutes les clotures
constituantes : elle est donc strictement plus conservatrice, n'introduit
aucune fuite, et fait coincider exactement les instruments d'une meme periode.

`close_stamp=CloseStamp.LAST_BAR` retablit l'ancien comportement pour l'analyse
mono-instrument, ou la question ne se pose pas.

Pourquoi en amont plutot qu'a la volee
--------------------------------------
Le reechantillonnage produit un `BarStore` ordinaire, consomme par un `Context`
ordinaire. Il n'existe aucun chemin permettant d'agreger depuis le `Context` :
ce serait le plus court chemin vers une barre partielle traitee comme complete,
puisqu'a l'instant `t` on ne sait pas encore si le mois est fini.

Ou se trouve la vraie garantie
------------------------------
Le magasin mensuel est bati hors ligne, donc "en connaissant le futur" au sens
trivial ou le fichier entier est lu. Cela n'ouvre aucune fuite, pour deux
raisons :

  - l'agregation d'une periode n'utilise que des barres de cette periode ;
  - le curseur du `Context` n'atteint la barre du mois M qu'apres l'avoir
    entierement traversee, et l'execution se fait a l'OUVERTURE de la barre
    suivante, c'est-a-dire au premier instant du mois M+1.

Le signal de fin de mois est donc lu a la fin du mois, et execute au debut du
suivant. C'est exactement le calendrier qu'un praticien peut tenir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Final

import numpy as np

from rsl.data.schema import BarStore, Granularity, IntArray
from rsl.data.session import NS_PER_MINUTE, SessionCalendar, bornes_de_seances
from rsl.errors import ConfigurationError

NS_PER_DAY: Final[int] = 86_400 * 1_000_000_000


class CloseStamp(StrEnum):
    """Quel horodatage porte la disponibilite d'une barre agregee."""

    PERIOD_END = "period_end"
    """Frontiere de periode. Defaut : aligne les instruments d'un panneau."""

    LAST_BAR = "last_bar"
    """Cloture de la derniere barre constituante. Mono-instrument uniquement."""


class Period(StrEnum):
    """Periodes supportees : intra-journalieres, puis calendaires.

    Les deux familles ne s'ancrent PAS de la meme facon, et c'est la seule
    chose a retenir de cette liste. Une periode calendaire se lit dans
    l'horodatage : le mois d'une barre ne depend que de sa date. Une periode
    intra-journaliere n'a aucun ancrage naturel - « une barre de 4 h » ne dit
    pas ou elle commence - et la reponse est prise dans le calendrier de
    SEANCE declare : elles commencent a l'ouverture.
    """

    MIN5 = "5min"
    MIN10 = "10min"
    MIN15 = "15min"
    MIN30 = "30min"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"

    @property
    def intra_journaliere(self) -> bool:
        """Exige-t-elle un calendrier de seance ?

        Predicat plutot que liste recopiee chez les appelants : la liste
        enumeree a deux endroits est fausse des le deuxieme ([[lessons]] L15).
        """
        return self in _MINUTES

    @property
    def minutes(self) -> int:
        """Duree en minutes. Leve sur une periode calendaire, qui n'en a pas."""
        duree = _MINUTES.get(self)
        if duree is None:
            raise ConfigurationError(
                f"'{self.value}' est une periode calendaire : sa duree varie, "
                f"c'est `ts_close` qui fait foi."
            )
        return duree


_MINUTES: Final[dict[Period, int]] = {
    Period.MIN5: 5,
    Period.MIN10: 10,
    Period.MIN15: 15,
    Period.MIN30: 30,
    Period.H1: 60,
    Period.H2: 120,
    Period.H4: 240,
}
"""Duree des periodes intra-journalieres. Cette table EST la definition de
`Period.intra_journaliere` : une periode ajoutee ici devient intra-journaliere,
sans qu'aucun autre endroit soit a modifier."""


_NOMINAL: Final[dict[Period, tuple[timedelta, str]]] = {
    Period.DAY: (timedelta(days=1), "1d"),
    Period.WEEK: (timedelta(days=7), "1w"),
    Period.MONTH: (timedelta(days=30), "1M"),
    Period.QUARTER: (timedelta(days=91), "1Q"),
    Period.YEAR: (timedelta(days=365), "1Y"),
}


def granularity_of(period: Period) -> Granularity:
    """Granularite nominale. La duree reelle varie ; c'est `ts_close` qui fait foi.

    Sur une periode intra-journaliere, « nominale » a un sens tres concret : la
    DERNIERE barre de chaque seance est plus courte des que la duree de seance
    n'est pas un multiple de la periode. Une seance ES de 23 h decoupee en 4 h
    donne cinq barres pleines et une de 3 h.
    """
    if period.intra_journaliere:
        return Granularity(timedelta(minutes=period.minutes), name=period.value)
    delta, name = _NOMINAL[period]
    return Granularity(delta, name=name)


def tranches_de_seance(
    ts_ns: IntArray, calendar: SessionCalendar, period: Period
) -> tuple[IntArray, IntArray]:
    """Decoupe intra-journalier ancre sur l'ouverture de seance DECLAREE.

    Rend `(debut_de_tranche, fin_de_seance)`, tous deux en nanosecondes UTC et
    alignes barre par barre.

    L'identifiant de tranche est l'INSTANT ou elle commence
    ------------------------------------------------------
    `debut = ouverture_de_la_seance + k x duree`, et cet entier sert
    directement de cle de regroupement. Trois proprietes en decoulent, sans
    qu'aucune constante arbitraire n'intervienne :

    - il est unique par (seance, tranche) - deux seances differentes ont des
      ouvertures differentes ;
    - il est strictement croissant dans le temps - la premiere tranche d'une
      seance commence a son ouverture, posterieure a tout debut de tranche de
      la seance precedente ;
    - il donne la fin nominale de la tranche par simple addition.

    Un identifiant compose du genre `numero_de_seance x 288 + k` aurait exige
    de borner `k`, donc de supposer une duree maximale de seance. Ici, rien
    n'est suppose.

    L'ancrage, et ce qu'il coute
    ----------------------------
    Une barre appartient a la seance ouverte a la derniere ouverture qui
    precede son horodatage - exactement la regle de `rsl.data.session`, et par
    le meme code, pour qu'il n'y ait pas deux definitions de « quelle seance ».

    Consequence a assumer : deux instruments dont les seances different n'ont
    plus aucune frontiere commune. Le decoupage intra-journalier ancre sur la
    seance est donc un outil MONO-INSTRUMENT, ou reserve a des instruments qui
    partagent le meme calendrier. Voir `docs/execution-model.md` §1.3.
    """
    ouverts, fermes = bornes_de_seances(ts_ns, calendar)
    rang = np.searchsorted(ouverts, ts_ns, side="right") - 1
    if bool(np.any(rang < 0)):  # pragma: no cover - la marge de deux jours l'evite
        raise ConfigurationError(
            "resample : une barre precede la premiere ouverture de seance calculee"
        )
    ouverture = ouverts[rang]
    duree = period.minutes * NS_PER_MINUTE
    tranche = (ts_ns - ouverture) // duree
    return (ouverture + tranche * duree, fermes[rang])


def bucket_ids(ts_ns: IntArray, period: Period) -> IntArray:
    """Identifiant de periode, strictement croissant dans le temps.

    Le decoupage se fait sur `ts_event`, l'ouverture de la barre : une barre
    appartient a la periode dans laquelle elle COMMENCE. A la minute, aucune
    barre ne chevauche une frontiere de mois, donc le point est sans effet ici
    - mais il doit etre fixe plutot que subi.

    Periodes CALENDAIRES uniquement : une periode intra-journaliere n'a pas
    d'ancrage lisible dans l'horodatage, elle passe par `tranches_de_seance`.
    """
    if period.intra_journaliere:
        raise ConfigurationError(
            f"'{period.value}' est intra-journaliere : son decoupage depend du "
            f"calendrier de seance declare, pas de l'horodatage seul. Passer par "
            f"`tranches_de_seance`."
        )
    as_datetime = ts_ns.astype("datetime64[ns]")
    match period:
        case Period.DAY:
            return as_datetime.astype("datetime64[D]").astype(np.int64)
        case Period.WEEK:
            # L'epoque (1970-01-01) etait un jeudi : +3 aligne les semaines sur
            # le lundi, convention ISO.
            days = as_datetime.astype("datetime64[D]").astype(np.int64)
            return (days + 3) // 7
        case Period.MONTH:
            return as_datetime.astype("datetime64[M]").astype(np.int64)
        case Period.QUARTER:
            months = as_datetime.astype("datetime64[M]").astype(np.int64)
            return months // 3
        case Period.YEAR:
            return as_datetime.astype("datetime64[Y]").astype(np.int64)
        case _:
            # Atteignable seulement si une periode CALENDAIRE est ajoutee a
            # l'enumeration sans arme ici. Les intra-journalieres ont deja leve
            # plus haut. Le refus vaut mieux qu'un decoupage par defaut.
            raise ConfigurationError(f"decoupage non defini pour '{period.value}'")


def period_end_ns(bucket: IntArray, period: Period) -> IntArray:
    """Premier instant de la periode SUIVANTE, en nanosecondes UTC.

    C'est la borne superieure de la periode : posterieure a toute barre qu'elle
    contient, donc utilisable comme instant de disponibilite sans rien
    anticiper.

    Periodes CALENDAIRES uniquement, comme `bucket_ids`.
    """
    if period.intra_journaliere:
        raise ConfigurationError(
            f"'{period.value}' est intra-journaliere : sa fin se lit dans la "
            f"seance, pas dans le calendrier."
        )
    following = bucket + 1
    match period:
        case Period.DAY:
            return following.astype("datetime64[D]").astype("datetime64[ns]").astype(np.int64)
        case Period.WEEK:
            days = following * 7 - 3
            return days.astype("datetime64[D]").astype("datetime64[ns]").astype(np.int64)
        case Period.MONTH:
            return following.astype("datetime64[M]").astype("datetime64[ns]").astype(np.int64)
        case Period.QUARTER:
            months = following * 3
            return months.astype("datetime64[M]").astype("datetime64[ns]").astype(np.int64)
        case Period.YEAR:
            return following.astype("datetime64[Y]").astype("datetime64[ns]").astype(np.int64)
        case _:
            raise ConfigurationError(f"fin de periode non definie pour '{period.value}'")


@dataclass(frozen=True, slots=True)
class ResampleReport:
    """Ce que l'agregation a produit, pour le manifeste de run."""

    symbol: str
    period: Period
    n_source_bars: int
    n_periods: int
    n_dropped_incomplete: int
    min_bars_in_a_period: int
    max_bars_in_a_period: int
    close_stamp: CloseStamp = CloseStamp.PERIOD_END

    def describe(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "period": self.period.value,
            "n_source_bars": self.n_source_bars,
            "n_periods": self.n_periods,
            "n_dropped_incomplete": self.n_dropped_incomplete,
            "min_bars_in_a_period": self.min_bars_in_a_period,
            "max_bars_in_a_period": self.max_bars_in_a_period,
            "close_stamp": self.close_stamp.value,
        }

    def render(self) -> str:
        return (
            f"{self.symbol} : {self.n_source_bars} barres -> {self.n_periods} "
            f"periodes ({self.period.value}) ; {self.n_dropped_incomplete} periode(s) "
            f"ecartee(s) ; {self.min_bars_in_a_period} a {self.max_bars_in_a_period} "
            f"barres par periode"
        )


def _fin_de_tranche(
    debuts: IntArray, fins_de_seance: IntArray, dernieres_clotures: IntArray, period: Period
) -> IntArray:
    """Instant ou une tranche de seance est complete.

    Trois termes, dans cet ordre :

    1. la fin NOMINALE, `debut + duree` ;
    2. bornee par la fin de SEANCE, car la derniere tranche d'une seance est
       plus courte des que la duree de seance n'est pas un multiple de la
       periode. Une seance ES de 23 h en tranches de 4 h donne cinq tranches
       pleines et une de 3 h ; la dater 1 h apres la cloture retarderait le
       signal de cloture d'une heure sans rien y gagner ;
    3. **jamais avant la derniere cloture reellement observee**. C'est ce
       troisieme terme qui rend la borne sure plutot que plausible : si une
       barre traine apres la fermeture declaree - donnee douteuse, fermeture
       mal declaree - les deux premiers termes donneraient une disponibilite
       ANTERIEURE a une barre du groupe, c'est-a-dire une fuite. Le maximum
       l'interdit par construction, sans avoir a supposer que les donnees sont
       propres.
    """
    duree = period.minutes * NS_PER_MINUTE
    return np.maximum(np.minimum(debuts + duree, fins_de_seance), dernieres_clotures)


def resample(
    store: BarStore,
    period: Period,
    *,
    min_bars: int | None = None,
    close_stamp: CloseStamp = CloseStamp.PERIOD_END,
    calendar: SessionCalendar | None = None,
) -> tuple[BarStore, ResampleReport]:
    """Agrege un magasin vers une periode calendaire.

    - `open`   : premiere ouverture de la periode
    - `high`   : maximum des hauts
    - `low`    : minimum des bas
    - `close`  : derniere cloture
    - `volume` : somme

    `close_stamp` fixe l'instant de disponibilite : frontiere de periode par
    defaut (voir l'entete du module), cloture de la derniere barre sinon.

    `min_bars` ecarte les periodes trop peu remplies. Utile pour retirer un mois
    partiel en debut ou en fin d'echantillon - un mois de trois seances aurait
    un rendement qui ne represente rien. Le defaut `None` ne retire rien : c'est
    a l'appelant de decider, et le rapport donne de quoi le faire.

    `calendar` est OBLIGATOIRE pour une periode intra-journaliere, et inutile
    pour une periode calendaire. Une barre de 4 h ne dit pas ou elle commence :
    la reponse vient de la seance declaree, jamais d'une convention devinee.
    """
    if store.n_bars == 0:
        raise ConfigurationError(f"magasin '{store.symbol}' vide : rien a reechantillonner")
    if min_bars is not None and min_bars < 1:
        raise ConfigurationError(f"min_bars doit etre >= 1, recu {min_bars}")
    if period.intra_journaliere and calendar is None:
        raise ConfigurationError(
            f"'{period.value}' exige un calendrier de seance : une barre de "
            f"{period.minutes} min ne dit pas ou elle commence. Declarer "
            f"`session` (start, end, timezone) sur cette entree de donnees. "
            f"Le socle ne devine aucune frontiere - voir le ledger."
        )
    if calendar is not None and not period.intra_journaliere:
        raise ConfigurationError(
            f"'{period.value}' est calendaire : elle se lit dans l'horodatage et "
            f"ignorerait le calendrier de seance fourni. Le passer laisserait "
            f"croire qu'il change quelque chose."
        )

    if calendar is not None:
        keys, fins_de_seance = tranches_de_seance(store.ts_event, calendar, period)
    else:
        keys = bucket_ids(store.ts_event, period)
        fins_de_seance = keys  # inutilise ; garde les types homogenes

    starts = np.concatenate(([0], np.flatnonzero(np.diff(keys)) + 1)).astype(np.int64)
    ends = np.append(starts[1:] - 1, store.n_bars - 1)
    counts = (ends - starts + 1).astype(np.int64)

    keep = np.ones(starts.shape[0], dtype=np.bool_) if min_bars is None else counts >= min_bars
    n_dropped = int(np.count_nonzero(~keep))

    if close_stamp is not CloseStamp.PERIOD_END:
        ts_close = store.ts_close[ends]
    elif calendar is not None:
        ts_close = _fin_de_tranche(
            keys[starts], fins_de_seance[starts], store.ts_close[ends], period
        )
    else:
        ts_close = period_end_ns(keys[starts], period)

    # Le calendrier declare fait partie de ce qui a produit ces barres : deux
    # decoupages sur des seances differentes ne doivent pas se presenter sous la
    # meme empreinte de source.
    trace = f"{store.source_hash}|resample:{period.value}"
    if calendar is not None:
        trace += f"@{calendar.start}-{calendar.end}@{calendar.timezone}"

    highs = np.maximum.reduceat(store.high, starts)
    lows = np.minimum.reduceat(store.low, starts)
    volumes = np.add.reduceat(store.volume, starts)

    aggregated = BarStore.build(
        symbol=store.symbol,
        granularity=granularity_of(period),
        ts_event=store.ts_event[starts][keep],
        open_=store.open[starts][keep],
        high=highs[keep],
        low=lows[keep],
        close=store.close[ends][keep],
        volume=volumes[keep],
        ts_close=ts_close[keep],
        source_hash=trace,
    )

    report = ResampleReport(
        symbol=store.symbol,
        period=period,
        n_source_bars=store.n_bars,
        n_periods=aggregated.n_bars,
        n_dropped_incomplete=n_dropped,
        min_bars_in_a_period=int(counts[keep].min()) if aggregated.n_bars else 0,
        max_bars_in_a_period=int(counts[keep].max()) if aggregated.n_bars else 0,
        close_stamp=close_stamp,
    )
    return aggregated, report
