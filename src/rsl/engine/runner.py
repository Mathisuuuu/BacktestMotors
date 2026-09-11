"""Boucle principale, mono-instrument.

L'ordre des etapes d'une iteration est celui de `docs/no-lookahead.md` §3, et
il n'est pas negociable :

    1. le feed avance le curseur      -> la barre i est close
    2. protections armees             -> evaluees contre OHLC(i)
    3. ordres dus                     -> remplis contre OHLC(i)
    4. marquage + invariante          -> equity(i) avec close(i)
    5. on_bar(ctx)                    -> nouveaux ordres, dus a i + lag
    6. enregistrement

`on_bar` est en DERNIER. Rien de ce que la strategie retourne ne peut affecter
les etapes 1 a 4 de la meme iteration : c'est ce qui rend le lag structurel
plutot que conventionnel.

Les protections passent AVANT les fills, et ce n'est pas un detail : un stop
attache a un ordre rempli a la barre `i` ne doit pas etre evalue contre cette
meme barre `i`. A l'etape 2, ce stop n'existe pas encore.

Boucle event-driven, pas de vectorisation : a cette etape la correction prime
sur la vitesse.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rsl.data.feed import BarContext, BarFeed
from rsl.data.schema import FLAT, Bar, BarStore, InstrumentSpec, PositionState
from rsl.engine.execution import (
    ExecutionConfig,
    ExecutionEngine,
    IntrabarPriority,
    assert_within_bar,
)
from rsl.engine.portfolio import EquityRecorder, Portfolio
from rsl.engine.risk import RiskManager
from rsl.errors import ConfigurationError
from rsl.orders import Fill, Order, OrderType, Side
from rsl.strategies.base import Strategy

SpecDict = dict[str, object]
NS_PER_SECOND = 1_000_000_000


@dataclass(slots=True)
class _SinceEntry:
    """Ce que seul le runner peut savoir : depuis quand, et jusqu'ou.

    Le portefeuille connait la quantite et le prix moyen ; il ne voit pas les
    barres. Les extremes traverses depuis l'entree ne peuvent donc etre
    accumules que par la boucle, barre apres barre.
    """

    opened_bar: int
    high: float
    low: float


def track_positions(
    tracking: dict[str, _SinceEntry],
    portfolio: Portfolio,
    bars: dict[str, Bar],
    index: int,
) -> None:
    """Met a jour le suivi apres les executions de la barre.

    Appele APRES les fills : une position ouverte a la barre `i` compte `i`
    comme sa barre d'entree, donc `bars_held = 0` sur cette barre-la.
    """
    for symbol, bar in bars.items():
        held = portfolio.quantity_of(symbol)
        if held == 0:
            tracking.pop(symbol, None)
            continue
        current = tracking.get(symbol)
        if current is None:
            tracking[symbol] = _SinceEntry(opened_bar=index, high=bar.high, low=bar.low)
        else:
            current.high = max(current.high, bar.high)
            current.low = min(current.low, bar.low)


def position_state(
    tracking: dict[str, _SinceEntry], portfolio: Portfolio, symbol: str, index: int
) -> PositionState:
    """Assemble l'etat expose a la strategie. Rien qui vienne d'apres `index`."""
    held = portfolio.quantity_of(symbol)
    if held == 0:
        return FLAT
    since = tracking.get(symbol)
    if since is None:
        return PositionState(quantity=held)
    return PositionState(
        quantity=held,
        bars_held=index - since.opened_bar,
        entry_price=portfolio.positions[symbol].avg_entry,
        high_since_entry=since.high,
        low_since_entry=since.low,
    )


def would_trigger(order: Order, bar: Bar) -> bool:
    """Le niveau de l'ordre est-il atteint dans cette barre ?

    Separe de `ExecutionEngine.try_fill` pour pouvoir arbitrer entre un stop et
    un take-profit tous deux atteignables sans consommer de compteur
    d'execution : les deux sont testes, un seul est execute.

    Partage par les deux runners.
    """
    match order.order_type:
        case OrderType.STOP:
            stop = order.stop_price
            assert stop is not None
            return bar.high >= stop if order.side is Side.BUY else bar.low <= stop
        case OrderType.LIMIT:
            limit = order.limit_price
            assert limit is not None
            return bar.low <= limit if order.side is Side.BUY else bar.high >= limit
        case OrderType.MARKET:
            return True


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Parametres d'un run. `execution` n'a pas de defaut : voir `execution.py`."""

    initial_cash: float
    execution: ExecutionConfig
    liquidate_at_end: bool = False
    check_invariant: bool = True
    stop: int | None = None
    min_warmup_bars: int = 0
    """Plancher de prechauffage, en plus de celui exigé par la strategie.

    Sert au walk-forward : une fenetre de test qui commence a la barre
    `k` se decrit comme `min_warmup_bars=k`. Les barres precedentes
    alimentent l'historique sans etre negociees - c'est exactement ce que
    veut dire "apprentissage" quand on ne cherche aucun parametre.
    """

    def __post_init__(self) -> None:
        if self.initial_cash <= 0.0:
            raise ConfigurationError(f"initial_cash doit etre > 0, recu {self.initial_cash}")
        if self.min_warmup_bars < 0:
            raise ConfigurationError(
                f"min_warmup_bars doit etre >= 0, recu {self.min_warmup_bars}"
            )

    def describe(self) -> SpecDict:
        return {
            "initial_cash": self.initial_cash,
            "liquidate_at_end": self.liquidate_at_end,
            "check_invariant": self.check_invariant,
            "stop": self.stop,
            "min_warmup_bars": self.min_warmup_bars,
            "execution": self.execution.describe(),
        }


@dataclass(slots=True)
class _PendingOrder:
    order_id: int
    order: Order
    due_index: int
    submitted_ts_ns: int


@dataclass(slots=True)
class _Protection:
    """Stop-loss et take-profit attaches a une position ouverte.

    Persistants, contrairement aux ordres : actifs jusqu'a execution ou
    fermeture de la position (`docs/execution-model.md` §3.2).
    """

    symbol: str
    direction: int
    quantity: int
    stop_loss: float | None
    take_profit: float | None
    armed_from: int
    tag: str


@dataclass(slots=True)
class RunCounters:
    n_orders_submitted: int = 0
    n_orders_dropped_risk: int = 0
    n_orders_expired_gap: int = 0
    n_orders_cancelled_unfilled: int = 0
    n_protection_fills: int = 0
    n_intrabar_ambiguous: int = 0
    n_bars: int = 0
    warmup_bars: int = 0
    terminal_liquidation: bool = False

    def describe(self) -> SpecDict:
        return {
            "n_orders_submitted": self.n_orders_submitted,
            "n_orders_dropped_risk": self.n_orders_dropped_risk,
            "n_orders_expired_gap": self.n_orders_expired_gap,
            "n_orders_cancelled_unfilled": self.n_orders_cancelled_unfilled,
            "n_protection_fills": self.n_protection_fills,
            "n_intrabar_ambiguous": self.n_intrabar_ambiguous,
            "n_bars": self.n_bars,
            "warmup_bars": self.warmup_bars,
            "terminal_liquidation": self.terminal_liquidation,
        }


@dataclass(slots=True)
class RunResult:
    """Tout ce qu'un run produit. Serialisable, comparable, hashable."""

    symbol: str
    equity: EquityRecorder
    fills: tuple[Fill, ...]
    portfolio: Portfolio
    counters: RunCounters
    config: RunConfig
    strategy_spec: SpecDict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    execution_stats: SpecDict = field(default_factory=dict)
    """Compteurs du moteur d'execution : fills, slippage borne, ordres a limite
    non touches, stops non declenches.

    Bloc SEPARE de `counters`, et non fusionne avec lui, parce que `counters`
    entre dans l'empreinte de resultat : l'y ajouter changerait l'empreinte de
    tous les runs deja archives, pour une information qui decrit le moteur et
    non la decision."""


    @property
    def final_equity(self) -> float:
        return self.equity.equity[-1] if self.equity.equity else self.config.initial_cash

    @property
    def total_return(self) -> float:
        return self.final_equity / self.config.initial_cash - 1.0

    def describe(self) -> SpecDict:
        return {
            "symbol": self.symbol,
            "n_equity_points": len(self.equity),
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "n_fills": len(self.fills),
            "counters": self.counters.describe(),
            "execution_stats": dict(self.execution_stats),
            "portfolio": self.portfolio.describe(),
            "config": self.config.describe(),
            "strategy": self.strategy_spec,
            "warnings": list(self.warnings),
        }


class SingleAssetRunner:
    """Exécute une `Strategy` sur un instrument, barre par barre."""

    __slots__ = ("_execution", "_next_order_id", "config", "risk", "spec", "store")

    def __init__(
        self,
        store: BarStore,
        spec: InstrumentSpec,
        config: RunConfig,
        *,
        risk: RiskManager | None = None,
    ) -> None:
        if store.symbol != spec.symbol:
            raise ConfigurationError(
                f"magasin '{store.symbol}' et specification '{spec.symbol}' ne concordent pas"
            )
        self.store = store
        self.spec = spec
        self.config = config
        self.risk = risk or RiskManager()
        self._execution = ExecutionEngine(config.execution)
        self._next_order_id = 0

    def run(self, strategy: Strategy) -> RunResult:
        """Un run complet. Deux appels identiques produisent des resultats identiques."""
        strategy.reset()
        self.risk.reset()
        self._execution.reset()
        self._next_order_id = 0

        warmup = max(
            strategy.warmup_bars, self.risk.warmup_bars, self.config.min_warmup_bars
        )
        portfolio = Portfolio(self.config.initial_cash, {self.spec.symbol: self.spec})
        recorder = EquityRecorder()
        counters = RunCounters(warmup_bars=warmup)

        pending: list[_PendingOrder] = []
        protections: list[_Protection] = []
        fills: list[Fill] = []
        tracking: dict[str, _SinceEntry] = {}
        started = False
        last_marks: dict[str, float] = {}

        feed = BarFeed(self.store, warmup_bars=warmup, stop=self.config.stop)
        for ctx in feed:
            index = ctx.n_bars_seen - 1
            bar = ctx.bar
            portfolio.begin_bar()

            fills_before = len(fills)
            self._fire_protections(protections, bar, index, portfolio, fills, counters)
            self._fill_due_orders(pending, bar, index, portfolio, fills, protections, counters)

            marks = {self.spec.symbol: bar.close}
            last_marks = marks
            equity = portfolio.end_bar(marks, check=self.config.check_invariant)

            for fill in fills[fills_before:]:
                strategy.on_fill(fill)

            track_positions(tracking, portfolio, {self.spec.symbol: bar}, index)
            ctx._set_position(
                position_state(tracking, portfolio, self.spec.symbol, index)
            )

            if not started:
                strategy.on_start(ctx)
                started = True

            self._submit(strategy.on_bar(ctx), ctx, index, portfolio, pending, counters, marks)

            recorder.record(
                ts_ns=int(bar.ts_close.timestamp() * NS_PER_SECOND),
                equity=equity,
                cash=portfolio.cash,
                gross_contracts=abs(portfolio.quantity_of(self.spec.symbol)),
            )
            counters.n_bars += 1

        counters.n_orders_cancelled_unfilled += len(pending)
        strategy.on_finish()

        if self.config.liquidate_at_end:
            self._liquidate(portfolio, recorder, fills, counters, last_marks)

        return RunResult(
            symbol=self.spec.symbol,
            equity=recorder,
            fills=tuple(fills),
            portfolio=portfolio,
            counters=counters,
            config=self.config,
            strategy_spec=strategy.describe(),
            warnings=self.risk.warnings,
            execution_stats=self._execution.stats.describe(),
        )

    # -- etapes ------------------------------------------------------------

    def _fire_protections(
        self,
        protections: list[_Protection],
        bar: Bar,
        index: int,
        portfolio: Portfolio,
        fills: list[Fill],
        counters: RunCounters,
    ) -> None:
        """Evalue les stops et take-profits armes contre la barre courante."""
        for protection in list(protections):
            if protection.armed_from > index:
                continue
            held = portfolio.quantity_of(protection.symbol)
            if held == 0 or (held > 0) != (protection.direction > 0):
                protections.remove(protection)
                continue

            closing_side = Side.SELL if protection.direction > 0 else Side.BUY
            quantity = min(protection.quantity, abs(held))

            stop_order = (
                Order(
                    symbol=protection.symbol,
                    side=closing_side,
                    quantity=quantity,
                    order_type=OrderType.STOP,
                    stop_price=protection.stop_loss,
                    reduce_only=True,
                    tag=f"{protection.tag}:stop_loss",
                )
                if protection.stop_loss is not None
                else None
            )
            target_order = (
                Order(
                    symbol=protection.symbol,
                    side=closing_side,
                    quantity=quantity,
                    order_type=OrderType.LIMIT,
                    limit_price=protection.take_profit,
                    reduce_only=True,
                    tag=f"{protection.tag}:take_profit",
                )
                if protection.take_profit is not None
                else None
            )

            stop_hit = stop_order is not None and would_trigger(stop_order, bar)
            target_hit = target_order is not None and would_trigger(target_order, bar)

            if stop_hit and target_hit:
                counters.n_intrabar_ambiguous += 1
                pessimistic = self.config.execution.intrabar_priority is (
                    IntrabarPriority.PESSIMISTIC
                )
                chosen = stop_order if pessimistic else target_order
            elif stop_hit:
                chosen = stop_order
            elif target_hit:
                chosen = target_order
            else:
                continue

            assert chosen is not None
            fill = self._execute(chosen, bar, index, portfolio, fills)
            if fill is not None:
                counters.n_protection_fills += 1
                protection.quantity -= fill.quantity
                if protection.quantity <= 0 or portfolio.quantity_of(protection.symbol) == 0:
                    protections.remove(protection)

    def _fill_due_orders(
        self,
        pending: list[_PendingOrder],
        bar: Bar,
        index: int,
        portfolio: Portfolio,
        fills: list[Fill],
        protections: list[_Protection],
        counters: RunCounters,
    ) -> None:
        due = [p for p in pending if p.due_index <= index]
        for entry in due:
            pending.remove(entry)

            gap = self.config.execution.max_fill_gap
            if gap is not None:
                elapsed_ns = int(bar.ts_event.timestamp() * NS_PER_SECOND) - entry.submitted_ts_ns
                if elapsed_ns > gap.total_seconds() * NS_PER_SECOND:
                    counters.n_orders_expired_gap += 1
                    continue

            order = entry.order
            if order.reduce_only:
                # La position a pu changer entre la soumission et le fill : on
                # revalide plutot que de laisser passer un ordre qui ouvrirait.
                revalidated = self.risk.revalidate_reduction(
                    order, portfolio.quantity_of(order.symbol)
                )
                if revalidated is None:
                    counters.n_orders_dropped_risk += 1
                    continue
                order = revalidated

            fill = self._execute(order, bar, index, portfolio, fills, order_id=entry.order_id)
            if fill is None:
                counters.n_orders_cancelled_unfilled += 1
                continue
            if order.stop_loss is not None or order.take_profit is not None:
                protections.append(
                    _Protection(
                        symbol=order.symbol,
                        direction=order.side.sign,
                        quantity=fill.quantity,
                        stop_loss=order.stop_loss,
                        take_profit=order.take_profit,
                        # Arme a partir de la barre SUIVANTE : une position ne
                        # peut pas etre protegee sur la barre qui l'a ouverte
                        # (`docs/execution-model.md` §2.2).
                        armed_from=index + 1,
                        tag=order.tag,
                    )
                )

    def _execute(
        self,
        order: Order,
        bar: Bar,
        index: int,
        portfolio: Portfolio,
        fills: list[Fill],
        *,
        order_id: int | None = None,
    ) -> Fill | None:
        if order_id is None:
            order_id = self._next_order_id
            self._next_order_id += 1
        fill = self._execution.try_fill(
            order, bar=bar, bar_index=index, spec=self.spec, order_id=order_id
        )
        if fill is None:
            return None
        assert_within_bar(fill.price, bar)
        portfolio.apply_fill(fill)
        fills.append(fill)
        return fill

    def _submit(
        self,
        orders: object,
        ctx: BarContext,
        index: int,
        portfolio: Portfolio,
        pending: list[_PendingOrder],
        counters: RunCounters,
        marks: dict[str, float],
    ) -> None:
        assert isinstance(orders, (list, tuple))
        for order in orders:
            assert isinstance(order, Order)
            counters.n_orders_submitted += 1
            prepared = self.risk.prepare(order, ctx, portfolio, marks)
            if prepared is None:
                counters.n_orders_dropped_risk += 1
                continue
            pending.append(
                _PendingOrder(
                    order_id=self._next_order_id,
                    order=prepared,
                    due_index=index + self.config.execution.execution_lag,
                    submitted_ts_ns=int(ctx.ts.timestamp() * NS_PER_SECOND),
                )
            )
            self._next_order_id += 1

    def _liquidate(
        self,
        portfolio: Portfolio,
        recorder: EquityRecorder,
        fills: list[Fill],
        counters: RunCounters,
        marks: dict[str, float],
    ) -> None:
        """Ferme les positions restantes a la cloture de la derniere barre.

        Commodite de REPORTING, pas action negociable : une strategie ne sait
        pas que la barre courante est la derniere (`docs/no-lookahead.md` §2.2,
        regle 4). C'est donc une decision du runner, desactivee par defaut, et
        signalee par `counters.terminal_liquidation`.

        Le dernier point de la courbe est remplace, pas duplique : liquider au
        prix de marque ne change l'equity que des frais.
        """
        held = portfolio.quantity_of(self.spec.symbol)
        if held == 0 or not recorder.equity:
            return

        mark = marks.get(self.spec.symbol)
        if mark is None:
            return

        counters.terminal_liquidation = True
        index = counters.n_bars - 1
        portfolio.begin_bar()
        order = Order(
            symbol=self.spec.symbol,
            side=Side.SELL if held > 0 else Side.BUY,
            quantity=abs(held),
            reduce_only=True,
            tag="terminal_liquidation",
        )
        fill = Fill(
            order_id=self._next_order_id,
            symbol=self.spec.symbol,
            side=order.side,
            quantity=order.quantity,
            price=mark,
            fee=self.config.execution.fees.fee(self.spec, order.quantity),
            slippage_cost=0.0,
            ts_ns=recorder.ts_ns[-1],
            bar_index=index,
            tag=order.tag,
        )
        self._next_order_id += 1
        portfolio.apply_fill(fill)
        fills.append(fill)
        equity = portfolio.end_bar(marks, check=self.config.check_invariant)

        recorder.equity[-1] = equity
        recorder.cash[-1] = portfolio.cash
        recorder.exposure[-1] = 0
