"""Buy & hold. La strategie de reference la plus utile du projet.

Elle a une verite terrain en forme fermee, calculable sans le moteur :

    equity_finale = cash_initial
                  + quantite * multiplicateur * (mark_final - prix_d_entree)
                  - frais_d_entree

avec `prix_d_entree = open(barre_1)` sous le lag d'execution par defaut : le
signal nait a la cloture de la barre 0, l'ordre s'execute a l'ouverture de la
barre 1 (`docs/execution-model.md` §2.1).

Si le moteur ne reproduit pas cette formule a l'epsilon pres, rien de ce qui
sera construit dessus n'a de valeur. C'est le test n° 3.

Avertissement sur les donnees reelles : les series continues `.v.0` ne sont pas
ajustees au roulement. Un buy & hold sur l'une d'elles mesure le rendement de
la SERIE, pas celui d'une position detenable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from rsl.data.feed import Context
from rsl.errors import ConfigurationError
from rsl.orders import Order, Side
from rsl.strategies.base import Strategy, StrategyParams, strategy

SpecDict = dict[str, object]


@dataclass(eq=False)
class BuyAndHold(Strategy):
    """Achete une fois, a la premiere barre soumise, et ne fait plus rien.

    `_entered` est remis a zero par `reset` : sans cela, un second run sur le
    meme objet n'entrerait pas, et le test de determinisme echouerait pour une
    raison qui n'aurait rien a voir avec le moteur.
    """

    symbol: str
    quantity: int = 1
    side: Side = Side.BUY
    _entered: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ConfigurationError(f"quantity doit etre > 0, recu {self.quantity}")

    @property
    def warmup_bars(self) -> int:
        return 0

    def reset(self) -> None:
        self._entered = False

    def on_bar(self, ctx: Context) -> Sequence[Order]:
        if self._entered:
            return ()
        self._entered = True
        return (
            Order(
                symbol=self.symbol,
                side=self.side,
                quantity=self.quantity,
                tag="buy_and_hold",
            ),
        )

    def describe(self) -> SpecDict:
        return {
            "class": type(self).__qualname__,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "side": self.side.value,
        }


class BuyAndHoldParams(StrategyParams):
    symbol: str
    quantity: int = 1


@strategy(
    "buy_and_hold",
    version=1,
    params=BuyAndHoldParams,
    summary="Achete a la premiere barre, conserve jusqu'a la fin.",
)
def _build_buy_and_hold(params: StrategyParams) -> Strategy:
    assert isinstance(params, BuyAndHoldParams)
    return BuyAndHold(symbol=params.symbol, quantity=params.quantity)
