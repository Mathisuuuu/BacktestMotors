"""Nos strategies, exprimees pour le moteur Nautilus.

Ce fichier est le POINT DE COMPARAISON, pas encore le remplacement. Tant que
les deux moteurs n'ont pas ete confrontes sur la meme serie, supprimer le notre
serait un acte de foi.

`SmaCrossoverNautilus` reproduit `sma_crossover@1` terme a terme :

- moyennes simples `fast` et `slow` sur les clotures ;
- entree quand `fast` croise la `slow` VERS LE HAUT, et seulement a plat ;
- sortie quand elle croise vers le bas, et seulement en position ;
- stop a `cloture - atr_multiple x ATR(atr_window)`, pose A L'ENTREE et fige.

Trois desaccords de modele, tous documentes ici plutot que masques
------------------------------------------------------------------
1. **L'ATR.** Notre `atr@1` est une moyenne SIMPLE des vrais ranges. Celui de
   Nautilus 1.221 a le meme defaut - verifie, pas suppose - mais nous le
   demandons explicitement quand meme : la famille porte aussi une variante de
   Wilder, et un defaut qui changerait entre deux versions deplacerait tous
   nos stops sans qu'aucune ligne ne le dise.

2. **Le decalage d'execution.** Notre moteur soumet a la barre `t` et remplit a
   `t+1` (`lag_bars >= 1`). Nautilus remplit l'ordre au marche des la barre
   suivante egalement, mais c'est le SIMULATEUR qui en decide - la propriete
   n'est pas la meme, elle est configuree et non structurelle.

3. **Le stop.** Chez nous, un `stop_loss` attache a l'ordre devient une
   protection geree par le runner. Ici, il devient un ordre STOP_MARKET separe,
   lie par `reduce_only`. Le comportement se ressemble ; l'ordre d'evaluation
   intra-barre, non. C'est l'une des choses que la comparaison doit chiffrer.
"""

from __future__ import annotations

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.message import Event
from nautilus_trader.indicators.averages import (
    MovingAverageType,
    SimpleMovingAverage,
)
from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


class SmaCrossoverConfig(StrategyConfig, frozen=True):
    """Les memes parametres que `sma_crossover@1`, aux memes defauts."""

    instrument_id: InstrumentId
    bar_type: BarType
    fast_window: int = 20
    slow_window: int = 100
    quantity: int = 1
    atr_window: int = 14
    atr_multiple: float = 2.0


class SmaCrossoverNautilus(Strategy):
    """Croisement SMA rapide / lente, long seulement, avec stop ATR."""

    def __init__(self, config: SmaCrossoverConfig) -> None:
        super().__init__(config)
        self.fast = SimpleMovingAverage(config.fast_window)
        self.slow = SimpleMovingAverage(config.slow_window)
        # Explicite bien que ce soit deja le defaut : voir l'en-tete.
        self.atr = AverageTrueRange(
            config.atr_window, ma_type=MovingAverageType.SIMPLE
        )
        self._fast_precedent: float | None = None
        self._slow_precedent: float | None = None

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"instrument introuvable : {self.config.instrument_id}")
            self.stop()
            return
        self.register_indicator_for_bars(self.config.bar_type, self.fast)
        self.register_indicator_for_bars(self.config.bar_type, self.slow)
        self.register_indicator_for_bars(self.config.bar_type, self.atr)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        """Une barre CLOSE. Les indicateurs sont deja a jour (Nautilus les met a
        jour avant le callback), donc `self.fast.value` porte la barre courante.

        Le croisement se lit sur DEUX barres, donc on garde les valeurs
        precedentes - exactement comme notre `ctx.shifted(1)`. Les recalculer
        depuis l'historique serait possible mais introduirait une seconde
        definition du « precedent ».
        """
        if not (self.fast.initialized and self.slow.initialized):
            return

        fast_now, slow_now = self.fast.value, self.slow.value
        fast_prev, slow_prev = self._fast_precedent, self._slow_precedent
        self._fast_precedent, self._slow_precedent = fast_now, slow_now
        if fast_prev is None or slow_prev is None:
            return

        position = self.portfolio.net_position(self.config.instrument_id)

        if position > 0 and fast_prev >= slow_prev and fast_now < slow_now:
            self.close_all_positions(self.config.instrument_id)
            return

        if position == 0 and fast_prev <= slow_prev and fast_now > slow_now:
            self._entrer(bar)

    def _entrer(self, bar: Bar) -> None:
        """Entree au marche, plus un stop si l'ATR est calculable.

        Meme convention que chez nous : un stop nul ou negatif n'est PAS pose.
        Mieux vaut une position sans stop qu'un stop absurde - et le cas se
        produit sur une serie plate, ou l'ATR vaut zero.
        """
        ordre = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.instrument.make_qty(self.config.quantity),
        )
        self.submit_order(ordre)

        if not self.atr.initialized or self.atr.value <= 0.0:
            return
        niveau = float(bar.close) - self.config.atr_multiple * self.atr.value
        if niveau <= 0.0:
            return
        self.submit_order(
            self.order_factory.stop_market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.SELL,
                quantity=self.instrument.make_qty(self.config.quantity),
                trigger_price=self.instrument.make_price(niveau),
                reduce_only=True,
            )
        )

    def on_event(self, event: Event) -> None:
        """Quand la position se ferme, les stops residuels n'ont plus d'objet.

        Sans cela, un stop survivant declencherait une position COURTE a la
        prochaine baisse - l'erreur classique que notre `revalidate_reduction`
        rend impossible de son cote.
        """
        if self.portfolio.is_flat(self.config.instrument_id):
            self.cancel_all_orders(self.config.instrument_id)

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.close_all_positions(self.config.instrument_id)

    def on_reset(self) -> None:
        self.fast.reset()
        self.slow.reset()
        self.atr.reset()
        self._fast_precedent = None
        self._slow_precedent = None
