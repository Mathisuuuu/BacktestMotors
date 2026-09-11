"""Boucle transversale : plusieurs instruments, rebalancement periodique.

Second mode de runner, annonce dans `docs/execution-model.md` §7. Il partage le
portefeuille, le modele d'execution, le `Context` et les types d'ordres du mode
mono-instrument ; seule la boucle differe. Forcer une abstraction unique aurait
mal servi les deux familles : l'une decide a chaque barre sur un instrument,
l'autre decide a quelques dates sur un panier.

Ordre d'une ligne, identique en esprit a celui du mono-instrument
(`docs/no-lookahead.md` §3) :

    1. le feed avance a la ligne k
    2. protections armees, pour les instruments qui cotent
    3. ordres dus, pour les instruments qui cotent
    4. marquage + invariante, sur les marques des seuls instruments cotants
    5. on_rebalance si le calendrier le dit -> ordres dus a k + lag
    6. enregistrement

Instruments absents
-------------------
Un instrument peut ne pas coter a une ligne donnee (calendrier UNION, cf.
`loader.build_panel`). Trois consequences, toutes deliberees :

  - la strategie ne le voit pas : `mctx.symbols` ne le liste pas ;
  - une ENTREE sur un instrument absent est abandonnee - elle ne pourrait etre
    ni dimensionnee ni evaluee ;
  - une SORTIE sur un instrument absent est conservee et reportee jusqu'a la
    premiere ligne ou l'instrument cote de nouveau. C'est le seul moyen de
    fermer une position devenue orpheline (`docs/no-lookahead.md` §4.2) ;
    l'evenement est compte dans `n_forced_liquidations`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rsl.data.feed import MultiContext, PanelFeed
from rsl.data.schema import Bar, InstrumentSpec, Panel
from rsl.engine.execution import ExecutionEngine, IntrabarPriority, assert_within_bar
from rsl.engine.portfolio import EquityRecorder, Portfolio
from rsl.engine.risk import RiskManager
from rsl.engine.runner import (
    NS_PER_SECOND,
    RunConfig,
    SpecDict,
    _PendingOrder,
    _Protection,
    _SinceEntry,
    position_state,
    track_positions,
    would_trigger,
)
from rsl.errors import ConfigurationError
from rsl.orders import Fill, Order, OrderType, Side
from rsl.strategies.base import CrossSectionalStrategy


@runtime_checkable
class RebalanceSchedule(Protocol):
    """Decide a quelles lignes du panneau la strategie est consultee.

    Le calendrier appartient au runner, pas a la strategie : c'est ce qui
    permet de rejouer la meme strategie a une autre frequence sans la modifier.
    """

    def is_rebalance(self, row: int) -> bool: ...

    def describe(self) -> SpecDict: ...


@dataclass(frozen=True, slots=True)
class EveryRow:
    """Rebalancement a chaque ligne.

    Sur un panneau deja reechantillonne au mois, c'est le cas usuel : une ligne
    y est un mois revolu.
    """

    def is_rebalance(self, row: int) -> bool:
        return True

    def describe(self) -> SpecDict:
        return {"schedule": "every_row"}


@dataclass(frozen=True, slots=True)
class EveryNRows:
    """Une ligne sur `n`, a partir de `offset`."""

    n: int
    offset: int = 0

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ConfigurationError(f"n doit etre >= 1, recu {self.n}")
        if self.offset < 0:
            raise ConfigurationError(f"offset doit etre >= 0, recu {self.offset}")

    def is_rebalance(self, row: int) -> bool:
        return row >= self.offset and (row - self.offset) % self.n == 0

    def describe(self) -> SpecDict:
        return {"schedule": "every_n_rows", "n": self.n, "offset": self.offset}


@dataclass(slots=True)
class CrossSectionalCounters:
    n_orders_submitted: int = 0
    n_orders_dropped_risk: int = 0
    n_orders_dropped_absent: int = 0
    n_orders_expired_gap: int = 0
    n_orders_cancelled_unfilled: int = 0
    n_protection_fills: int = 0
    n_intrabar_ambiguous: int = 0
    n_rebalances: int = 0
    n_rows: int = 0
    warmup_rows: int = 0
    n_forced_liquidations: int = 0

    def describe(self) -> SpecDict:
        return {
            "n_orders_submitted": self.n_orders_submitted,
            "n_orders_dropped_risk": self.n_orders_dropped_risk,
            "n_orders_dropped_absent": self.n_orders_dropped_absent,
            "n_orders_expired_gap": self.n_orders_expired_gap,
            "n_orders_cancelled_unfilled": self.n_orders_cancelled_unfilled,
            "n_protection_fills": self.n_protection_fills,
            "n_intrabar_ambiguous": self.n_intrabar_ambiguous,
            "n_rebalances": self.n_rebalances,
            "n_rows": self.n_rows,
            "warmup_rows": self.warmup_rows,
            "n_forced_liquidations": self.n_forced_liquidations,
        }


@dataclass(slots=True)
class CrossSectionalRunResult:
    """Resultat d'un run transversal."""

    symbols: tuple[str, ...]
    equity: EquityRecorder
    fills: tuple[Fill, ...]
    portfolio: Portfolio
    counters: CrossSectionalCounters
    config: RunConfig
    strategy_spec: SpecDict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    stale_bars: dict[str, int] = field(default_factory=dict)
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
            "symbols": list(self.symbols),
            "n_equity_points": len(self.equity),
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "n_fills": len(self.fills),
            "counters": self.counters.describe(),
            "execution_stats": dict(self.execution_stats),
            "portfolio": self.portfolio.describe(),
            "config": self.config.describe(),
            "strategy": self.strategy_spec,
            "stale_bars": dict(self.stale_bars),
            "warnings": list(self.warnings),
        }


class CrossSectionalRunner:
    """Execute une `CrossSectionalStrategy` sur un panneau multi-instruments."""

    __slots__ = ("_execution", "_next_order_id", "config", "panel", "risk", "schedule", "specs")

    def __init__(
        self,
        panel: Panel,
        specs: dict[str, InstrumentSpec],
        config: RunConfig,
        *,
        risk: RiskManager | None = None,
        schedule: RebalanceSchedule | None = None,
    ) -> None:
        missing = sorted(set(panel.symbols) - set(specs))
        if missing:
            raise ConfigurationError(f"specification manquante pour : {', '.join(missing)}")
        self.panel = panel
        self.specs = {s: specs[s] for s in panel.symbols}
        self.config = config
        self.risk = risk or RiskManager()
        self.schedule: RebalanceSchedule = schedule or EveryRow()
        self._execution = ExecutionEngine(config.execution)
        self._next_order_id = 0

    def run(self, strategy: CrossSectionalStrategy) -> CrossSectionalRunResult:
        """Un run complet. Deux appels identiques produisent des resultats identiques."""
        strategy.reset()
        self.risk.reset()
        self._execution.reset()
        self._next_order_id = 0

        warmup = max(
            strategy.warmup_bars, self.risk.warmup_bars, self.config.min_warmup_bars
        )
        portfolio = Portfolio(self.config.initial_cash, self.specs)
        recorder = EquityRecorder()
        counters = CrossSectionalCounters(warmup_rows=warmup)

        pending: list[_PendingOrder] = []
        protections: list[_Protection] = []
        fills: list[Fill] = []
        tracking: dict[str, _SinceEntry] = {}

        for mctx in PanelFeed(self.panel, warmup_rows=warmup, stop=self.config.stop):
            row = mctx._row
            bars = {symbol: mctx[symbol].bar for symbol in mctx.symbols}
            portfolio.begin_bar()

            fills_before = len(fills)
            self._fire_protections(protections, bars, row, portfolio, fills, counters)
            self._fill_due_orders(pending, bars, row, portfolio, fills, protections, counters)

            marks = {symbol: bar.close for symbol, bar in bars.items()}
            equity = portfolio.end_bar(marks, check=self.config.check_invariant)

            for fill in fills[fills_before:]:
                strategy.on_fill(fill)

            track_positions(tracking, portfolio, bars, row)
            for symbol in bars:
                mctx[symbol]._set_position(
                    position_state(tracking, portfolio, symbol, row)
                )

            if self.schedule.is_rebalance(row):
                counters.n_rebalances += 1
                self._submit(
                    strategy.on_rebalance(mctx), mctx, row, portfolio, pending, counters
                )

            recorder.record(
                ts_ns=int(self.panel.ts_close[row]),
                equity=equity,
                cash=portfolio.cash,
                gross_contracts=sum(abs(p.quantity) for p in portfolio.positions.values()),
            )
            counters.n_rows += 1

        counters.n_orders_cancelled_unfilled += len(pending)
        strategy.on_finish()

        return CrossSectionalRunResult(
            symbols=self.panel.symbols,
            equity=recorder,
            fills=tuple(fills),
            portfolio=portfolio,
            counters=counters,
            config=self.config,
            strategy_spec=strategy.describe(),
            warnings=self.risk.warnings,
            stale_bars={s: self.panel.n_stale(s) for s in self.panel.symbols},
            execution_stats=self._execution.stats.describe(),
        )

    # -- etapes ------------------------------------------------------------

    def _fire_protections(
        self,
        protections: list[_Protection],
        bars: dict[str, Bar],
        row: int,
        portfolio: Portfolio,
        fills: list[Fill],
        counters: CrossSectionalCounters,
    ) -> None:
        for protection in list(protections):
            if protection.armed_from > row or protection.symbol not in bars:
                continue
            held = portfolio.quantity_of(protection.symbol)
            if held == 0 or (held > 0) != (protection.direction > 0):
                protections.remove(protection)
                continue

            bar = bars[protection.symbol]
            side = Side.SELL if protection.direction > 0 else Side.BUY
            quantity = min(protection.quantity, abs(held))
            chosen = self._pick_protection(protection, bar, side, quantity, counters)
            if chosen is None:
                continue

            fill = self._execute(chosen, bar, row, portfolio, fills)
            if fill is not None:
                counters.n_protection_fills += 1
                protection.quantity -= fill.quantity
                if protection.quantity <= 0 or portfolio.quantity_of(protection.symbol) == 0:
                    protections.remove(protection)

    def _pick_protection(
        self,
        protection: _Protection,
        bar: Bar,
        side: Side,
        quantity: int,
        counters: CrossSectionalCounters,
    ) -> Order | None:
        stop_order = (
            Order(
                symbol=protection.symbol,
                side=side,
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
                side=side,
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
            pessimistic = (
                self.config.execution.intrabar_priority is IntrabarPriority.PESSIMISTIC
            )
            return stop_order if pessimistic else target_order
        if stop_hit:
            return stop_order
        if target_hit:
            return target_order
        return None

    def _fill_due_orders(
        self,
        pending: list[_PendingOrder],
        bars: dict[str, Bar],
        row: int,
        portfolio: Portfolio,
        fills: list[Fill],
        protections: list[_Protection],
        counters: CrossSectionalCounters,
    ) -> None:
        due = sorted((p for p in pending if p.due_index <= row), key=lambda p: p.order_id)
        for entry in due:
            bar = bars.get(entry.order.symbol)
            if bar is None:
                # L'instrument ne cote pas : l'ordre attend la prochaine ligne ou
                # il cotera. L'annuler ici laisserait une position sur un
                # instrument mort sans jamais pouvoir la fermer.
                continue

            pending.remove(entry)
            was_late = entry.due_index < row

            gap = self.config.execution.max_fill_gap
            if gap is not None:
                elapsed = int(bar.ts_event.timestamp() * NS_PER_SECOND) - entry.submitted_ts_ns
                if elapsed > gap.total_seconds() * NS_PER_SECOND:
                    counters.n_orders_expired_gap += 1
                    continue

            order = entry.order
            if order.reduce_only:
                revalidated = self.risk.revalidate_reduction(
                    order, portfolio.quantity_of(order.symbol)
                )
                if revalidated is None:
                    counters.n_orders_dropped_risk += 1
                    continue
                order = revalidated
                if was_late:
                    counters.n_forced_liquidations += 1

            fill = self._execute(order, bar, row, portfolio, fills, order_id=entry.order_id)
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
                        armed_from=row + 1,
                        tag=order.tag,
                    )
                )

    def _execute(
        self,
        order: Order,
        bar: Bar,
        row: int,
        portfolio: Portfolio,
        fills: list[Fill],
        *,
        order_id: int | None = None,
    ) -> Fill | None:
        if order_id is None:
            order_id = self._next_order_id
            self._next_order_id += 1
        fill = self._execution.try_fill(
            order, bar=bar, bar_index=row, spec=self.specs[order.symbol], order_id=order_id
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
        mctx: MultiContext,
        row: int,
        portfolio: Portfolio,
        pending: list[_PendingOrder],
        counters: CrossSectionalCounters,
    ) -> None:
        assert isinstance(orders, (list, tuple))
        present = set(mctx.symbols)
        marks = {s: mctx[s].bar.close for s in mctx.symbols}
        due_index = row + self.config.execution.execution_lag
        submitted_ts_ns = int(mctx.ts.timestamp() * NS_PER_SECOND)

        for order in orders:
            assert isinstance(order, Order)
            counters.n_orders_submitted += 1
            if order.symbol not in self.specs:
                raise ConfigurationError(
                    f"la strategie a emis un ordre sur '{order.symbol}', hors du panneau"
                )

            if order.symbol not in present:
                if not order.reduce_only:
                    counters.n_orders_dropped_absent += 1
                    continue
                prepared: Order | None = order
            else:
                prepared = self.risk.prepare(order, mctx[order.symbol], portfolio, marks)

            if prepared is None:
                counters.n_orders_dropped_risk += 1
                continue

            pending.append(
                _PendingOrder(
                    order_id=self._next_order_id,
                    order=prepared,
                    due_index=due_index,
                    submitted_ts_ns=submitted_ts_ns,
                )
            )
            self._next_order_id += 1
