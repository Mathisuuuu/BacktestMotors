"""Evaluation par fenetres successives, toujours vers l'avant.

Ce que ce runner fait, et ce qu'il ne fait pas
----------------------------------------------
Il execute LA MEME strategie, avec LES MEMES parametres, sur des fenetres de
test successives et disjointes. Il ne cherche aucun parametre - l'optimisation
est hors du perimetre de cette phase, et le rester est important : un
walk-forward qui optimise sur la fenetre d'apprentissage est un outil tout
different, avec ses propres pieges.

La question a laquelle il repond est donc plus modeste, et plus utile qu'il n'y
parait : **la performance tient-elle sur toute la periode, ou vient-elle d'un
seul morceau ?** Un Sharpe de 1,5 porte par un pli sur huit et un Sharpe de 0,8
present dans les huit ne sont pas la meme chose, et une metrique agregee sur
l'echantillon entier ne les distingue pas.

A quoi sert la fenetre d'apprentissage
---------------------------------------
Puisque rien n'est optimise, elle ne sert pas a estimer des parametres. Elle
sert d'HISTORIQUE : la strategie la traverse pour remplir ses fenetres
glissantes, sans negocier. Un pli qui demarre a la barre `k` se decrit
exactement par `min_warmup_bars=k` - c'est la meme mecanique que le
prechauffage ordinaire, appliquee a une frontiere choisie.

C'est aussi le point de branchement d'une phase ulterieure : le jour ou une
selection de parametres existera, elle s'inserera entre les deux fenetres sans
que le reste bouge.

Consequence a ne pas masquer : tant que rien n'est optimise, un decoupage ANCRE
et un decoupage GLISSANT donnent exactement les memes plis, donc les memes
resultats. Leur difference porte sur ce qu'on APPREND de la fenetre
d'apprentissage, et on n'en apprend rien. Les deux existent parce que le jour
ou ce sera faux, le choix comptera - pas parce qu'ils different aujourd'hui.
Le rapport le signale plutot que de laisser croire a deux mesures
independantes.

Position ouverte a la fin d'un pli
-----------------------------------
Par defaut, chaque pli est LIQUIDE a sa derniere barre. Sans cela, le rendement
d'un pli contiendrait le profit latent d'une position que le pli suivant
n'herite pas : un meme gain serait compte dans un pli et absent du suivant,
alors qu'aucun compte reel ne se comporte ainsi. La liquidation terminale est
une commodite de mesure, pas une action negociable - elle est signalee dans le
rapport, et `liquidate_folds=False` la desactive.

Capital de depart de chaque pli
-------------------------------
Chaque pli repart de `initial_cash`. Enchainer le capital rendrait les plis
tardifs mecaniquement plus gros et fausserait la comparaison : on veut savoir
si la strategie marche a chaque epoque, pas ce qu'aurait fait un compte qui
aurait compose. Le rendement compose est neanmoins rapporte a part, pour qui
veut l'autre lecture.

Un pli n'est pas un essai
--------------------------
Les Sharpe des plis ne sont PAS a verser dans un `TrialLog`. Un essai est une
configuration differente sur les memes donnees ; un pli est la meme
configuration sur des donnees differentes. Les confondre gonflerait le
compteur du Deflated Sharpe avec des observations qui ne mesurent pas de la
selection - et le DSR deviendrait pessimiste pour une mauvaise raison.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from rsl.config import BacktestSpec, build_panel_from, load_stores
from rsl.data.schema import BarStore
from rsl.errors import ConfigurationError
from rsl.manifest import RunManifest
from rsl.metrics.performance import PerformanceMetrics, compute_performance
from rsl.metrics.statistics import Split, WalkForwardSplitter
from rsl.primitives.registry import RegistrySnapshot
from rsl.report import execute_run, result_fingerprint
from rsl.strategies.base import build_strategy, get_strategy

SpecDict = dict[str, object]


@dataclass(frozen=True, slots=True)
class Fold:
    """Un pli : sa fenetre, ses metriques, son empreinte."""

    index: int
    split: Split
    metrics: PerformanceMetrics
    fingerprint: str

    @property
    def total_return(self) -> float:
        return self.metrics.total_return

    @property
    def sharpe(self) -> float | None:
        return self.metrics.sharpe

    @property
    def is_positive(self) -> bool:
        return self.metrics.total_return > 0.0

    def describe(self) -> SpecDict:
        return {
            "index": self.index,
            "split": self.split.describe(),
            "fingerprint": self.fingerprint,
            "metrics": self.metrics.describe(),
        }

    @property
    def was_idle(self) -> bool:
        """Le pli n'a jamais porte de position.

        A distinguer de "aucun trade cloture" : une entree sans sortie donne
        zero trade mais une exposition, et un rendement bien reel.
        """
        return self.metrics.exposure == 0.0

    def render(self) -> str:
        sharpe = "n/d" if self.sharpe is None else f"{self.sharpe:+5.2f}"
        drawdown = (
            f"{self.metrics.drawdown_daily.max_drawdown * 100:+6.1f} %"
            if self.metrics.drawdown_daily is not None
            else "   n/d"
        )
        return (
            f"  pli {self.index:>2}  barres {self.split.test_start:>6}-{self.split.test_stop:<6} "
            f"rendement {self.total_return * 100:+7.2f} %  Sharpe {sharpe}  "
            f"DD {drawdown}  {self.metrics.n_trades:>3} trades  "
            f"expo {self.metrics.exposure * 100:>5.1f} %"
        )


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    """Resultat d'une evaluation par fenetres."""

    name: str
    symbols: tuple[str, ...]
    cross_sectional: bool
    splitter: SpecDict
    folds: tuple[Fold, ...]
    manifest: RunManifest
    specification: SpecDict
    liquidate_folds: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)

    # -- agregats ----------------------------------------------------------

    @property
    def n_folds(self) -> int:
        return len(self.folds)

    @property
    def sharpes(self) -> tuple[float, ...]:
        return tuple(f.sharpe for f in self.folds if f.sharpe is not None)

    @property
    def sharpe_mean(self) -> float | None:
        values = self.sharpes
        return sum(values) / len(values) if values else None

    @property
    def sharpe_median(self) -> float | None:
        values = self.sharpes
        return median(values) if values else None

    @property
    def sharpe_spread(self) -> float | None:
        """Ecart-type des Sharpe entre plis - la grandeur qui interesse ici.

        Une moyenne seule ne dit pas si la performance est repartie ou
        concentree ; c'est la dispersion qui repond.
        """
        values = self.sharpes
        if len(values) < 2:
            return None
        mean = sum(values) / len(values)
        return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))

    @property
    def worst_fold(self) -> Fold | None:
        return min(self.folds, key=lambda f: f.total_return, default=None)

    @property
    def best_fold(self) -> Fold | None:
        return max(self.folds, key=lambda f: f.total_return, default=None)

    @property
    def positive_share(self) -> float | None:
        """Part des plis dont le rendement est positif."""
        if not self.folds:
            return None
        return sum(1 for f in self.folds if f.is_positive) / len(self.folds)

    @property
    def compounded_return(self) -> float:
        """Rendement obtenu en reinvestissant d'un pli au suivant.

        Lecture alternative, fournie parce qu'elle est celle qu'on attend
        instinctivement. Elle suppose que le capital passe d'un pli a l'autre,
        ce que la comparaison entre plis, elle, ne suppose pas.
        """
        total = 1.0
        for fold in self.folds:
            total *= 1.0 + fold.total_return
        return total - 1.0

    @property
    def concentration(self) -> float | None:
        """Part du gain total portee par le meilleur pli.

        Superieure a 1 quand les autres plis perdent en moyenne : le resultat
        d'ensemble tient alors entierement a une periode.
        """
        best = self.best_fold
        if best is None or best.total_return <= 0.0:
            return None
        gains = sum(f.total_return for f in self.folds if f.total_return > 0.0)
        total = sum(f.total_return for f in self.folds)
        if abs(total) < 1e-12:
            return None
        return best.total_return / total if total > 0.0 else best.total_return / gains

    # -- sorties -----------------------------------------------------------

    def describe(self) -> SpecDict:
        return {
            "name": self.name,
            "cross_sectional": self.cross_sectional,
            "symbols": list(self.symbols),
            "splitter": self.splitter,
            "liquidate_folds": self.liquidate_folds,
            "aggregate": {
                "n_folds": self.n_folds,
                "sharpe_mean": self.sharpe_mean,
                "sharpe_median": self.sharpe_median,
                "sharpe_spread": self.sharpe_spread,
                "positive_share": self.positive_share,
                "compounded_return": self.compounded_return,
                "concentration": self.concentration,
                "worst_fold": None if self.worst_fold is None else self.worst_fold.index,
                "best_fold": None if self.best_fold is None else self.best_fold.index,
            },
            "folds": [f.describe() for f in self.folds],
            "manifest": self.manifest.describe(),
            "specification": self.specification,
            "warnings": list(self.warnings),
        }

    def render(self) -> str:
        rule = "-" * 78
        mode = "transversal" if self.cross_sectional else "mono-instrument"
        lines = [
            rule,
            f"{self.name}   [walk-forward, {mode}]   {', '.join(self.symbols)}",
            f"{self.splitter}",
            rule,
        ]
        lines.extend(fold.render() for fold in self.folds)
        lines.append(rule)

        def num(value: float | None, digits: int = 2) -> str:
            return "n/d" if value is None else f"{value:.{digits}f}"

        def pct(value: float | None) -> str:
            return "n/d" if value is None else f"{value * 100:+.2f} %"

        lines.append(
            f"Sharpe       moyen {num(self.sharpe_mean)}   median {num(self.sharpe_median)}   "
            f"dispersion {num(self.sharpe_spread)}"
        )
        lines.append(
            f"Plis         {self.n_folds} au total, "
            f"{pct(self.positive_share)} positifs"
        )
        if self.worst_fold is not None and self.best_fold is not None:
            lines.append(
                f"Extremes     pire pli {self.worst_fold.index} "
                f"({pct(self.worst_fold.total_return)})   "
                f"meilleur pli {self.best_fold.index} ({pct(self.best_fold.total_return)})"
            )
        lines.append(f"Compose      {pct(self.compounded_return)}")
        lines.append(
            "Plis         "
            + (
                "liquides a leur derniere barre"
                if self.liquidate_folds
                else "laisses ouverts : le rendement contient du latent"
            )
        )
        if self.concentration is not None:
            lines.append(
                f"Concentration {self.concentration * 100:.0f} % du resultat vient d'un seul pli"
            )
        lines.extend(f"Avertissement  {w}" for w in self.warnings)
        lines.append(rule)
        return "\n".join(lines)


def run_walk_forward(
    spec: BacktestSpec,
    splitter: WalkForwardSplitter,
    *,
    liquidate_folds: bool = True,
) -> WalkForwardReport:
    """Execute la strategie sur chaque fenetre de test du decoupage.

    Les donnees ne sont chargees et validees qu'une fois : les plis ne
    different que par leurs bornes. Chaque pli reconstruit en revanche une
    strategie NEUVE - reutiliser l'objet ferait heriter au pli suivant la
    position du precedent, ce qui reintroduirait entre les plis exactement la
    continuite qu'on cherche a rompre.
    """
    entry = get_strategy(*_parse_ref(spec.strategy.ref))
    # Sonde de validation : l'arbre de signaux est construit puis jete, pour
    # qu'une specification fausse soit refusee avant de lire les donnees. Le
    # pli construira sa propre strategie - en reutiliser une ferait heriter au
    # pli suivant la position du precedent.
    build_strategy(spec.strategy.as_dict())
    stores, instruments, sources = load_stores(spec)
    n_bars = _available_bars(spec, stores, cross_sectional=entry.cross_sectional)

    splits = list(splitter.split(n_bars))
    warnings: list[str] = []
    if not splits:
        raise ConfigurationError(
            f"aucun pli : {n_bars} barres disponibles ne suffisent pas au decoupage "
            f"{splitter.describe()}"
        )
    if len(splits) < 3:
        warnings.append(
            f"{len(splits)} pli(s) seulement : la dispersion entre plis ne signifie "
            f"pas grand-chose en dessous de trois"
        )

    folds: list[Fold] = []
    for index, split in enumerate(splits):
        fold_spec = spec.model_copy(
            update={
                "stop": split.test_stop,
                "min_warmup_bars": split.test_start,
                "liquidate_at_end": liquidate_folds or spec.liquidate_at_end,
            }
        )
        result = execute_run(
            fold_spec,
            stores,
            instruments,
            build_strategy(spec.strategy.as_dict()),
            entry.cross_sectional,
        )
        folds.append(
            Fold(
                index=index,
                split=split,
                metrics=compute_performance(
                    result, risk_free_annual=spec.risk_free_annual
                ),
                fingerprint=result_fingerprint(result),
            )
        )

    idle = [f.index for f in folds if f.was_idle]
    if idle:
        warnings.append(
            f"pli(s) sans aucune position : {', '.join(map(str, idle))}. Leur rendement "
            f"nul n'est pas un resultat, c'est une absence de resultat, et il tire la "
            f"moyenne vers zero sans rien mesurer."
        )
    unclosed = [
        f.index for f in folds if f.metrics.n_trades == 0 and not f.was_idle
    ]
    if unclosed and not liquidate_folds:
        warnings.append(
            f"pli(s) termines sur une position ouverte : {', '.join(map(str, unclosed))}. "
            f"Leur rendement contient un profit latent que le pli suivant n'herite pas."
        )

    manifest = RunManifest.capture(
        config={"specification": spec.canonical(), "splitter": splitter.describe()},
        seed=spec.seed,
        data_sources=sources,
        primitives=RegistrySnapshot.capture().entries,
    )
    return WalkForwardReport(
        liquidate_folds=liquidate_folds,
        name=spec.name,
        symbols=tuple(sorted(stores)),
        cross_sectional=entry.cross_sectional,
        splitter=splitter.describe(),
        folds=tuple(folds),
        manifest=manifest,
        specification=spec.canonical(),
        warnings=tuple(warnings),
    )


def _available_bars(
    spec: BacktestSpec, stores: dict[str, BarStore], *, cross_sectional: bool
) -> int:
    """Longueur sur laquelle le decoupage s'applique.

    En transversal, c'est celle du calendrier COMMUN - pas celle d'un
    instrument pris au hasard, qui ne dirait rien du panier.
    """
    if not cross_sectional:
        return next(iter(stores.values())).n_bars
    return build_panel_from(spec, stores).n_rows


def _parse_ref(ref: str) -> tuple[str, int | None]:
    name, _, version = ref.partition("@")
    if version and not version.isdigit():
        raise ConfigurationError(f"version invalide dans '{ref}'")
    return name, int(version) if version else None
