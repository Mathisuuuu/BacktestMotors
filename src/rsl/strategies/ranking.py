"""`RankingStrategy` : une famille transversale entiere, decrite en donnees.

`CrossSectionalMomentum` est parametrable mais pas descriptible : on peut
changer `lookback` ou `n_long`, pas le CRITERE de tri, qui est ecrit en dur
dans la classe. Impossible d'y demander « classe par momentum ajuste de la
volatilite » depuis un fichier.

`RankingStrategy` renverse cela : le critere est un SIGNAL, donc un arbre de
noeuds, donc du JSON. Le reste - trier, selectionner les extremes, diffuser les
ordres vers la cible - est la mecanique commune a toute strategie de classement.

Un test verifie que cette classe reproduit exactement `CrossSectionalMomentum`
lorsqu'on lui donne le score correspondant, ordre par ordre. C'est la meme
methode que pour `SmaCrossover` et sa composition : deux implementations
independantes qui concordent valent mieux qu'une seule verifiee contre
elle-meme.

Le score est evalue instrument par instrument
----------------------------------------------
Chaque instrument present dans la coupe recoit le signal sur SON propre
`Context`. Le signal ne voit donc qu'un instrument a la fois, et ne peut pas
comparer - c'est la strategie qui compare, apres. Cette separation est ce qui
permet de reutiliser tel quel le vocabulaire mono-instrument.

Classer a l'envers
------------------
Il n'y a pas d'option « ordre croissant ». Une strategie de faible volatilite
s'ecrit en niant le score :

    {"type": "arith", "op": "-",
     "left":  {"type": "constant", "value": 0.0},
     "right": {"type": "primitive", "ref": "volatility@1", "params": {"window": 60}}}

Un bouton de plus aurait duplique ce que le vocabulaire sait deja faire.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import Field as PydField

from rsl.data.feed import Context, MultiContext
from rsl.engine.orders import Fill, Order, Side
from rsl.errors import ConfigurationError
from rsl.strategies.base import CrossSectionalStrategy, StrategyParams, strategy
from rsl.strategies.signals import Signal, SpecDict, build_signal


@dataclass(eq=False)
class RankingStrategy(CrossSectionalStrategy):
    """Trie l'univers par un signal, prend les extremes, rebalance."""

    score: Signal
    n_long: int = 3
    n_short: int = 3
    quantity: int = 1
    long_short: bool = True
    extra_warmup: int = 0
    _positions: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _rebalances: int = field(default=0, init=False, repr=False)
    _skipped: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.n_long < 1:
            raise ConfigurationError(f"n_long doit etre >= 1, recu {self.n_long}")
        if self.long_short and self.n_short < 1:
            raise ConfigurationError(
                f"n_short doit etre >= 1 en long-short, recu {self.n_short}"
            )
        if self.quantity < 1:
            raise ConfigurationError(f"quantity doit etre >= 1, recu {self.quantity}")
        if self.extra_warmup < 0:
            raise ConfigurationError(f"extra_warmup doit etre >= 0, recu {self.extra_warmup}")

    # -- contrat -----------------------------------------------------------

    @property
    def warmup_bars(self) -> int:
        return self.score.warmup_bars + self.extra_warmup

    @property
    def required_universe(self) -> int:
        return self.n_long + self.n_short if self.long_short else self.n_long

    def reset(self) -> None:
        self._positions = {}
        self._rebalances = 0
        self._skipped = 0

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
            # Univers trop etroit pour former les jambes demandees. On CONSERVE
            # plutot que de liquider : manquer de donnees n'est pas un signal de
            # vente, et vendre ici fabriquerait des frais que rien ne justifie.
            self._skipped += 1
            return ()
        return self._orders_towards(self._targets(scores))

    def describe(self) -> SpecDict:
        return {
            "class": type(self).__qualname__,
            "score": self.score.describe(),
            "n_long": self.n_long,
            "n_short": self.n_short,
            "quantity": self.quantity,
            "long_short": self.long_short,
            "extra_warmup": self.extra_warmup,
            "n_rebalances": self._rebalances,
            "n_skipped_rebalances": self._skipped,
        }

    # -- interne -----------------------------------------------------------

    def _scores(self, ctx: MultiContext) -> dict[str, float]:
        """Score de chaque instrument qui cote ET qui a assez d'historique.

        Un instrument trop jeune est simplement absent du classement : il
        entrera quand il aura de quoi etre evalue, pas avant. C'est ce qui
        evite le biais de survie sur un univers a geometrie variable.
        """
        scores: dict[str, float] = {}
        for symbol in ctx.symbols:
            sub: Context = ctx[symbol]
            if sub.n_bars_seen < self.score.warmup_bars:
                continue
            value = self.score(sub)
            if value is not None:
                scores[symbol] = value
        return scores

    def _targets(self, scores: dict[str, float]) -> dict[str, int]:
        """Direction cible : +1 pour les meilleurs scores, -1 pour les pires.

        Tri sur `(-score, symbole)` : a score egal, l'ordre alphabetique
        tranche. Sans cette seconde cle, deux runs identiques pourraient
        differer selon l'ordre d'insertion d'un dictionnaire.
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
                        tag="ranking_exit",
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
                    tag="ranking_long" if wanted > 0 else "ranking_short",
                )
            )

        return orders


class RankingParams(StrategyParams):
    """Parametres d'une strategie de classement.

    `score` est une specification de noeud - c'est la que reside toute
    l'expressivite. Sa validation est faite par `build_signal`, qui connait le
    registre des noeuds ; le schema publie par `rsl schema` en donne le contrat.
    """

    score: dict[str, object] = PydField(default_factory=dict)
    n_long: int = 3
    n_short: int = 3
    quantity: int = 1
    long_short: bool = True
    extra_warmup: int = 0


@strategy(
    "ranking",
    version=1,
    params=RankingParams,
    summary=(
        "Classe l'univers par un signal quelconque, prend les extremes. "
        "Aucune classe a ecrire."
    ),
    cross_sectional=True,
)
def _build_ranking(params: StrategyParams) -> CrossSectionalStrategy:
    assert isinstance(params, RankingParams)
    if not params.score:
        raise ConfigurationError(
            "'ranking' exige un `score` : sans critere de tri, il n'y a rien a classer"
        )
    return RankingStrategy(
        score=build_signal(params.score),
        n_long=params.n_long,
        n_short=params.n_short,
        quantity=params.quantity,
        long_short=params.long_short,
        extra_warmup=params.extra_warmup,
    )


def momentum_score(*, lookback: int = 12, skip: int = 1) -> SpecDict:
    """Le score de `cross_sectional_momentum@1`, sous forme de donnees.

    `P(t - skip) / P(t - lookback) - 1`. Fourni pour montrer que la strategie
    ecrite a la main n'a rien qui echappe au vocabulaire - et pour servir de
    point de depart a qui veut la modifier sans ecrire de classe.
    """
    if not 0 <= skip < lookback:
        raise ConfigurationError(
            f"skip doit etre dans [0, lookback[, recu {skip} pour lookback={lookback}"
        )
    return {
        "type": "arith",
        "op": "-",
        "left": {
            "type": "arith",
            "op": "/",
            "left": {"type": "price", "field": "close", "lag": skip},
            "right": {"type": "price", "field": "close", "lag": lookback},
        },
        "right": {"type": "constant", "value": 1.0},
    }
