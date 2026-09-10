"""`RankingStrategy` : une famille transversale entiere, decrite en donnees.

Le test qui porte tout le fichier est
`TestItReproducesTheHandWrittenMomentum` : la classe generique, alimentee par
le score adequat, doit produire exactement les memes ordres que le momentum
ecrit a la main. Si les deux concordent, le moule est reel ; sinon il ne
capture pas la famille qu'il pretend capturer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fixtures import synthetic
from rsl.config import BacktestSpec
from rsl.data.feed import MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import Granularity, InstrumentSpec, Panel
from rsl.engine.cross_sectional import CrossSectionalRunner
from rsl.engine.execution import ExecutionConfig, ZeroFee, ZeroSlippage
from rsl.engine.orders import Fill, Order, Side
from rsl.engine.runner import RunConfig
from rsl.errors import ConfigurationError
from rsl.report import run_backtest
from rsl.strategies.base import build_strategy, get_strategy
from rsl.strategies.handwritten import CrossSectionalMomentum
from rsl.strategies.ranking import RankingStrategy, momentum_score
from rsl.strategies.signals import build_signal, prim

DAY = Granularity(timedelta(days=1), name="1d")
EPOCH = datetime(2016, 1, 4, tzinfo=UTC)
CASH = 1_000_000.0

SLOPES = {"S0": 5.0, "S1": 4.0, "S2": 3.0, "S3": 2.0, "S4": 1.0, "S5": 0.0}


def ramp_panel(n: int = 60) -> Panel:
    return build_panel(
        {
            name: synthetic.make_store(
                synthetic.ramp(n, 100.0, slope), symbol=name, granularity=DAY, start=EPOCH
            )
            for name, slope in SLOPES.items()
        }
    )


def noisy_panel(n: int = 300) -> Panel:
    """Marches aleatoires seedees : le classement y tourne vraiment."""
    return build_panel(
        {
            name: synthetic.make_store(
                synthetic.random_walk(n, 100.0 + 20 * i, sigma=1.5, seed=100 + i),
                symbol=name,
                granularity=DAY,
                start=EPOCH,
            )
            for i, name in enumerate(SLOPES)
        }
    )


def multi_at(panel: Panel, row: int) -> MultiContext:
    ctx = MultiContext(panel)
    ctx._seek_row(row)
    return ctx


def fill_for(order: Order) -> Fill:
    return Fill(
        order_id=0, symbol=order.symbol, side=order.side, quantity=order.quantity,
        price=100.0, fee=0.0, slippage_cost=0.0, ts_ns=0, bar_index=0, tag=order.tag,
    )


def ranking(**overrides: object) -> RankingStrategy:
    defaults: dict[str, object] = {
        "score": build_signal(momentum_score(lookback=12, skip=1)),
        "n_long": 2,
        "n_short": 2,
    }
    defaults.update(overrides)
    return RankingStrategy(**defaults)  # type: ignore[arg-type]


class TestValidation:
    @pytest.mark.parametrize(
        "kwargs", [{"n_long": 0}, {"n_short": 0}, {"quantity": 0}, {"extra_warmup": -1}]
    )
    def test_invalid_parameters_refused(self, kwargs):
        with pytest.raises(ConfigurationError):
            ranking(**kwargs)

    def test_long_only_may_have_no_short_leg(self):
        strategy = ranking(n_short=0, long_short=False)
        assert strategy.required_universe == strategy.n_long

    def test_warmup_comes_from_the_score(self):
        strategy = ranking(score=prim("sma@1", window=42))
        assert strategy.warmup_bars == 42

    def test_extra_warmup_is_added(self):
        strategy = ranking(score=prim("sma@1", window=42), extra_warmup=8)
        assert strategy.warmup_bars == 50

    def test_a_ranking_without_a_score_is_refused(self):
        with pytest.raises(ConfigurationError, match="rien a classer"):
            build_strategy({"ref": "ranking@1", "params": {}})


class TestRanking:
    def test_it_ranks_by_the_score(self):
        panel = ramp_panel()
        targets = ranking()._targets(ranking()._scores(multi_at(panel, 20)))
        assert targets == {"S0": 1, "S1": 1, "S4": -1, "S5": -1}

    def test_a_different_score_gives_a_different_ranking(self):
        """La preuve que le critere est vraiment pilote par les donnees."""
        panel = noisy_panel()
        by_momentum = ranking()._targets(ranking()._scores(multi_at(panel, 200)))
        volatile = ranking(score=prim("volatility@1", window=30))
        by_volatility = volatile._targets(volatile._scores(multi_at(panel, 200)))
        assert by_momentum != by_volatility

    def test_a_negated_score_reverses_the_legs(self):
        """Classer a l'envers s'ecrit avec le vocabulaire, sans bouton dedie."""
        panel = noisy_panel()
        plain = ranking(score=prim("volatility@1", window=30))
        negated = ranking(
            score=build_signal(
                {
                    "type": "arith",
                    "op": "-",
                    "left": {"type": "constant", "value": 0.0},
                    "right": {
                        "type": "primitive",
                        "ref": "volatility@1",
                        "params": {"window": 30},
                    },
                }
            )
        )
        ctx = multi_at(panel, 200)
        longs = {s for s, d in plain._targets(plain._scores(ctx)).items() if d > 0}
        shorts = {s for s, d in negated._targets(negated._scores(ctx)).items() if d < 0}
        assert longs == shorts

    def test_an_instrument_without_enough_history_is_not_ranked(self):
        assert ranking()._scores(multi_at(ramp_panel(), 5)) == {}

    def test_a_score_that_returns_none_excludes_the_instrument(self):
        """Un z-score indefini sur serie plate : l'instrument sort du classement."""
        flat = build_panel(
            {
                name: synthetic.make_store(
                    synthetic.constant(60, 100.0), symbol=name, granularity=DAY, start=EPOCH
                )
                for name in SLOPES
            }
        )
        strategy = ranking(score=prim("zscore@1", window=20))
        assert strategy._scores(multi_at(flat, 40)) == {}

    def test_ties_are_broken_alphabetically(self):
        strategy = ranking()
        assert strategy._targets({"D": 0.1, "A": 0.1, "C": 0.1, "B": 0.1}) == {
            "A": 1, "B": 1, "C": -1, "D": -1
        }

    def test_a_narrow_universe_holds_instead_of_liquidating(self):
        strategy = ranking(n_long=4, n_short=4)
        strategy.on_fill(fill_for(Order(symbol="S0", side=Side.BUY, quantity=1)))
        assert strategy.on_rebalance(multi_at(ramp_panel(), 20)) == ()
        assert strategy._skipped == 1
        assert strategy._positions == {"S0": 1}


class TestOrders:
    def test_it_opens_both_legs_from_flat(self):
        orders = ranking().on_rebalance(multi_at(ramp_panel(), 20))
        assert {(o.symbol, o.side) for o in orders} == {
            ("S0", Side.BUY), ("S1", Side.BUY), ("S4", Side.SELL), ("S5", Side.SELL)
        }

    def test_a_kept_leg_produces_no_order(self):
        panel = ramp_panel()
        strategy = ranking()
        for order in strategy.on_rebalance(multi_at(panel, 20)):
            strategy.on_fill(fill_for(order))
        assert strategy.on_rebalance(multi_at(panel, 21)) == []

    def test_exits_come_before_entries(self):
        strategy = ranking()
        strategy.on_fill(fill_for(Order(symbol="S2", side=Side.BUY, quantity=1)))
        orders = strategy.on_rebalance(multi_at(ramp_panel(), 20))
        first_entry = next(i for i, o in enumerate(orders) if not o.reduce_only)
        assert all(o.reduce_only for o in orders[:first_entry])

    def test_emission_is_deterministic(self):
        panel = ramp_panel()

        def once():
            strategy = ranking()
            strategy.on_fill(fill_for(Order(symbol="S2", side=Side.BUY, quantity=1)))
            return [
                (o.symbol, o.side.value, o.quantity, o.reduce_only)
                for o in strategy.on_rebalance(multi_at(panel, 20))
            ]

        assert once() == once()


class TestItReproducesTheHandWrittenMomentum:
    """Le moule capture-t-il vraiment la famille ? Ordre par ordre."""

    @pytest.mark.parametrize(("lookback", "skip"), [(12, 1), (6, 1), (20, 0), (10, 3)])
    def test_same_orders_at_every_rebalance(self, lookback: int, skip: int):
        panel = noisy_panel()
        handwritten = CrossSectionalMomentum(
            lookback=lookback, skip=skip, n_long=2, n_short=2, quantity=1
        )
        generic = RankingStrategy(
            score=build_signal(momentum_score(lookback=lookback, skip=skip)),
            n_long=2,
            n_short=2,
            quantity=1,
        )
        assert handwritten.warmup_bars >= generic.warmup_bars

        produced = 0
        for row in range(handwritten.warmup_bars, 300):
            ctx = multi_at(panel, row)
            a = list(handwritten.on_rebalance(ctx))
            b = list(generic.on_rebalance(ctx))
            assert [(o.symbol, o.side, o.quantity, o.reduce_only) for o in a] == [
                (o.symbol, o.side, o.quantity, o.reduce_only) for o in b
            ], f"divergence a la ligne {row}"
            produced += len(a)
            for order in a:
                handwritten.on_fill(fill_for(order))
            for order in b:
                generic.on_fill(fill_for(order))

        assert produced > 20, "le classement ne tourne pas : le test serait creux"

    def test_the_scores_themselves_agree(self):
        panel = noisy_panel()
        handwritten = CrossSectionalMomentum(lookback=12, skip=1)
        generic = ranking()
        ctx = multi_at(panel, 200)
        left = handwritten._scores(ctx)
        right = generic._scores(ctx)
        assert set(left) == set(right)
        for symbol in left:
            assert left[symbol] == pytest.approx(right[symbol])

    def test_the_score_helper_is_json_serialisable(self):
        spec = momentum_score(lookback=12, skip=1)
        assert json.loads(json.dumps(spec)) == spec

    def test_the_helper_refuses_an_impossible_skip(self):
        with pytest.raises(ConfigurationError, match="skip"):
            momentum_score(lookback=5, skip=5)


class TestThroughTheEngine:
    def _specs(self, spec: InstrumentSpec) -> dict[str, InstrumentSpec]:
        return {
            name: spec.model_copy(update={"symbol": name, "root": name}) for name in SLOPES
        }

    def test_a_full_run_trades_and_holds_the_invariant(self, spec: InstrumentSpec):
        panel = noisy_panel()
        result = CrossSectionalRunner(
            panel,
            self._specs(spec),
            RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
        ).run(ranking())
        assert result.counters.n_rebalances > 0
        assert len(result.fills) > 10

    def test_it_is_registered_and_buildable(self):
        entry = get_strategy("ranking")
        assert entry.cross_sectional
        built = build_strategy(
            {
                "ref": "ranking@1",
                "params": {"score": momentum_score(), "n_long": 1, "n_short": 1},
            }
        )
        assert isinstance(built, RankingStrategy)

    def test_describe_is_serialisable(self):
        described = ranking().describe()
        assert json.loads(json.dumps(described)) == described


class TestFromAConfigurationFile:
    """Le but : une strategie transversale entierement decrite en JSON."""

    def _files(self, tmp_path: Path) -> dict[str, Path]:
        series = {
            "ES": synthetic.random_walk(400, 2000.0, sigma=20.0, seed=1),
            "NQ": synthetic.random_walk(400, 4000.0, sigma=45.0, seed=2),
            "GC": synthetic.random_walk(400, 1800.0, sigma=15.0, seed=3),
            "CL": synthetic.random_walk(400, 70.0, sigma=1.0, seed=4),
        }
        out: dict[str, Path] = {}
        for root, closes in series.items():
            path = tmp_path / f"{root}_v0_1m.parquet"
            synthetic.make_frame(closes, granularity=DAY, start=EPOCH).write_parquet(path)
            out[root] = path
        return out

    def _spec(self, tmp_path: Path, score: dict[str, object]) -> BacktestSpec:
        return BacktestSpec.model_validate(
            {
                "name": "classement-sans-code",
                "initial_cash": CASH,
                "data": [
                    {"root": r, "path": str(p)} for r, p in sorted(self._files(tmp_path).items())
                ],
                "execution": {"fees": {"kind": "zero"}, "slippage": {"kind": "zero"}},
                "strategy": {
                    "ref": "ranking@1",
                    "params": {"score": score, "n_long": 1, "n_short": 1},
                },
            }
        )

    def test_momentum_from_json(self, tmp_path: Path):
        report = run_backtest(self._spec(tmp_path, momentum_score(lookback=20, skip=1)))
        assert report.cross_sectional
        assert report.metrics.n_trades > 0

    def test_a_criterion_that_no_class_implements(self, tmp_path: Path):
        """Momentum ajuste de la volatilite : impossible avant, trivial maintenant."""
        score: dict[str, object] = {
            "type": "arith",
            "op": "/",
            "left": {"type": "primitive", "ref": "returns@1", "params": {"window": 60}},
            "right": {
                "type": "primitive",
                "ref": "volatility@1",
                "params": {"window": 60},
            },
        }
        report = run_backtest(self._spec(tmp_path, score))
        assert report.metrics.n_trades > 0

    def test_a_low_volatility_criterion(self, tmp_path: Path):
        score: dict[str, object] = {
            "type": "arith",
            "op": "-",
            "left": {"type": "constant", "value": 0.0},
            "right": {"type": "primitive", "ref": "volatility@1", "params": {"window": 40}},
        }
        report = run_backtest(self._spec(tmp_path, score))
        assert report.metrics.n_trades > 0

    def test_two_different_criteria_give_two_different_runs(self, tmp_path: Path):
        momentum = run_backtest(self._spec(tmp_path, momentum_score(lookback=20, skip=1)))
        low_vol = run_backtest(
            self._spec(
                tmp_path,
                {
                    "type": "arith",
                    "op": "-",
                    "left": {"type": "constant", "value": 0.0},
                    "right": {
                        "type": "primitive",
                        "ref": "volatility@1",
                        "params": {"window": 40},
                    },
                },
            )
        )
        assert momentum.result_fingerprint != low_vol.result_fingerprint
