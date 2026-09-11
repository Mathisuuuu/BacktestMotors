"""Contrat des strategies, `RuleStrategy` et registre versionne."""

from __future__ import annotations

import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, Field, PositionState
from rsl.engine.orders import Fill, Order, OrderType, Side
from rsl.errors import ConfigurationError, RegistryError
from rsl.strategies.base import (
    NoStrategyParams,
    Strategy,
    StrategyParams,
    build_strategy,
    describe_strategies,
    get_strategy,
    list_strategies,
    strategy,
)
from rsl.strategies.rules import FlatStrategy, RuleStrategy
from rsl.strategies.signals import (
    FALSE,
    TRUE,
    Arith,
    ArithOp,
    Compare,
    CompareOp,
    CrossesAbove,
    CrossesBelow,
    Position,
    Rolling,
    RollingStat,
    const,
    price,
    prim,
)

SINE = synthetic.sine(600, 100.0, 10.0, 64)


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


def fill_for(order: Order, price_: float = 100.0) -> Fill:
    return Fill(
        order_id=0,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        price=price_,
        fee=0.0,
        slippage_cost=0.0,
        ts_ns=0,
        bar_index=0,
        tag=order.tag,
    )


def crossover_strategy(**overrides: object) -> RuleStrategy:
    fast, slow = prim("sma@1", window=5), prim("sma@1", window=20)
    defaults: dict[str, object] = {
        "symbol": "SYNTH.v.0",
        "quantity": 1,
        "entry_long": CrossesAbove(fast, slow),
        "exit_long": CrossesBelow(fast, slow),
    }
    defaults.update(overrides)
    return RuleStrategy(**defaults)  # type: ignore[arg-type]


class TestOrderTypes:
    def test_quantity_must_be_positive(self):
        with pytest.raises(ConfigurationError, match="quantity"):
            Order(symbol="X", side=Side.BUY, quantity=0)

    def test_side_carries_the_direction(self):
        assert Order(symbol="X", side=Side.SELL, quantity=3).signed_quantity == -3
        assert Side.BUY.opposite is Side.SELL

    def test_limit_requires_a_level(self):
        with pytest.raises(ConfigurationError, match="LIMIT"):
            Order(symbol="X", side=Side.BUY, quantity=1, order_type=OrderType.LIMIT)

    def test_stop_requires_a_level(self):
        with pytest.raises(ConfigurationError, match="STOP"):
            Order(symbol="X", side=Side.BUY, quantity=1, order_type=OrderType.STOP)

    def test_market_refuses_a_useless_level(self):
        with pytest.raises(ConfigurationError, match="MARKET"):
            Order(symbol="X", side=Side.BUY, quantity=1, limit_price=100.0)

    def test_reduce_only_cannot_attach_protections(self):
        with pytest.raises(ConfigurationError, match="reduce_only"):
            Order(symbol="X", side=Side.SELL, quantity=1, reduce_only=True, stop_loss=90.0)

    def test_orders_are_frozen(self):
        order = Order(symbol="X", side=Side.BUY, quantity=1)
        with pytest.raises(Exception, match=r"cannot assign|frozen|immutable"):
            order.quantity = 2  # type: ignore[misc]

    def test_orders_carry_no_identifier(self):
        """Un identifiant genere par la strategie casserait le determinisme."""
        assert not hasattr(Order(symbol="X", side=Side.BUY, quantity=1), "id")


class TestFlatStrategy:
    def test_never_emits_an_order(self):
        store = synthetic.make_store(SINE)
        flat = FlatStrategy()
        assert flat.warmup_bars == 0
        for i in range(0, 600, 37):
            assert flat.on_bar(at(store, i)) == ()


class TestRuleStrategyWarmup:
    def test_warmup_is_the_deepest_rule(self):
        assert crossover_strategy().warmup_bars == 21

    def test_extra_warmup_is_added(self):
        assert crossover_strategy(extra_warmup=100).warmup_bars == 121

    def test_stop_rule_counts_towards_warmup(self):
        stop = Arith(price("close"), ArithOp.SUB, prim("atr@1", window=100))
        assert crossover_strategy(stop_loss=stop).warmup_bars == 101

    def test_negative_extra_warmup_refused(self):
        with pytest.raises(ConfigurationError, match="extra_warmup"):
            crossover_strategy(extra_warmup=-1)

    def test_a_strategy_without_any_entry_is_refused(self):
        with pytest.raises(ConfigurationError, match="FlatStrategy"):
            RuleStrategy(symbol="X", quantity=1)

    def test_non_positive_quantity_refused(self):
        with pytest.raises(ConfigurationError, match="quantity"):
            crossover_strategy(quantity=0)


class TestRuleStrategyBehaviour:
    def test_enters_long_on_a_bullish_cross(self):
        store = synthetic.make_store(SINE)
        strat = crossover_strategy()
        entries = [
            order
            for i in range(strat.warmup_bars, 600)
            for order in strat.on_bar(at(store, i))
        ]
        assert entries
        assert all(o.side is Side.BUY and o.tag == "entry_long" for o in entries)

    def test_does_not_pyramid_by_default(self):
        store = synthetic.make_store(SINE)
        strat = crossover_strategy()
        position = 0
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                position += order.signed_quantity
                assert abs(position) <= 1

    def test_pyramiding_can_be_enabled(self):
        store = synthetic.make_store(SINE)
        strat = crossover_strategy(allow_pyramiding=True)
        position = 0
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                position += order.signed_quantity
        assert position >= 1

    def test_exit_is_reduce_only(self):
        store = synthetic.make_store(SINE)
        strat = crossover_strategy()
        exits: list[Order] = []
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                if order.tag == "exit_long":
                    exits.append(order)
        assert exits
        assert all(o.reduce_only and o.side is Side.SELL for o in exits)

    def test_no_exit_is_emitted_while_flat(self):
        """Une sortie sans position ouvrirait une position inverse : interdit.

        La regle de sortie se declenche souvent alors que la strategie est
        plate (croisement baissier sans position). Le test verifie qu'aucun
        ordre `reduce_only` n'est emis dans ce cas - pas seulement qu'il serait
        neutralise plus tard par le moteur.
        """
        store = synthetic.make_store(SINE)
        strat = crossover_strategy()
        seen_flat_exit_opportunity = False
        for i in range(strat.warmup_bars, 600):
            position_before = strat._position
            orders = strat.on_bar(at(store, i))
            if position_before == 0:
                assert not [o for o in orders if o.reduce_only]
                if strat.exit_long is not None and strat.exit_long(at(store, i)) == 1.0:
                    seen_flat_exit_opportunity = True
            for order in orders:
                strat.on_fill(fill_for(order))
        assert seen_flat_exit_opportunity, "le scenario teste ne s'est jamais presente"

    def test_reset_clears_the_position(self):
        strat = crossover_strategy()
        strat.on_fill(fill_for(Order(symbol="SYNTH.v.0", side=Side.BUY, quantity=1)))
        assert strat._position == 1
        strat.reset()
        assert strat._position == 0

    def test_fills_of_another_symbol_are_ignored(self):
        strat = crossover_strategy()
        strat.on_fill(fill_for(Order(symbol="AUTRE", side=Side.BUY, quantity=5)))
        assert strat._position == 0

    def test_undefined_signal_triggers_nothing(self):
        """Un signal indefini n'est pas une raison d'agir."""
        flat_store = synthetic.make_store(synthetic.constant(300, 50.0))
        strat = RuleStrategy(
            symbol="SYNTH.v.0",
            quantity=1,
            entry_long=Compare(prim("zscore@1", window=20), CompareOp.GT, const(0.0)),
        )
        for i in range(strat.warmup_bars, 300, 13):
            assert strat.on_bar(at(flat_store, i)) == []

    def test_attached_stop_level_is_computed_from_the_signal(self):
        store = synthetic.make_store(SINE)
        stop = Arith(price("close"), ArithOp.SUB, prim("atr@1", window=14))
        strat = crossover_strategy(stop_loss=stop)
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                if order.tag == "entry_long":
                    assert order.stop_loss is not None
                    assert order.stop_loss < at(store, i).bar.close
                    return
        pytest.fail("aucune entree produite")

    def test_short_side_works_symmetrically(self):
        store = synthetic.make_store(SINE)
        fast, slow = prim("sma@1", window=5), prim("sma@1", window=20)
        strat = RuleStrategy(
            symbol="SYNTH.v.0",
            quantity=1,
            entry_short=CrossesBelow(fast, slow),
            exit_short=CrossesAbove(fast, slow),
        )
        position = 0
        for i in range(strat.warmup_bars, 600):
            for order in strat.on_bar(at(store, i)):
                strat.on_fill(fill_for(order))
                position += order.signed_quantity
                assert -1 <= position <= 0
        assert position <= 0


class TestRuleStrategySpec:
    def test_describe_then_rebuild_is_equivalent(self):
        original = crossover_strategy()
        rebuilt = RuleStrategy.from_spec(original.describe())
        assert rebuilt.describe() == original.describe()
        assert rebuilt.warmup_bars == original.warmup_bars

    def test_rebuilt_strategy_produces_the_same_orders(self):
        store = synthetic.make_store(SINE)
        original = crossover_strategy()
        rebuilt = RuleStrategy.from_spec(original.describe())
        for i in range(original.warmup_bars, 400):
            ctx = at(store, i)
            a, b = original.on_bar(ctx), rebuilt.on_bar(ctx)
            assert a == b
            for order in a:
                original.on_fill(fill_for(order))
            for order in b:
                rebuilt.on_fill(fill_for(order))

    def test_spec_is_json_serialisable(self):
        import json

        spec = crossover_strategy().describe()
        assert json.loads(json.dumps(spec)) == spec

    def test_missing_symbol_refused(self):
        with pytest.raises(ConfigurationError, match="symbol"):
            RuleStrategy.from_spec({"quantity": 1, "rules": {}})

    def test_missing_quantity_refused(self):
        with pytest.raises(ConfigurationError, match="quantity"):
            RuleStrategy.from_spec({"symbol": "X", "rules": {}})


class TestStrategyRegistry:
    def test_register_build_and_describe(self):
        class Params(StrategyParams):
            window: int = 10

        @strategy("test_probe_strategy", version=1, params=Params, summary="sonde")
        def _factory(params: StrategyParams) -> Strategy:
            assert isinstance(params, Params)
            return FlatStrategy()

        entry = get_strategy("test_probe_strategy")
        assert entry.version == 1
        assert entry.summary == "sonde"
        assert isinstance(entry.build({"window": 5}), FlatStrategy)
        assert any(e["ref"] == "test_probe_strategy@1" for e in describe_strategies())

    def test_build_from_spec(self):
        @strategy("test_spec_strategy", version=1)
        def _factory(params: StrategyParams) -> Strategy:
            return FlatStrategy()

        assert isinstance(build_strategy({"ref": "test_spec_strategy@1"}), FlatStrategy)
        assert isinstance(build_strategy({"ref": "test_spec_strategy"}), FlatStrategy)

    def test_unknown_strategy_raises(self):
        with pytest.raises(RegistryError, match="inconnue"):
            get_strategy("nope")

    def test_spec_without_ref_refused(self):
        with pytest.raises(ConfigurationError, match="'ref'"):
            build_strategy({"params": {}})

    def test_unknown_parameter_refused(self):
        class Params(StrategyParams):
            window: int = 10

        @strategy("test_strict_params", version=1, params=Params)
        def _factory(params: StrategyParams) -> Strategy:
            return FlatStrategy()

        with pytest.raises(Exception, match=r"extra|windwo"):
            build_strategy({"ref": "test_strict_params@1", "params": {"windwo": 3}})

    def test_listing_is_sorted(self):
        names = [(e.name, e.version) for e in list_strategies()]
        assert names == sorted(names)

    def test_no_params_model_accepts_empty(self):
        assert NoStrategyParams().model_dump() == {}


class TestTypeDOrdreALEntree:
    """`entry_limit` et `entry_stop` : le moteur savait deja, le vocabulaire non.

    Semantique a connaitre, et elle surprend : un ordre a limite vaut pour la
    SEULE barre d'execution. S'il n'est pas touche, l'entree est abandonnee et
    comptee dans `n_orders_cancelled_unfilled`. Ce n'est pas un ordre au
    carnet qui attendrait plusieurs barres.
    """

    def barre_declenchante(self) -> BarContext:
        store = synthetic.make_store(synthetic.ramp(60, 100.0, 1.0))
        ctx = BarContext(store)
        for _ in range(40):
            ctx._advance()
        return ctx

    def ordres(self, **overrides: object) -> list[Order]:
        """Entree TOUJOURS vraie : ce qui est teste ici est le type d'ordre, pas
        le declenchement. Dependre d'un croisement ferait echouer ces tests pour
        une raison sans rapport avec ce qu'ils gardent."""
        params: dict[str, object] = {
            "symbol": "SYNTH.v.0", "quantity": 1, "entry_long": const(TRUE),
        }
        params.update(overrides)
        strategie = RuleStrategy(**params)  # type: ignore[arg-type]
        return list(strategie.on_bar(self.barre_declenchante()))

    def test_sans_rien_declarer_l_ordre_reste_au_marche(self):
        """Retrocompatibilite : aucune specification existante ne change."""
        (ordre,) = self.ordres()
        assert ordre.order_type is OrderType.MARKET
        assert ordre.limit_price is None and ordre.stop_price is None

    def test_entry_limit_produit_un_ordre_a_limite(self):
        (ordre,) = self.ordres(entry_limit=const(123.5))
        assert ordre.order_type is OrderType.LIMIT
        assert ordre.limit_price == pytest.approx(123.5)
        assert ordre.stop_price is None

    def test_entry_stop_produit_un_ordre_a_seuil(self):
        (ordre,) = self.ordres(entry_stop=const(150.0))
        assert ordre.order_type is OrderType.STOP
        assert ordre.stop_price == pytest.approx(150.0)
        assert ordre.limit_price is None

    def test_le_prix_vient_d_une_expression_pas_d_une_constante(self):
        """C'est tout l'interet : « une ATR sous la cloture » s'ecrit."""
        niveau = Arith(price("close"), ArithOp.SUB, prim("atr@1", window=5))
        (ordre,) = self.ordres(entry_limit=niveau)
        assert ordre.order_type is OrderType.LIMIT
        assert ordre.limit_price is not None
        assert ordre.limit_price < self.barre_declenchante().value(Field.CLOSE)

    def test_les_deux_ensemble_sont_refuses(self):
        """Un ordre a un seul type : repli OU cassure, pas les deux."""
        with pytest.raises(ConfigurationError, match="exclusifs"):
            RuleStrategy(symbol="X", quantity=1, entry_long=const(TRUE),
                         entry_limit=const(1.0), entry_stop=const(2.0))

    def test_un_prix_indefini_abandonne_l_entree(self):
        """Le point delicat : il ne FAUT PAS retomber sur un ordre au marche.

        Ce serait changer silencieusement le type d'ordre, donc le
        comportement, au moment ou l'on en sait le moins.
        """
        indefini = Rolling(RollingStat.MEAN, 5000, price("close"))
        assert self.ordres(entry_limit=indefini) == []

    def test_une_sortie_reste_au_marche_et_reduce_only(self):
        """Le type d'ordre ne concerne que l'ENTREE : `stop_loss` et
        `take_profit` couvrent deja la sortie, attaches a l'ordre."""
        strategie = RuleStrategy(
            symbol="SYNTH.v.0", quantity=1, entry_long=const(TRUE),
            exit_long=const(TRUE), entry_limit=const(90.0),
        )
        strategie.on_fill(fill_for(
            Order(symbol="SYNTH.v.0", side=Side.BUY, quantity=1)
        ))
        sorties = [o for o in strategie.on_bar(self.barre_declenchante())
                   if o.reduce_only]
        assert sorties, "la sortie doit etre emise"
        for ordre in sorties:
            assert ordre.order_type is OrderType.MARKET

    def test_le_warmup_couvre_le_signal_de_prix(self):
        strategie = RuleStrategy(
            symbol="X", quantity=1, entry_long=const(TRUE),
            entry_limit=Rolling(RollingStat.MEAN, 120, price("close")),
        )
        assert strategie.warmup_bars >= 120

    def test_aller_retour_declaratif(self):
        strategie = RuleStrategy(symbol="SYNTH.v.0", quantity=1,
                                 entry_long=const(TRUE), entry_stop=const(42.0))
        decrit = strategie.describe()
        assert decrit["rules"]["entry_stop"] == {"type": "constant", "version": 1,
                                                 "value": 42.0}
        reconstruit = RuleStrategy.from_spec({
            "symbol": "SYNTH.v.0", "quantity": 1,
            "rules": {
                "entry_long": {"type": "constant", "value": 1.0},
                "entry_stop": {"type": "constant", "value": 42.0},
            },
        })
        (ordre,) = reconstruit.on_bar(self.barre_declenchante())
        assert ordre.order_type is OrderType.STOP
        assert ordre.stop_price == pytest.approx(42.0)


class TestSortiePartielle:
    """`exit_quantity` : alleger au lieu de tout fermer.

    Sans cette cle, une sortie est tout ou rien - c'etait la troisieme des
    limites trouvees en comparant le moteur au vocabulaire.
    """

    def contexte(self) -> BarContext:
        store = synthetic.make_store(synthetic.ramp(60, 100.0, 1.0))
        ctx = BarContext(store)
        for _ in range(40):
            ctx._advance()
        return ctx

    def en_position(self, taille: int, **overrides: object) -> RuleStrategy:
        """Strategie deja en position, sortie declenchee a la prochaine barre."""
        params: dict[str, object] = {
            "symbol": "SYNTH.v.0", "quantity": abs(taille),
            "entry_long": const(FALSE), "entry_short": const(FALSE),
            "exit_long": const(TRUE), "exit_short": const(TRUE),
        }
        params.update(overrides)
        strategie = RuleStrategy(**params)  # type: ignore[arg-type]
        cote = Side.BUY if taille > 0 else Side.SELL
        strategie.on_fill(fill_for(
            Order(symbol="SYNTH.v.0", side=cote, quantity=abs(taille))
        ))
        return strategie

    def test_sans_la_cle_la_position_entiere_est_fermee(self):
        """Retrocompatibilite : le comportement d'avant, inchange."""
        (ordre,) = self.en_position(5).on_bar(self.contexte())
        assert ordre.quantity == 5
        assert ordre.side is Side.SELL and ordre.reduce_only

    def test_une_quantite_partielle_est_respectee(self):
        (ordre,) = self.en_position(5, exit_quantity=const(2.0)).on_bar(self.contexte())
        assert ordre.quantity == 2

    def test_la_demande_est_bornee_a_ce_qui_est_detenu(self):
        """L'ordre est `reduce_only` de toute facon ; mieux vaut le dire ici."""
        (ordre,) = self.en_position(3, exit_quantity=const(99.0)).on_bar(self.contexte())
        assert ordre.quantity == 3

    def test_le_signe_est_ignore_car_la_quantite_est_une_magnitude(self):
        """C'est ce qui permet d'ecrire `position.quantity * 0.5` et d'alleger
        de moitie qu'on soit long ou court, `quantity` etant signee."""
        moitie = Arith(Position("quantity"), ArithOp.MUL, const(0.5))

        def avec_position(taille: int):
            """Le compteur interne de la strategie et l'etat expose par le
            contexte sont deux choses distinctes : en run reel le runner les
            garde d'accord, ici il faut renseigner les deux."""
            ctx = self.contexte()
            ctx._set_position(PositionState(quantity=taille))
            return self.en_position(taille, exit_quantity=moitie).on_bar(ctx)

        (long_,) = avec_position(4)
        (court,) = avec_position(-4)
        assert long_.quantity == 2 and long_.side is Side.SELL
        assert court.quantity == 2 and court.side is Side.BUY

    def test_moins_d_un_contrat_n_emet_rien(self):
        """On ne ferme pas une fraction de contrat, et arrondir a 1 trahirait
        l'intention."""
        assert self.en_position(1, exit_quantity=const(0.4)).on_bar(self.contexte()) == []

    def test_une_quantite_nulle_ou_negative_n_emet_rien(self):
        assert self.en_position(5, exit_quantity=const(0.0)).on_bar(self.contexte()) == []

    def test_un_signal_indefini_n_emet_rien(self):
        """Meme convention que partout : « je ne sais pas » n'est pas une
        raison d'agir."""
        indefini = Rolling(RollingStat.MEAN, 5000, price("close"))
        assert self.en_position(5, exit_quantity=indefini).on_bar(self.contexte()) == []

    def test_la_sortie_partielle_reste_reduce_only(self):
        (ordre,) = self.en_position(5, exit_quantity=const(2.0)).on_bar(self.contexte())
        assert ordre.reduce_only is True

    def test_alleger_laisse_la_position_ouverte(self):
        """La propriete qui definit la sortie partielle."""
        strategie = self.en_position(5, exit_quantity=const(2.0))
        (ordre,) = strategie.on_bar(self.contexte())
        strategie.on_fill(fill_for(ordre))
        assert strategie._position == 3

    def test_le_warmup_couvre_le_signal_de_quantite(self):
        strategie = RuleStrategy(
            symbol="X", quantity=1, entry_long=const(TRUE),
            exit_quantity=Rolling(RollingStat.MEAN, 150, price("close")),
        )
        assert strategie.warmup_bars >= 150

    def test_aller_retour_declaratif(self):
        reconstruit = RuleStrategy.from_spec({
            "symbol": "SYNTH.v.0", "quantity": 5,
            "rules": {
                "entry_long": {"type": "constant", "value": 0.0},
                "exit_long": {"type": "constant", "value": 1.0},
                "exit_quantity": {"type": "constant", "value": 2.0},
            },
        })
        reconstruit.on_fill(fill_for(
            Order(symbol="SYNTH.v.0", side=Side.BUY, quantity=5)
        ))
        (ordre,) = reconstruit.on_bar(self.contexte())
        assert ordre.quantity == 2
