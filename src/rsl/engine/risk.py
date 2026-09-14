"""Dimensionnement et garde-fous de marge.

Le dimensionnement est une affaire du moteur, pas de la strategie : c'est ce
qui permet de rejouer la meme strategie sous une autre regle de taille sans la
modifier. Une strategie emet une intention ; la couche risque decide combien.

Troncature vers zero, jamais d'arrondi
--------------------------------------
Un future se traite en contrats entiers. `round()` ferait passer 0,5 contrat a
1 et creerait des positions que personne n'a demandees ; la troncature les
laisse a zero et l'ordre n'est pas emis. Le compteur `n_dropped_sizing` rend le
phenomene visible plutot que silencieux (`docs/execution-model.md` §6.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from rsl.data.feed import Context
from rsl.data.schema import InstrumentSpec
from rsl.engine.execution import MarginPolicy
from rsl.engine.limites import (
    AUCUN,
    AUCUNE_LIMITE,
    MOTIFS,
    PortfolioLimits,
    classe_de,
    mesurer,
    projeter,
)
from rsl.engine.portfolio import Portfolio
from rsl.errors import ConfigurationError
from rsl.orders import Order
from rsl.primitives.base import SupportsSignal
from rsl.primitives.registry import bind_primitive

SpecDict = dict[str, object]


@runtime_checkable
class SizingRule(Protocol):
    """Combien de contrats pour une intention d'entree."""

    @property
    def warmup_bars(self) -> int: ...

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int: ...

    def describe(self) -> SpecDict: ...


@dataclass(frozen=True, slots=True)
class FixedContracts:
    """Taille constante. La regle la plus simple, et la seule qui ne depende
    d'aucune estimation - donc celle des tests analytiques."""

    n: int = 1

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ConfigurationError(f"n doit etre >= 1, recu {self.n}")

    @property
    def warmup_bars(self) -> int:
        return 0

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        return self.n

    def describe(self) -> SpecDict:
        return {"rule": "fixed_contracts", "n": self.n}


@dataclass(frozen=True, slots=True)
class EquityFraction:
    """Notionnel cible en fraction de l'equity.

    `contracts = trunc(equity * fraction / (prix * multiplicateur))`.

    Attention a l'interpretation : sur un future, ce notionnel n'est pas
    finance par du cash. Une fraction de 1,0 sur ES represente un levier
    d'environ 15 fois la marge initiale, pas une position "sans levier".
    """

    fraction: float

    def __post_init__(self) -> None:
        if not self.fraction > 0.0:
            raise ConfigurationError(f"fraction doit etre > 0, recu {self.fraction}")

    @property
    def warmup_bars(self) -> int:
        return 0

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        notional_per_contract = abs(reference_price) * spec.multiplier
        if notional_per_contract <= 0.0:
            return 0
        return int(equity * self.fraction / notional_per_contract)

    def describe(self) -> SpecDict:
        return {"rule": "equity_fraction", "fraction": self.fraction}


@dataclass(frozen=True, slots=True)
class RiskFraction:
    """Taille par risque : une fraction de l'equity perdue si le stop touche.

    `risque_par_contrat = atr_multiple * ATR(window) * multiplicateur`
    `contracts = trunc(equity * fraction / risque_par_contrat)`

    L'ATR est evalue sur le `Context`, donc uniquement sur des barres closes.
    Le dimensionnement herite ainsi de la garantie anti-look-ahead sans regle
    supplementaire.

    Suppose que le stop est place a `atr_multiple` ATR de l'entree. Si la
    strategie place son stop ailleurs, la taille ne correspond pas au risque
    annonce - c'est a l'utilisateur de faire coincider les deux.
    """

    fraction: float
    atr_window: int = 14
    atr_multiple: float = 2.0

    def __post_init__(self) -> None:
        if not 0.0 < self.fraction < 1.0:
            raise ConfigurationError(f"fraction doit etre dans ]0, 1[, recu {self.fraction}")
        if self.atr_window < 1:
            raise ConfigurationError(f"atr_window doit etre >= 1, recu {self.atr_window}")
        if self.atr_multiple <= 0.0:
            raise ConfigurationError(f"atr_multiple doit etre > 0, recu {self.atr_multiple}")

    @property
    def warmup_bars(self) -> int:
        return self.atr_window + 1

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        atr = bind_primitive("atr@1", window=self.atr_window)(ctx)
        if atr is None or atr <= 0.0:
            return 0
        risk_per_contract = self.atr_multiple * atr * spec.multiplier
        if risk_per_contract <= 0.0:
            return 0
        return int(equity * self.fraction / risk_per_contract)

    def describe(self) -> SpecDict:
        return {
            "rule": "risk_fraction",
            "fraction": self.fraction,
            "atr_window": self.atr_window,
            "atr_multiple": self.atr_multiple,
        }


@dataclass(frozen=True, slots=True)
class VolatilityTarget:
    """Taille inversement proportionnelle a la volatilite realisee.

        facteur   = min(vol_max_multiple, vol_target / volatilite_realisee)
        contracts = trunc(contracts_de_base * facteur)

    A distinguer de `RiskFraction`, avec laquelle on la confond souvent : celle-ci
    dimensionne sur la distance au stop, donc sur le risque d'UN trade. Celle-la
    vise une volatilite de PORTEFEUILLE et ne depend d'aucun stop. Ce sont deux
    idees differentes, pas deux reglages de la meme.

    `vol_target` est un ecart-type **PAR BARRE**, jamais annualise. Le socle
    refuse les facteurs d'annualisation supposes : le pas d'annualisation est
    mesure sur l'echantillon, apres coup, et une regle de dimensionnement ne le
    connait pas au moment de decider. Exprimer la cible en annuel obligerait a
    en supposer un - c'est exactement l'erreur que le ledger consigne comme
    gonflant le Sharpe d'un facteur deux sur des donnees minute.

    Piege a connaitre : le nombre de contrats est TRONQUE, comme dans toutes les
    autres regles. Avec `contracts: 1` et un facteur d'echelle inferieur a 1,
    `int(1 * 0.9)` vaut zero - la strategie ne prend alors jamais position, sans
    erreur. Choisir une base assez grande pour que la troncature ne mange pas
    tout le signal : `contracts: 10` donne dix paliers, `contracts: 100` en
    donne cent.

    Pas de decalage explicite : le `Context` n'expose que des barres CLOSES, et
    l'execution est retardee d'au moins une barre (`lag_bars >= 1`). Lire la
    barre courante n'est donc pas lire son propre resultat - c'est la meme
    garantie dont `RiskFraction` herite pour son ATR, sans regle supplementaire.
    """

    vol_target: float
    vol_window: int = 20
    vol_max_multiple: float = 4.0
    contracts_base: int = 1

    def __post_init__(self) -> None:
        if self.vol_target <= 0.0:
            raise ConfigurationError(f"vol_target doit etre > 0, recu {self.vol_target}")
        if self.vol_window < 2:
            raise ConfigurationError(
                f"vol_window doit etre >= 2, recu {self.vol_window} : "
                f"un seul rendement n'a pas de dispersion"
            )
        if self.vol_max_multiple <= 0.0:
            raise ConfigurationError(
                f"vol_max_multiple doit etre > 0, recu {self.vol_max_multiple}"
            )
        if self.contracts_base < 1:
            raise ConfigurationError(
                f"contracts doit etre >= 1, recu {self.contracts_base}"
            )

    @property
    def warmup_bars(self) -> int:
        return self.vol_window + 1

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        """Zero quand la volatilite n'est pas estimable.

        Meme convention que `RiskFraction` : une taille non calculable ne
        devient pas une taille par defaut. Le compteur `n_dropped_sizing` rend
        l'evenement visible plutot que silencieux.
        """
        realisee = bind_primitive("volatility@1", window=self.vol_window, log=True)(ctx)
        if realisee is None or realisee <= 0.0:
            return 0
        facteur = min(self.vol_max_multiple, self.vol_target / realisee)
        return int(self.contracts_base * facteur)

    def describe(self) -> SpecDict:
        return {
            "rule": "vol_target",
            "vol_target": self.vol_target,
            "vol_window": self.vol_window,
            "vol_max_multiple": self.vol_max_multiple,
            "contracts": self.contracts_base,
        }


@dataclass(frozen=True, slots=True)
class SignalSizing:
    """Taille donnee par une EXPRESSION du vocabulaire, pas par un mode fige.

    Les quatre autres regles repondent chacune a une question precise - combien
    de contrats, quelle fraction d'equity, quel risque au stop, quelle
    volatilite cible. Celle-ci ne repond a aucune : elle evalue le signal qu'on
    lui donne et prend le resultat pour un nombre de contrats.

        sizing = { "kind": "signal",
                   "signal": { ... n'importe quel noeud ... },
                   "max_contracts": 20 }

    Elle depend du protocole `SupportsSignal`, pas du vocabulaire : le moteur
    de risque reste ignorant des types de noeuds, et c'est la couche
    `config` qui construit l'arbre. Sans cela, `engine` dependrait de
    `strategies`, alors que la dependance va dans l'autre sens.

    Conventions, identiques a celles des autres regles :

    - un signal indefini (`None`) rend 0, donc aucun ordre - "je ne sais pas"
      n'est pas "une position par defaut" ;
    - un resultat negatif rend 0 : le SENS vient des regles d'entree, la taille
      n'est qu'une magnitude. Un signal negatif ne retourne pas la position ;
    - le nombre est TRONQUE, comme partout ailleurs : un signal qui vaut 0,8
      ne prend pas position. Mettre le signal a l'echelle attendue.

    `max_contracts` est obligatoire. Une expression arbitraire peut produire
    n'importe quelle valeur - un z-score divise par une volatilite qui approche
    zero, par exemple - et une taille non bornee n'est pas une strategie, c'est
    un accident qui attend son tour.
    """

    signal: SupportsSignal
    max_contracts: int

    def __post_init__(self) -> None:
        if self.max_contracts < 1:
            raise ConfigurationError(
                f"max_contracts doit etre >= 1, recu {self.max_contracts}"
            )

    @property
    def warmup_bars(self) -> int:
        return self.signal.warmup_bars

    def contracts(
        self, ctx: Context, spec: InstrumentSpec, equity: float, reference_price: float
    ) -> int:
        valeur = self.signal(ctx)
        if valeur is None or not math.isfinite(valeur) or valeur <= 0.0:
            return 0
        return min(int(valeur), self.max_contracts)

    def describe(self) -> SpecDict:
        decrire = getattr(self.signal, "describe", None)
        return {
            "rule": "signal",
            "max_contracts": self.max_contracts,
            "signal": decrire() if callable(decrire) else str(self.signal),
        }


@dataclass(slots=True)
class RiskStats:
    """Un compteur par facon de perdre un ordre.

    Un seul compteur global aurait dit qu'on a refuse, jamais pourquoi - et
    « la strategie ne trade pas » est precisement la question qu'on se pose en
    lisant ces chiffres. Les quatre derniers sont les plafonds de portefeuille,
    nommes comme les motifs de `limites.MOTIFS`.
    """

    n_dropped_sizing: int = 0
    n_rejected_margin: int = 0
    n_warned_margin: int = 0
    n_rejected_gross_cap: int = 0
    n_reduce_only_dropped: int = 0
    n_rejected_gross_exposure: int = 0
    n_rejected_net_exposure: int = 0
    n_rejected_positions: int = 0
    n_rejected_per_category: int = 0

    def compter_refus(self, motif: str) -> None:
        """Incremente le compteur du motif. Leve si le motif est inconnu.

        Le `getattr`/`setattr` est deliberement garde par `MOTIFS` : sans lui,
        un motif mal orthographie creerait un attribut fantome sur un
        `dataclass` a `slots`... ou, pire, passerait inapercu.
        """
        if motif not in MOTIFS:
            raise ValueError(f"motif de refus inconnu : {motif!r}")
        nom = f"n_rejected_{motif}"
        setattr(self, nom, int(getattr(self, nom)) + 1)

    @property
    def n_rejected_portfolio(self) -> int:
        """Total des refus de plafond de portefeuille, tous motifs confondus."""
        return sum(int(getattr(self, f"n_rejected_{motif}")) for motif in MOTIFS)

    def describe(self) -> SpecDict:
        decrit: SpecDict = {
            "n_dropped_sizing": self.n_dropped_sizing,
            "n_rejected_margin": self.n_rejected_margin,
            "n_warned_margin": self.n_warned_margin,
            "n_rejected_gross_cap": self.n_rejected_gross_cap,
            "n_reduce_only_dropped": self.n_reduce_only_dropped,
        }
        for motif in MOTIFS:
            decrit[f"n_rejected_{motif}"] = getattr(self, f"n_rejected_{motif}")
        return decrit


class RiskManager:
    """Se place entre la strategie et l'execution.

    Quatre responsabilites, dans cet ordre :

      1. neutraliser les ordres `reduce_only` sans position a reduire ;
      2. dimensionner les entrees ;
      3. refuser ce qui depasse le plafond de contrats de l'INSTRUMENT ;
      4. refuser ce qui depasse un plafond du PORTEFEUILLE, ou la marge.

    Les etapes 3 et 4 ne mesurent pas la meme chose, et leurs noms se
    ressemblent assez pour qu'on les confonde. `max_gross_contracts` borne
    `abs(position)` sur un instrument, en contrats. `limits` borne le
    portefeuille entier, en argent rapporte a l'equity. Un plafond en contrats
    n'a pas de sens d'un instrument a l'autre - voir `engine/limites.py`.
    """

    __slots__ = (
        "_reserved",
        "_warnings",
        "limits",
        "margin_policy",
        "max_gross_contracts",
        "sizing",
        "stats",
    )

    def __init__(
        self,
        *,
        sizing: SizingRule | None = None,
        margin_policy: MarginPolicy = MarginPolicy.REJECT,
        max_gross_contracts: int | None = None,
        limits: PortfolioLimits | None = None,
    ) -> None:
        if max_gross_contracts is not None and max_gross_contracts < 1:
            raise ConfigurationError(
                f"max_gross_contracts doit etre >= 1, recu {max_gross_contracts}"
            )
        self.sizing = sizing
        self.margin_policy = margin_policy
        self.max_gross_contracts = max_gross_contracts
        self.limits = AUCUNE_LIMITE if limits is None else limits
        self.stats = RiskStats()
        self._warnings: list[str] = []
        self._reserved: dict[str, int] = {}

    def reset(self) -> None:
        self.stats = RiskStats()
        self._warnings = []
        self._reserved = {}

    def begin_submission(self) -> None:
        """Ouvre une nouvelle FOURNEE d'ordres. A appeler par le runner.

        Un plafond de portefeuille n'a de sens que si les ordres d'une meme
        fournee se voient les uns les autres. Sans cela, un rebalancement
        transversal qui emet dix ordres d'un coup les evalue tous contre le
        portefeuille d'avant : chacun lit « aucune position detenue », chacun
        passe, et un plafond de deux instruments en laisse ouvrir dix.

        Mesure le 2026-09-12 sur `momentum_12_1_mensuel` : `max_positions=2`
        laissait detenir jusqu'a SIX instruments. C'est precisement la ou un
        plafond de portefeuille sert - une strategie de classement - qu'il ne
        servait a rien.

        La reservation dure une fournee, et pas davantage, parce que le runner
        remplit les ordres dus AVANT de soumettre les suivants : au moment de
        la fournee suivante, ce qui devait etre execute est deja dans le
        portefeuille. L'exception est l'ordre a cours limite reste en attente -
        il n'est ni rempli ni reserve, et le plafond l'ignore jusqu'a ce qu'il
        touche. Meme famille d'approximation que le decalage des marques, et
        documentee pour la meme raison dans `engine/limites.py`.
        """
        self._reserved = {}

    def _reserver(self, order: Order) -> None:
        """Inscrit un ordre accepte au portefeuille projete de la fournee.

        Les REDUCTIONS y sont inscrites comme les entrees, et c'est necessaire,
        pas genereux : `ranking@1` emet ses sorties avant ses entrees, et un
        plafond qui ne crediterait pas les sorties refuserait toute rotation -
        le portefeuille resterait fige sur ses premieres positions.
        """
        if not self.limits.actives:
            return
        symbole = order.symbol
        self._reserved[symbole] = self._reserved.get(symbole, 0) + order.signed_quantity

    def _quantites_projetees(self, portfolio: Portfolio) -> dict[str, int]:
        """Positions detenues, plus ce que la fournee courante a deja accepte."""
        quantites = {s: p.quantity for s, p in portfolio.positions.items()}
        for symbole, reserve in self._reserved.items():
            quantites[symbole] = quantites.get(symbole, 0) + reserve
        return quantites

    @property
    def warmup_bars(self) -> int:
        return 0 if self.sizing is None else self.sizing.warmup_bars

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    def prepare(
        self, order: Order, ctx: Context, portfolio: Portfolio, marks: dict[str, float]
    ) -> Order | None:
        """Retourne l'ordre a soumettre, eventuellement redimensionne, ou `None`."""
        spec = portfolio.spec_of(order.symbol)

        if order.reduce_only:
            reduit = self.revalidate_reduction(
                order, portfolio.quantity_of(order.symbol)
            )
            if reduit is not None:
                self._reserver(reduit)
            return reduit

        sized = self._size(order, ctx, spec, portfolio, marks)
        if sized is None:
            return None
        accepte = self._check_limits(sized, spec, portfolio, marks)
        if accepte is not None:
            self._reserver(accepte)
        return accepte

    # -- etapes ------------------------------------------------------------

    def revalidate_reduction(self, order: Order, held: int) -> Order | None:
        """Un `reduce_only` ne peut que reduire : sans position, il disparait.

        C'est ce qui empeche l'erreur classique du backtest a regles - une
        sortie qui, faute de position, ouvre une position inverse.
        """
        if held == 0 or (held > 0) == (order.side.sign > 0):
            self.stats.n_reduce_only_dropped += 1
            return None
        capped = min(order.quantity, abs(held))
        if capped == order.quantity:
            return order
        return Order(
            symbol=order.symbol,
            side=order.side,
            quantity=capped,
            order_type=order.order_type,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            reduce_only=True,
            tag=order.tag,
        )

    def _size(
        self,
        order: Order,
        ctx: Context,
        spec: InstrumentSpec,
        portfolio: Portfolio,
        marks: dict[str, float],
    ) -> Order | None:
        if self.sizing is None:
            return order
        equity = portfolio.equity(marks)
        quantity = self.sizing.contracts(ctx, spec, equity, ctx.bar.close)
        if quantity < 1:
            self.stats.n_dropped_sizing += 1
            return None
        if quantity == order.quantity:
            return order
        return Order(
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            order_type=order.order_type,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            tag=order.tag,
        )

    def _check_limits(
        self,
        order: Order,
        spec: InstrumentSpec,
        portfolio: Portfolio,
        marks: dict[str, float],
    ) -> Order | None:
        held = portfolio.quantity_of(order.symbol)
        projected = abs(held + order.signed_quantity)

        if self.max_gross_contracts is not None and projected > self.max_gross_contracts:
            self.stats.n_rejected_gross_cap += 1
            return None

        if self.limits.actives and not self._portfolio_limits_ok(
            order, spec, portfolio, marks
        ):
            return None

        # MEME ratio que le portefeuille : projeter avec la marge de place
        # alors que le portefeuille immobilise une marge de jour refuserait
        # des ordres que le compte peut financer.
        added_margin = (
            (projected - abs(held)) * spec.initial_margin * portfolio.margin_ratio
        )
        if added_margin <= 0.0:
            return order

        required = portfolio.margin_required() + added_margin
        available = portfolio.equity(marks)
        if required <= available:
            return order

        if self.margin_policy is MarginPolicy.REJECT:
            self.stats.n_rejected_margin += 1
            return None

        self.stats.n_warned_margin += 1
        if len(self._warnings) < 20:
            self._warnings.append(
                f"marge requise {required:.0f} > equity {available:.0f} sur {order.symbol} "
                f"(politique 'warn' : l'ordre passe quand meme)"
            )
        return order

    def _portfolio_limits_ok(
        self,
        order: Order,
        spec: InstrumentSpec,
        portfolio: Portfolio,
        marks: dict[str, float],
    ) -> bool:
        """Le portefeuille d'APRES respecte-t-il les plafonds declares ?

        Les marques sont resolues par `Portfolio.mark_of` - la meme resolution
        que celle de l'equity a laquelle les expositions sont rapportees. Les
        prendre dans `marks` seul ferait tomber le numerateur des instruments
        qui ne cotent pas a cette barre, alors qu'ils comptent dans le
        denominateur : le ratio serait faux dans le sens PERMISSIF.
        """
        quantites = self._quantites_projetees(portfolio)
        specs = {s: portfolio.spec_of(s) for s in quantites}
        marques = {
            s: mark
            for s in quantites
            if (mark := portfolio.mark_of(s, marks)) is not None
        }
        avant = mesurer(quantites, specs, marques)
        apres = mesurer(
            projeter(quantites, order.symbol, order.signed_quantity), specs, marques
        )
        motif = self.limits.refus(
            avant, apres, portfolio.equity(marks), classe_de(spec)
        )
        if motif == AUCUN:
            return True
        self.stats.compter_refus(motif)
        return False

    def describe(self) -> SpecDict:
        return {
            "sizing": None if self.sizing is None else self.sizing.describe(),
            "margin_policy": self.margin_policy.value,
            "max_gross_contracts": self.max_gross_contracts,
            "limits": self.limits.describe(),
            "stats": self.stats.describe(),
        }
