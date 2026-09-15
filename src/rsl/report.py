"""Execution d'une specification, et rapport - JSON et texte.

Un rapport reunit quatre choses qui n'ont d'interet qu'ensemble :

  - la **provenance** (`manifest.py`) : quelles donnees, quel code, quel etat
    du depot ;
  - la **specification** : ce qui a ete demande, sous forme canonique ;
  - les **metriques** : ce qui en est sorti ;
  - l'**empreinte de resultat** : de quoi verifier qu'un second run donne bien
    la meme chose.

L'empreinte de resultat merite un mot. Elle porte sur la courbe d'equity, les
fills, les compteurs et la comptabilite - jamais sur l'horodatage du run ni sur
la machine. Deux runs identiques lances a dix minutes d'intervalle doivent
avoir la meme empreinte ; y meler la date rendrait l'exigence de
reproductibilite inverifiable, ce qui est pire que de ne pas l'exiger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rsl.config import (
    BacktestSpec,
    build_panel_from,
    load_events,
    load_exogenes,
    load_stores,
)
from rsl.data.schema import BarStore, InstrumentSpec
from rsl.engine.cross_sectional import CrossSectionalRunner, CrossSectionalRunResult
from rsl.engine.limites import MOTIFS as LIMIT_MOTIFS
from rsl.engine.runner import RunResult, SingleAssetRunner
from rsl.errors import ConfigurationError
from rsl.manifest import RunManifest, apply_seed, canonical_hash
from rsl.metrics.intraday import (
    AttributionHoraire,
    attribution_horaire,
    verifier_coherence,
)
from rsl.metrics.performance import PerformanceMetrics, compute_performance
from rsl.metrics.silences import Silences, mesurer_les_silences
from rsl.metrics.statistics import DeflatedSharpeResult, TrialLog, deflated_sharpe_ratio
from rsl.primitives.registry import RegistrySnapshot
from rsl.strategies.base import (
    CrossSectionalStrategy,
    Strategy,
    build_strategy,
    get_strategy,
)

SpecDict = dict[str, object]

AnyRunResult = RunResult | CrossSectionalRunResult
"""Les deux runners produisent des types distincts, volontairement : leurs
compteurs ne decrivent pas les memes evenements. Ce qui les traite en aval
accepte donc l'un ou l'autre."""


def result_fingerprint(result: AnyRunResult) -> str:
    """Empreinte deterministe d'un resultat de run.

    Contient tout ce qui doit etre stable entre deux executions identiques, et
    rien de ce qui ne peut pas l'etre. Les flottants sont haches sous leur
    forme hexadecimale exacte : une comparaison a 15 decimales laisserait
    passer une derive d'un bit, qui est precisement ce qu'on cherche a exclure.
    """
    equity = result.equity
    portfolio = result.portfolio

    payload = {
        "equity": [value.hex() for value in equity.equity],
        "cash": [value.hex() for value in equity.cash],
        "ts_ns": list(equity.ts_ns),
        "exposure": list(equity.exposure),
        "fills": [
            [
                fill.order_id,
                fill.symbol,
                fill.bar_index,
                fill.side.value,
                fill.quantity,
                fill.price.hex(),
                fill.fee.hex(),
                fill.slippage_cost.hex(),
                fill.was_clamped,
                fill.tag,
            ]
            for fill in result.fills
        ],
        "trades": [
            [t.symbol, t.opened_bar, t.closed_bar, t.direction, t.gross_pnl.hex(), t.fees.hex()]
            for t in portfolio.closed_trades
        ],
        "counters": result.counters.describe(),
        "portfolio": portfolio.describe(),
    }
    return canonical_hash(payload)


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """Produit complet d'un run."""

    spec: BacktestSpec
    manifest: RunManifest
    metrics: PerformanceMetrics
    run: SpecDict
    result_fingerprint: str
    deflated_sharpe: DeflatedSharpeResult | None
    symbols: tuple[str, ...]
    cross_sectional: bool
    silences: Silences | None = None
    """Ce qui s'est passe sans qu'aucun compteur du moteur le dise.

    Hors `result_fingerprint` comme l'attribution, et pour la meme
    raison : un diagnostic decrit un run, il ne le definit pas.
    """
    attribution: AttributionHoraire | None = None
    """Repartition des trades par heure de seance. `None` sans calendrier.

    Champ a defaut plutot qu'obligatoire : un `BacktestReport` se construit
    aussi dans les tests avec un minimum de matiere, et exiger l'attribution
    partout aurait fait porter a chacun d'eux le chargement d'un magasin.
    """

    def to_dict(self) -> SpecDict:
        return {
            "name": self.spec.name,
            "cross_sectional": self.cross_sectional,
            "symbols": list(self.symbols),
            "result_fingerprint": self.result_fingerprint,
            **(
                {}
                if self.attribution is None
                else {"attribution_horaire": self.attribution.describe()}
            ),
            **(
                {}
                if self.silences is None or self.silences.est_vide
                else {"silences": self.silences.describe()}
            ),
            "manifest": self.manifest.describe(),
            "specification": self.spec.canonical(),
            "metrics": self.metrics.describe(),
            "deflated_sharpe": (
                None if self.deflated_sharpe is None else self.deflated_sharpe.describe()
            ),
            "run": self.run,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, ensure_ascii=False)

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def _lignes_de_plafonds(self) -> list[str]:
        """Les plafonds de portefeuille, et ce qu'ils ont refuse.

        Rien n'est emis quand aucun plafond n'est declare : c'est le cas de
        toute specification anterieure au 2026-09-12, et leur rendu doit rester
        identique au caractere pres.

        Les refus sont affiches meme a zero des qu'un plafond existe. « Zero
        refus » est une information - le plafond etait peut-etre trop large
        pour mordre - alors qu'une ligne absente ne se distingue pas d'une
        fonctionnalite oubliee.
        """
        declares = {
            nom: valeur
            for nom, valeur in self.spec.risk.limits.model_dump().items()
            if valeur is not None and nom != "note"
        }
        if not declares:
            return []
        lignes = [
            "Plafonds     "
            + ", ".join(f"{nom} {valeur}" for nom, valeur in sorted(declares.items()))
        ]
        stats = self.run.get("risk_stats")
        if isinstance(stats, dict) and not any(
            stats.get(f"n_rejected_{motif}") for motif in LIMIT_MOTIFS
        ):
            # « Zero refus » est une information : le plafond etait peut-etre
            # trop large pour mordre. Quand il a MORDU, le detail est rendu
            # par `_detail_des_refus`, qui couvre tous les motifs et non les
            # seuls plafonds - le dire deux fois inviterait a lire deux
            # chiffres differents comme s'ils comptaient la meme chose.
            lignes.append("Refus        aucun plafond n'a mordu")
        return lignes

    def _lignes_d_execution(self) -> list[str]:
        """Combien d'ordres ont ete EXECUTES, et ce qui a arrete les autres.

        Pourquoi cette ligne existe
        ---------------------------
        Le 2026-09-13, un run rendait **-25,62 % avec 2 trades** sur 10,6
        ans. Lu comme un resultat, c'etait une strategie qui perd. Ce n'en
        etait pas un : **5 080 ordres sur 5 084 avaient ete refuses pour
        marge**, la strategie demandant 4 contrats NQ - 108 000 de marge -
        sur un compte de 100 000. Le -25,62 % mesurait deux trades.

        Le chiffre etait publie dans le JSON (`risk_stats.n_rejected_margin`)
        et NULLE PART dans ce resume. C'etait la troisieme occurrence de la
        meme famille - [[lessons]] L18, L25, L28 : un backtest empeche
        produit un nombre LISIBLE, et rien ne distingue « la strategie n'a
        pas gagne » de « la strategie n'a jamais joue ».

        Ce que la ligne montre, et quand
        --------------------------------
        TOUJOURS, des qu'un ordre a ete emis - y compris a 100 %. Un taux
        plein est une information ; une ligne absente ne se distingue pas
        d'une fonctionnalite oubliee, ce qui est precisement l'erreur que
        cette ligne repare.

        Le detail par motif couvre TOUS les compteurs de refus, pas les
        seuls plafonds de portefeuille : `margin` et `sizing` ne relevent
        d'aucun plafond declare, et ce sont eux qui avaient mordu.
        """
        compteurs = self.run.get("counters")
        if not isinstance(compteurs, dict):
            return []

        def entier(source: dict[str, object], cle: str) -> int:
            """Zero si la cle manque ou n'est pas un entier.

            Un rapport ancien peut ne pas porter ces compteurs ; le resume ne
            doit pas lever pour autant.
            """
            valeur = source.get(cle)
            return valeur if isinstance(valeur, int) and not isinstance(valeur, bool) else 0

        emis = entier(compteurs, "n_orders_submitted")
        if emis == 0:
            return []

        remplis = entier(self.run, "n_fills")
        taux = remplis / emis
        ligne = (
            f"Execution    {remplis} fill(s) sur {emis} ordre(s) emis   "
            f"taux {taux * 100:.1f} %"
        )

        lignes = [ligne]
        lignes.extend(self._detail_des_refus())
        lignes.extend(self._ligne_de_troncature())

        # Le seuil est deliberement HAUT. Un run sain remplit la quasi-
        # totalite de ce qu'il emet ; des qu'un ordre sur dix tombe, le
        # rendement affiche ne mesure plus la strategie declaree.
        if taux < 0.90:
            lignes.append(
                f"AVERTISSEMENT  {emis - remplis} ordre(s) sur {emis} "
                f"n'ont pas ete executes ({(1 - taux) * 100:.1f} %). Le rendement "
                f"ci-dessus ne mesure PAS la strategie declaree, mais ce qui "
                f"a pu en passer."
            )
        return lignes

    def _detail_des_refus(self) -> list[str]:
        """Un motif par compteur non nul, du plus frequent au moins.

        Trie par nombre : quand plusieurs motifs mordent, celui qui explique
        le run est le premier, pas celui dont le nom vient en tete de
        l'alphabet.
        """
        stats = self.run.get("risk_stats")
        if not isinstance(stats, dict):
            return []
        # `n_tailles_mesurees` est un DENOMINATEUR, pas un refus. Il s'est
        # affiche une fois sous « Refus » - « tailles_mesurees 1148 » se
        # lisait comme 1 148 ordres refuses alors que c'est le nombre
        # d'ordres DIMENSIONNES. Exactement le nombre lisible et faux que
        # ces compteurs existent pour supprimer.
        pas_des_refus = {"n_warned_margin", "n_tailles_mesurees"}
        motifs = [
            (nom, int(valeur))
            for nom, valeur in stats.items()
            if isinstance(valeur, int) and valeur > 0 and nom not in pas_des_refus
        ]
        if not motifs:
            return []
        motifs.sort(key=lambda paire: (-paire[1], paire[0]))
        detail = ", ".join(
            f"{nom.removeprefix('n_rejected_').removeprefix('n_')} {nombre}"
            for nom, nombre in motifs
        )
        return [f"Refus        {detail}"]

    def _ligne_de_troncature(self) -> list[str]:
        """L'exposition supprimee par l'arrondi aux contrats entiers.

        Un contrat est entier, et le socle ne ment pas la-dessus. Mais la
        strategie, elle, a demande autre chose - et l'ecart n'est pas un bruit
        d'arrondi. Mesure sur Zarattini le 2026-09-15 : **26,4 % d'exposition
        supprimee**, dont **271 seances entierement muettes** concentrees sur
        2020, 2022 et 2025, ou `0,02 / sigma` tombait sous UN.

        Absente quand aucune regle qui divise n'a repondu : « rien perdu » et
        « personne n'a divise » ne sont pas la meme affirmation.
        """
        stats = self.run.get("risk_stats")
        if not isinstance(stats, dict):
            return []
        perte = stats.get("perte_par_troncature")
        mesurees = stats.get("n_tailles_mesurees")
        if not isinstance(perte, float) or not isinstance(mesurees, int):
            return []
        ligne = (
            f"Troncature   {perte * 100:.1f} % de l'exposition demandee "
            f"supprimee par l'arrondi aux contrats entiers "
            f"({mesurees:,} dimensionnement(s))"
        )
        if perte < 0.05:
            return [ligne]
        return [
            ligne,
            "             la strategie negociee n'est pas celle qui est "
            "declaree : verifier si les tailles nulles se concentrent sur "
            "certains regimes",
        ]

    def render(self) -> str:
        rule = "-" * 72
        mode = "transversal" if self.cross_sectional else "mono-instrument"
        lines = [
            rule,
            f"{self.spec.name}   [{mode}]   {', '.join(self.symbols)}",
            rule,
            self.manifest.render(),
            rule,
            f"Strategie    {self.spec.strategy.ref}   {self.spec.strategy.params}",
            f"Couts        frais {self.spec.execution.fees.kind}, "
            f"slippage {self.spec.execution.slippage.kind}, "
            f"lag {self.spec.execution.lag_bars} barre(s)",
            f"Risque       sizing {self.spec.risk.sizing.kind}",
            *self._lignes_de_plafonds(),
            rule,
            self.metrics.render(),
            # A COTE du rendement, et non dans un bloc separe : c'est
            # ensemble que les deux se lisent.
            *self._lignes_d_execution(),
            rule,
        ]
        if self.silences is not None:
            muets = self.silences.render()
            if muets:
                lines.extend([*muets, rule])
        if self.attribution is not None:
            horaires = self.attribution.render()
            if horaires:
                lines.extend([*horaires, rule])
        if self.deflated_sharpe is not None:
            lines.extend([self.deflated_sharpe.render(), rule])
        lines.append(f"Empreinte    {self.result_fingerprint}")
        lines.append(rule)
        return "\n".join(lines)


def run_backtest(spec: BacktestSpec, *, trial_log: TrialLog | None = None) -> BacktestReport:
    """Execute une specification et produit son rapport.

    Enveloppe de `run_backtest_detailed` : la plupart des appelants n'ont que
    faire du `RunResult` brut.
    """
    return run_backtest_detailed(spec, trial_log=trial_log).report


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    """Tout ce qu'un run a produit, y compris ce que le rapport ne porte pas.

    Le rapport porte des agregats. Un tableau de bord a besoin des fills, des
    trades fermes, de la courbe d'equity et des barres effectivement servies au
    moteur - les barres APRES reechantillonnage, pas les fichiers d'origine,
    sans quoi le graphe de prix ne montrerait pas ce sur quoi la strategie a
    decide.
    """

    report: BacktestReport
    result: AnyRunResult
    stores: dict[str, BarStore]
    instruments: dict[str, InstrumentSpec]


def run_backtest_detailed(
    spec: BacktestSpec, *, trial_log: TrialLog | None = None
) -> RunArtifacts:
    """Comme `run_backtest`, mais rend AUSSI la matiere brute du run.

    Une seconde fonction plutot qu'un second appel : rejouer le run pour
    l'afficher couterait le double et ouvrirait la porte a ce que la fenetre
    montre un run different de celui qui a ete rapporte.

    `trial_log` porte le compteur d'essais du Deflated Sharpe. Sans lui, le run
    est traite comme un essai unique - ce qui est vrai pour un run isole, et
    faux des qu'on explore. Le DSR emet alors son avertissement plutot que de
    laisser croire a une significativite.
    """
    apply_seed(spec.seed)

    entry = get_strategy(*_parse_ref(spec.strategy.ref))
    # La strategie est construite AVANT le chargement des donnees : c'est elle
    # qui valide tout l'arbre de signaux, et une specification fausse doit etre
    # refusee sans avoir lu le moindre parquet. Mesure sur un univers de dix
    # instruments : 0,1 ms au lieu de 6,1 s.
    strategy = build_strategy(spec.strategy.as_dict())
    stores, instruments, sources = load_stores(spec)

    result = execute_run(spec, stores, instruments, strategy, entry.cross_sectional)
    symbols = tuple(sorted(stores))

    metrics = compute_performance(result, risk_free_annual=spec.risk_free_annual)
    manifest = RunManifest.capture(
        config=spec.canonical(),
        seed=spec.seed,
        data_sources=sources,
        primitives=RegistrySnapshot.capture().entries,
    )

    log = trial_log if trial_log is not None else TrialLog()
    log.record(spec.canonical(), metrics.sharpe_per_period or 0.0, label=spec.name)
    deflated = (
        deflated_sharpe_ratio(
            sharpe_per_period=metrics.sharpe_per_period,
            n_observations=metrics.n_returns,
            skewness=metrics.returns_skewness,
            kurtosis=metrics.returns_kurtosis,
            n_trials=log.n_trials,
            variance_of_trial_sharpes=log.variance_of_sharpes,
        )
        if metrics.sharpe_per_period is not None
        else None
    )

    fermes = result.portfolio.closed_trades
    attribution = attribution_horaire(fermes, stores)
    if attribution is not None:
        # Un tableau dont les lignes ne somment pas au total serait pire
        # qu'absent : il aurait l'air complet.
        verifier_coherence(attribution, len(fermes))

    silences = mesurer_les_silences(
        stores, result.fills, spec.execution.lag_bars
    )

    report = BacktestReport(
        spec=spec,
        manifest=manifest,
        metrics=metrics,
        run=result.describe(),
        result_fingerprint=result_fingerprint(result),
        deflated_sharpe=deflated,
        symbols=symbols,
        cross_sectional=entry.cross_sectional,
        attribution=attribution,
        silences=silences,
    )
    return RunArtifacts(
        report=report, result=result, stores=stores, instruments=instruments
    )


def execute_run(
    spec: BacktestSpec,
    stores: dict[str, BarStore],
    instruments: dict[str, InstrumentSpec],
    strategy: Strategy | CrossSectionalStrategy,
    cross_sectional: bool,
) -> AnyRunResult:
    """Aiguille vers le runner qui convient.

    Extrait de `run_backtest` pour que le walk-forward puisse enchainer
    des fenetres sans recharger les donnees a chaque pli.
    """
    if cross_sectional:
        return _run_cross_sectional(spec, stores, instruments, strategy)
    return _run_single(spec, stores, instruments, strategy)


def _parse_ref(ref: str) -> tuple[str, int | None]:
    name, _, version = ref.partition("@")
    if version and not version.isdigit():
        raise ConfigurationError(f"version invalide dans '{ref}'")
    return name, int(version) if version else None


def _run_single(
    spec: BacktestSpec,
    stores: dict[str, BarStore],
    instruments: dict[str, InstrumentSpec],
    strategy: Strategy | CrossSectionalStrategy,
) -> RunResult:
    if len(stores) != 1:
        raise ConfigurationError(
            f"la strategie '{spec.strategy.ref}' est mono-instrument mais la "
            f"specification en declare {len(stores)}"
        )
    if not isinstance(strategy, Strategy):
        raise ConfigurationError(f"'{spec.strategy.ref}' n'est pas une strategie mono-instrument")
    symbol = next(iter(stores))
    runner = SingleAssetRunner(
        stores[symbol],
        instruments[symbol],
        spec.build_run_config(),
        risk=spec.build_risk(),
        events=load_events(spec),
        exogenes=load_exogenes(spec),
    )
    return runner.run(strategy)


def _run_cross_sectional(
    spec: BacktestSpec,
    stores: dict[str, BarStore],
    instruments: dict[str, InstrumentSpec],
    strategy: Strategy | CrossSectionalStrategy,
) -> CrossSectionalRunResult:
    if not isinstance(strategy, CrossSectionalStrategy):
        raise ConfigurationError(f"'{spec.strategy.ref}' n'est pas une strategie transversale")
    runner = CrossSectionalRunner(
        build_panel_from(spec, stores),
        instruments,
        spec.build_run_config(),
        risk=spec.build_risk(),
        schedule=spec.rebalance.build(),
        events=load_events(spec),
        exogenes=load_exogenes(spec),
    )
    return runner.run(strategy)
