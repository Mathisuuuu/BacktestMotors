"""Modele de fill : declenchement, prix, frais, slippage.

Regle non negociable (`docs/execution-model.md` §3.1) : un fill se produit
toujours a un prix qui a existe dans la barre de fill.

    low(barre_de_fill) <= fill_price <= high(barre_de_fill)

Verifie par assertion a chaque fill, en plus du test property-based. Un
slippage qui pousserait le prix hors de la barre est ecrete a la borne et
l'ecretage est compte : on prefere sous-estimer le slippage plutot que de
remplir a un prix qui n'a jamais ete cote.

Les couts n'ont AUCUNE valeur par defaut. Une `ExecutionConfig` sans modele de
frais ni modele de slippage ne se construit pas. Pour le cas sans friction
- test analytique buy & hold, test de la strategie plate - on ecrit
`ZeroFee()` et `ZeroSlippage()` : des objets nommes, qui apparaissent dans le
manifeste de run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from rsl.data.schema import Bar, InstrumentSpec
from rsl.engine.orders import Fill, Order, OrderType, Side
from rsl.errors import ConfigurationError

SpecDict = dict[str, object]


# ---------------------------------------------------------------------------
# Modeles de couts
# ---------------------------------------------------------------------------


@runtime_checkable
class FeeModel(Protocol):
    """Frais d'une execution, en devise du contrat."""

    def fee(self, spec: InstrumentSpec, quantity: int) -> float: ...

    def describe(self) -> SpecDict: ...


@dataclass(frozen=True, slots=True)
class PerContractFee:
    """Frais par contrat et par cote, lus dans la specification d'instrument.

    Pas de frais en pourcentage du notionnel : ce n'est pas ainsi qu'un future
    est facture, et un modele en points de base produirait des ordres de
    grandeur faux (ES vaut ~250 k$ de notionnel pour ~2 $ de frais par cote).
    """

    def fee(self, spec: InstrumentSpec, quantity: int) -> float:
        return quantity * spec.fee_per_contract_per_side

    def describe(self) -> SpecDict:
        return {"model": "per_contract_fee", "source": "instrument_spec"}


@dataclass(frozen=True, slots=True)
class FlatFee:
    """Frais forfaitaires par contrat, independants de l'instrument."""

    per_contract: float

    def __post_init__(self) -> None:
        if self.per_contract < 0.0:
            raise ConfigurationError(f"per_contract doit etre >= 0, recu {self.per_contract}")

    def fee(self, spec: InstrumentSpec, quantity: int) -> float:
        return quantity * self.per_contract

    def describe(self) -> SpecDict:
        return {"model": "flat_fee", "per_contract": self.per_contract}


@dataclass(frozen=True, slots=True)
class ZeroFee:
    """Absence de frais, DECLAREE. Reserve aux tests analytiques."""

    def fee(self, spec: InstrumentSpec, quantity: int) -> float:
        return 0.0

    def describe(self) -> SpecDict:
        return {"model": "zero_fee", "warning": "aucun frais : resultat non realisable"}


@runtime_checkable
class SlippageModel(Protocol):
    """Ecart de prix defavorable, toujours >= 0. Le sens est applique par le moteur."""

    def offset(self, spec: InstrumentSpec, reference_price: float) -> float: ...

    def describe(self) -> SpecDict: ...


@dataclass(frozen=True, slots=True)
class TickSlippage:
    """`ticks * tick_size`. Le modele adapte aux futures : le slippage y est une
    affaire de ticks, pas de pourcentage."""

    ticks: float

    def __post_init__(self) -> None:
        if self.ticks < 0.0:
            raise ConfigurationError(f"ticks doit etre >= 0, recu {self.ticks}")

    def offset(self, spec: InstrumentSpec, reference_price: float) -> float:
        return self.ticks * spec.tick_size

    def describe(self) -> SpecDict:
        return {"model": "tick_slippage", "ticks": self.ticks}


@dataclass(frozen=True, slots=True)
class BpsSlippage:
    """Slippage proportionnel au prix, en points de base."""

    bps: float

    def __post_init__(self) -> None:
        if self.bps < 0.0:
            raise ConfigurationError(f"bps doit etre >= 0, recu {self.bps}")

    def offset(self, spec: InstrumentSpec, reference_price: float) -> float:
        return abs(reference_price) * self.bps / 10_000.0

    def describe(self) -> SpecDict:
        return {"model": "bps_slippage", "bps": self.bps}


@dataclass(frozen=True, slots=True)
class ZeroSlippage:
    """Absence de slippage, DECLAREE. Reserve aux tests analytiques."""

    def offset(self, spec: InstrumentSpec, reference_price: float) -> float:
        return 0.0

    def describe(self) -> SpecDict:
        return {"model": "zero_slippage", "warning": "aucun slippage : resultat non realisable"}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class IntrabarPriority(StrEnum):
    PESSIMISTIC = "pessimistic"
    """Le stop est repute toucher avant le take-profit. Defaut."""

    OPTIMISTIC = "optimistic"
    """Le take-profit est repute toucher en premier. A n'utiliser qu'en
    sensibilite, pour mesurer de combien le resultat depend de l'hypothese."""


class MarginPolicy(StrEnum):
    REJECT = "reject"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Parametres d'execution. `fees` et `slippage` n'ont pas de defaut."""

    fees: FeeModel
    slippage: SlippageModel
    execution_lag: int = 1
    intrabar_priority: IntrabarPriority = IntrabarPriority.PESSIMISTIC
    max_fill_gap: timedelta | None = None
    margin_policy: MarginPolicy = MarginPolicy.REJECT

    def __post_init__(self) -> None:
        if self.execution_lag < 1:
            raise ConfigurationError(
                f"execution_lag doit etre >= 1, recu {self.execution_lag}. Executer a la "
                f"cloture qui a produit le signal est le mode de fuite le plus courant des "
                f"backtests naifs ; il est absent du moteur, pas desactive par defaut."
            )
        if self.max_fill_gap is not None and self.max_fill_gap.total_seconds() <= 0:
            raise ConfigurationError(f"max_fill_gap doit etre > 0, recu {self.max_fill_gap}")

    def describe(self) -> SpecDict:
        return {
            "execution_lag": self.execution_lag,
            "intrabar_priority": self.intrabar_priority.value,
            "max_fill_gap_seconds": (
                None if self.max_fill_gap is None else self.max_fill_gap.total_seconds()
            ),
            "margin_policy": self.margin_policy.value,
            "fees": self.fees.describe(),
            "slippage": self.slippage.describe(),
        }


ZERO_COST = ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())
"""Configuration sans friction, nommee. Utilisee par les tests analytiques.

Elle porte ses avertissements dans son `describe()`, donc dans le manifeste :
un resultat produit avec elle se reconnait sans avoir a relire la config.
"""


# ---------------------------------------------------------------------------
# Moteur d'execution
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExecutionStats:
    n_fills: int = 0
    n_slippage_clamped: int = 0
    n_limit_not_touched: int = 0
    n_stop_not_triggered: int = 0

    def describe(self) -> SpecDict:
        return {
            "n_fills": self.n_fills,
            "n_slippage_clamped": self.n_slippage_clamped,
            "n_limit_not_touched": self.n_limit_not_touched,
            "n_stop_not_triggered": self.n_stop_not_triggered,
        }


class ExecutionEngine:
    """Transforme un ordre du carnet en `Fill`, contre une barre precise.

    Sans etat au-dela de ses compteurs : le carnet d'ordres appartient au
    runner. Deux appels identiques donnent le meme fill.
    """

    __slots__ = ("config", "stats")

    def __init__(self, config: ExecutionConfig) -> None:
        self.config = config
        self.stats = ExecutionStats()

    def reset(self) -> None:
        self.stats = ExecutionStats()

    def try_fill(
        self,
        order: Order,
        *,
        bar: Bar,
        bar_index: int,
        spec: InstrumentSpec,
        order_id: int,
    ) -> Fill | None:
        """Tente d'executer `order` contre `bar`. `None` si le niveau n'est pas atteint."""
        trigger = self._trigger_price(order, bar)
        if trigger is None:
            return None

        raw_price = trigger
        slippage_applies = order.order_type in (OrderType.MARKET, OrderType.STOP)
        offset = self.config.slippage.offset(spec, raw_price) if slippage_applies else 0.0
        signed = raw_price + order.side.sign * offset

        price, clamped = self._clamp_to_bar(signed, bar)
        if clamped:
            self.stats.n_slippage_clamped += 1

        # Le prix effectivement paye en slippage, apres ecretage : c'est celui
        # qui compte pour le rapport, pas le slippage theorique.
        slippage_cost = abs(price - raw_price)

        self.stats.n_fills += 1
        return Fill(
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            fee=self.config.fees.fee(spec, order.quantity),
            slippage_cost=slippage_cost,
            ts_ns=int(bar.ts_close.timestamp() * 1_000_000_000),
            bar_index=bar_index,
            was_clamped=clamped,
            tag=order.tag,
        )

    def _trigger_price(self, order: Order, bar: Bar) -> float | None:
        """Prix de reference avant slippage, ou `None` si l'ordre ne se declenche pas.

        Les regles `LIMIT` et `STOP` encodent le gap : si la barre ouvre deja
        au-dela du niveau, le fill se fait a l'ouverture, jamais au niveau
        demande. C'est la direction defavorable, et la seule realiste.
        """
        match order.order_type:
            case OrderType.MARKET:
                return bar.open

            case OrderType.LIMIT:
                limit = order.limit_price
                assert limit is not None  # garanti par Order.__post_init__
                if order.side is Side.BUY:
                    if bar.low > limit:
                        self.stats.n_limit_not_touched += 1
                        return None
                    return min(limit, bar.open)
                if bar.high < limit:
                    self.stats.n_limit_not_touched += 1
                    return None
                return max(limit, bar.open)

            case OrderType.STOP:
                stop = order.stop_price
                assert stop is not None
                if order.side is Side.BUY:
                    if bar.high < stop:
                        self.stats.n_stop_not_triggered += 1
                        return None
                    return max(stop, bar.open)
                if bar.low > stop:
                    self.stats.n_stop_not_triggered += 1
                    return None
                return min(stop, bar.open)

    @staticmethod
    def _clamp_to_bar(price: float, bar: Bar) -> tuple[float, bool]:
        if price > bar.high:
            return bar.high, True
        if price < bar.low:
            return bar.low, True
        return price, False


def assert_within_bar(price: float, bar: Bar) -> None:
    """Garde utilisable par les tests et par le runner.

    Volontairement une fonction et non un `assert` inline : elle doit survivre
    a un `python -O`, qui desactive les assertions. Une garantie qui disparait
    en production n'en est pas une.
    """
    if not (bar.low <= price <= bar.high):
        raise AssertionError(
            f"fill a {price} hors de la barre [{bar.low}, {bar.high}] "
            f"({bar.ts_close.isoformat()}) : ce prix n'a jamais existe"
        )
