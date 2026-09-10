"""`RuleStrategy` : une strategie construite par composition, sans code neuf.

C'est le point d'arrivee du socle de creation. Une strategie a base de regles
est entierement decrite par cinq signaux et une taille :

    entree_longue, sortie_longue, entree_courte, sortie_courte, et les niveaux
    de stop / take-profit.

Aucune de ces regles n'exige d'ecrire une classe. Une famille de strategies
nouvelle s'obtient en composant des noeuds existants ; un indicateur nouveau,
en ajoutant une primitive. Le code publie n'est jamais modifie.

Position et sorties
-------------------
La strategie ne lit pas le portefeuille. Elle apprend sa position par
`on_fill`, et emet ses sorties en `reduce_only` : si elle est deja plate,
l'ordre est sans effet cote moteur. Cela evite l'erreur classique du backtest a
regles - une sortie qui, faute de position, ouvre une position inverse.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from rsl.data.feed import Context
from rsl.engine.orders import Fill, Order, Side
from rsl.errors import ConfigurationError
from rsl.strategies.base import Strategy
from rsl.strategies.signals import FALSE, Signal, SpecDict, build_signal, warmup_of


def _as_int(value: object, label: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"'{label}' doit etre un entier, recu {value!r}")
    return value


@dataclass(eq=False)
class RuleStrategy(Strategy):
    """Strategie a regles, composee de signaux.

    Les regles sont evaluees dans cet ordre a chaque barre : sorties d'abord,
    entrees ensuite. Une barre qui declenche a la fois une sortie et une
    entree inverse produit donc deux ordres, dans cet ordre - jamais un
    retournement implicite dont la taille serait ambigue.

    Un signal indefini (`None`) ne declenche RIEN. "Je ne sais pas" n'est pas
    "non", mais ce n'est pas non plus une raison d'agir.
    """

    symbol: str
    quantity: int
    entry_long: Signal | None = None
    exit_long: Signal | None = None
    entry_short: Signal | None = None
    exit_short: Signal | None = None
    stop_loss: Signal | None = None
    take_profit: Signal | None = None
    allow_pyramiding: bool = False
    extra_warmup: int = 0
    _position: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ConfigurationError(f"quantity doit etre > 0, recu {self.quantity}")
        if self.extra_warmup < 0:
            raise ConfigurationError(f"extra_warmup doit etre >= 0, recu {self.extra_warmup}")
        if self.entry_long is None and self.entry_short is None:
            raise ConfigurationError(
                "une strategie sans entree longue ni entree courte ne peut rien faire. "
                "Si c'est voulu (test de la strategie plate), utilisez `FlatStrategy`."
            )

    # -- contrat Strategy --------------------------------------------------

    @property
    def warmup_bars(self) -> int:
        signals = [
            s
            for s in (
                self.entry_long,
                self.exit_long,
                self.entry_short,
                self.exit_short,
                self.stop_loss,
                self.take_profit,
            )
            if s is not None
        ]
        return warmup_of(signals) + self.extra_warmup

    def reset(self) -> None:
        self._position = 0

    def on_fill(self, fill: Fill) -> None:
        if fill.symbol == self.symbol:
            self._position += fill.signed_quantity

    def on_bar(self, ctx: Context) -> Sequence[Order]:
        orders: list[Order] = []

        if self._position > 0 and self._fires(self.exit_long, ctx):
            orders.append(self._close(Side.SELL, abs(self._position), "exit_long"))
        elif self._position < 0 and self._fires(self.exit_short, ctx):
            orders.append(self._close(Side.BUY, abs(self._position), "exit_short"))

        projected = self._position + sum(o.signed_quantity for o in orders)

        if self._can_open(projected, Side.BUY) and self._fires(self.entry_long, ctx):
            orders.append(self._open(Side.BUY, ctx, "entry_long"))
        elif self._can_open(projected, Side.SELL) and self._fires(self.entry_short, ctx):
            orders.append(self._open(Side.SELL, ctx, "entry_short"))

        return orders

    def describe(self) -> SpecDict:
        return {
            "class": type(self).__qualname__,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "allow_pyramiding": self.allow_pyramiding,
            "extra_warmup": self.extra_warmup,
            "rules": {
                name: (signal.describe() if signal is not None else None)
                for name, signal in (
                    ("entry_long", self.entry_long),
                    ("exit_long", self.exit_long),
                    ("entry_short", self.entry_short),
                    ("exit_short", self.exit_short),
                    ("stop_loss", self.stop_loss),
                    ("take_profit", self.take_profit),
                )
            },
        }

    @staticmethod
    def from_spec(spec: SpecDict) -> RuleStrategy:
        """Reconstruit une strategie a regles depuis sa specification declarative."""
        symbol = spec.get("symbol")
        quantity = spec.get("quantity")
        if not isinstance(symbol, str):
            raise ConfigurationError("'symbol' textuel attendu")
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise ConfigurationError("'quantity' entier attendu")
        rules = spec.get("rules") or {}
        if not isinstance(rules, dict):
            raise ConfigurationError("'rules' doit etre un objet")

        def node(key: str) -> Signal | None:
            raw = rules.get(key)
            return build_signal(raw) if isinstance(raw, dict) else None

        return RuleStrategy(
            symbol=symbol,
            quantity=quantity,
            entry_long=node("entry_long"),
            exit_long=node("exit_long"),
            entry_short=node("entry_short"),
            exit_short=node("exit_short"),
            stop_loss=node("stop_loss"),
            take_profit=node("take_profit"),
            allow_pyramiding=bool(spec.get("allow_pyramiding", False)),
            extra_warmup=_as_int(spec.get("extra_warmup", 0), "extra_warmup"),
        )

    # -- interne -----------------------------------------------------------

    @staticmethod
    def _fires(signal: Signal | None, ctx: Context) -> bool:
        if signal is None:
            return False
        value = signal(ctx)
        return value is not None and value != FALSE

    def _can_open(self, projected: int, side: Side) -> bool:
        if projected == 0:
            return True
        if not self.allow_pyramiding:
            return False
        return (projected > 0) == (side is Side.BUY)

    def _close(self, side: Side, quantity: int, tag: str) -> Order:
        return Order(
            symbol=self.symbol,
            side=side,
            quantity=quantity,
            reduce_only=True,
            tag=tag,
        )

    def _open(self, side: Side, ctx: Context, tag: str) -> Order:
        return Order(
            symbol=self.symbol,
            side=side,
            quantity=self.quantity,
            stop_loss=self._level(self.stop_loss, ctx),
            take_profit=self._level(self.take_profit, ctx),
            tag=tag,
        )

    @staticmethod
    def _level(signal: Signal | None, ctx: Context) -> float | None:
        if signal is None:
            return None
        value = signal(ctx)
        if value is None or value <= 0.0:
            return None
        return value


@dataclass(eq=False)
class FlatStrategy(Strategy):
    """Ne prend jamais position. Support du test exige n° 4.

    Sa courbe d'equity doit etre exactement constante, frais nuls. C'est le
    test le plus simple du moteur, et celui qui attrape le plus de bugs de
    comptabilite : toute derive de l'equity ici est un mouvement de cash que
    personne n'a demande.
    """

    @property
    def warmup_bars(self) -> int:
        return 0

    def on_bar(self, ctx: Context) -> Sequence[Order]:
        return ()

    def describe(self) -> SpecDict:
        return {"class": type(self).__qualname__}
