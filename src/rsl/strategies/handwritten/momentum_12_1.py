"""Momentum transversal 12-1.

Famille cross-sectionnelle : tri, rebalancement periodique, long-short,
ponderation.

Definition retenue
------------------
Le score de l'instrument `i` a la date de rebalancement `t` est

    score_i(t) = P_i(t - skip) / P_i(t - lookback) - 1

Avec les defauts `lookback=12` et `skip=1`, c'est `P(t-1) / P(t-12) - 1` : le
rendement des douze derniers mois EN SAUTANT le mois le plus recent. Le saut
est la partie "-1" du nom, et il n'est pas cosmetique - le rendement du mois
ecoule presente un renversement a court terme qui pollue le signal de momentum.

Les periodes sont des BARRES du panneau, pas des mois calendaires. Sur un
panneau reechantillonne au mois (`rsl.data.resample`), les deux coincident ;
sur un panneau quotidien, `lookback=12` signifie douze jours. Le nom de la
strategie decrit son usage attendu, pas une contrainte du code.

Ce que la strategie voit, et ce qu'elle ne voit pas
---------------------------------------------------
Elle voit les instruments qui COTENT a la date de rebalancement, et leur
historique clos. Elle ne voit ni le portefeuille, ni l'equity, ni la taille de
l'echantillon. Elle apprend ses positions par `on_fill`.

Un instrument absent de la coupe n'est pas classe - il n'a pas "le prix
d'avant" (`docs/no-lookahead.md` §4.1). S'il etait detenu, l'ordre de sortie
est tout de meme emis : le runner le reportera jusqu'a ce que l'instrument
cote de nouveau.

Univers variable
----------------
L'appartenance a l'univers est recalculee a chaque rebalancement, avec la seule
information disponible a cet instant : un instrument entre quand il a
`lookback + 1` barres closes, pas avant. C'est ce qui permet de traiter un
instrument qui demarre au milieu de l'echantillon (FDAX, mars 2025) sans biais
de survie.

Taille des jambes
-----------------
La strategie emet une INTENTION de direction et une quantite nominale. Si un
`SizingRule` est branche sur le `RiskManager`, c'est lui qui fixe le nombre de
contrats - la strategie n'a pas acces a l'equity, donc ne peut pas equilibrer
les notionnels elle-meme.

Une jambe qui reste selectionnee d'un rebalancement au suivant n'est PAS
redimensionnee. C'est un choix : sur des contrats entiers, re-equilibrer chaque
mois produit une nuee de micro-transactions dont les frais depassent le gain de
precision. Le prix a payer est que les poids derivent entre deux entrees.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from rsl.data.feed import Context, MultiContext
from rsl.data.schema import Field
from rsl.engine.orders import Fill, Order, Side
from rsl.errors import ConfigurationError
from rsl.strategies.base import CrossSectionalStrategy, StrategyParams, strategy

SpecDict = dict[str, object]


@dataclass(eq=False)
class CrossSectionalMomentum(CrossSectionalStrategy):
    """Momentum transversal, long-short, rebalance a chaque appel."""

    lookback: int = 12
    skip: int = 1
    n_long: int = 3
    n_short: int = 3
    quantity: int = 1
    long_short: bool = True
    _positions: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _skipped_rebalances: int = field(default=0, init=False, repr=False)
    _rebalances: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.lookback < 2:
            raise ConfigurationError(f"lookback doit etre >= 2, recu {self.lookback}")
        if not 0 <= self.skip < self.lookback:
            raise ConfigurationError(
                f"skip doit etre dans [0, lookback[, recu {self.skip} pour "
                f"lookback={self.lookback}"
            )
        if self.n_long < 1:
            raise ConfigurationError(f"n_long doit etre >= 1, recu {self.n_long}")
        if self.long_short and self.n_short < 1:
            raise ConfigurationError(
                f"n_short doit etre >= 1 en long-short, recu {self.n_short}"
            )
        if self.quantity < 1:
            raise ConfigurationError(f"quantity doit etre >= 1, recu {self.quantity}")

    # -- contrat CrossSectionalStrategy ------------------------------------

    @property
    def warmup_bars(self) -> int:
        """`lookback + 1` barres closes : il faut pouvoir lire `lag=lookback`."""
        return self.lookback + 1

    @property
    def required_universe(self) -> int:
        return self.n_long + self.n_short if self.long_short else self.n_long

    def reset(self) -> None:
        self._positions = {}
        self._skipped_rebalances = 0
        self._rebalances = 0

    def on_fill(self, fill: Fill) -> None:
        current = self._positions.get(fill.symbol, 0) + fill.signed_quantity
        if current == 0:
            self._positions.pop(fill.symbol, None)
        else:
            self._positions[fill.symbol] = current

    def on_rebalance(self, ctx: MultiContext) -> Sequence[Order]:
        self._rebalances += 1
        scores = self._scores(ctx)

        if len(scores) < self.required_universe:
            # Univers trop etroit pour former les deux jambes. On CONSERVE les
            # positions plutot que de liquider : liquider sur un manque de
            # donnees fabriquerait des transactions que le signal ne demande
            # pas. L'evenement est compte et remonte dans le rapport.
            self._skipped_rebalances += 1
            return ()

        targets = self._targets(scores)
        return self._orders_towards(targets)

    def describe(self) -> SpecDict:
        return {
            "class": type(self).__qualname__,
            "lookback": self.lookback,
            "skip": self.skip,
            "n_long": self.n_long,
            "n_short": self.n_short,
            "quantity": self.quantity,
            "long_short": self.long_short,
            "n_rebalances": self._rebalances,
            "n_skipped_rebalances": self._skipped_rebalances,
        }

    # -- interne -----------------------------------------------------------

    def _scores(self, ctx: MultiContext) -> dict[str, float]:
        """Score de momentum des instruments eligibles, dans l'ordre trie."""
        scores: dict[str, float] = {}
        for symbol in ctx.symbols:
            sub: Context = ctx[symbol]
            if sub.n_bars_seen < self.lookback + 1:
                continue
            recent = sub.value(Field.CLOSE, lag=self.skip)
            older = sub.value(Field.CLOSE, lag=self.lookback)
            if older <= 0.0 or recent <= 0.0:
                continue
            scores[symbol] = recent / older - 1.0
        return scores

    def _targets(self, scores: dict[str, float]) -> dict[str, int]:
        """Direction cible par instrument : +1 long, -1 short.

        Le tri est `(-score, symbole)` : a score egal, l'ordre alphabetique
        tranche. Sans cette seconde cle, deux runs identiques pourraient
        differer selon l'ordre d'insertion du dictionnaire - et l'exigence de
        reproductibilite tomberait sur un detail invisible.
        """
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        targets: dict[str, int] = {}
        for symbol, _ in ranked[: self.n_long]:
            targets[symbol] = 1
        if self.long_short:
            for symbol, _ in ranked[-self.n_short :]:
                targets[symbol] = -1
        return targets

    def _orders_towards(self, targets: dict[str, int]) -> list[Order]:
        """Sorties d'abord, entrees ensuite, chaque groupe dans l'ordre trie."""
        orders: list[Order] = []

        for symbol in sorted(self._positions):
            held = self._positions[symbol]
            wanted = targets.get(symbol, 0)
            if held != 0 and (1 if held > 0 else -1) != wanted:
                orders.append(
                    Order(
                        symbol=symbol,
                        side=Side.SELL if held > 0 else Side.BUY,
                        quantity=abs(held),
                        reduce_only=True,
                        tag="momentum_exit",
                    )
                )

        for symbol in sorted(targets):
            wanted = targets[symbol]
            held = self._positions.get(symbol, 0)
            if held != 0 and (1 if held > 0 else -1) == wanted:
                continue
            orders.append(
                Order(
                    symbol=symbol,
                    side=Side.BUY if wanted > 0 else Side.SELL,
                    quantity=self.quantity,
                    tag="momentum_long" if wanted > 0 else "momentum_short",
                )
            )

        return orders


class MomentumParams(StrategyParams):
    lookback: int = 12
    skip: int = 1
    n_long: int = 3
    n_short: int = 3
    quantity: int = 1
    long_short: bool = True


@strategy(
    "cross_sectional_momentum",
    version=1,
    params=MomentumParams,
    summary="Momentum transversal 12-1, long-short, rebalance a chaque periode.",
    cross_sectional=True,
)
def _build_momentum(params: StrategyParams) -> CrossSectionalStrategy:
    assert isinstance(params, MomentumParams)
    return CrossSectionalMomentum(
        lookback=params.lookback,
        skip=params.skip,
        n_long=params.n_long,
        n_short=params.n_short,
        quantity=params.quantity,
        long_short=params.long_short,
    )
