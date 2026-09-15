"""Le vocabulaire JSON, execute par le moteur Nautilus.

L'idee, et pourquoi elle est courte
------------------------------------
Porter 136 primitives et 23 types de noeuds vers les indicateurs de Nautilus
aurait demande des semaines, et aurait produit une SECONDE definition de chaque
calcul - donc, tot ou tard, deux resultats pour un meme JSON.

Rien de tout cela n'est necessaire. Le vocabulaire ne parle pas a un moteur, il
parle a un `Context` : un curseur sur des barres closes, sans `len()`, sans lag
negatif, sans NaN. Il suffit donc que quelqu'un tienne ce curseur.

C'est ce que fait ce module : **Nautilus mene l'horloge, notre `BarContext`
sert le vocabulaire**. Les 136 primitives et les 23 noeuds fonctionnent sans
qu'une ligne de leur code change, et `rules@1` avec ses neuf cles - pyramidage,
sorties partielles, ordres a cours limite - est reutilise tel quel.

« Mais le magasin contient tout le futur »
-------------------------------------------
Oui, et c'est precisement le point. `BarStore` est immuable et `BarContext` est
concu pour rendre ce futur INATTEIGNABLE : pas de `__len__`, pas de lag negatif,
`InsufficientHistoryError` au lieu d'un NaN. La garantie ne vient pas de ce que
le magasin ignore, elle vient de ce que le contexte refuse.

Reutiliser cet objet conserve donc la garantie entiere. La reecrire au-dessus
d'un tampon glissant l'aurait au contraire remise en jeu, pour rien.

La synchronisation est VERIFIEE, pas supposee
----------------------------------------------
Tout repose sur une correspondance : la n-ieme barre que Nautilus livre doit
etre la n-ieme barre du magasin. Elle l'est par construction - les barres
Nautilus sont engendrees depuis ce magasin - mais « par construction » est
exactement le genre de phrase qui vieillit mal.

`_avancer` compare donc l'horodatage de chaque barre livree a celui du curseur,
et LEVE en cas de desaccord. Un decalage silencieux ferait lire un signal a la
mauvaise barre, ce qui est indiscernable d'un resultat normal.
"""

from __future__ import annotations

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy as StrategyNautilus

from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, PositionState
from rsl.errors import ConfigurationError
from rsl.orders import Fill, Order, OrderType, Side
from rsl.strategies.base import Strategy as StrategyRsl
from rsl.strategies.base import build_strategy

SpecDict = dict[str, object]


class VocabulaireConfig(StrategyConfig, frozen=True):
    """Une strategie du depot, telle qu'elle s'ecrit en JSON.

    `strategie` est le bloc `{"ref": ..., "params": {...}}` d'une
    specification - exactement ce que `build_strategy` attend, et exactement ce
    que `rsl squelette` decrit. Aucune traduction : le JSON qui tourne sur
    notre moteur tourne ici sans etre touche.
    """

    instrument_id: InstrumentId
    bar_type: BarType
    strategie: dict[str, object]
    sur_ticks: bool = False
    """Vider la file au premier TICK de la barre suivante, et non a sa cloture.

    C'est ce qui fait passer le remplissage de `close[t+1]` a `open[t+1]`,
    notre convention. Sans ce basculement, la file se vide dans `on_bar`,
    et Nautilus remplit l'ordre au marche immediatement - donc au dernier
    prix connu, la cloture de la barre qui vient d'arriver.

    Exige que le moteur ait ete monte avec `Montage(en_ticks=True)`, qui
    ajoute les ticks au flux ET bascule l'appariement dessus.

    Reste `False` par defaut : le basculement change les chiffres de tous
    les runs Nautilus, et il doit etre demande.
    """


class VocabulaireNautilus(StrategyNautilus):
    """Execute n'importe quelle strategie `rules@1` sur le moteur Nautilus."""

    def __init__(self, config: VocabulaireConfig) -> None:
        super().__init__(config)
        construite = build_strategy(dict(config.strategie))
        if not isinstance(construite, StrategyRsl):
            raise ConfigurationError(
                f"'{config.strategie.get('ref')}' est une strategie TRANSVERSALE. "
                f"Ce pont ne porte que les strategies mono-instrument ; le "
                f"transversal demande un `MultiContext`, qui n'a pas encore "
                f"d'equivalent Nautilus ici."
            )
        self._regles: StrategyRsl = construite
        self._ctx: BarContext | None = None
        self._position: int = 0
        self._prochain_id: int = 0
        self._en_attente: list[Order] = []
        # `symbol` n'appartient pas au protocole `Strategy` - il est propre aux
        # strategies mono-instrument. Lu une fois ici plutot qu'a chaque fill.
        self._symbole: str = str(getattr(construite, "symbol", ""))

    def attacher(self, store: BarStore) -> None:
        """Branche le magasin qui a servi a engendrer les barres.

        Appele par le lanceur AVANT `run()`. Passer par une methode plutot que
        par la configuration est delibere : un `BarStore` porte des tableaux de
        plusieurs millions de valeurs, et la configuration d'une strategie
        Nautilus est serialisable - y mettre le magasin la rendrait enorme et
        illisible.
        """
        ctx = BarContext(store)
        ctx._set_position_depth(self._regles.warmup_bars)
        # Curseur AVANT la premiere barre : `_avancer` le place sur la barre 0
        # a la premiere livraison.
        ctx._seek(-1)
        self._ctx = ctx

    # -- cycle de vie Nautilus ---------------------------------------------

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"instrument introuvable : {self.config.instrument_id}")
            self.stop()
            return
        if self._ctx is None:
            raise ConfigurationError(
                "magasin non attache : appeler `attacher(store)` avant `run()`."
            )
        self._regles.reset()
        self._position = 0
        self._en_attente.clear()
        self.subscribe_bars(self.config.bar_type)
        if self.config.sur_ticks:
            # Les BARRES portent les signaux, les TICKS portent l'execution.
            # La strategie a besoin des deux, et pour deux raisons
            # differentes.
            self.subscribe_trade_ticks(self.config.instrument_id)

    def on_bar(self, bar: Bar) -> None:
        """Une barre close : d'abord executer ce qui a ete decide HIER.

        L'ordre des deux moities est ce qui reproduit `lag_bars = 1`, et il a
        ete impose par une mesure. Sans differe, Nautilus remplit un ordre au
        marche a la CLOTURE DE LA BARRE QUI L'A DECLENCHE - un prix deja connu
        au moment de decider. Constate le 2026-09-13 sur `_moule.json` : les
        fills tombaient exactement sur `close[t]`, et l'equity finale depassait
        la notre de 19,43 %.

        Faire porter cette garantie par un `LatencyModel` aurait marche sur des
        barres quotidiennes et casse ailleurs : une latence se regle en
        nanosecondes, pas en barres. La file est ici, elle ne depend d'aucun
        defaut de la bibliotheque.
        """
        if not self.config.sur_ticks:
            self._vider_la_file()

        ctx = self._avancer(bar)
        if ctx.n_bars_seen <= self._regles.warmup_bars:
            # Le warmup est celui que la STRATEGIE a declare. Le faire respecter
            # ici plutot que de laisser les noeuds lever garde le meme sens
            # qu'avec notre runner : avant, la strategie ne decide pas.
            return
        self._en_attente.extend(self._regles.on_bar(ctx))

    def _vider_la_file(self) -> None:
        """Soumet ce qui a ete decide avant, puis oublie.

        Extraite pour que les deux moments possibles - la barre suivante ou
        son premier tick - partagent le meme code. Deux copies auraient
        diverge, et la divergence ne se serait vue que dans un chiffre.
        """
        a_soumettre, self._en_attente = self._en_attente, []
        for ordre in a_soumettre:
            self._soumettre(ordre)

    def on_trade_tick(self, tick: object) -> None:
        """Le premier tick apres une decision l'execute.

        C'est ici que `open[t+1]` se produit. Les quatre ticks d'une barre
        tombent STRICTEMENT AVANT sa livraison ; une decision prise sur la
        barre `t` ne rencontre donc son premier tick qu'a l'ouverture de
        `t+1`. La chronologie suffit - aucune regle n'est a faire
        respecter, et c'est pour cela que les ticks sont horodates comme
        ils le sont (voir `rsl/nautilus/ticks.py`).

        Sans `sur_ticks`, cette methode ne fait rien : la file se vide dans
        `on_bar` comme avant, et les comparaisons archivees ne bougent pas.
        """
        if self.config.sur_ticks and self._en_attente:
            self._vider_la_file()

    def on_order_filled(self, event: object) -> None:
        """Rend la position a la strategie, comme le ferait notre runner.

        `rules@1` tient sa propre position et s'en sert pour `position`,
        `allow_pyramiding` et `exit_quantity`. Sans ce retour, elle se croirait
        a plat en permanence et n'emettrait que des entrees.
        """
        remplissage = getattr(event, "last_qty", None)
        cote = getattr(event, "order_side", None)
        if remplissage is None or cote is None:
            return
        signe = 1 if cote == OrderSide.BUY else -1
        quantite = signe * int(remplissage.as_double())
        self._position += quantite
        self._regles.on_fill(self._fill_rsl(event, quantite))

    def on_stop(self) -> None:
        # Les ordres decides a la derniere barre ne sont JAMAIS soumis : il n'y
        # a pas de barre suivante pour les executer. Les passer ici reviendrait
        # a negocier sur une information qui n'a pas eu de lendemain.
        self._en_attente.clear()
        self.cancel_all_orders(self.config.instrument_id)
        self.close_all_positions(self.config.instrument_id)

    def on_reset(self) -> None:
        self._regles.reset()
        self._position = 0
        self._en_attente.clear()
        if self._ctx is not None:
            self._ctx._seek(-1)

    # -- interne ------------------------------------------------------------

    def _avancer(self, bar: Bar) -> BarContext:
        """Avance le curseur d'UNE barre, et verifie la correspondance.

        La verification est le coeur de ce module. Si Nautilus livrait une
        barre qui n'est pas celle du curseur - donnees rechargees dans un autre
        ordre, agregation differente, barre manquante - le vocabulaire lirait
        un signal a la mauvaise date et rendrait un resultat plausible.
        """
        ctx = self._ctx
        if ctx is None:  # pragma: no cover - `on_start` l'aurait deja refuse
            raise ConfigurationError("magasin non attache")
        ctx._advance()
        attendu = int(ctx._store.ts_close[ctx._i])
        if int(bar.ts_event) != attendu:
            raise ConfigurationError(
                f"desynchronisation a la barre {ctx._i} : Nautilus livre "
                f"{bar.ts_event}, le magasin attend {attendu}. Le vocabulaire "
                f"lirait ses signaux a la mauvaise date."
            )
        # L'etat de position de CETTE barre, comme le fait notre runner : c'est
        # lui qui alimente le noeud `position`.
        ctx._set_position(self._etat_de_position(ctx))
        return ctx

    def _etat_de_position(self, ctx: BarContext) -> PositionState:
        """Ce que la strategie sait de sa position a cette barre.

        `bars_held`, `entry_price` et les extremes depuis l'entree ne sont PAS
        renseignes : Nautilus les tient dans son `Portfolio`, sous une autre
        forme, et les recopier approximativement serait pire que de les laisser
        a zero. Consequence assumee et a lever plus tard - les noeuds
        `position(bars_held)` et `position(high_since_entry)` rendent zero sur
        ce pont.
        """
        return PositionState(quantity=self._position)

    def _fill_rsl(self, event: object, quantite: int) -> Fill:
        """Traduit un `OrderFilled` Nautilus vers notre `Fill`.

        Seuls les champs que `rules@1` lit sont renseignes. Les frais et le
        slippage restent a zero : ils sont comptes par Nautilus, et les
        dupliquer ici les ferait apparaitre deux fois si un jour on additionnait
        les deux sources.
        """
        prix = getattr(event, "last_px", None)
        return Fill(
            order_id=self._prochain_id,
            symbol=self._symbole,
            side=Side.BUY if quantite > 0 else Side.SELL,
            quantity=abs(quantite),
            price=float(prix) if prix is not None else 0.0,
            fee=0.0,
            slippage_cost=0.0,
            ts_ns=int(getattr(event, "ts_event", 0)),
            bar_index=self._ctx._i if self._ctx is not None else 0,
        )

    def _soumettre(self, ordre: Order) -> None:
        """Notre `Order` vers un ordre Nautilus.

        Les trois types se correspondent un a un. Le `stop_loss` attache, lui,
        n'a PAS d'equivalent : chez nous c'est une protection geree par le
        runner, ici il faut un ordre separe. Il est donc emis comme un
        `stop_market` `reduce_only`, et `on_position_closed` nettoie ce qui
        reste.
        """
        self._prochain_id += 1
        cote = OrderSide.BUY if ordre.side is Side.BUY else OrderSide.SELL
        quantite = self.instrument.make_qty(ordre.quantity)

        match ordre.order_type:
            case OrderType.MARKET:
                nautilus = self.order_factory.market(
                    instrument_id=self.config.instrument_id,
                    order_side=cote,
                    quantity=quantite,
                    reduce_only=ordre.reduce_only,
                )
            case OrderType.LIMIT:
                if ordre.limit_price is None:
                    return
                nautilus = self.order_factory.limit(
                    instrument_id=self.config.instrument_id,
                    order_side=cote,
                    quantity=quantite,
                    price=self.instrument.make_price(ordre.limit_price),
                    time_in_force=TimeInForce.GTC,
                    reduce_only=ordre.reduce_only,
                )
            case OrderType.STOP:
                if ordre.stop_price is None:
                    return
                nautilus = self.order_factory.stop_market(
                    instrument_id=self.config.instrument_id,
                    order_side=cote,
                    quantity=quantite,
                    trigger_price=self.instrument.make_price(ordre.stop_price),
                    reduce_only=ordre.reduce_only,
                )
            case _:  # pragma: no cover - l'enumeration n'a que trois membres
                raise ConfigurationError(f"type d'ordre non porte : {ordre.order_type}")

        self.submit_order(nautilus)
        self._poser_protections(ordre, cote)

    def _poser_protections(self, ordre: Order, cote: OrderSide) -> None:
        """Le `stop_loss` et le `take_profit` attaches a une entree.

        Emis en `reduce_only` et dans le sens INVERSE de l'entree. Un stop qui
        ne serait pas `reduce_only` ouvrirait une position opposee quand il
        touche - l'erreur que `revalidate_reduction` rend impossible de notre
        cote, et qu'il faut ici interdire explicitement.
        """
        if ordre.reduce_only:
            return
        inverse = OrderSide.SELL if cote == OrderSide.BUY else OrderSide.BUY
        quantite = self.instrument.make_qty(ordre.quantity)
        if ordre.stop_loss is not None and ordre.stop_loss > 0.0:
            self.submit_order(
                self.order_factory.stop_market(
                    instrument_id=self.config.instrument_id,
                    order_side=inverse,
                    quantity=quantite,
                    trigger_price=self.instrument.make_price(ordre.stop_loss),
                    reduce_only=True,
                )
            )
        if ordre.take_profit is not None and ordre.take_profit > 0.0:
            self.submit_order(
                self.order_factory.limit(
                    instrument_id=self.config.instrument_id,
                    order_side=inverse,
                    quantity=quantite,
                    price=self.instrument.make_price(ordre.take_profit),
                    time_in_force=TimeInForce.GTC,
                    reduce_only=True,
                )
            )

    def on_position_closed(self, event: object) -> None:
        """Les protections survivantes n'ont plus d'objet une fois a plat."""
        self.cancel_all_orders(self.config.instrument_id)
