"""Ingestion : lecture, validation, gel en magasin immuable.

Le loader ne repare rien. Il ne trie pas, ne deduplique pas, ne comble pas, ne
convertit pas de fuseau devine. Il lit, il valide, et soit il gele un
`BarStore`, soit il leve `DataValidationError` avec le rapport complet.

Les fichiers sources sont deja au format canonique (Parquet, `ts_event` UTC,
colonnes OHLCV) : il n'y a donc pas d'etape de conversion. Le role du loader
est le controle et le gel, pas la normalisation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

from rsl.data.schema import (
    ABSENT,
    ALL_FIELDS,
    TIMESTAMP_COLUMN,
    AlignPolicy,
    BarStore,
    Granularity,
    IntArray,
    Panel,
)
from rsl.data.validation import ValidationConfig, ValidationReport, validate_frame
from rsl.errors import ConfigurationError, DataValidationError

TIMESTAMP_CANDIDATES: Final[tuple[str, ...]] = ("ts_event", "timestamp", "time", "datetime", "ts")
HASH_CHUNK: Final[int] = 1 << 20


def file_sha256(path: Path) -> str:
    """Empreinte du fichier source, pour le manifeste de run."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def read_ohlcv_frame(path: Path, *, timestamp_column: str | None = None) -> pl.DataFrame:
    """Lit un Parquet et retourne les colonnes canoniques, sans les toucher.

    Aucun tri, aucune deduplication : c'est la validation qui juge. Un loader
    qui trie masque une source corrompue et rend le rapport mensonger.
    """
    frame = pl.read_parquet(path)
    resolved = _resolve_timestamp_column(frame.columns, timestamp_column, path)
    if resolved != TIMESTAMP_COLUMN:
        frame = frame.rename({resolved: TIMESTAMP_COLUMN})

    wanted = [TIMESTAMP_COLUMN, *(f.value for f in ALL_FIELDS)]
    present = [c for c in wanted if c in frame.columns]
    return frame.select(present)


def _resolve_timestamp_column(
    columns: Iterable[str], explicit: str | None, path: Path
) -> str:
    cols = list(columns)
    if explicit is not None:
        if explicit not in cols:
            raise ConfigurationError(
                f"colonne d'horodatage '{explicit}' absente de {path.name} "
                f"(colonnes : {', '.join(cols)})"
            )
        return explicit
    found = [c for c in TIMESTAMP_CANDIDATES if c in cols]
    if len(found) == 1:
        return found[0]
    if not found:
        raise ConfigurationError(
            f"aucune colonne d'horodatage reconnue dans {path.name} "
            f"(colonnes : {', '.join(cols)}). Precisez `timestamp_column`."
        )
    raise ConfigurationError(
        f"plusieurs colonnes d'horodatage candidates dans {path.name} : "
        f"{', '.join(found)}. Precisez `timestamp_column` : le loader ne devine pas."
    )


def validate_file(
    path: Path,
    *,
    symbol: str,
    timestamp_column: str | None = None,
    config: ValidationConfig | None = None,
) -> ValidationReport:
    """Valide sans charger : utile en amont d'un run, ou en diagnostic."""
    frame = read_ohlcv_frame(path, timestamp_column=timestamp_column)
    return validate_frame(frame, symbol=symbol, source=str(path), config=config)


def load_bar_store(
    path: Path,
    *,
    symbol: str,
    granularity: Granularity,
    timestamp_column: str | None = None,
    config: ValidationConfig | None = None,
    with_hash: bool = True,
) -> tuple[BarStore, ValidationReport]:
    """Charge, valide et gele. Leve `DataValidationError` si une regle ERROR sort.

    Retourne aussi le rapport : meme valides, les donnees ont des WARNING et
    des INFO qui doivent finir dans le manifeste de run.
    """
    frame = read_ohlcv_frame(path, timestamp_column=timestamp_column)
    report = validate_frame(frame, symbol=symbol, source=str(path), config=config)
    if not report.is_valid:
        raise DataValidationError(
            f"{path.name} rejete par la validation :\n{report.render()}", report
        )

    ts = frame[TIMESTAMP_COLUMN].to_numpy().astype("datetime64[ns]").astype(np.int64)
    store = BarStore.build(
        symbol=symbol,
        granularity=granularity,
        ts_event=ts,
        open_=frame["open"].to_numpy().astype(np.float64),
        high=frame["high"].to_numpy().astype(np.float64),
        low=frame["low"].to_numpy().astype(np.float64),
        close=frame["close"].to_numpy().astype(np.float64),
        volume=frame["volume"].to_numpy().astype(np.float64),
        source_hash=file_sha256(path) if with_hash else "",
    )
    return store, report


def build_panel(
    stores: Mapping[str, BarStore],
    *,
    align_policy: AlignPolicy = AlignPolicy.DROP,
    max_ffill_bars: int | None = None,
) -> Panel:
    """Aligne plusieurs magasins sur le calendrier UNION de leurs clotures.

    `align_policy` :

    - `DROP` (defaut) : un instrument sans barre a `t` est absent de la coupe.
      Aucun report de prix.
    - `FFILL` : report explicite, borne par `max_ffill_bars` (obligatoire), et
      compte dans `Panel.is_stale`. Chaque barre reportee est marquee, et la
      strategie peut le lire.
    - `ERROR` : toute absence fait echouer la construction.

    Le forward-fill n'est jamais implicite : reporter le dernier prix d'un
    instrument ferme melange deux instants, et un tri cross-sectionnel lui
    attribue alors un rendement nul artificiel (`docs/no-lookahead.md` §4.1).
    """
    if not stores:
        raise ConfigurationError("panneau vide : au moins un instrument est requis")
    if align_policy is AlignPolicy.FFILL and max_ffill_bars is None:
        raise ConfigurationError(
            "align_policy='ffill' exige `max_ffill_bars` : un report non borne "
            "fait coter un instrument mort indefiniment"
        )
    if max_ffill_bars is not None and max_ffill_bars < 0:
        raise ConfigurationError(f"max_ffill_bars doit etre >= 0, recu {max_ffill_bars}")

    granularities = {s.granularity for s in stores.values()}
    if len(granularities) != 1:
        raise ConfigurationError(
            f"granularites heterogenes dans le panneau : "
            f"{sorted(str(g) for g in granularities)}"
        )
    granularity = granularities.pop()

    symbols = tuple(sorted(stores))  # ordre trie : le resultat ne depend pas de l'insertion
    calendar: IntArray = np.unique(
        np.concatenate([stores[s].ts_close for s in symbols])
    ).astype(np.int64)

    row_index: dict[str, IntArray] = {}
    stale_flags: dict[str, npt.NDArray[np.bool_]] = {}

    for sym in symbols:
        store = stores[sym]
        positions = np.searchsorted(calendar, store.ts_close)
        idx = np.full(calendar.shape[0], ABSENT, dtype=np.int64)
        idx[positions] = np.arange(store.n_bars, dtype=np.int64)
        stale = np.zeros(calendar.shape[0], dtype=np.bool_)

        if align_policy is AlignPolicy.ERROR and np.any(idx == ABSENT):
            missing = int(np.count_nonzero(idx == ABSENT))
            raise DataValidationError(
                f"align_policy='error' : {sym} manque a {missing} ligne(s) du calendrier commun"
            )
        if align_policy is AlignPolicy.FFILL:
            idx, stale = _bounded_ffill(idx, int(max_ffill_bars or 0))

        row_index[sym] = idx
        stale_flags[sym] = stale

    return Panel(
        granularity=granularity,
        ts_close=calendar,
        symbols=symbols,
        stores=dict(stores),
        row_index=row_index,
        is_stale=stale_flags,
        align_policy=align_policy,
    )


def _bounded_ffill(idx: IntArray, max_bars: int) -> tuple[IntArray, npt.NDArray[np.bool_]]:
    """Report vers l'avant, borne a `max_bars` lignes consecutives.

    Boucle explicite plutot que vectorisation : la borne est un compteur de
    lignes consecutives, et la lisibilite prime ici sur la vitesse. Le panneau
    n'est construit qu'une fois par run.
    """
    out = idx.copy()
    stale = np.zeros(idx.shape[0], dtype=np.bool_)
    last = ABSENT
    run = 0
    for k in range(idx.shape[0]):
        if idx[k] != ABSENT:
            last = int(idx[k])
            run = 0
            continue
        if last == ABSENT or run >= max_bars:
            continue
        out[k] = last
        stale[k] = True
        run += 1
    return out, stale
