"""Croisement de moyennes mobiles avec stop-loss.

Famille time-series / a regles : entree, sortie, stop, dimensionnement.

Ecrite en code EXPLICITE, et non par composition de noeuds de signaux. Ce n'est
pas une redondance : `RuleStrategy` peut exprimer exactement la meme regle, et
un test verifie que les deux produisent la meme suite d'ordres, barre par
barre. Deux implementations independantes qui concordent valent mieux qu'une
seule verifiee contre elle-meme - c'est la couche de signaux qui est testee au
passage.

Regles
------
- entree longue : la moyenne rapide croise la lente vers le haut ;
- sortie        : elle la croise vers le bas ;
- stop-loss     : `cloture - multiple * ATR`, attache a l'entree, persistant.

Le croisement est evalue sans etat : la valeur de la barre precedente est lue
via `Context.shifted(1)` plutot que memorisee. Un etat interne survivrait d'un
run a l'autre et casserait le determinisme.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from rsl.data.feed import Context
from rsl.errors import ConfigurationError
from rsl.orders import Fill, Order, Side
from rsl.primitives.base import BoundPrimitive
from rsl.primitives.registry import bind_primitive
from rsl.strategies.base import Strategy, StrategyParams, strategy

SpecDict = dict[str, object]


@dataclass(eq=False)
class SmaCrossover(Strategy):
    """Croisement SMA rapide / lente, long seulement, avec stop ATR."""

    symbol: str
    fast_window: int = 20
    slow_window: int = 100
    quantity: int = 1
    atr_window: int = 14
    atr_multiple: float = 2.0
    _position: int = field(default=0, init=False, repr=False)
    _fast: BoundPrimitive = field(init=False, repr=False)
    _slow: BoundPrimitive = field(init=False, repr=False)
    _atr: BoundPrimitive = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.fast_window < 1 or self.slow_window < 1:
            raise ConfigurationError(
                f"fenetres doivent etre >= 1, recu {self.fast_window} et {self.slow_window}"
            )
        if self.fast_window >= self.slow_window:
            raise ConfigurationError(
                f"fast_window ({self.fast_window}) doit etre < slow_window "
                f"({self.slow_window}) : sans cela il n'y a pas de croisement a detecter"
            )
        if self.quantity < 1:
            raise ConfigurationError(f"quantity doit etre >= 1, recu {self.quantity}")
        if self.atr_window < 1:
            raise ConfigurationError(f"atr_window doit etre >= 1, recu {self.atr_window}")
        if self.atr_multiple <= 0.0:
            raise ConfigurationError(f"atr_multiple doit etre > 0, recu {self.atr_multiple}")

        self._fast = bind_primitive("sma@1", window=self.fast_window)
        self._slow = bind_primitive("sma@1", window=self.slow_window)
        self._atr = bind_primitive("atr@1", window=self.atr_window)

    # -- contrat Strategy --------------------------------------------------

    @property
    def warmup_bars(self) -> int:
        """La barre supplementaire couvre la lecture de `shifted(1)`."""
        return max(self._slow.warmup_bars, self._atr.warmup_bars) + 1

    def reset(self) -> None:
        self._position = 0

    def on_fill(self, fill: Fill) -> None:
        if fill.symbol == self.symbol:
            self._position += fill.signed_quantity

    def on_bar(self, ctx: Context) -> Sequence[Order]:
        fast_now = self._fast(ctx)
        slow_now = self._slow(ctx)
        if fast_now is None or slow_now is None:
            return ()

        previous = ctx.shifted(1)
        fast_prev = self._fast(previous)
        slow_prev = self._slow(previous)
        if fast_prev is None or slow_prev is None:
            return ()

        if self._position > 0 and fast_prev >= slow_prev and fast_now < slow_now:
            return (
                Order(
                    symbol=self.symbol,
                    side=Side.SELL,
                    quantity=abs(self._position),
                    reduce_only=True,
                    tag="sma_exit",
                ),
            )

        if self._position == 0 and fast_prev <= slow_prev and fast_now > slow_now:
            return (
                Order(
                    symbol=self.symbol,
                    side=Side.BUY,
                    quantity=self.quantity,
                    stop_loss=self._stop_level(ctx),
                    tag="sma_entry",
                ),
            )

        return ()

    def describe(self) -> SpecDict:
        return {
            "class": type(self).__qualname__,
            "symbol": self.symbol,
            "fast_window": self.fast_window,
            "slow_window": self.slow_window,
            "quantity": self.quantity,
            "atr_window": self.atr_window,
            "atr_multiple": self.atr_multiple,
        }

    # -- interne -----------------------------------------------------------

    def _stop_level(self, ctx: Context) -> float | None:
        """`cloture - multiple * ATR`, ou `None` si l'ATR n'est pas calculable.

        Un stop nul ou negatif n'est pas attache : mieux vaut une position sans
        protection, visible dans le rapport, qu'un stop a un prix impossible
        qui ne se declencherait jamais.
        """
        atr = self._atr(ctx)
        if atr is None or atr <= 0.0:
            return None
        level = ctx.bar.close - self.atr_multiple * atr
        return level if level > 0.0 else None


class SmaCrossoverParams(StrategyParams):
    symbol: str
    fast_window: int = 20
    slow_window: int = 100
    quantity: int = 1
    atr_window: int = 14
    atr_multiple: float = 2.0


@strategy(
    "sma_crossover",
    version=1,
    params=SmaCrossoverParams,
    summary="Croisement de moyennes mobiles, long seulement, stop-loss a N ATR.",
)
def _build_sma_crossover(params: StrategyParams) -> Strategy:
    assert isinstance(params, SmaCrossoverParams)
    return SmaCrossover(
        symbol=params.symbol,
        fast_window=params.fast_window,
        slow_window=params.slow_window,
        quantity=params.quantity,
        atr_window=params.atr_window,
        atr_multiple=params.atr_multiple,
    )
