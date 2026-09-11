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

from pydantic import Field as PydField

from rsl.data.feed import Context, MultiContext
from rsl.engine.orders import Fill, Order, OrderType, Side
from rsl.errors import ConfigurationError
from rsl.strategies.base import (
    CrossSectionalStrategy,
    Strategy,
    StrategyParams,
    strategy,
)
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
    entry_limit: Signal | None = None
    entry_stop: Signal | None = None
    allow_pyramiding: bool = False
    extra_warmup: int = 0
    _position: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ConfigurationError(f"quantity doit etre > 0, recu {self.quantity}")
        if self.extra_warmup < 0:
            raise ConfigurationError(f"extra_warmup doit etre >= 0, recu {self.extra_warmup}")
        if self.entry_limit is not None and self.entry_stop is not None:
            raise ConfigurationError(
                "`entry_limit` et `entry_stop` sont exclusifs : un ordre a un seul "
                "type. Choisir d'entrer sur repli (limite) OU sur cassure (stop)."
            )
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
                self.entry_limit,
                self.entry_stop,
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

        entree: Order | None = None
        if self._can_open(projected, Side.BUY) and self._fires(self.entry_long, ctx):
            entree = self._open(Side.BUY, ctx, "entry_long")
        elif self._can_open(projected, Side.SELL) and self._fires(self.entry_short, ctx):
            entree = self._open(Side.SELL, ctx, "entry_short")
        if entree is not None:
            orders.append(entree)

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
                    ("entry_limit", self.entry_limit),
                    ("entry_stop", self.entry_stop),
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
            entry_limit=node("entry_limit"),
            entry_stop=node("entry_stop"),
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

    def _open(self, side: Side, ctx: Context, tag: str) -> Order | None:
        """Ordre d'entree, ou `None` si son prix ne peut pas etre calcule.

        Un `entry_limit` declare dont le signal est indefini a cette barre ne
        donne PAS un ordre au marche : ce serait changer silencieusement le
        type d'ordre, donc le comportement. L'entree est simplement abandonnee,
        conformement a la regle du socle - « je ne sais pas » n'est pas une
        raison d'agir.
        """
        order_type = OrderType.MARKET
        limit_price: float | None = None
        stop_price: float | None = None

        if self.entry_limit is not None:
            limit_price = self._level(self.entry_limit, ctx)
            if limit_price is None:
                return None
            order_type = OrderType.LIMIT
        elif self.entry_stop is not None:
            stop_price = self._level(self.entry_stop, ctx)
            if stop_price is None:
                return None
            order_type = OrderType.STOP

        return Order(
            symbol=self.symbol,
            side=side,
            quantity=self.quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
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


class RuleStrategyParams(StrategyParams):
    """Parametres d'une strategie a regles, tels qu'ils arrivent d'un fichier.

    `rules` est un dictionnaire de specifications de noeuds - c'est la que se
    trouve toute l'expressivite. Il n'est PAS valide par pydantic au-dela de sa
    forme : sa validation reelle est faite par `build_signal`, qui connait le
    registre des noeuds et refuse un type inconnu, un operateur invalide ou une
    reference de primitive inexistante. Un schema pydantic fige ici
    dupliquerait ce registre et divergerait de lui.
    """

    symbol: str
    quantity: int = 1
    rules: dict[str, object] = PydField(default_factory=dict)
    allow_pyramiding: bool = False
    extra_warmup: int = 0


@strategy(
    "rules",
    version=1,
    params=RuleStrategyParams,
    summary=(
        "Strategie a regles, decrite entierement par des signaux composes. "
        "Aucune classe a ecrire."
    ),
)
def _build_rule_strategy(params: StrategyParams) -> Strategy:
    """Fabrique la strategie a partir de sa seule description.

    C'est le chemin qui permet a une specification - ecrite a la main
    aujourd'hui, produite par une machine demain - de devenir une strategie
    executable sans qu'une ligne de code soit generee.
    """
    assert isinstance(params, RuleStrategyParams)
    return RuleStrategy.from_spec(
        {
            "symbol": params.symbol,
            "quantity": params.quantity,
            "rules": params.rules,
            "allow_pyramiding": params.allow_pyramiding,
            "extra_warmup": params.extra_warmup,
        }
    )


@dataclass(eq=False)
class PanelRuleStrategy(CrossSectionalStrategy):
    """Regles mono-instrument, evaluees sur un PANNEAU.

    Meme logique que `RuleStrategy` - elle la delegue entierement - mais
    executee par le runner transversal, ce qui donne acces aux autres
    instruments via le noeud `peer`. C'est ce qu'il faut pour negocier UN
    instrument en regardant les AUTRES : spread, ratio, couverture, filtre de
    regime pris sur un indice.

    Pourquoi un troisieme moule plutot qu'un drapeau sur `RuleStrategy`
    -------------------------------------------------------------------
    Ce n'est pas la logique de decision qui change - elle est identique, et
    litteralement partagee - c'est la FORME D'EXECUTION : il faut un panneau,
    donc un calendrier commun, donc l'autre runner. Le meme raisonnement que
    pour les deux modes de runner (`docs/execution-model.md` §7) : une
    abstraction unique servirait mal les deux.

    Si son instrument ne cote pas a une ligne donnee, la strategie ne fait
    rien. Elle ne peut ni evaluer ses regles ni etre executee sans barre.
    """

    inner: RuleStrategy

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars

    @property
    def symbol(self) -> str:
        return self.inner.symbol

    def reset(self) -> None:
        self.inner.reset()

    def on_fill(self, fill: Fill) -> None:
        self.inner.on_fill(fill)

    def on_rebalance(self, ctx: MultiContext) -> Sequence[Order]:
        if self.inner.symbol not in ctx.symbols:
            return ()
        return self.inner.on_bar(ctx[self.inner.symbol])

    def describe(self) -> SpecDict:
        return {"class": type(self).__qualname__, "inner": self.inner.describe()}


@strategy(
    "panel_rules",
    version=1,
    params=RuleStrategyParams,
    summary=(
        "Regles mono-instrument evaluees sur un panneau : donne acces aux autres "
        "instruments via le noeud `peer`."
    ),
    cross_sectional=True,
)
def _build_panel_rules(params: StrategyParams) -> CrossSectionalStrategy:
    assert isinstance(params, RuleStrategyParams)
    inner = _build_rule_strategy(params)
    assert isinstance(inner, RuleStrategy)
    return PanelRuleStrategy(inner=inner)


class MultiRuleParams(StrategyParams):
    """Un jeu de regles PAR instrument, dans un portefeuille commun.

    `books` associe un symbole a ses parametres - `quantity`, `rules`,
    `allow_pyramiding`, `extra_warmup` - exactement ceux de `rules@1`, moins
    `symbol` qui est deja la cle. Comme pour `rules@1`, le contenu de `rules`
    n'est pas valide par pydantic au-dela de sa forme : `build_signal` s'en
    charge, et dupliquer le registre ici le ferait diverger de lui.
    """

    books: dict[str, dict[str, object]] = PydField(default_factory=dict)
    extra_warmup: int = 0


@dataclass(slots=True)
class MultiRuleStrategy(CrossSectionalStrategy):
    """Plusieurs instruments, chacun ses regles, un seul portefeuille.

    `rules@1` et `panel_rules@1` ne negocient qu'UN symbole : le second voit
    les autres par `peer`, mais n'y prend pas position. Pour tenir ES sur une
    logique et NQ sur une autre, il fallait deux runs - donc deux equity
    separees, deux drawdowns sans rapport, et aucune contrainte de risque
    commune. Ce moule supprime cette limite.

    Ce qu'il ne change PAS, volontairement :

    - chaque livre est une `RuleStrategy` ordinaire, litteralement la meme
      classe. La logique de decision n'est pas dupliquee ;
    - chaque livre recoit `ctx[symbole]`, donc le noeud `peer` continue de
      fonctionner a l'interieur : un livre peut regarder les autres ;
    - un livre dont l'instrument ne cote pas a cette ligne ne fait rien, comme
      dans `panel_rules@1` - on ne decide pas sans barre.

    Les livres sont parcourus dans l'ordre TRIE des symboles, jamais dans
    l'ordre d'insertion du dictionnaire : deux specifications identiques a
    l'ordre des cles pres doivent produire la meme suite d'ordres, donc la
    meme empreinte.
    """

    books: tuple[RuleStrategy, ...]
    extra_warmup: int = 0

    def __post_init__(self) -> None:
        if not self.books:
            raise ConfigurationError(
                "`books` est vide : une strategie multi-instruments a besoin d'au "
                "moins un livre."
            )
        if self.extra_warmup < 0:
            raise ConfigurationError(
                f"extra_warmup doit etre >= 0, recu {self.extra_warmup}"
            )
        symboles = [livre.symbol for livre in self.books]
        doublons = {s for s in symboles if symboles.count(s) > 1}
        if doublons:
            raise ConfigurationError(
                f"symbole(s) en double dans `books` : {sorted(doublons)}. Deux jeux "
                f"de regles sur le meme instrument se marcheraient dessus - leurs "
                f"positions ne sont pas separables dans un portefeuille commun."
            )

    @property
    def warmup_bars(self) -> int:
        """Le plus exigeant des livres.

        Un warmup par livre serait plus fin, mais le runner transversal n'en
        expose qu'un : mieux vaut attendre trop que decider sur un indicateur
        pas encore defini.
        """
        return max(livre.warmup_bars for livre in self.books) + self.extra_warmup

    def reset(self) -> None:
        for livre in self.books:
            livre.reset()

    def on_fill(self, fill: Fill) -> None:
        """Diffuse a tous les livres.

        Chacun filtre deja sur `fill.symbol == self.symbol` : router ici
        dupliquerait ce filtrage, donc une occasion de le faire differemment.
        """
        for livre in self.books:
            livre.on_fill(fill)

    def on_rebalance(self, ctx: MultiContext) -> Sequence[Order]:
        orders: list[Order] = []
        for livre in self.books:
            if livre.symbol not in ctx.symbols:
                continue
            orders.extend(livre.on_bar(ctx[livre.symbol]))
        return orders

    def describe(self) -> SpecDict:
        return {
            "class": type(self).__qualname__,
            "extra_warmup": self.extra_warmup,
            "books": {livre.symbol: livre.describe() for livre in self.books},
        }


@strategy(
    "multi_rules",
    version=1,
    params=MultiRuleParams,
    summary=(
        "Un jeu de regles PAR instrument, dans un portefeuille commun. "
        "Aucune classe a ecrire."
    ),
    cross_sectional=True,
)
def _build_multi_rules(params: StrategyParams) -> CrossSectionalStrategy:
    assert isinstance(params, MultiRuleParams)
    if not params.books:
        raise ConfigurationError("`books` est vide : declarer au moins un instrument")

    livres: list[RuleStrategy] = []
    for symbole in sorted(params.books):
        # Le type de `books` garantit deja que chaque valeur est un objet :
        # pydantic rejette le reste avant d'arriver ici.
        brut = params.books[symbole]
        if "symbol" in brut:
            raise ConfigurationError(
                f"books['{symbole}'] porte un champ `symbol` : le symbole est deja "
                f"la cle. En declarer un second ouvrirait la porte a ce que les deux "
                f"divergent."
            )
        # Un livre EST un jeu de parametres `rules@1` moins le symbole : on
        # passe par le meme modele, donc les memes defauts et la meme
        # validation. Construire a la main dupliquerait les deux, et les ferait
        # diverger au premier changement.
        livre = RuleStrategyParams.model_validate({**brut, "symbol": symbole})
        construit = _build_rule_strategy(livre)
        assert isinstance(construit, RuleStrategy)
        livres.append(construit)
    return MultiRuleStrategy(books=tuple(livres), extra_warmup=params.extra_warmup)
