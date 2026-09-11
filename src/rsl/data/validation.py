"""Validation stricte des donnees sources.

Le loader REJETTE, il ne repare pas. Une donnee reparee silencieusement est une
donnee dont plus personne ne connait la provenance ; un backtest construit
dessus n'a pas de verite terrain.

Les regles forment un registre ouvert a l'extension : ajouter une regle se fait
en decorant une nouvelle fonction avec `@validation_rule`, jamais en modifiant
une regle existante. L'ordre d'execution est l'ordre d'enregistrement, donc
deterministe.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Protocol

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydField

from rsl.data.schema import ALL_FIELDS, PRICE_FIELDS, TIMESTAMP_COLUMN, Field
from rsl.errors import RegistryError

MAX_SAMPLES = 5


class Severity(StrEnum):
    """ERROR fait echouer le chargement. WARNING et INFO sont rapportes."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationConfig(BaseModel):
    """Seuils de validation. Tout est explicite ; rien n'est devine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_gap: timedelta | None = PydField(
        default=None,
        description=(
            "Ecart maximal tolere entre deux barres consecutives. `None` desactive la "
            "regle. Le defaut est `None` a dessein : sur des futures 1 minute, tout "
            "seuil inferieur a 49 heures rejette chaque fichier (week-ends), et tout "
            "seuil superieur ne detecte plus rien d'anormal. Le profil des ecarts est "
            "rapporte en INFO dans tous les cas."
        ),
    )
    allow_non_positive_prices: bool = PydField(
        default=True,
        description=(
            "Un prix de future peut etre negatif : le WTI a cote -37 $ le 20 avril 2020. "
            "Le cas est donc un WARNING par defaut, pas une erreur."
        ),
    )
    max_bar_return: float | None = PydField(
        default=None,
        gt=0.0,
        description="Variation close-a-close maximale toleree, en fraction. `None` desactive.",
    )


@dataclass(frozen=True, slots=True)
class Violation:
    """Resultat d'une regle qui a trouve quelque chose."""

    rule: str
    severity: Severity
    count: int
    message: str
    samples: tuple[str, ...] = ()

    def render(self) -> str:
        head = f"[{self.severity.value.upper():7}] {self.rule}: {self.message}"
        if not self.samples:
            return head
        return head + "".join(f"\n              - {s}" for s in self.samples)


class ValidationRule(Protocol):
    """Signature d'une regle. Retourne `None` si tout va bien."""

    __rsl_rule_name__: str

    def __call__(self, frame: pl.DataFrame, config: ValidationConfig) -> Violation | None: ...


_RULES: list[ValidationRule] = []
_RULE_NAMES: set[str] = set()

RuleFn = Callable[[pl.DataFrame, ValidationConfig], "Violation | None"]


def validation_rule(name: str) -> Callable[[RuleFn], RuleFn]:
    """Enregistre une regle dans le registre statique.

    Ajouter une regle = ajouter une fonction decoree. On ne modifie jamais une
    regle deja publiee : un rapport de validation archive doit rester
    interpretable a l'identique.
    """

    def decorate(fn: RuleFn) -> RuleFn:
        if name in _RULE_NAMES:
            raise RegistryError(f"regle de validation '{name}' deja enregistree")
        _RULE_NAMES.add(name)
        fn.__rsl_rule_name__ = name  # type: ignore[attr-defined]
        _RULES.append(fn)  # type: ignore[arg-type]
        return fn

    return decorate


def registered_rules() -> tuple[ValidationRule, ...]:
    """Regles dans leur ordre d'enregistrement, donc deterministe."""
    return tuple(_RULES)


# --------------------------------------------------------------------------
# Regles. Ordre d'enregistrement = ordre d'execution : les regles de structure
# passent d'abord, celles qui supposent la structure valide ensuite.
# --------------------------------------------------------------------------


@validation_rule("required_columns")
def _required_columns(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    expected = {TIMESTAMP_COLUMN, *(f.value for f in ALL_FIELDS)}
    missing = sorted(expected - set(frame.columns))
    if missing:
        return Violation(
            rule="required_columns",
            severity=Severity.ERROR,
            count=len(missing),
            message=f"colonnes manquantes : {', '.join(missing)}",
            samples=(f"colonnes presentes : {', '.join(frame.columns)}",),
        )
    return None


@validation_rule("timestamp_dtype")
def _timestamp_dtype(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    if TIMESTAMP_COLUMN not in frame.columns:
        return None
    dtype = frame.schema[TIMESTAMP_COLUMN]
    if not isinstance(dtype, pl.Datetime):
        return Violation(
            rule="timestamp_dtype",
            severity=Severity.ERROR,
            count=1,
            message=f"'{TIMESTAMP_COLUMN}' doit etre un Datetime, trouve {dtype}",
        )
    if dtype.time_zone != "UTC":
        return Violation(
            rule="timestamp_dtype",
            severity=Severity.ERROR,
            count=1,
            message=(
                f"'{TIMESTAMP_COLUMN}' doit porter le fuseau UTC, trouve "
                f"{dtype.time_zone!r}. Un horodatage naif ou local est refuse : "
                "le socle ne devine pas de fuseau."
            ),
        )
    return None


@validation_rule("timestamps_non_null")
def _timestamps_non_null(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    if TIMESTAMP_COLUMN not in frame.columns:
        return None
    n_null = int(frame[TIMESTAMP_COLUMN].null_count())
    if n_null:
        return Violation(
            rule="timestamps_non_null",
            severity=Severity.ERROR,
            count=n_null,
            message=f"{n_null} horodatage(s) nul(s)",
        )
    return None


@validation_rule("timestamps_strictly_monotonic")
def _timestamps_monotonic(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    """Couvre d'un coup l'ordre et les doublons : `diff > 0` interdit les deux."""
    if TIMESTAMP_COLUMN not in frame.columns or frame.height < 2:
        return None
    ts = frame[TIMESTAMP_COLUMN].to_numpy().astype("datetime64[ns]").astype(np.int64)
    deltas = np.diff(ts)
    bad = np.flatnonzero(deltas <= 0)
    if bad.size == 0:
        return None
    n_dup = int(np.count_nonzero(deltas == 0))
    n_back = int(np.count_nonzero(deltas < 0))
    samples = tuple(
        f"index {int(i)} -> {int(i) + 1} : {ts[int(i)]} puis {ts[int(i) + 1]} "
        f"(delta {int(deltas[int(i)])} ns)"
        for i in bad[:MAX_SAMPLES]
    )
    return Violation(
        rule="timestamps_strictly_monotonic",
        severity=Severity.ERROR,
        count=int(bad.size),
        message=(
            f"index non strictement croissant : {n_dup} doublon(s), "
            f"{n_back} retour(s) en arriere"
        ),
        samples=samples,
    )


@validation_rule("prices_finite")
def _prices_finite(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    offenders: list[str] = []
    total = 0
    for f in PRICE_FIELDS:
        if f.value not in frame.columns:
            continue
        col = frame[f.value].to_numpy().astype(np.float64)
        bad = np.flatnonzero(~np.isfinite(col))
        if bad.size:
            total += int(bad.size)
            offenders.append(f"{f.value}: {bad.size} valeur(s) NaN/inf, 1er index {int(bad[0])}")
    if total:
        return Violation(
            rule="prices_finite",
            severity=Severity.ERROR,
            count=total,
            message="prix non finis (NaN ou inf)",
            samples=tuple(offenders[:MAX_SAMPLES]),
        )
    return None


@validation_rule("volume_valid")
def _volume_valid(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    if Field.VOLUME.value not in frame.columns:
        return None
    vol = frame[Field.VOLUME.value].to_numpy().astype(np.float64)
    bad = np.flatnonzero(~np.isfinite(vol) | (vol < 0.0))
    if bad.size == 0:
        return None
    samples = tuple(f"index {int(i)} : volume = {vol[int(i)]}" for i in bad[:MAX_SAMPLES])
    return Violation(
        rule="volume_valid",
        severity=Severity.ERROR,
        count=int(bad.size),
        message="volume negatif ou non fini",
        samples=samples,
    )


@validation_rule("high_low_ordering")
def _high_low_ordering(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    if not {Field.HIGH.value, Field.LOW.value} <= set(frame.columns):
        return None
    high = frame[Field.HIGH.value].to_numpy().astype(np.float64)
    low = frame[Field.LOW.value].to_numpy().astype(np.float64)
    bad = np.flatnonzero(high < low)
    if bad.size == 0:
        return None
    samples = tuple(
        f"index {int(i)} : high={high[int(i)]} < low={low[int(i)]}" for i in bad[:MAX_SAMPLES]
    )
    return Violation(
        rule="high_low_ordering",
        severity=Severity.ERROR,
        count=int(bad.size),
        message="high < low",
        samples=samples,
    )


@validation_rule("open_close_within_range")
def _open_close_within_range(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    """`open` et `close` doivent tenir dans `[low, high]`.

    C'est l'invariant dont depend directement la garantie "aucun fill hors
    barre" (`docs/execution-model.md` §3.1) : si la source viole cette borne,
    le moteur remplit a un prix qui n'a pas existe.
    """
    needed = {Field.HIGH.value, Field.LOW.value, Field.OPEN.value, Field.CLOSE.value}
    if not needed <= set(frame.columns):
        return None
    high = frame[Field.HIGH.value].to_numpy().astype(np.float64)
    low = frame[Field.LOW.value].to_numpy().astype(np.float64)
    samples: list[str] = []
    total = 0
    for f in (Field.OPEN, Field.CLOSE):
        col = frame[f.value].to_numpy().astype(np.float64)
        bad = np.flatnonzero((col > high) | (col < low))
        total += int(bad.size)
        samples.extend(
            f"index {int(i)} : {f.value}={col[int(i)]} hors [{low[int(i)]}, {high[int(i)]}]"
            for i in bad[:MAX_SAMPLES]
        )
    if total:
        return Violation(
            rule="open_close_within_range",
            severity=Severity.ERROR,
            count=total,
            message="open ou close hors de [low, high]",
            samples=tuple(samples[:MAX_SAMPLES]),
        )
    return None


@validation_rule("non_positive_prices")
def _non_positive_prices(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    if not {f.value for f in PRICE_FIELDS} <= set(frame.columns):
        return None
    samples: list[str] = []
    total = 0
    for f in PRICE_FIELDS:
        col = frame[f.value].to_numpy().astype(np.float64)
        bad = np.flatnonzero(col <= 0.0)
        total += int(bad.size)
        samples.extend(f"index {int(i)} : {f.value}={col[int(i)]}" for i in bad[:MAX_SAMPLES])
    if not total:
        return None
    severity = Severity.WARNING if config.allow_non_positive_prices else Severity.ERROR
    return Violation(
        rule="non_positive_prices",
        severity=severity,
        count=total,
        message=(
            "prix negatif ou nul. Legitime sur certains futures (WTI, avril 2020) ; "
            "mettre `allow_non_positive_prices=False` pour en faire une erreur."
        ),
        samples=tuple(samples[:MAX_SAMPLES]),
    )


@validation_rule("max_bar_return")
def _max_bar_return(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    if config.max_bar_return is None or Field.CLOSE.value not in frame.columns:
        return None
    close = frame[Field.CLOSE.value].to_numpy().astype(np.float64)
    if close.shape[0] < 2:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = np.abs(close[1:] / close[:-1] - 1.0)
    bad = np.flatnonzero(np.isfinite(ret) & (ret > config.max_bar_return))
    if bad.size == 0:
        return None
    samples = tuple(
        f"index {int(i) + 1} : variation {ret[int(i)] * 100:.3f} %" for i in bad[:MAX_SAMPLES]
    )
    return Violation(
        rule="max_bar_return",
        severity=Severity.ERROR,
        count=int(bad.size),
        message=f"variation close-a-close superieure a {config.max_bar_return * 100:.3f} %",
        samples=samples,
    )


@validation_rule("max_gap")
def _max_gap(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    if config.max_gap is None or TIMESTAMP_COLUMN not in frame.columns or frame.height < 2:
        return None
    ts = frame[TIMESTAMP_COLUMN].to_numpy().astype("datetime64[ns]").astype(np.int64)
    deltas = np.diff(ts)
    limit_ns = int(config.max_gap.total_seconds() * 1_000_000_000)
    bad = np.flatnonzero(deltas > limit_ns)
    if bad.size == 0:
        return None
    samples = tuple(
        f"index {int(i)} -> {int(i) + 1} : ecart {deltas[int(i)] / 6e10:.1f} min"
        for i in bad[:MAX_SAMPLES]
    )
    return Violation(
        rule="max_gap",
        severity=Severity.ERROR,
        count=int(bad.size),
        message=f"ecart superieur a {config.max_gap}",
        samples=samples,
    )


@validation_rule("gap_profile")
def _gap_profile(frame: pl.DataFrame, config: ValidationConfig) -> Violation | None:
    """Toujours INFO : decrit les trous sans juger.

    Sur des futures, les trous sont la norme (coupure de maintenance
    quotidienne, week-ends, feries). Les compter et les montrer vaut mieux que
    de pretendre les interdire.
    """
    if TIMESTAMP_COLUMN not in frame.columns or frame.height < 2:
        return None
    ts = frame[TIMESTAMP_COLUMN].to_numpy().astype("datetime64[ns]").astype(np.int64)
    deltas = np.diff(ts)
    if deltas.size == 0 or np.any(deltas <= 0):
        return None
    step = int(np.median(deltas))
    irregular = np.flatnonzero(deltas != step)
    if irregular.size == 0:
        return None
    minutes = deltas / 6e10
    buckets = (
        ("<= 6 min", int(np.count_nonzero((deltas != step) & (minutes <= 6)))),
        ("6 min - 2 h", int(np.count_nonzero((minutes > 6) & (minutes <= 120)))),
        ("2 h - 3 j", int(np.count_nonzero((minutes > 120) & (minutes <= 4320)))),
        ("> 3 j", int(np.count_nonzero(minutes > 4320))),
    )
    return Violation(
        rule="gap_profile",
        severity=Severity.INFO,
        count=int(irregular.size),
        message=(
            f"pas median {step / 6e10:.0f} min ; {irregular.size} ecart(s) irregulier(s) ; "
            f"ecart max {minutes.max() / 1440:.2f} j"
        ),
        samples=tuple(f"{label} : {n}" for label, n in buckets if n),
    )


# --------------------------------------------------------------------------
# Rapport
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Resultat complet d'une validation, serialisable pour le manifeste de run."""

    source: str
    symbol: str
    n_rows: int
    first_ts: str | None
    last_ts: str | None
    violations: tuple[Violation, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.WARNING)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "symbol": self.symbol,
            "n_rows": self.n_rows,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "is_valid": self.is_valid,
            "violations": [
                {
                    "rule": v.rule,
                    "severity": v.severity.value,
                    "count": v.count,
                    "message": v.message,
                    "samples": list(v.samples),
                }
                for v in self.violations
            ],
        }

    def render(self) -> str:
        verdict = "VALIDE" if self.is_valid else "REJETE"
        lines = [
            f"Validation {self.symbol} [{verdict}]",
            f"  source  : {self.source}",
            f"  barres  : {self.n_rows}",
            f"  periode : {self.first_ts} -> {self.last_ts}",
        ]
        lines.extend("  " + v.render() for v in self.violations)
        if not self.violations:
            lines.append("  aucune anomalie")
        return "\n".join(lines)


def validate_frame(
    frame: pl.DataFrame,
    *,
    symbol: str,
    source: str = "<memoire>",
    config: ValidationConfig | None = None,
) -> ValidationReport:
    """Applique toutes les regles enregistrees, dans l'ordre d'enregistrement."""
    cfg = config or ValidationConfig()
    violations = tuple(v for rule in registered_rules() if (v := rule(frame, cfg)) is not None)

    first_ts: str | None = None
    last_ts: str | None = None
    if TIMESTAMP_COLUMN in frame.columns and frame.height:
        first_ts = str(frame[TIMESTAMP_COLUMN][0])
        last_ts = str(frame[TIMESTAMP_COLUMN][-1])

    return ValidationReport(
        source=source,
        symbol=symbol,
        n_rows=frame.height,
        first_ts=first_ts,
        last_ts=last_ts,
        violations=violations,
    )
