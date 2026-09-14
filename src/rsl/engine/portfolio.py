"""Comptabilite : positions, cash, equity marked-to-market.

L'invariante comptable du projet (`docs/execution-model.md` §6) :

    equity(t) == cash(t) + Sigma_i  qty_i * multiplier_i * (mark_i(t) - avg_entry_i)

La verifier telle quelle ne prouverait rien : si `equity` est DEFINIE comme
`cash + non realise`, l'egalite est une tautologie. Le portefeuille maintient
donc l'equity par DEUX chemins independants, et les compare a chaque barre :

  1. le chemin d'etat      : `cash + non realise`, recalcule depuis les
                             positions et les prix de marque ;
  2. le chemin incremental : `equity(t-1)` plus l'attribution de P&L de la
                             barre - variation de marque sur les positions
                             deja detenues, plus l'ecart entre marque et prix
                             de fill sur les executions de la barre, moins les
                             frais.

Les deux ne partagent aucun calcul. S'ils coincident a 1e-9 pres a chaque
barre, la comptabilite est juste. S'ils divergent, le moteur a cree ou detruit
de la valeur, et le run est arrete.

Portee de la verification : elle couvre l'ATTRIBUTION de P&L a l'interieur
d'une barre - un fill mal impute, une marque mal appliquee, des frais oublies,
une position qui bouge sans passer par `apply_fill`. Elle ne pretend pas
detecter une corruption d'etat entre deux barres : `begin_bar` rephotographie
les positions, donc les deux chemins repartent d'un etat commun. Ce n'est pas
un detecteur de sabotage, c'est un detecteur de bug comptable - et c'est ce que
le moteur peut reellement garantir.

Cash et marge de variation
--------------------------
Le `cash` n'est mouvemente que par le P&L REALISE et les frais. La marge de
variation quotidienne n'est pas balayee dans le cash. Ce choix change la
trajectoire de `cash` mais pas celle d'`equity`, et comme aucun interet n'est
modelise sur le cash en phase 1, les deux conventions donnent la meme equity
bit a bit. Celle-ci est la plus simple a tester.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rsl.data.schema import InstrumentSpec
from rsl.errors import ConfigurationError, RslError
from rsl.orders import Fill

SpecDict = dict[str, object]

INVARIANT_RTOL = 1e-9


class AccountingError(RslError, AssertionError):
    """Les deux chemins de calcul de l'equity divergent.

    N'est jamais rattrapee : un moteur qui cree ou detruit de la valeur ne
    produit pas un resultat approximatif, il ne produit pas de resultat.
    """


@dataclass(slots=True)
class Position:
    """Position ouverte sur un instrument.

    `quantity` est signee : positive a l'achat, negative a la vente.
    `avg_entry` est le prix moyen pondere des lots ouverts. Les fermetures
    partielles realisent au prix moyen - pas de FIFO fiscal, hors perimetre.
    """

    symbol: str
    quantity: int = 0
    avg_entry: float = 0.0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    def unrealized(self, spec: InstrumentSpec, mark: float) -> float:
        if self.quantity == 0:
            return 0.0
        return self.quantity * spec.multiplier * (mark - self.avg_entry)

    def margin(self, spec: InstrumentSpec, ratio: float = 1.0) -> float:
        """Marge immobilisee. `ratio` < 1 represente une marge de JOUR."""
        return abs(self.quantity) * spec.initial_margin * ratio


@dataclass(slots=True)
class ClosedTrade:
    """Aller-retour complet, du premier contrat ouvert au dernier ferme."""

    symbol: str
    opened_bar: int
    closed_bar: int
    direction: int
    max_quantity: int
    gross_pnl: float
    fees: float

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.fees

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0.0


@dataclass(slots=True)
class _OpenTrade:
    opened_bar: int
    direction: int
    max_quantity: int
    gross_pnl: float = 0.0
    fees: float = 0.0


@dataclass(slots=True)
class PortfolioStats:
    n_fills: int = 0
    fees_paid: float = 0.0
    slippage_paid: float = 0.0
    realized_pnl: float = 0.0
    turnover_notional: float = 0.0
    contracts_traded: int = 0
    max_margin_used: float = 0.0

    def describe(self) -> SpecDict:
        return {
            "n_fills": self.n_fills,
            "fees_paid": self.fees_paid,
            "slippage_paid": self.slippage_paid,
            "realized_pnl": self.realized_pnl,
            "turnover_notional": self.turnover_notional,
            "contracts_traded": self.contracts_traded,
            "max_margin_used": self.max_margin_used,
        }


class Portfolio:
    """Etat comptable d'un run. Un seul par run, remis a zero par `reset`."""

    __slots__ = (
        "_bar_fees",
        "_bar_fills",
        "_bar_open_quantities",
        "_equity_incremental",
        "_in_bar",
        "_last_marks",
        "_open_trades",
        "_specs",
        "cash",
        "closed_trades",
        "initial_cash",
        "margin_ratio",
        "positions",
        "stats",
    )

    def __init__(
        self,
        initial_cash: float,
        specs: dict[str, InstrumentSpec],
        margin_ratio: float = 1.0,
    ) -> None:
        if initial_cash <= 0.0:
            raise ConfigurationError(f"initial_cash doit etre > 0, recu {initial_cash}")
        if not specs:
            raise ConfigurationError("au moins une specification d'instrument est requise")
        if not 0.0 < margin_ratio <= 1.0:
            raise ConfigurationError(
                f"margin_ratio doit etre dans ]0, 1], recu {margin_ratio}"
            )
        self._specs = dict(specs)
        self.margin_ratio = margin_ratio
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, Position] = {s: Position(s) for s in sorted(specs)}
        self.stats = PortfolioStats()
        self.closed_trades: list[ClosedTrade] = []
        self._open_trades: dict[str, _OpenTrade] = {}
        self._equity_incremental = initial_cash
        self._last_marks: dict[str, float] = {}
        self._bar_open_quantities: dict[str, int] = {}
        self._bar_fills: list[Fill] = []
        self._bar_fees = 0.0
        self._in_bar = False

    # -- cycle de vie ------------------------------------------------------

    def reset(self) -> None:
        self.cash = self.initial_cash
        self.positions = {s: Position(s) for s in sorted(self._specs)}
        self.stats = PortfolioStats()
        self.closed_trades = []
        self._open_trades = {}
        self._equity_incremental = self.initial_cash
        self._last_marks = {}
        self._bar_open_quantities = {}
        self._bar_fills = []
        self._bar_fees = 0.0
        self._in_bar = False

    def begin_bar(self) -> None:
        """Photographie les positions avant toute execution de la barre."""
        self._bar_open_quantities = {s: p.quantity for s, p in self.positions.items()}
        self._bar_fills = []
        self._bar_fees = 0.0
        self._in_bar = True

    def end_bar(self, marks: dict[str, float], *, check: bool = True) -> float:
        """Marque le portefeuille, met a jour les deux chemins, retourne l'equity.

        `marks` ne contient que les instruments qui cotent a cet instant. Un
        instrument absent conserve sa derniere marque connue POUR LE CALCUL DE
        L'EQUITY uniquement - c'est une necessite comptable (une position
        existe meme quand son marche est ferme), pas un forward-fill de
        donnees : rien de tout cela n'est visible depuis un `Context`.
        """
        if not self._in_bar:
            raise AccountingError("end_bar appele sans begin_bar")

        delta = -self._bar_fees
        for symbol in self.positions:
            spec = self._specs[symbol]
            mark = marks.get(symbol, self._last_marks.get(symbol))
            if mark is None:
                continue
            previous = self._last_marks.get(symbol, mark)
            quantity_before = self._bar_open_quantities.get(symbol, 0)
            delta += quantity_before * spec.multiplier * (mark - previous)

        for fill in self._bar_fills:
            spec = self._specs[fill.symbol]
            mark = marks.get(fill.symbol, self._last_marks.get(fill.symbol))
            if mark is None:
                continue
            delta += fill.signed_quantity * spec.multiplier * (mark - fill.price)

        self._equity_incremental += delta
        for symbol, mark in marks.items():
            self._last_marks[symbol] = mark

        equity = self.equity(marks)
        if check:
            self._check_invariant(equity)

        margin = self.margin_required()
        if margin > self.stats.max_margin_used:
            self.stats.max_margin_used = margin

        self._in_bar = False
        return equity

    # -- lecture -----------------------------------------------------------

    def mark_of(self, symbol: str, marks: dict[str, float]) -> float | None:
        return marks.get(symbol, self._last_marks.get(symbol))

    def unrealized(self, marks: dict[str, float]) -> float:
        total = 0.0
        for symbol, position in self.positions.items():
            mark = self.mark_of(symbol, marks)
            if mark is not None:
                total += position.unrealized(self._specs[symbol], mark)
        return total

    def equity(self, marks: dict[str, float]) -> float:
        """Chemin d'etat : `cash + non realise`."""
        return self.cash + self.unrealized(marks)

    @property
    def equity_incremental(self) -> float:
        """Chemin d'attribution de P&L. Doit coincider avec `equity`."""
        return self._equity_incremental

    def opened_bar_of(self, symbol: str) -> int | None:
        """Barre d'ouverture du trade EN COURS, ou `None` s'il n'y en a pas.

        Le portefeuille est seul a connaitre la frontiere entre deux
        trades : il voit les fills, donc il sait qu'une vente suivie d'un
        achat sur la MEME barre ferme un aller-retour et en ouvre un autre.
        La quantite, elle, ne le dit pas - elle ne passe jamais par zero.

        Publie le 2026-09-14 parce que le runner en avait besoin : sans
        elle, `bars_held` continuait de compter depuis l'entree d'ORIGINE
        pendant que `entry_price` prenait le prix du trade NEUF, et les
        deux champs decrivaient des trades differents.
        """
        trade = self._open_trades.get(symbol)
        return None if trade is None else trade.opened_bar

    def margin_required(self) -> float:
        return sum(
            p.margin(self._specs[s], self.margin_ratio)
            for s, p in self.positions.items()
        )

    def quantity_of(self, symbol: str) -> int:
        position = self.positions.get(symbol)
        return 0 if position is None else position.quantity

    def spec_of(self, symbol: str) -> InstrumentSpec:
        if symbol not in self._specs:
            raise ConfigurationError(f"instrument '{symbol}' absent du portefeuille")
        return self._specs[symbol]

    # -- ecriture ----------------------------------------------------------

    def apply_fill(self, fill: Fill) -> float:
        """Impute un fill. Retourne le P&L realise brut (hors frais)."""
        if not self._in_bar:
            raise AccountingError("apply_fill appele hors d'une barre (begin_bar manquant)")
        spec = self.spec_of(fill.symbol)
        position = self.positions[fill.symbol]

        realized = self._apply_to_position(position, fill, spec)

        self.cash += realized - fill.fee
        self.stats.n_fills += 1
        self.stats.fees_paid += fill.fee
        self.stats.slippage_paid += fill.slippage_cost * fill.quantity * spec.multiplier
        self.stats.realized_pnl += realized
        self.stats.turnover_notional += fill.quantity * spec.multiplier * abs(fill.price)
        self.stats.contracts_traded += fill.quantity

        self._bar_fills.append(fill)
        self._bar_fees += fill.fee
        return realized

    def _apply_to_position(
        self, position: Position, fill: Fill, spec: InstrumentSpec
    ) -> float:
        before = position.quantity
        delta = fill.signed_quantity
        after = before + delta
        realized = 0.0

        opening = before == 0 or (before > 0) == (delta > 0)
        if opening:
            total = abs(before) + abs(delta)
            position.avg_entry = (
                abs(before) * position.avg_entry + abs(delta) * fill.price
            ) / total
            position.quantity = after
        else:
            closed = min(abs(delta), abs(before))
            direction = 1 if before > 0 else -1
            realized = closed * spec.multiplier * (fill.price - position.avg_entry) * direction
            position.quantity = after
            if after == 0:
                position.avg_entry = 0.0
            elif (after > 0) != (before > 0):
                # Retournement : la partie excedentaire ouvre une position neuve.
                position.avg_entry = fill.price

        self._track_trade(fill, before, after, realized)
        return realized

    def _track_trade(self, fill: Fill, before: int, after: int, realized: float) -> None:
        """Suit les allers-retours pour les metriques (hit rate, profit factor).

        Les frais du fill sont imputes au trade ouvert AVANT le fill quand il
        y en a un, sinon au trade qu'il ouvre. Sur un retournement, ils vont
        donc au trade qui se ferme - convention documentee, et sans effet sur
        le P&L total.
        """
        symbol = fill.symbol
        open_trade = self._open_trades.get(symbol)

        if open_trade is not None:
            open_trade.gross_pnl += realized
            open_trade.fees += fill.fee
            open_trade.max_quantity = max(open_trade.max_quantity, abs(before), abs(after))

        if before != 0 and (after == 0 or (after > 0) != (before > 0)) and open_trade is not None:
            self.closed_trades.append(
                ClosedTrade(
                    symbol=symbol,
                    opened_bar=open_trade.opened_bar,
                    closed_bar=fill.bar_index,
                    direction=open_trade.direction,
                    max_quantity=open_trade.max_quantity,
                    gross_pnl=open_trade.gross_pnl,
                    fees=open_trade.fees,
                )
            )
            del self._open_trades[symbol]
            open_trade = None

        if after != 0 and open_trade is None:
            fees = 0.0 if before != 0 else fill.fee
            self._open_trades[symbol] = _OpenTrade(
                opened_bar=fill.bar_index,
                direction=1 if after > 0 else -1,
                max_quantity=abs(after),
                fees=fees,
            )

    # -- verification ------------------------------------------------------

    def _check_invariant(self, equity: float) -> None:
        difference = abs(equity - self._equity_incremental)
        tolerance = INVARIANT_RTOL * max(1.0, abs(equity))
        if difference > tolerance:
            raise AccountingError(
                f"invariante comptable violee : chemin d'etat {equity!r} contre chemin "
                f"incremental {self._equity_incremental!r} (ecart {difference:.6g}, "
                f"tolerance {tolerance:.6g}). cash={self.cash!r} "
                f"positions={ {s: p.quantity for s, p in self.positions.items() if p.quantity} }"
            )

    def describe(self) -> SpecDict:
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "positions": {s: p.quantity for s, p in self.positions.items() if p.quantity},
            "n_closed_trades": len(self.closed_trades),
            "stats": self.stats.describe(),
        }


@dataclass(slots=True)
class EquityRecorder:
    """Enregistre la courbe d'equity barre par barre.

    Des listes Python plutot que des tableaux redimensionnes : la longueur du
    run n'est pas connue d'avance, et le cout est negligeable devant celui de
    la boucle event-driven.
    """

    ts_ns: list[int] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    cash: list[float] = field(default_factory=list)
    exposure: list[int] = field(default_factory=list)

    def record(self, ts_ns: int, equity: float, cash: float, gross_contracts: int) -> None:
        self.ts_ns.append(ts_ns)
        self.equity.append(equity)
        self.cash.append(cash)
        self.exposure.append(gross_contracts)

    def __len__(self) -> int:
        return len(self.equity)

    def clear(self) -> None:
        self.ts_ns.clear()
        self.equity.clear()
        self.cash.clear()
        self.exposure.clear()
