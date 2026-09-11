"""Dimensionnement et garde-fous de marge.

Le dimensionnement est une affaire du moteur, pas de la strategie : c'est ce
qui permet de rejouer la meme strategie sous une autre regle de taille sans la
modifier. Une strategie emet une intention ; la couche risque decide combien.

Troncature vers zero, jamais d'arrondi
--------------------------------------
Un future se traite en contrats entiers. `round()` ferait passer 0,5 contrat a
1 et creerait des positions que personne n'a demandees ; la troncature les
laisse a zero et l'ordre n'est pas emis. Le compteur `n_dropped_sizing` rend le
phenomene visible plutot que silencieux (`docs/execution-model.md` §6.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from rsl.data.feed import Context
from rsl.data.schema import InstrumentSpec
from rsl.engine.execution import MarginPolicy
from rsl.engine.orders import Order
from rsl.engine.portfolio import Portfolio
from rsl.errors import ConfigurationError
from rsl.primitives.registry import bind_primitive

SpecDict = dict[str, object]


@runtime_checkable
class SizingRule(Protocol):
    """Combien de contrats pour une intention d'entree."""

    @property
    def warmup_bars(self) -> int: ...

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int: ...

    def describe(self) -> SpecDict: ...


@dataclass(frozen=True, slots=True)
class FixedContracts:
    """Taille constante. La regle la plus simple, et la seule qui ne depende
    d'aucune estimation - donc celle des tests analytiques."""

    n: int = 1

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ConfigurationError(f"n doit etre >= 1, recu {self.n}")

    @property
    def warmup_bars(self) -> int:
        return 0

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        return self.n

    def describe(self) -> SpecDict:
        return {"rule": "fixed_contracts", "n": self.n}


@dataclass(frozen=True, slots=True)
class EquityFraction:
    """Notionnel cible en fraction de l'equity.

    `contracts = trunc(equity * fraction / (prix * multiplicateur))`.

    Attention a l'interpretation : sur un future, ce notionnel n'est pas
    finance par du cash. Une fraction de 1,0 sur ES represente un levier
    d'environ 15 fois la marge initiale, pas une position "sans levier".
    """

    fraction: float

    def __post_init__(self) -> None:
        if not self.fraction > 0.0:
            raise ConfigurationError(f"fraction doit etre > 0, recu {self.fraction}")

    @property
    def warmup_bars(self) -> int:
        return 0

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        notional_per_contract = abs(reference_price) * spec.multiplier
        if notional_per_contract <= 0.0:
            return 0
        return int(equity * self.fraction / notional_per_contract)

    def describe(self) -> SpecDict:
        return {"rule": "equity_fraction", "fraction": self.fraction}


@dataclass(frozen=True, slots=True)
class RiskFraction:
    """Taille par risque : une fraction de l'equity perdue si le stop touche.

    `risque_par_contrat = atr_multiple * ATR(window) * multiplicateur`
    `contracts = trunc(equity * fraction / risque_par_contrat)`

    L'ATR est evalue sur le `Context`, donc uniquement sur des barres closes.
    Le dimensionnement herite ainsi de la garantie anti-look-ahead sans regle
    supplementaire.

    Suppose que le stop est place a `atr_multiple` ATR de l'entree. Si la
    strategie place son stop ailleurs, la taille ne correspond pas au risque
    annonce - c'est a l'utilisateur de faire coincider les deux.
    """

    fraction: float
    atr_window: int = 14
    atr_multiple: float = 2.0

    def __post_init__(self) -> None:
        if not 0.0 < self.fraction < 1.0:
            raise ConfigurationError(f"fraction doit etre dans ]0, 1[, recu {self.fraction}")
        if self.atr_window < 1:
            raise ConfigurationError(f"atr_window doit etre >= 1, recu {self.atr_window}")
        if self.atr_multiple <= 0.0:
            raise ConfigurationError(f"atr_multiple doit etre > 0, recu {self.atr_multiple}")

    @property
    def warmup_bars(self) -> int:
        return self.atr_window + 1

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        atr = bind_primitive("atr@1", window=self.atr_window)(ctx)
        if atr is None or atr <= 0.0:
            return 0
        risk_per_contract = self.atr_multiple * atr * spec.multiplier
        if risk_per_contract <= 0.0:
            return 0
        return int(equity * self.fraction / risk_per_contract)

    def describe(self) -> SpecDict:
        return {
            "rule": "risk_fraction",
            "fraction": self.fraction,
            "atr_window": self.atr_window,
            "atr_multiple": self.atr_multiple,
        }


@dataclass(frozen=True, slots=True)
class VolatilityTarget:
    """Taille inversement proportionnelle a la volatilite realisee.

        facteur   = min(vol_max_multiple, vol_target / volatilite_realisee)
        contracts = trunc(contracts_de_base * facteur)

    A distinguer de `RiskFraction`, avec laquelle on la confond souvent : celle-ci
    dimensionne sur la distance au stop, donc sur le risque d'UN trade. Celle-la
    vise une volatilite de PORTEFEUILLE et ne depend d'aucun stop. Ce sont deux
    idees differentes, pas deux reglages de la meme.

    `vol_target` est un ecart-type **PAR BARRE**, jamais annualise. Le socle
    refuse les facteurs d'annualisation supposes : le pas d'annualisation est
    mesure sur l'echantillon, apres coup, et une regle de dimensionnement ne le
    connait pas au moment de decider. Exprimer la cible en annuel obligerait a
    en supposer un - c'est exactement l'erreur que le ledger consigne comme
    gonflant le Sharpe d'un facteur deux sur des donnees minute.

    Piege a connaitre : le nombre de contrats est TRONQUE, comme dans toutes les
    autres regles. Avec `contracts: 1` et un facteur d'echelle inferieur a 1,
    `int(1 * 0.9)` vaut zero - la strategie ne prend alors jamais position, sans
    erreur. Choisir une base assez grande pour que la troncature ne mange pas
    tout le signal : `contracts: 10` donne dix paliers, `contracts: 100` en
    donne cent.

    Pas de decalage explicite : le `Context` n'expose que des barres CLOSES, et
    l'execution est retardee d'au moins une barre (`lag_bars >= 1`). Lire la
    barre courante n'est donc pas lire son propre resultat - c'est la meme
    garantie dont `RiskFraction` herite pour son ATR, sans regle supplementaire.
    """

    vol_target: float
    vol_window: int = 20
    vol_max_multiple: float = 4.0
    contracts_base: int = 1

    def __post_init__(self) -> None:
        if self.vol_target <= 0.0:
            raise ConfigurationError(f"vol_target doit etre > 0, recu {self.vol_target}")
        if self.vol_window < 2:
            raise ConfigurationError(
                f"vol_window doit etre >= 2, recu {self.vol_window} : "
                f"un seul rendement n'a pas de dispersion"
            )
        if self.vol_max_multiple <= 0.0:
            raise ConfigurationError(
                f"vol_max_multiple doit etre > 0, recu {self.vol_max_multiple}"
            )
        if self.contracts_base < 1:
            raise ConfigurationError(
                f"contracts doit etre >= 1, recu {self.contracts_base}"
            )

    @property
    def warmup_bars(self) -> int:
        return self.vol_window + 1

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        """Zero quand la volatilite n'est pas estimable.

        Meme convention que `RiskFraction` : une taille non calculable ne
        devient pas une taille par defaut. Le compteur `n_dropped_sizing` rend
        l'evenement visible plutot que silencieux.
        """
        realisee = bind_primitive("volatility@1", window=self.vol_window, log=True)(ctx)
        if realisee is None or realisee <= 0.0:
            return 0
        facteur = min(self.vol_max_multiple, self.vol_target / realisee)
        return int(self.contracts_base * facteur)

    def describe(self) -> SpecDict:
        return {
            "rule": "vol_target",
            "vol_target": self.vol_target,
            "vol_window": self.vol_window,
            "vol_max_multiple": self.vol_max_multiple,
            "contracts": self.contracts_base,
        }


@dataclass(slots=True)
class RiskStats:
    n_dropped_sizing: int = 0
    n_rejected_margin: int = 0
    n_warned_margin: int = 0
    n_rejected_gross_cap: int = 0
    n_reduce_only_dropped: int = 0

    def describe(self) -> SpecDict:
        return {
            "n_dropped_sizing": self.n_dropped_sizing,
            "n_rejected_margin": self.n_rejected_margin,
            "n_warned_margin": self.n_warned_margin,
            "n_rejected_gross_cap": self.n_rejected_gross_cap,
            "n_reduce_only_dropped": self.n_reduce_only_dropped,
        }


class RiskManager:
    """Se place entre la strategie et l'execution.

    Trois responsabilites, dans cet ordre :

      1. neutraliser les ordres `reduce_only` sans position a reduire ;
      2. dimensionner les entrees ;
      3. refuser ce qui depasse la marge disponible ou le plafond de contrats.
    """

    __slots__ = ("_warnings", "margin_policy", "max_gross_contracts", "sizing", "stats")

    def __init__(
        self,
        *,
        sizing: SizingRule | None = None,
        margin_policy: MarginPolicy = MarginPolicy.REJECT,
        max_gross_contracts: int | None = None,
    ) -> None:
        if max_gross_contracts is not None and max_gross_contracts < 1:
            raise ConfigurationError(
                f"max_gross_contracts doit etre >= 1, recu {max_gross_contracts}"
            )
        self.sizing = sizing
        self.margin_policy = margin_policy
        self.max_gross_contracts = max_gross_contracts
        self.stats = RiskStats()
        self._warnings: list[str] = []

    def reset(self) -> None:
        self.stats = RiskStats()
        self._warnings = []

    @property
    def warmup_bars(self) -> int:
        return 0 if self.sizing is None else self.sizing.warmup_bars

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    def prepare(
        self, order: Order, ctx: Context, portfolio: Portfolio, marks: dict[str, float]
    ) -> Order | None:
        """Retourne l'ordre a soumettre, eventuellement redimensionne, ou `None`."""
        spec = portfolio.spec_of(order.symbol)

        if order.reduce_only:
            return self.revalidate_reduction(order, portfolio.quantity_of(order.symbol))

        sized = self._size(order, ctx, spec, portfolio, marks)
        if sized is None:
            return None
        return self._check_limits(sized, spec, portfolio, marks)

    # -- etapes ------------------------------------------------------------

    def revalidate_reduction(self, order: Order, held: int) -> Order | None:
        """Un `reduce_only` ne peut que reduire : sans position, il disparait.

        C'est ce qui empeche l'erreur classique du backtest a regles - une
        sortie qui, faute de position, ouvre une position inverse.
        """
        if held == 0 or (held > 0) == (order.side.sign > 0):
            self.stats.n_reduce_only_dropped += 1
            return None
        capped = min(order.quantity, abs(held))
        if capped == order.quantity:
            return order
        return Order(
            symbol=order.symbol,
            side=order.side,
            quantity=capped,
            order_type=order.order_type,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            reduce_only=True,
            tag=order.tag,
        )

    def _size(
        self,
        order: Order,
        ctx: Context,
        spec: InstrumentSpec,
        portfolio: Portfolio,
        marks: dict[str, float],
    ) -> Order | None:
        if self.sizing is None:
            return order
        equity = portfolio.equity(marks)
        quantity = self.sizing.contracts(ctx, spec, equity, ctx.bar.close)
        if quantity < 1:
            self.stats.n_dropped_sizing += 1
            return None
        if quantity == order.quantity:
            return order
        return Order(
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            order_type=order.order_type,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            tag=order.tag,
        )

    def _check_limits(
        self,
        order: Order,
        spec: InstrumentSpec,
        portfolio: Portfolio,
        marks: dict[str, float],
    ) -> Order | None:
        held = portfolio.quantity_of(order.symbol)
        projected = abs(held + order.signed_quantity)

        if self.max_gross_contracts is not None and projected > self.max_gross_contracts:
            self.stats.n_rejected_gross_cap += 1
            return None

        added_margin = (projected - abs(held)) * spec.initial_margin
        if added_margin <= 0.0:
            return order

        required = portfolio.margin_required() + added_margin
        available = portfolio.equity(marks)
        if required <= available:
            return order

        if self.margin_policy is MarginPolicy.REJECT:
            self.stats.n_rejected_margin += 1
            return None

        self.stats.n_warned_margin += 1
        if len(self._warnings) < 20:
            self._warnings.append(
                f"marge requise {required:.0f} > equity {available:.0f} sur {order.symbol} "
                f"(politique 'warn' : l'ordre passe quand meme)"
            )
        return order

    def describe(self) -> SpecDict:
        return {
            "sizing": None if self.sizing is None else self.sizing.describe(),
            "margin_policy": self.margin_policy.value,
            "max_gross_contracts": self.max_gross_contracts,
            "stats": self.stats.describe(),
        }
