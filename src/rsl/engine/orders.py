"""Types d'ordres et de fills.

Structures de donnees pures : aucune logique d'execution ici (elle est dans
`execution.py`). Les regles de fill et les bornes de prix sont decrites dans
`docs/execution-model.md` §3.

Un `Order` ne porte pas d'identifiant : c'est le moteur qui attribue des
numeros sequentiels a la soumission. Un identifiant genere par la strategie
(uuid, hash d'objet, adresse memoire) casserait le determinisme bit a bit
exige par le test n° 8.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rsl.errors import ConfigurationError


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        """+1 a l'achat, -1 a la vente. Sert au calcul de position et de P&L."""
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(StrEnum):
    MARKET = "market"
    """Rempli a l'ouverture de la barre de fill, plus slippage."""

    LIMIT = "limit"
    """Rempli si le niveau est atteint dans [low, high] ; optimiste (§3)."""

    STOP = "stop"
    """Declenche si le niveau est atteint ; rempli au pire de (niveau, open)."""


@dataclass(frozen=True, slots=True)
class Order:
    """Ordre soumis par une strategie a la cloture d'une barre.

    `quantity` est un nombre entier de contrats, strictement positif : le sens
    est porte par `side`, pas par le signe de la quantite. Un future ne se
    traite pas en fractions (`docs/execution-model.md` §6.2).

    `stop_loss` et `take_profit` sont des niveaux de prix attaches a la
    position ouverte par cet ordre. Contrairement a l'ordre lui-meme, ils sont
    persistants : actifs jusqu'a execution ou fermeture (§3.2).

    `reduce_only` interdit a l'ordre d'ouvrir ou d'agrandir une position ; il
    ne peut que la reduire ou la fermer. C'est ce qui permet d'ecrire une
    sortie sans connaitre la taille exacte de la position.
    """

    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    reduce_only: bool = False
    tag: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ConfigurationError(
                f"quantity doit etre un entier > 0, recu {self.quantity}. "
                f"Le sens est porte par `side`, pas par le signe."
            )
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ConfigurationError("un ordre LIMIT exige `limit_price`")
        if self.order_type is OrderType.STOP and self.stop_price is None:
            raise ConfigurationError("un ordre STOP exige `stop_price`")
        if self.order_type is OrderType.MARKET and (
            self.limit_price is not None or self.stop_price is not None
        ):
            raise ConfigurationError(
                "un ordre MARKET ne prend ni `limit_price` ni `stop_price` : "
                "un prix qui ne sert a rien est un prix qui ment sur l'intention"
            )
        for label, price in (
            ("limit_price", self.limit_price),
            ("stop_price", self.stop_price),
            ("stop_loss", self.stop_loss),
            ("take_profit", self.take_profit),
        ):
            if price is not None and not price > 0.0:
                # Un prix negatif est possible sur certains futures, mais pas
                # comme niveau d'ordre en phase 1 : le cas n'est pas teste.
                raise ConfigurationError(f"{label} doit etre > 0, recu {price}")
        if self.reduce_only and (self.stop_loss is not None or self.take_profit is not None):
            raise ConfigurationError(
                "un ordre `reduce_only` ne peut pas attacher de stop ni de take-profit : "
                "il ferme une position, il n'en ouvre pas"
            )

    @property
    def signed_quantity(self) -> int:
        return self.side.sign * self.quantity


@dataclass(frozen=True, slots=True)
class Fill:
    """Execution effective d'un ordre contre une barre precise.

    `bar_index` et `ts` designent la barre de FILL, pas celle qui a produit le
    signal. L'ecart entre les deux est le lag d'execution.

    Invariant verifie a la construction dans `execution.py` :
    `bar_low <= price <= bar_high` (`docs/execution-model.md` §3.1).
    """

    order_id: int
    symbol: str
    side: Side
    quantity: int
    price: float
    fee: float
    slippage_cost: float
    ts_ns: int
    bar_index: int
    was_clamped: bool = False
    tag: str = ""

    @property
    def signed_quantity(self) -> int:
        return self.side.sign * self.quantity
