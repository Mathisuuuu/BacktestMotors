"""Deflated Sharpe Ratio, compteur d'essais, et interfaces de validation.

Le probleme que ce module adresse
---------------------------------
`performance.py` sait calculer un Sharpe. Il ne sait pas si ce Sharpe vaut
quelque chose. Sur un echantillon fixe, essayer suffisamment de strategies
finit toujours par en produire une qui brille : le maximum d'un ensemble de
tirages n'est pas un tirage, et le comparer a zero n'a pas de sens.

Bailey et Lopez de Prado (2014) formalisent la correction. Le Deflated Sharpe
Ratio compare le Sharpe observe non pas a zero, mais au maximum ATTENDU sous
l'hypothese nulle, compte tenu du nombre d'essais et de leur dispersion. Il
tient aussi compte de l'asymetrie et des queues epaisses des rendements, que le
Sharpe ordinaire ignore.

Le compteur d'essais n'est pas facultatif
-----------------------------------------
Le DSR a besoin de deux choses que seul le chercheur connait : COMBIEN de
configurations ont ete essayees, et avec quelle DISPERSION de Sharpe. Aucune
des deux ne se devine depuis un backtest isole - et un `n_trials` saisi de
memoire est une fiction confortable.

`TrialLog` existe pour cela : il enregistre chaque essai au moment ou il est
fait. Le nombre d'essais et leur variance en sortent, plutot que d'etre
declares apres coup. C'est la seule defense du socle contre la septieme voie du
modele de menace (`docs/no-lookahead.md` §7.1), celle qu'aucun `Context` ne peut
fermer.

Convention
----------
Tous les Sharpe de ce module sont PAR PERIODE, non annualises. Passer un Sharpe
annualise dans ces formules donne un resultat faux mais plausible, ce qui est
la pire categorie d'erreur ; `PerformanceMetrics.sharpe_per_period` fournit la
bonne valeur.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Final, Protocol, runtime_checkable

import numpy as np

from rsl.errors import ConfigurationError

SpecDict = dict[str, object]

EULER_MASCHERONI: Final[float] = 0.577_215_664_901_532_9
_NORMAL: Final[NormalDist] = NormalDist()


# ---------------------------------------------------------------------------
# Compteur d'essais
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrialEntry:
    """Un essai : sa specification, son empreinte, son Sharpe par periode."""

    fingerprint: str
    sharpe_per_period: float
    label: str = ""

    def describe(self) -> SpecDict:
        return {
            "fingerprint": self.fingerprint,
            "sharpe_per_period": self.sharpe_per_period,
            "label": self.label,
        }


@dataclass(slots=True)
class TrialLog:
    """Journal des configurations essayees sur un meme echantillon.

    A tenir sur toute la duree d'une recherche, pas par run. Deux essais
    identiques - meme specification - ne comptent qu'une fois : rejouer un
    backtest n'est pas un nouvel essai, et gonfler artificiellement le compteur
    penaliserait la reproductibilite.
    """

    entries: list[TrialEntry] = field(default_factory=list)

    def record(self, spec: SpecDict, sharpe_per_period: float, *, label: str = "") -> TrialEntry:
        """Enregistre un essai. Retourne l'entree, existante ou nouvelle."""
        if not math.isfinite(sharpe_per_period):
            raise ConfigurationError(
                f"sharpe_per_period doit etre fini, recu {sharpe_per_period}"
            )
        fingerprint = fingerprint_of(spec)
        for entry in self.entries:
            if entry.fingerprint == fingerprint:
                return entry
        entry = TrialEntry(fingerprint, sharpe_per_period, label)
        self.entries.append(entry)
        return entry

    @property
    def n_trials(self) -> int:
        return len(self.entries)

    @property
    def sharpes(self) -> np.ndarray:
        return np.array([e.sharpe_per_period for e in self.entries], dtype=np.float64)

    @property
    def variance_of_sharpes(self) -> float:
        """Variance des Sharpe essayes, estimateur non biaise.

        Avec moins de deux essais elle vaut zero : il n'y a alors pas de
        selection, donc rien a corriger.
        """
        if self.n_trials < 2:
            return 0.0
        return float(np.var(self.sharpes, ddof=1))

    @property
    def best(self) -> TrialEntry | None:
        return max(self.entries, key=lambda e: e.sharpe_per_period, default=None)

    def describe(self) -> SpecDict:
        return {
            "n_trials": self.n_trials,
            "variance_of_sharpes": self.variance_of_sharpes,
            "best": None if self.best is None else self.best.describe(),
            "entries": [e.describe() for e in self.entries],
        }


def fingerprint_of(spec: SpecDict) -> str:
    """Empreinte stable d'une specification.

    `sort_keys` garantit que l'ordre d'insertion d'un dictionnaire ne change
    pas l'empreinte - sans quoi deux essais identiques compteraient deux fois.
    """
    payload = json.dumps(spec, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Sharpe probabiliste et deflate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeflatedSharpeResult:
    """Sortie complete du calcul, avec ses entrees pour audit."""

    deflated_sharpe: float | None
    """Probabilite que le vrai Sharpe depasse le maximum attendu sous H0."""

    probabilistic_sharpe: float | None
    """Meme calcul contre un Sharpe de reference de zero."""

    observed_sharpe_per_period: float
    expected_max_sharpe: float
    n_observations: int
    n_trials: int
    variance_of_trial_sharpes: float
    skewness: float
    kurtosis: float
    warnings: tuple[str, ...] = ()

    @property
    def is_significant(self) -> bool:
        """Convention usuelle : DSR > 0,95."""
        return self.deflated_sharpe is not None and self.deflated_sharpe > 0.95

    def describe(self) -> SpecDict:
        return {
            "deflated_sharpe": self.deflated_sharpe,
            "probabilistic_sharpe": self.probabilistic_sharpe,
            "observed_sharpe_per_period": self.observed_sharpe_per_period,
            "expected_max_sharpe": self.expected_max_sharpe,
            "n_observations": self.n_observations,
            "n_trials": self.n_trials,
            "variance_of_trial_sharpes": self.variance_of_trial_sharpes,
            "skewness": self.skewness,
            "kurtosis": self.kurtosis,
            "is_significant": self.is_significant,
            "warnings": list(self.warnings),
        }

    def render(self) -> str:
        def prob(value: float | None) -> str:
            return "n/d" if value is None else f"{value:.4f}"

        lines = [
            f"Sharpe observe (par periode)  {self.observed_sharpe_per_period:.4f}",
            f"Maximum attendu sous H0       {self.expected_max_sharpe:.4f} "
            f"({self.n_trials} essai(s), variance {self.variance_of_trial_sharpes:.5f})",
            f"PSR (contre zero)             {prob(self.probabilistic_sharpe)}",
            f"DSR (contre le maximum)       {prob(self.deflated_sharpe)}"
            f"{'  SIGNIFICATIF' if self.is_significant else ''}",
            f"Moments                       asymetrie {self.skewness:+.3f}, "
            f"kurtosis {self.kurtosis:.3f}, {self.n_observations} observations",
        ]
        lines.extend(f"Avertissement  {w}" for w in self.warnings)
        return "\n".join(lines)


def probabilistic_sharpe_ratio(
    *,
    sharpe_per_period: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
    benchmark_sharpe: float = 0.0,
) -> float | None:
    """PSR : probabilite que le vrai Sharpe depasse `benchmark_sharpe`.

        PSR = Phi( (SR - SR*) * sqrt(n - 1) / sqrt(1 - g3*SR + (g4 - 1)/4 * SR^2) )

    `kurtosis` est NON excedentaire (3 pour une loi normale). Retourne `None`
    si le denominateur n'est pas defini - cela arrive sur des rendements tres
    asymetriques, et mieux vaut une absence de reponse qu'un nombre invente.
    """
    if n_observations < 2:
        return None
    variance = (
        1.0
        - skewness * sharpe_per_period
        + (kurtosis - 1.0) / 4.0 * sharpe_per_period**2
    )
    if variance <= 0.0 or not math.isfinite(variance):
        return None
    statistic = (sharpe_per_period - benchmark_sharpe) * math.sqrt(n_observations - 1)
    return float(_NORMAL.cdf(statistic / math.sqrt(variance)))


def expected_max_sharpe(n_trials: int, variance_of_trial_sharpes: float) -> float:
    """Maximum attendu du Sharpe sous H0, apres `n_trials` essais.

        E[max SR] = sqrt(V) * [ (1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N*e)) ]

    avec `g` la constante d'Euler-Mascheroni. Un seul essai ne selectionne
    rien : le maximum attendu vaut alors zero.
    """
    if n_trials < 1:
        raise ConfigurationError(f"n_trials doit etre >= 1, recu {n_trials}")
    if variance_of_trial_sharpes < 0.0:
        raise ConfigurationError(
            f"variance_of_trial_sharpes doit etre >= 0, recu {variance_of_trial_sharpes}"
        )
    if n_trials == 1 or variance_of_trial_sharpes == 0.0:
        return 0.0

    first = _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    second = _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(variance_of_trial_sharpes) * (
        (1.0 - EULER_MASCHERONI) * first + EULER_MASCHERONI * second
    )


def deflated_sharpe_ratio(
    *,
    sharpe_per_period: float,
    n_observations: int,
    skewness: float,
    kurtosis: float,
    n_trials: int,
    variance_of_trial_sharpes: float,
) -> DeflatedSharpeResult:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    `n_trials` et `variance_of_trial_sharpes` n'ont pas de valeur par defaut :
    les inventer reviendrait a supposer qu'aucune selection n'a eu lieu, ce qui
    est precisement l'hypothese que le DSR sert a rejeter. `TrialLog` les
    fournit a partir d'essais reellement enregistres.
    """
    warnings: list[str] = []
    if n_trials == 1:
        warnings.append(
            "un seul essai enregistre : le DSR se confond avec le PSR. Si d'autres "
            "configurations ont ete essayees sans etre journalisees, ce chiffre est trop "
            "optimiste."
        )
    if variance_of_trial_sharpes == 0.0 and n_trials > 1:
        warnings.append(
            "variance des Sharpe essayes nulle : le maximum attendu sous H0 vaut zero, "
            "donc le DSR degenere en PSR"
        )
    if n_observations < 30:
        warnings.append(
            f"{n_observations} observations seulement : les moments d'ordre 3 et 4 sont "
            f"mal estimes, et le DSR en depend directement"
        )

    threshold = expected_max_sharpe(n_trials, variance_of_trial_sharpes)
    deflated = probabilistic_sharpe_ratio(
        sharpe_per_period=sharpe_per_period,
        n_observations=n_observations,
        skewness=skewness,
        kurtosis=kurtosis,
        benchmark_sharpe=threshold,
    )
    plain = probabilistic_sharpe_ratio(
        sharpe_per_period=sharpe_per_period,
        n_observations=n_observations,
        skewness=skewness,
        kurtosis=kurtosis,
        benchmark_sharpe=0.0,
    )
    if deflated is None:
        warnings.append(
            "denominateur du PSR non defini : les moments des rendements sortent du "
            "domaine ou la formule a un sens"
        )

    return DeflatedSharpeResult(
        deflated_sharpe=deflated,
        probabilistic_sharpe=plain,
        observed_sharpe_per_period=sharpe_per_period,
        expected_max_sharpe=threshold,
        n_observations=n_observations,
        n_trials=n_trials,
        variance_of_trial_sharpes=variance_of_trial_sharpes,
        skewness=skewness,
        kurtosis=kurtosis,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Validation hors echantillon : interfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Split:
    """Une coupe apprentissage / test, en index de barres."""

    train_start: int
    train_stop: int
    test_start: int
    test_stop: int

    def __post_init__(self) -> None:
        if self.train_start >= self.train_stop:
            raise ConfigurationError(f"fenetre d'apprentissage vide : {self}")
        if self.test_start >= self.test_stop:
            raise ConfigurationError(f"fenetre de test vide : {self}")
        if self.test_start < self.train_stop:
            raise ConfigurationError(
                f"le test commence avant la fin de l'apprentissage : {self}. "
                f"Un walk-forward qui se chevauche ne teste rien."
            )

    def describe(self) -> SpecDict:
        return {
            "train": [self.train_start, self.train_stop],
            "test": [self.test_start, self.test_stop],
        }


@runtime_checkable
class WalkForwardSplitter(Protocol):
    """Decoupe un echantillon en coupes successives, toujours vers l'avant."""

    def split(self, n_bars: int) -> Iterator[Split]: ...

    def describe(self) -> SpecDict: ...


@dataclass(frozen=True, slots=True)
class RollingWalkForward:
    """Fenetre glissante de taille fixe.

    Le test suit immediatement l'apprentissage, et les deux avancent de `step`.
    Aucun chevauchement : `Split` le refuse.
    """

    train_bars: int
    test_bars: int
    step_bars: int | None = None

    def __post_init__(self) -> None:
        if self.train_bars < 1 or self.test_bars < 1:
            raise ConfigurationError("train_bars et test_bars doivent etre >= 1")
        if self.step_bars is not None and self.step_bars < 1:
            raise ConfigurationError(f"step_bars doit etre >= 1, recu {self.step_bars}")

    @property
    def step(self) -> int:
        return self.step_bars if self.step_bars is not None else self.test_bars

    def split(self, n_bars: int) -> Iterator[Split]:
        start = 0
        while start + self.train_bars + self.test_bars <= n_bars:
            yield Split(
                train_start=start,
                train_stop=start + self.train_bars,
                test_start=start + self.train_bars,
                test_stop=start + self.train_bars + self.test_bars,
            )
            start += self.step

    def describe(self) -> SpecDict:
        return {
            "splitter": "rolling",
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "step_bars": self.step,
        }


@dataclass(frozen=True, slots=True)
class AnchoredWalkForward:
    """Fenetre d'apprentissage ancree au debut, qui s'allonge a chaque coupe."""

    initial_train_bars: int
    test_bars: int

    def __post_init__(self) -> None:
        if self.initial_train_bars < 1 or self.test_bars < 1:
            raise ConfigurationError("initial_train_bars et test_bars doivent etre >= 1")

    def split(self, n_bars: int) -> Iterator[Split]:
        train_stop = self.initial_train_bars
        while train_stop + self.test_bars <= n_bars:
            yield Split(
                train_start=0,
                train_stop=train_stop,
                test_start=train_stop,
                test_stop=train_stop + self.test_bars,
            )
            train_stop += self.test_bars

    def describe(self) -> SpecDict:
        return {
            "splitter": "anchored",
            "initial_train_bars": self.initial_train_bars,
            "test_bars": self.test_bars,
        }


@runtime_checkable
class OverfittingEstimator(Protocol):
    """Probabilite de surapprentissage (PBO par CSCV). NON IMPLEMENTE en phase 1.

    Le protocole est fixe maintenant parce que la forme de ses entrees
    contraint le reste : la CSCV de Bailey, Borwein, Lopez de Prado et Zhu
    travaille sur une MATRICE de performances - `n_configurations` lignes,
    `n_sous_periodes` colonnes - et non sur des runs isoles. Un socle qui ne
    saurait produire cette matrice devrait etre repris pour l'accueillir ; il
    peut la produire.

    Aucune implementation n'est fournie a cette phase, conformement au
    perimetre.
    """

    def probability_of_backtest_overfitting(
        self, performance_matrix: np.ndarray, n_partitions: int
    ) -> float: ...
