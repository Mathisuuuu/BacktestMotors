"""Series synthetiques deterministes.

Les tests unitaires du socle ne touchent pas aux donnees reelles : une serie
constante, une rampe et une sinusoide ont une verite terrain calculable a la
main, ce qu'aucun fichier de marche n'a. Le hasard, quand il est utile, est
seede.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import numpy.typing as npt
import polars as pl

from rsl.data.schema import (
    NS_PER_SECOND,
    TIMESTAMP_COLUMN,
    BarStore,
    Granularity,
    datetime_to_ns,
)

FloatArray = npt.NDArray[np.float64]

EPOCH = datetime(2020, 1, 1, tzinfo=UTC)
MINUTE = Granularity.minutes(1)


# -- generateurs de series de cloture ---------------------------------------


def constant(n: int, value: float = 100.0) -> FloatArray:
    return np.full(n, value, dtype=np.float64)


def ramp(n: int, start: float = 100.0, step: float = 1.0) -> FloatArray:
    return start + step * np.arange(n, dtype=np.float64)


def sine(
    n: int, level: float = 100.0, amplitude: float = 10.0, period: int = 64
) -> FloatArray:
    t = np.arange(n, dtype=np.float64)
    return level + amplitude * np.sin(2.0 * np.pi * t / period)


def random_walk(
    n: int, start: float = 100.0, sigma: float = 0.5, seed: int = 20240101
) -> FloatArray:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, sigma, size=n)
    walk = start + np.cumsum(steps)
    return np.maximum(walk, 1.0)


# -- construction de barres --------------------------------------------------


def ohlc_from_closes(
    closes: FloatArray, *, wick: float = 0.001
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """OHLC valide a partir d'une serie de clotures.

    `open[i] = close[i-1]` (pas de gap synthetique par defaut), et les meches
    encadrent strictement `[min(o, c), max(o, c)]`, de sorte que la regle
    `open_close_within_range` passe toujours.
    """
    closes = np.asarray(closes, dtype=np.float64)
    opens = np.empty_like(closes)
    opens[0] = closes[0]
    opens[1:] = closes[:-1]
    upper = np.maximum(opens, closes)
    lower = np.minimum(opens, closes)
    return opens, upper * (1.0 + wick), lower * (1.0 - wick), closes


def timestamps(
    n: int, *, start: datetime = EPOCH, granularity: Granularity = MINUTE
) -> npt.NDArray[np.int64]:
    step = granularity.nanoseconds
    return datetime_to_ns(start) + step * np.arange(n, dtype=np.int64)


def make_store(
    closes: FloatArray,
    *,
    symbol: str = "SYNTH.v.0",
    granularity: Granularity = MINUTE,
    start: datetime = EPOCH,
    wick: float = 0.001,
    volume: float = 1_000.0,
    source_hash: str = "synthetic",
) -> BarStore:
    """Magasin gele a partir d'une serie de clotures."""
    opens, highs, lows, closes_ = ohlc_from_closes(closes, wick=wick)
    n = closes_.shape[0]
    return BarStore.build(
        symbol=symbol,
        granularity=granularity,
        ts_event=timestamps(n, start=start, granularity=granularity),
        open_=opens,
        high=highs,
        low=lows,
        close=closes_,
        volume=np.full(n, volume, dtype=np.float64),
        source_hash=source_hash,
    )


def make_frame(
    closes: FloatArray,
    *,
    granularity: Granularity = MINUTE,
    start: datetime = EPOCH,
    wick: float = 0.001,
    volume: float = 1_000.0,
) -> pl.DataFrame:
    """`DataFrame` polars au format canonique, pour les tests de validation."""
    opens, highs, lows, closes_ = ohlc_from_closes(closes, wick=wick)
    n = closes_.shape[0]
    ts_ns = timestamps(n, start=start, granularity=granularity)
    return pl.DataFrame(
        {
            TIMESTAMP_COLUMN: pl.Series(
                ts_ns.astype("datetime64[ns]"), dtype=pl.Datetime("ns")
            ).dt.replace_time_zone("UTC"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes_,
            "volume": np.full(n, volume, dtype=np.float64),
        }
    )


def make_gapped_store(
    closes: FloatArray,
    *,
    gap_after: int,
    gap: timedelta,
    symbol: str = "GAP.v.0",
    granularity: Granularity = MINUTE,
    start: datetime = EPOCH,
    wick: float = 0.001,
    volume: float = 1_000.0,
) -> BarStore:
    """Serie reguliere, sauf un trou apres l'index `gap_after`.

    Reproduit ce que sont vraiment les donnees de futures : une coupure de
    maintenance, un week-end, un ferie (`docs/execution-model.md` §5).
    """
    opens, highs, lows, closes_ = ohlc_from_closes(closes, wick=wick)
    n = closes_.shape[0]
    ts_ns = timestamps(n, start=start, granularity=granularity).copy()
    ts_ns[gap_after + 1 :] += int(gap.total_seconds() * NS_PER_SECOND)
    return BarStore.build(
        symbol=symbol,
        granularity=granularity,
        ts_event=ts_ns,
        open_=opens,
        high=highs,
        low=lows,
        close=closes_,
        volume=np.full(n, volume, dtype=np.float64),
        source_hash="synthetic-gapped",
    )


def corrupt_future(
    store: BarStore, *, after_index: int, seed: int = 987654321
) -> BarStore:
    """Remplace toutes les barres d'index > `after_index` par du bruit seede.

    Le bruit reste OHLC-valide et l'index temporel est preserve : sinon le
    loader rejetterait le magasin corrompu, et le test verifierait la
    validation plutot que l'absence de look-ahead.

    C'est l'outil du test adversarial n° 1 (`docs/no-lookahead.md` §6).
    """
    n = store.n_bars
    if not 0 <= after_index < n:
        raise ValueError(f"after_index={after_index} hors de [0, {n})")

    rng = np.random.default_rng(seed)
    tail = n - after_index - 1
    if tail == 0:
        return store

    noisy_close = rng.uniform(1.0, 10_000.0, size=tail)
    noisy_open = rng.uniform(1.0, 10_000.0, size=tail)
    upper = np.maximum(noisy_open, noisy_close)
    lower = np.minimum(noisy_open, noisy_close)

    def spliced(head: FloatArray, tail_values: FloatArray) -> FloatArray:
        return np.concatenate([head[: after_index + 1], tail_values])

    return BarStore.build(
        symbol=store.symbol,
        granularity=store.granularity,
        ts_event=store.ts_event,
        open_=spliced(store.open, noisy_open),
        high=spliced(store.high, upper * 1.01),
        low=spliced(store.low, lower * 0.99),
        close=spliced(store.close, noisy_close),
        volume=spliced(store.volume, rng.uniform(1.0, 1e6, size=tail)),
        source_hash=store.source_hash + "+corrupted",
    )


def ns_of(dt: datetime) -> int:
    return int(dt.timestamp() * NS_PER_SECOND)
