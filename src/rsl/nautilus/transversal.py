"""Le vocabulaire TRANSVERSAL, execute par le moteur Nautilus.

Le meme principe que `vocabulaire.py`, et une difficulte de plus
-----------------------------------------------------------------
`vocabulaire.py` porte les strategies mono-instrument : Nautilus livre une
barre, notre `BarContext` avance d'un cran, le vocabulaire fait le reste.

Le transversal ne peut pas faire cela, parce qu'il ne decide pas sur une barre
mais sur une LIGNE DE PANNEAU - une coupe a un instant, sur tous les
instruments qui cotent alors. Or Nautilus ne livre pas de coupes : il livre des
barres, instrument par instrument.

Reconstituer la coupe : COMPTER les barres attendues
-----------------------------------------------------
Nautilus livre les donnees triees par instant, donc les barres d'un meme
instant arrivent consecutivement. Reste a savoir quand l'instant est complet.

Une premiere version declenchait au CHANGEMENT d'horodatage : a l'arrivee de la
premiere barre de `T1`, la ligne `T0` etait reputee finie. Elle l'etait - mais
le simulateur, lui, n'avait traite qu'UNE barre de `T1`, et les neuf autres
instruments n'avaient pas encore de prix a cet instant. Nautilus rejetait alors
chaque ordre avec `no market for NQ.v.0.SIM` : **684 ordres emis, 684 rejetes,
zero position**, sans la moindre erreur - seulement un resultat plat.

Le panneau sait combien d'instruments cotent a chaque ligne
(`present_symbols`). On COMPTE donc les barres recues, et la ligne n'est traitee
qu'a la derniere. Tous les instruments ont alors un marche.

Le decalage d'execution, lui, reste explicite
----------------------------------------------
Les ordres decides a la ligne `r` sont mis en file et soumis quand la ligne
`r+1` est complete. Ils se remplissent donc au prix de `r+1`, jamais a celui de
`r` que la strategie vient de lire.

Meme mecanisme que `vocabulaire._en_attente`, et pour la meme raison : une fuite
de 19,43 % mesuree le 2026-09-13 sur le mono-instrument.

Ce que ce pont ne porte pas encore
-----------------------------------
Le `RiskManager` : plafonds de portefeuille, dimensionnement, allocation. Les
ordres sortent de la strategie et vont directement a Nautilus, dont le
`RiskEngine` a ses propres regles. Une specification qui declare
`risk.limits` ou `risk.sizing` verra donc ces reglages IGNORES de ce cote -
et `monter_transversal` le refuse plutot que de les laisser passer sans effet.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy as StrategyNautilus

from rsl.data.feed import MultiContext
from rsl.data.schema import AccountState, Panel, PositionState
from rsl.engine.cross_sectional import RebalanceSchedule
from rsl.errors import ConfigurationError
from rsl.orders import Fill, Order, OrderType, Side
from rsl.strategies.base import CrossSectionalStrategy, build_strategy

SpecDict = dict[str, object]


class TransversalConfig(StrategyConfig, frozen=True):
    """Une strategie transversale du depot, telle qu'elle s'ecrit en JSON."""

    strategie: dict[str, object]
    venue: str
    agregation: str = "1-DAY-LAST"
    """La specification Nautilus des barres auxquelles s'abonner.

    DOIT correspondre a celle qui a charge le moteur. Elle etait codee en dur a
    `1-DAY-LAST` dans une premiere version : la strategie s'abonnait a des
    barres quotidiennes pendant que le moteur servait du mensuel, donc aucune
    barre n'arrivait et aucune position n'etait prise - sans la moindre erreur.
    Constate le 2026-09-13 sur `momentum_12_1_mensuel`."""


class TransversalNautilus(StrategyNautilus):
    """Execute `panel_rules@1` ou `ranking@1` sur le moteur Nautilus."""

    def __init__(self, config: TransversalConfig) -> None:
        super().__init__(config)
        construite = build_strategy(dict(config.strategie))
        if not isinstance(construite, CrossSectionalStrategy):
            raise ConfigurationError(
                f"'{config.strategie.get('ref')}' n'est pas une strategie "
                f"transversale. Les strategies mono-instrument passent par "
                f"`rsl.nautilus.vocabulaire`."
            )
        self._regles: CrossSectionalStrategy = construite
        self._mctx: MultiContext | None = None
        self._panel: Panel | None = None
        self._schedule: RebalanceSchedule | None = None
        self._capital: float = 0.0
        self._sommet: float = 0.0
        self._positions: dict[str, int] = {}
        self._instruments: dict[str, Any] = {}
        self._ts_courant: int | None = None
        self._ligne: int = -1
        self._recues: int = 0
        self._attendues: int = 0
        self._en_attente: list[Order] = []
        self._prochain_id: int = 0

    def attacher(
        self,
        panel: Panel,
        multiplicateurs: dict[str, float],
        *,
        capital: float,
        schedule: RebalanceSchedule,
    ) -> None:
        """Branche le panneau qui a servi a engendrer les barres.

        Comme pour le mono-instrument, par une methode et non par la
        configuration : un panneau porte plusieurs magasins de millions de
        valeurs, et une configuration de strategie Nautilus est serialisable.
        """
        mctx = MultiContext(panel)
        mctx._set_multipliers(multiplicateurs)
        mctx._account_history().set_initial(capital)
        for symbole in panel.symbols:
            mctx._context_of(symbole)._set_position_depth(self._regles.warmup_bars)
        self._mctx = mctx
        self._panel = panel
        self._capital = capital
        self._sommet = capital
        self._schedule = schedule

    # -- cycle de vie --------------------------------------------------------

    def on_start(self) -> None:
        if self._mctx is None or self._panel is None:
            raise ConfigurationError(
                "panneau non attache : appeler `attacher(...)` avant `run()`."
            )
        self._regles.reset()
        self._positions = {}
        self._ts_courant = None
        for symbole in self._panel.symbols:
            identifiant = self._identifiant(symbole)
            instrument = self.cache.instrument(identifiant)
            if instrument is None:
                raise ConfigurationError(f"instrument absent du cache : {symbole}")
            self._instruments[symbole] = instrument
            self.subscribe_bars(self._type_de_barre(symbole))

    def on_bar(self, bar: Bar) -> None:
        """Compte les barres jusqu'a ce que la coupe soit complete.

        Voir l'en-tete : declencher a la premiere barre d'un instant faisait
        rejeter TOUS les ordres, les autres instruments n'ayant pas encore de
        marche a cet instant.
        """
        instant = int(bar.ts_event)
        if instant != self._ts_courant:
            self._ts_courant = instant
            self._recues = 0
            self._ligne = self._ligne_de(instant)
            self._attendues = len(self._present_a(self._ligne))
        self._recues += 1
        if self._recues < self._attendues:
            return
        self._traiter_la_ligne(self._ligne)

    def on_order_filled(self, event: object) -> None:
        """Tient la position par symbole, comme le ferait notre runner."""
        quantite = getattr(event, "last_qty", None)
        cote = getattr(event, "order_side", None)
        identifiant = getattr(event, "instrument_id", None)
        if quantite is None or cote is None or identifiant is None:
            return
        # `InstrumentId` se rend en `ES.v.0.SIM` : le symbole est tout ce qui
        # precede le DERNIER point, le venue etant le suffixe. Un `split` sur le
        # premier point couperait `ES.v.0` en deux.
        symbole = str(identifiant).rsplit(".", 1)[0]
        signe = 1 if cote == OrderSide.BUY else -1
        signee = signe * int(quantite.as_double())
        self._positions[symbole] = self._positions.get(symbole, 0) + signee
        self._regles.on_fill(
            Fill(
                order_id=self._prochain_id,
                symbol=symbole,
                side=Side.BUY if signee > 0 else Side.SELL,
                quantity=abs(signee),
                price=float(getattr(event, "last_px", 0.0)),
                fee=0.0,
                slippage_cost=0.0,
                ts_ns=int(getattr(event, "ts_event", 0)),
                bar_index=0,
            )
        )

    def on_stop(self) -> None:
        """La DERNIERE ligne n'est jamais decidee : aucune barre ne l'annonce.

        C'est volontaire et non un oubli. Decider sur la derniere coupe
        reviendrait a soumettre des ordres qu'aucune barre suivante ne pourrait
        remplir - donc a negocier sur une information sans lendemain.
        """
        # Les ordres decides a la DERNIERE ligne ne sont jamais soumis :
        # aucune coupe suivante ne pourrait les remplir.
        self._en_attente.clear()
        self._regles.on_finish()
        for symbole in self._instruments:
            self.cancel_all_orders(self._identifiant(symbole))
            self.close_all_positions(self._identifiant(symbole))

    def on_reset(self) -> None:
        self._regles.reset()
        self._positions = {}
        self._ts_courant = None
        self._en_attente.clear()
        self._sommet = self._capital

    # -- interne -------------------------------------------------------------

    def _ligne_de(self, instant: int) -> int:
        """Index de ligne du panneau pour cet instant. Leve s'il est absent."""
        panel = self._panel
        if panel is None:  # pragma: no cover - `on_start` l'a refuse
            raise ConfigurationError("panneau non attache")
        ligne = int(np.searchsorted(panel.ts_close, instant))
        if ligne >= panel.n_rows or int(panel.ts_close[ligne]) != instant:
            raise ConfigurationError(
                f"instant {instant} absent du calendrier du panneau : les barres "
                f"livrees par Nautilus ne correspondent pas au panneau attache."
            )
        return ligne

    def _present_a(self, ligne: int) -> tuple[str, ...]:
        """Les instruments qui cotent a cette ligne. C'est le COMPTE attendu."""
        panel = self._panel
        if panel is None:  # pragma: no cover
            raise ConfigurationError("panneau non attache")
        return panel.present_symbols(ligne)

    def _traiter_la_ligne(self, ligne: int) -> None:
        """La coupe est complete : executer HIER, puis decider AUJOURD'HUI.

        L'ordre des deux moities porte le decalage d'execution. Decider avant
        de soumettre ferait remplir au prix que la strategie vient de lire.
        """
        mctx = self._mctx
        if mctx is None:  # pragma: no cover - `on_start` l'a refuse
            return

        a_soumettre, self._en_attente = self._en_attente, []
        for ordre in a_soumettre:
            self._soumettre(ordre)

        mctx._seek_row(ligne)
        self._alimenter(mctx, ligne)

        if ligne < self._regles.warmup_bars:
            return
        schedule = self._schedule
        if schedule is not None and not schedule.is_rebalance(ligne):
            return
        self._en_attente.extend(self._regles.on_rebalance(mctx))

    def _alimenter(self, mctx: MultiContext, ligne: int) -> None:
        """Renseigne compte et positions, comme le fait notre runner.

        L'equity vient du `Portfolio` de Nautilus : il n'y a qu'une source de
        verite comptable, et ce n'est pas nous. Le sommet, lui, est suivi ici -
        Nautilus ne le publie pas, et le noeud `account(drawdown)` en depend.
        """
        equity = self._equity()
        self._sommet = max(self._sommet, equity)
        mctx._set_account(
            AccountState(
                equity=equity,
                cash=equity,
                peak_equity=self._sommet,
                initial_equity=self._capital,
            )
        )
        for symbole in mctx.symbols:
            mctx._context_of(symbole)._set_position(
                PositionState(quantity=self._positions.get(symbole, 0))
            )

    def _equity(self) -> float:
        from nautilus_trader.model.currencies import USD
        from nautilus_trader.model.identifiers import Venue

        compte = self.portfolio.account(Venue(self.config.venue))
        if compte is None:  # pragma: no cover - le venue est monte avant le run
            return self._capital
        return float(compte.balance_total(USD).as_double())

    def _identifiant(self, symbole: str) -> Any:
        from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

        return InstrumentId(Symbol(symbole), Venue(self.config.venue))

    def _type_de_barre(self, symbole: str) -> Any:
        from nautilus_trader.model.data import BarType

        from rsl.nautilus.pont import etiquette_executable

        return BarType.from_str(
            f"{symbole}.{self.config.venue}-"
            f"{etiquette_executable(self.config.agregation)}-EXTERNAL"
        )

    def _soumettre(self, ordre: Order) -> None:
        """Notre `Order` vers un ordre Nautilus, sur le bon instrument."""
        instrument = self._instruments.get(ordre.symbol)
        if instrument is None:
            raise ConfigurationError(
                f"la strategie a emis un ordre sur '{ordre.symbol}', hors du panneau"
            )
        self._prochain_id += 1
        identifiant = self._identifiant(ordre.symbol)
        cote = OrderSide.BUY if ordre.side is Side.BUY else OrderSide.SELL
        quantite = instrument.make_qty(ordre.quantity)

        match ordre.order_type:
            case OrderType.MARKET:
                nautilus = self.order_factory.market(
                    instrument_id=identifiant,
                    order_side=cote,
                    quantity=quantite,
                    reduce_only=ordre.reduce_only,
                )
            case OrderType.LIMIT:
                if ordre.limit_price is None:
                    return
                nautilus = self.order_factory.limit(
                    instrument_id=identifiant,
                    order_side=cote,
                    quantity=quantite,
                    price=instrument.make_price(ordre.limit_price),
                    time_in_force=TimeInForce.GTC,
                    reduce_only=ordre.reduce_only,
                )
            case OrderType.STOP:
                if ordre.stop_price is None:
                    return
                nautilus = self.order_factory.stop_market(
                    instrument_id=identifiant,
                    order_side=cote,
                    quantity=quantite,
                    trigger_price=instrument.make_price(ordre.stop_price),
                    reduce_only=ordre.reduce_only,
                )
            case _:  # pragma: no cover - l'enumeration n'a que trois membres
                raise ConfigurationError(f"type d'ordre non porte : {ordre.order_type}")
        self.submit_order(nautilus)
