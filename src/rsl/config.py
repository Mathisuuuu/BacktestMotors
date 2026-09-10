"""Specification declarative d'un backtest, et sa traduction en objets moteur.

Un fichier de configuration decrit un run entierement : donnees, couts,
execution, risque, strategie. Il est valide par pydantic avec
`extra="forbid"` - un parametre mal orthographie est une erreur, jamais un
defaut silencieux. C'est la meme regle que pour les parametres de primitives,
et pour la meme raison : ces fichiers seront bientot ecrits par une machine.

La specification est aussi ce qui est hache dans le manifeste. Deux runs de
meme `config_hash` ont recu les memes instructions - a condition que le hash
porte sur la specification CANONIQUE, pas sur le texte du fichier. Un fichier
reindente donnerait sinon un run "different".
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rsl.data.instruments import get_instrument
from rsl.data.loader import build_panel, load_bar_store
from rsl.data.resample import CloseStamp, Period, resample
from rsl.data.schema import (
    AlignPolicy,
    BarStore,
    Granularity,
    InstrumentSpec,
    Panel,
    ns_to_datetime,
)
from rsl.data.validation import ValidationConfig
from rsl.engine.cross_sectional import EveryNRows, EveryRow, RebalanceSchedule
from rsl.engine.execution import (
    BpsSlippage,
    ExecutionConfig,
    FeeModel,
    FlatFee,
    IntrabarPriority,
    MarginPolicy,
    PerContractFee,
    SlippageModel,
    TickSlippage,
    ZeroFee,
    ZeroSlippage,
)
from rsl.engine.risk import (
    EquityFraction,
    FixedContracts,
    RiskFraction,
    RiskManager,
    SizingRule,
)
from rsl.engine.runner import RunConfig
from rsl.errors import ConfigurationError
from rsl.manifest import DataSource

SpecDict = dict[str, object]


class StrictModel(BaseModel):
    """Base commune : immuable et fermee aux champs inconnus."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Donnees
# ---------------------------------------------------------------------------


class DataSpec(StrictModel):
    """Un instrument, son fichier, et son eventuelle agregation."""

    root: str = Field(min_length=1, description="Racine connue de la table d'instruments")
    path: Path
    timestamp_column: str | None = None
    granularity_minutes: int = Field(default=1, ge=1)
    resample: Period | None = Field(
        default=None,
        description="Agregation calendaire appliquee apres chargement.",
    )
    resample_min_bars: int | None = Field(default=None, ge=1)
    close_stamp: CloseStamp = CloseStamp.PERIOD_END
    max_gap_seconds: float | None = Field(default=None, gt=0.0)
    allow_non_positive_prices: bool = True

    @property
    def instrument(self) -> InstrumentSpec:
        return get_instrument(self.root)

    @property
    def validation(self) -> ValidationConfig:
        return ValidationConfig(
            max_gap=(
                None if self.max_gap_seconds is None else timedelta(seconds=self.max_gap_seconds)
            ),
            allow_non_positive_prices=self.allow_non_positive_prices,
        )


# ---------------------------------------------------------------------------
# Couts et execution
# ---------------------------------------------------------------------------


class FeeSpec(StrictModel):
    """Modele de frais. Aucun defaut : le choix doit etre ecrit."""

    kind: Literal["per_contract", "flat", "zero"]
    per_contract: float | None = Field(default=None, ge=0.0)

    def build(self) -> FeeModel:
        match self.kind:
            case "per_contract":
                return PerContractFee()
            case "flat":
                if self.per_contract is None:
                    raise ConfigurationError("frais 'flat' : `per_contract` est requis")
                return FlatFee(self.per_contract)
            case "zero":
                return ZeroFee()


class SlippageSpec(StrictModel):
    """Modele de slippage. Aucun defaut, meme raison."""

    kind: Literal["tick", "bps", "zero"]
    ticks: float | None = Field(default=None, ge=0.0)
    bps: float | None = Field(default=None, ge=0.0)

    def build(self) -> SlippageModel:
        match self.kind:
            case "tick":
                if self.ticks is None:
                    raise ConfigurationError("slippage 'tick' : `ticks` est requis")
                return TickSlippage(self.ticks)
            case "bps":
                if self.bps is None:
                    raise ConfigurationError("slippage 'bps' : `bps` est requis")
                return BpsSlippage(self.bps)
            case "zero":
                return ZeroSlippage()


class ExecutionSpec(StrictModel):
    """Parametres d'execution. `fees` et `slippage` sont obligatoires."""

    fees: FeeSpec
    slippage: SlippageSpec
    lag_bars: int = Field(default=1, ge=1)
    intrabar_priority: IntrabarPriority = IntrabarPriority.PESSIMISTIC
    max_fill_gap_seconds: float | None = Field(default=None, gt=0.0)
    margin_policy: MarginPolicy = MarginPolicy.REJECT

    def build(self) -> ExecutionConfig:
        return ExecutionConfig(
            fees=self.fees.build(),
            slippage=self.slippage.build(),
            execution_lag=self.lag_bars,
            intrabar_priority=self.intrabar_priority,
            max_fill_gap=(
                None
                if self.max_fill_gap_seconds is None
                else timedelta(seconds=self.max_fill_gap_seconds)
            ),
            margin_policy=self.margin_policy,
        )


# ---------------------------------------------------------------------------
# Risque
# ---------------------------------------------------------------------------


class SizingSpec(StrictModel):
    kind: Literal["none", "fixed", "equity_fraction", "risk_fraction"] = "none"
    contracts: int | None = Field(default=None, ge=1)
    fraction: float | None = Field(default=None, gt=0.0)
    atr_window: int = Field(default=14, ge=1)
    atr_multiple: float = Field(default=2.0, gt=0.0)

    def build(self) -> SizingRule | None:
        match self.kind:
            case "none":
                return None
            case "fixed":
                if self.contracts is None:
                    raise ConfigurationError("sizing 'fixed' : `contracts` est requis")
                return FixedContracts(self.contracts)
            case "equity_fraction":
                if self.fraction is None:
                    raise ConfigurationError("sizing 'equity_fraction' : `fraction` est requis")
                return EquityFraction(self.fraction)
            case "risk_fraction":
                if self.fraction is None:
                    raise ConfigurationError("sizing 'risk_fraction' : `fraction` est requis")
                return RiskFraction(
                    self.fraction, atr_window=self.atr_window, atr_multiple=self.atr_multiple
                )


class RiskSpec(StrictModel):
    sizing: SizingSpec = SizingSpec()
    max_gross_contracts: int | None = Field(default=None, ge=1)

    def build(self, margin_policy: MarginPolicy) -> RiskManager:
        return RiskManager(
            sizing=self.sizing.build(),
            margin_policy=margin_policy,
            max_gross_contracts=self.max_gross_contracts,
        )


# ---------------------------------------------------------------------------
# Strategie et calendrier
# ---------------------------------------------------------------------------


class StrategySpec(StrictModel):
    ref: str = Field(min_length=1, description="Reference versionnee, ex. 'sma_crossover@1'")
    params: dict[str, object] = Field(default_factory=dict)

    def as_dict(self) -> SpecDict:
        return {"ref": self.ref, "params": dict(self.params)}


class RebalanceSpec(StrictModel):
    kind: Literal["every_row", "every_n_rows"] = "every_row"
    n: int = Field(default=1, ge=1)
    offset: int = Field(default=0, ge=0)

    def build(self) -> RebalanceSchedule:
        if self.kind == "every_row":
            return EveryRow()
        return EveryNRows(self.n, self.offset)


class PanelSpec(StrictModel):
    align_policy: AlignPolicy = AlignPolicy.DROP
    max_ffill_bars: int | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# Specification complete
# ---------------------------------------------------------------------------


class BacktestSpec(StrictModel):
    """Tout ce qu'il faut pour lancer un run, et rien d'autre."""

    name: str = Field(min_length=1)
    initial_cash: float = Field(gt=0.0)
    data: list[DataSpec] = Field(min_length=1)
    execution: ExecutionSpec
    strategy: StrategySpec
    risk: RiskSpec = RiskSpec()
    panel: PanelSpec = PanelSpec()
    rebalance: RebalanceSpec = RebalanceSpec()
    seed: int = 0
    stop: int | None = Field(default=None, ge=1)
    liquidate_at_end: bool = False
    check_invariant: bool = True
    risk_free_annual: float = Field(default=0.0, ge=-0.5)
    with_data_hash: bool = Field(
        default=True,
        description=(
            "Calculer le SHA-256 des fichiers sources. Le desactiver accelere une "
            "exploration mais rend le manifeste incomplet, et le rapport le signale."
        ),
    )

    def canonical(self) -> SpecDict:
        """Forme canonique hachee dans le manifeste.

        Les chemins sont normalises en absolus : deux invocations depuis des
        repertoires differents doivent donner la meme empreinte si elles
        designent les memes fichiers.
        """
        payload = self.model_dump(mode="json")
        for entry, source in zip(payload["data"], self.data, strict=True):
            entry["path"] = str(source.path.resolve())
        return payload

    def build_run_config(self) -> RunConfig:
        return RunConfig(
            initial_cash=self.initial_cash,
            execution=self.execution.build(),
            liquidate_at_end=self.liquidate_at_end,
            check_invariant=self.check_invariant,
            stop=self.stop,
        )

    def build_risk(self) -> RiskManager:
        return self.risk.build(self.execution.margin_policy)


# ---------------------------------------------------------------------------
# Chargement des donnees
# ---------------------------------------------------------------------------


def load_stores(
    spec: BacktestSpec,
) -> tuple[dict[str, BarStore], dict[str, InstrumentSpec], tuple[DataSource, ...]]:
    """Charge, valide, agrege si demande, et decrit chaque source.

    Leve `DataValidationError` si un fichier est rejete : mieux vaut pas de
    resultat qu'un resultat sur des donnees douteuses.
    """
    stores: dict[str, BarStore] = {}
    instruments: dict[str, InstrumentSpec] = {}
    sources: list[DataSource] = []

    for entry in spec.data:
        instrument = entry.instrument
        store, _report = load_bar_store(
            entry.path,
            symbol=instrument.symbol,
            granularity=Granularity.minutes(entry.granularity_minutes),
            timestamp_column=entry.timestamp_column,
            config=entry.validation,
            with_hash=spec.with_data_hash,
        )
        transformations: list[str] = []
        if entry.resample is not None:
            store, resample_report = resample(
                store,
                entry.resample,
                min_bars=entry.resample_min_bars,
                close_stamp=entry.close_stamp,
            )
            transformations.append(
                f"resample:{entry.resample.value}"
                f"({resample_report.n_periods} periodes, "
                f"{resample_report.n_dropped_incomplete} ecartee(s))"
            )

        if instrument.symbol in stores:
            raise ConfigurationError(
                f"'{instrument.symbol}' apparait deux fois dans la specification"
            )
        stores[instrument.symbol] = store
        instruments[instrument.symbol] = instrument
        sources.append(
            DataSource(
                symbol=instrument.symbol,
                path=str(entry.path.resolve()),
                source_hash=store.source_hash,
                n_bars=store.n_bars,
                granularity=str(store.granularity),
                first_ts=ns_to_datetime(int(store.ts_close[0])).isoformat(),
                last_ts=ns_to_datetime(int(store.ts_close[-1])).isoformat(),
                transformations=tuple(transformations),
            )
        )

    return stores, instruments, tuple(sources)


def build_panel_from(spec: BacktestSpec, stores: dict[str, BarStore]) -> Panel:
    """Panneau multi-instruments, selon la politique d'alignement demandee."""
    return build_panel(
        stores,
        align_policy=spec.panel.align_policy,
        max_ffill_bars=spec.panel.max_ffill_bars,
    )
