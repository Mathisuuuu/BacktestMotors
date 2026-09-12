"""Dimensionnement, troncature vers zero, garde-fous de marge."""

from __future__ import annotations

from typing import ClassVar

import pytest

from rsl.data.feed import BarContext
from rsl.data.schema import BarStore
from rsl.engine.execution import MarginPolicy
from rsl.engine.limites import MOTIFS, PortfolioLimits
from rsl.engine.portfolio import Portfolio
from rsl.engine.risk import (
    EquityFraction,
    FixedContracts,
    RiskFraction,
    RiskManager,
    SizingRule,
)
from rsl.errors import ConfigurationError
from rsl.orders import Fill, Order, Side

SYMBOL = "TEST.v.0"
CASH = 100_000.0


@pytest.fixture
def ctx(test_store: BarStore) -> BarContext:
    context = BarContext(test_store)
    for _ in range(100):
        context._advance()
    return context


@pytest.fixture
def portfolio(spec) -> Portfolio:
    return Portfolio(CASH, {SYMBOL: spec})


def marks_of(ctx: BarContext) -> dict[str, float]:
    return {SYMBOL: ctx.bar.close}


def entry(quantity: int = 1) -> Order:
    return Order(symbol=SYMBOL, side=Side.BUY, quantity=quantity, tag="entry")


def hold(portfolio: Portfolio, quantity: int, price: float = 100.0) -> None:
    portfolio.begin_bar()
    portfolio.apply_fill(
        Fill(
            order_id=0,
            symbol=SYMBOL,
            side=Side.BUY if quantity > 0 else Side.SELL,
            quantity=abs(quantity),
            price=price,
            fee=0.0,
            slippage_cost=0.0,
            ts_ns=0,
            bar_index=0,
        )
    )
    portfolio.end_bar({SYMBOL: price})


class TestSizingRules:
    def test_all_rules_satisfy_the_protocol(self):
        for rule in (FixedContracts(2), EquityFraction(0.5), RiskFraction(0.01)):
            assert isinstance(rule, SizingRule)

    def test_fixed_contracts(self, ctx, spec):
        assert FixedContracts(3).contracts(ctx, spec, CASH, 100.0) == 3
        assert FixedContracts(3).warmup_bars == 0

    def test_fixed_contracts_below_one_refused(self):
        with pytest.raises(ConfigurationError, match="n doit"):
            FixedContracts(0)

    def test_equity_fraction(self, ctx, spec):
        # 100 000 * 0,5 / (100 * 50) = 10 contrats
        assert EquityFraction(0.5).contracts(ctx, spec, 100_000.0, 100.0) == 10

    def test_equity_fraction_truncates_towards_zero(self, ctx, spec):
        """0,9 contrat donne 0, pas 1 : `round` creerait une position non voulue."""
        assert EquityFraction(0.5).contracts(ctx, spec, 9_000.0, 100.0) == 0
        assert EquityFraction(0.5).contracts(ctx, spec, 19_000.0, 100.0) == 1

    def test_equity_fraction_refuses_non_positive(self):
        with pytest.raises(ConfigurationError, match="fraction"):
            EquityFraction(0.0)

    def test_risk_fraction_uses_the_atr(self, ctx, spec):
        from rsl.primitives.registry import bind_primitive

        atr = bind_primitive("atr@1", window=14)(ctx)
        assert atr is not None
        rule = RiskFraction(0.01, atr_window=14, atr_multiple=2.0)
        expected = int(CASH * 0.01 / (2.0 * atr * spec.multiplier))
        assert rule.contracts(ctx, spec, CASH, ctx.bar.close) == expected

    def test_risk_fraction_warmup_covers_the_atr(self):
        assert RiskFraction(0.01, atr_window=20).warmup_bars == 21

    @pytest.mark.parametrize(
        "kwargs", [{"fraction": 0.0}, {"fraction": 1.0}, {"fraction": 0.1, "atr_window": 0},
                   {"fraction": 0.1, "atr_multiple": 0.0}]
    )
    def test_risk_fraction_validation(self, kwargs):
        with pytest.raises(ConfigurationError):
            RiskFraction(**kwargs)

    def test_describe_is_serialisable(self):
        import json

        for rule in (FixedContracts(2), EquityFraction(0.5), RiskFraction(0.01)):
            assert json.loads(json.dumps(rule.describe())) == rule.describe()


class TestReduceOnly:
    def test_dropped_when_flat(self, ctx, portfolio):
        manager = RiskManager()
        order = Order(symbol=SYMBOL, side=Side.SELL, quantity=1, reduce_only=True)
        assert manager.prepare(order, ctx, portfolio, marks_of(ctx)) is None
        assert manager.stats.n_reduce_only_dropped == 1

    def test_dropped_when_it_would_add_to_the_position(self, ctx, portfolio):
        hold(portfolio, 2)
        manager = RiskManager()
        order = Order(symbol=SYMBOL, side=Side.BUY, quantity=1, reduce_only=True)
        assert manager.prepare(order, ctx, portfolio, marks_of(ctx)) is None

    def test_capped_to_the_held_quantity(self, ctx, portfolio):
        hold(portfolio, 2)
        manager = RiskManager()
        order = Order(symbol=SYMBOL, side=Side.SELL, quantity=10, reduce_only=True)
        prepared = manager.prepare(order, ctx, portfolio, marks_of(ctx))
        assert prepared is not None
        assert prepared.quantity == 2
        assert prepared.reduce_only

    def test_passes_through_unchanged_when_it_fits(self, ctx, portfolio):
        hold(portfolio, 5)
        manager = RiskManager()
        order = Order(symbol=SYMBOL, side=Side.SELL, quantity=5, reduce_only=True)
        assert manager.prepare(order, ctx, portfolio, marks_of(ctx)) is order

    def test_reduce_only_is_never_resized_by_the_sizing_rule(self, ctx, portfolio):
        hold(portfolio, 2)
        manager = RiskManager(sizing=FixedContracts(7))
        order = Order(symbol=SYMBOL, side=Side.SELL, quantity=2, reduce_only=True)
        prepared = manager.prepare(order, ctx, portfolio, marks_of(ctx))
        assert prepared is not None
        assert prepared.quantity == 2


class TestSizingApplication:
    def test_no_rule_leaves_the_order_untouched(self, ctx, portfolio):
        order = entry(3)
        assert RiskManager().prepare(order, ctx, portfolio, marks_of(ctx)) is order

    def test_rule_overrides_the_strategy_quantity(self, ctx, portfolio):
        prepared = RiskManager(sizing=FixedContracts(4)).prepare(
            entry(1), ctx, portfolio, marks_of(ctx)
        )
        assert prepared is not None
        assert prepared.quantity == 4

    def test_zero_contracts_drops_the_order(self, ctx, portfolio):
        manager = RiskManager(sizing=EquityFraction(0.0001))
        assert manager.prepare(entry(1), ctx, portfolio, marks_of(ctx)) is None
        assert manager.stats.n_dropped_sizing == 1

    def test_protections_survive_resizing(self, ctx, portfolio):
        order = Order(symbol=SYMBOL, side=Side.BUY, quantity=1, stop_loss=90.0, take_profit=120.0)
        prepared = RiskManager(sizing=FixedContracts(4)).prepare(
            order, ctx, portfolio, marks_of(ctx)
        )
        assert prepared is not None
        assert prepared.stop_loss == 90.0
        assert prepared.take_profit == 120.0


class TestMargin:
    def test_order_within_margin_passes(self, ctx, portfolio):
        # equity 100 000, marge initiale 10 000 -> 10 contrats tiennent
        prepared = RiskManager().prepare(entry(10), ctx, portfolio, marks_of(ctx))
        assert prepared is not None

    def test_order_beyond_margin_is_rejected(self, ctx, portfolio):
        manager = RiskManager()
        assert manager.prepare(entry(11), ctx, portfolio, marks_of(ctx)) is None
        assert manager.stats.n_rejected_margin == 1

    def test_warn_policy_lets_it_through_and_records(self, ctx, portfolio):
        manager = RiskManager(margin_policy=MarginPolicy.WARN)
        assert manager.prepare(entry(50), ctx, portfolio, marks_of(ctx)) is not None
        assert manager.stats.n_warned_margin == 1
        assert manager.warnings and "marge requise" in manager.warnings[0]

    def test_a_reducing_order_never_hits_the_margin_check(self, ctx, portfolio):
        hold(portfolio, 10)
        manager = RiskManager()
        order = Order(symbol=SYMBOL, side=Side.SELL, quantity=10, reduce_only=True)
        assert manager.prepare(order, ctx, portfolio, marks_of(ctx)) is not None
        assert manager.stats.n_rejected_margin == 0


class TestGrossCap:
    def test_cap_rejects_the_excess(self, ctx, portfolio):
        manager = RiskManager(max_gross_contracts=2)
        assert manager.prepare(entry(3), ctx, portfolio, marks_of(ctx)) is None
        assert manager.stats.n_rejected_gross_cap == 1

    def test_cap_counts_the_existing_position(self, ctx, portfolio):
        hold(portfolio, 2)
        manager = RiskManager(max_gross_contracts=2)
        assert manager.prepare(entry(1), ctx, portfolio, marks_of(ctx)) is None

    def test_invalid_cap_refused(self):
        with pytest.raises(ConfigurationError, match="max_gross_contracts"):
            RiskManager(max_gross_contracts=0)


class TestManagerLifecycle:
    def test_reset_clears_stats_and_warnings(self, ctx, portfolio):
        manager = RiskManager(margin_policy=MarginPolicy.WARN)
        manager.prepare(entry(50), ctx, portfolio, marks_of(ctx))
        manager.reset()
        assert manager.stats.n_warned_margin == 0
        assert manager.warnings == ()

    def test_warmup_comes_from_the_sizing_rule(self):
        assert RiskManager().warmup_bars == 0
        assert RiskManager(sizing=RiskFraction(0.01, atr_window=30)).warmup_bars == 31

    def test_describe_is_serialisable(self):
        import json

        described = RiskManager(sizing=FixedContracts(2)).describe()
        assert json.loads(json.dumps(described)) == described


class TestPlafondsDePortefeuille:
    """Les plafonds de `engine/limites.py`, vus depuis le `RiskManager`.

    Les regles elles-memes sont eprouvees dans
    `tests/unit/test_limites_portefeuille.py`, sur des photographies. Ici on
    verifie le CABLAGE : que le gestionnaire mesure bien le portefeuille reel,
    qu'il projette l'ordre avant de trancher, et qu'il compte le refus sous le
    bon motif.

    Arithmetique du montage : multiplicateur 50, marque 100, donc 5 000 le
    contrat sur une equity de 100 000 - un contrat vaut 0,05 d'exposition.
    """

    MARQUE = 100.0
    MARQUES: ClassVar[dict[str, float]] = {SYMBOL: MARQUE}

    def gestionnaire(self, **plafonds: object) -> RiskManager:
        return RiskManager(limits=PortfolioLimits(**plafonds))

    def test_sans_plafond_declare_rien_ne_change(self, ctx, portfolio):
        """Le defaut doit etre strictement inerte : toutes les empreintes
        archivees en dependent.

        Cinq contrats et non cinquante : la MARGE reste active, et 50 x 10 000
        la depasserait. Un `None` viendrait alors d'elle, pas du defaut teste
        ici - le test aurait passe pour la mauvaise raison."""
        risk = RiskManager()
        assert risk.prepare(entry(5), ctx, portfolio, self.MARQUES) is not None
        assert risk.stats.n_rejected_portfolio == 0

    def test_un_ordre_qui_ferait_franchir_le_brut_est_refuse(self, ctx, portfolio):
        risk = self.gestionnaire(max_gross_exposure=0.1)  # 2 contrats
        assert risk.prepare(entry(3), ctx, portfolio, self.MARQUES) is None
        assert risk.stats.n_rejected_gross_exposure == 1

    def test_un_ordre_qui_reste_sous_le_brut_passe(self, ctx, portfolio):
        risk = self.gestionnaire(max_gross_exposure=0.1)
        assert risk.prepare(entry(2), ctx, portfolio, self.MARQUES) is not None
        assert risk.stats.n_rejected_portfolio == 0

    def test_le_plafond_porte_sur_le_portefeuille_d_apres(self, ctx, portfolio):
        """Deja 2 contrats en portefeuille, plafond a 2 : un troisieme doit
        etre refuse. Mesurer l'etat AVANT le laisserait passer, et le plafond
        ne mordrait qu'une fois deja depasse."""
        hold(portfolio, 2, price=self.MARQUE)
        risk = self.gestionnaire(max_gross_exposure=0.1)
        assert risk.prepare(entry(1), ctx, portfolio, self.MARQUES) is None
        assert risk.stats.n_rejected_gross_exposure == 1

    def test_une_sortie_reduce_only_n_est_jamais_soumise_aux_plafonds(
        self, ctx, portfolio
    ):
        """Un `reduce_only` sort par un autre chemin, avant tout controle. S'il
        y passait, un portefeuille au-dessus du plafond ne pourrait plus se
        fermer - et les stops empruntent ce meme chemin."""
        hold(portfolio, 5, price=self.MARQUE)
        risk = self.gestionnaire(max_gross_exposure=0.01)
        sortie = Order(symbol=SYMBOL, side=Side.SELL, quantity=5, reduce_only=True)
        assert risk.prepare(sortie, ctx, portfolio, self.MARQUES) is not None
        assert risk.stats.n_rejected_portfolio == 0

    def test_le_plafond_par_classe_compte_les_instruments_sans_classe(
        self, ctx, portfolio
    ):
        """L'instrument de test n'en declare pas. Il est compte avec les autres
        sans classe, jamais exempte : sinon omettre un champ facultatif
        contournerait le plafond."""
        risk = self.gestionnaire(max_per_category=1)
        assert risk.prepare(entry(1), ctx, portfolio, self.MARQUES) is not None
        hold(portfolio, 1, price=self.MARQUE)
        # Renforcer ne cree pas une seconde position dans la classe.
        assert risk.prepare(entry(1), ctx, portfolio, self.MARQUES) is not None
        assert risk.stats.n_rejected_per_category == 0

    def test_le_refus_de_portefeuille_est_distinct_du_plafond_de_contrats(
        self, ctx, portfolio
    ):
        """Deux compteurs, parce que deux limites differentes : l'une borne un
        instrument en contrats, l'autre le portefeuille en argent."""
        risk = RiskManager(
            max_gross_contracts=10, limits=PortfolioLimits(max_gross_exposure=0.1)
        )
        assert risk.prepare(entry(5), ctx, portfolio, self.MARQUES) is None
        assert risk.stats.n_rejected_gross_cap == 0
        assert risk.stats.n_rejected_gross_exposure == 1

    def test_le_plafond_de_contrats_tranche_en_premier(self, ctx, portfolio):
        """L'ordre des controles est observable : quand les deux mordent, c'est
        le plafond d'instrument qui compte le refus."""
        risk = RiskManager(
            max_gross_contracts=2, limits=PortfolioLimits(max_gross_exposure=0.1)
        )
        assert risk.prepare(entry(5), ctx, portfolio, self.MARQUES) is None
        assert risk.stats.n_rejected_gross_cap == 1
        assert risk.stats.n_rejected_portfolio == 0

    def test_un_motif_inconnu_est_refuse_plutot_qu_ecrit(self):
        """Le compteur est indexe par nom : sans garde, une faute de frappe
        creerait un compteur fantome au lieu d'echouer."""
        risk = RiskManager()
        with pytest.raises(ValueError, match="motif de refus inconnu"):
            risk.stats.compter_refus("gross_exposition")

    def test_reset_remet_les_compteurs_de_plafond_a_zero(self, ctx, portfolio):
        risk = self.gestionnaire(max_gross_exposure=0.01)
        risk.prepare(entry(1), ctx, portfolio, self.MARQUES)
        assert risk.stats.n_rejected_portfolio == 1
        risk.reset()
        assert risk.stats.n_rejected_portfolio == 0

    def test_describe_publie_les_plafonds_et_leurs_compteurs(self, ctx, portfolio):
        """Un run qui refuse des ordres doit dire lesquels, et pourquoi -
        sinon « la strategie ne trade pas » reste sans explication."""
        risk = self.gestionnaire(max_positions=1, max_gross_exposure=2.0)
        decrit = risk.describe()
        assert decrit["limits"] == {
            "max_gross_exposure": 2.0,
            "max_net_exposure": None,
            "max_positions": 1,
            "max_per_category": None,
        }
        stats = decrit["stats"]
        assert isinstance(stats, dict)
        for motif in MOTIFS:
            assert f"n_rejected_{motif}" in stats


class TestUneFourneeDOrdresSeVoitElleMeme:
    """Le defaut trouve le 2026-09-12, isole ici pour qu'il ne revienne pas.

    Un plafond de portefeuille etait evalue contre le portefeuille COMMITE.
    Or un rebalancement transversal emet tous ses ordres d'un coup, avant
    qu'aucun ne soit rempli : chacun lisait « aucune position detenue »,
    chacun passait, et `max_positions=2` laissait detenir jusqu'a SIX
    instruments sur `momentum_12_1_mensuel`.

    La correction est une RESERVATION valable le temps d'une fournee. Ces
    tests l'exercent sur un seul instrument, la ou tout est verifiable de
    tete ; l'effet sur les dix instruments reels est verifie dans
    `tests/test_integration_reelle.py`.
    """

    MARQUES: ClassVar[dict[str, float]] = {SYMBOL: 100.0}

    def test_deux_ordres_de_la_meme_fournee_se_cumulent(self, ctx, portfolio):
        """Plafond a 2 contrats. Deux ordres d'un contrat passent ; le
        troisieme est refuse, alors que le portefeuille est encore vide."""
        risk = RiskManager(limits=PortfolioLimits(max_gross_exposure=0.1))
        risk.begin_submission()
        assert risk.prepare(entry(1), ctx, portfolio, self.MARQUES) is not None
        assert risk.prepare(entry(1), ctx, portfolio, self.MARQUES) is not None
        assert risk.prepare(entry(1), ctx, portfolio, self.MARQUES) is None
        assert risk.stats.n_rejected_gross_exposure == 1

    def test_une_nouvelle_fournee_repart_des_positions_reelles(self, ctx, portfolio):
        """La reservation ne dure QU'une fournee : le runner remplit les ordres
        dus avant de soumettre les suivants, donc a la fournee d'apres, ce qui
        devait s'executer est deja dans le portefeuille. La garder plus
        longtemps compterait deux fois la meme position."""
        risk = RiskManager(limits=PortfolioLimits(max_gross_exposure=0.1))
        risk.begin_submission()
        assert risk.prepare(entry(2), ctx, portfolio, self.MARQUES) is not None
        risk.begin_submission()
        assert risk.prepare(entry(2), ctx, portfolio, self.MARQUES) is not None

    def test_une_sortie_libere_la_place_pour_une_entree(self, ctx, portfolio):
        """La raison pour laquelle les REDUCTIONS sont reservees elles aussi.

        `ranking@1` emet ses sorties avant ses entrees. Un plafond qui ne
        crediterait pas les sorties refuserait toute rotation : le portefeuille
        resterait fige sur ses premieres positions - la meme facon de pieger un
        portefeuille que celle contre laquelle la regle de non-aggravation
        protege."""
        hold(portfolio, 2, price=100.0)
        risk = RiskManager(limits=PortfolioLimits(max_gross_exposure=0.1))
        risk.begin_submission()
        sortie = Order(symbol=SYMBOL, side=Side.SELL, quantity=2, reduce_only=True)
        assert risk.prepare(sortie, ctx, portfolio, self.MARQUES) is not None
        assert risk.prepare(entry(2), ctx, portfolio, self.MARQUES) is not None
        assert risk.stats.n_rejected_portfolio == 0

    def test_sans_plafond_aucune_reservation_n_est_tenue(self, ctx, portfolio):
        """Le chemin par defaut ne doit rien payer, ni rien retenir."""
        risk = RiskManager()
        risk.begin_submission()
        risk.prepare(entry(1), ctx, portfolio, self.MARQUES)
        assert risk._reserved == {}

    def test_reset_efface_les_reservations(self, ctx, portfolio):
        risk = RiskManager(limits=PortfolioLimits(max_gross_exposure=0.5))
        risk.begin_submission()
        risk.prepare(entry(1), ctx, portfolio, self.MARQUES)
        assert risk._reserved
        risk.reset()
        assert risk._reserved == {}
