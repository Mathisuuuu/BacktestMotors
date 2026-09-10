"""Les deux derniers manques : le calendrier et le multi-instrument.

Avec `time`, `peer` et `rolling`, une strategie de paires s'ecrit entierement
en JSON. Ce fichier verifie les trois noeuds separement, puis ensemble sur une
paire complete passee par le moteur.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fixtures import synthetic
from rsl.config import BacktestSpec
from rsl.data.feed import BarContext, MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import TIME_FIELDS, BarStore, Granularity, Panel, time_field
from rsl.errors import ConfigurationError
from rsl.report import run_backtest
from rsl.strategies.rules import PanelRuleStrategy, RuleStrategy
from rsl.strategies.signals import (
    Arith,
    ArithOp,
    Compare,
    CompareOp,
    RollingStat,
    build_signal,
    const,
    peer,
    price,
    prim,
    rolling,
    when,
)

DAY = Granularity(timedelta(days=1), name="1d")
MONDAY = datetime(2021, 1, 4, tzinfo=UTC)


def store(closes, symbol: str = "A", start: datetime = MONDAY) -> BarStore:
    return synthetic.make_store(closes, symbol=symbol, granularity=DAY, start=start)


def solo(closes=None, index: int = 10) -> BarContext:
    ctx = BarContext(store(closes if closes is not None else synthetic.ramp(60, 100.0, 1.0)))
    for _ in range(index + 1):
        ctx._advance()
    return ctx


def pair_panel(n_a: int = 200, n_b: int = 200) -> Panel:
    return build_panel(
        {
            "A": store(synthetic.random_walk(n_a, 100.0, sigma=1.0, seed=1), "A"),
            "B": store(synthetic.random_walk(n_b, 200.0, sigma=2.0, seed=2), "B"),
        }
    )


def multi_at(panel: Panel, row: int) -> MultiContext:
    ctx = MultiContext(panel)
    ctx._seek_row(row)
    return ctx


# ---------------------------------------------------------------------------
# Calendrier
# ---------------------------------------------------------------------------


class TestTimeNode:
    def test_weekday_follows_the_python_convention(self):
        """Lundi vaut 0. La barre 0 clot le mardi : `ts` est la CLOTURE."""
        ctx = solo(index=0)
        assert ctx.ts == MONDAY + timedelta(days=1)
        assert when("weekday")(ctx) == 1.0

    def test_it_reads_the_close_not_the_open(self):
        """Une barre ouverte le vendredi soir est datee du samedi."""
        friday_evening = datetime(2021, 1, 8, 23, 30, tzinfo=UTC)
        ctx = BarContext(
            synthetic.make_store(
                synthetic.ramp(10), symbol="A", granularity=Granularity.minutes(60),
                start=friday_evening,
            )
        )
        ctx._advance()
        assert ctx.ts_event.weekday() == 4
        assert when("weekday")(ctx) == 5.0

    @pytest.mark.parametrize("name", TIME_FIELDS)
    def test_every_field_is_readable(self, name):
        assert isinstance(when(name)(solo()), float)

    def test_the_fields_match_the_datetime(self):
        ctx = solo(index=5)
        moment = ctx.ts
        assert when("day")(ctx) == float(moment.day)
        assert when("month")(ctx) == float(moment.month)
        assert when("year")(ctx) == float(moment.year)

    def test_an_unknown_field_is_refused(self):
        with pytest.raises(ConfigurationError, match="champ inconnu"):
            when("saison")

    def test_the_helper_refuses_it_too(self):
        with pytest.raises(ValueError, match="champ calendaire inconnu"):
            time_field(MONDAY, "saison")

    def test_it_needs_one_bar(self):
        assert when("weekday").warmup_bars == 1

    def test_it_round_trips(self):
        node = when("hour")
        assert build_signal(node.describe()).describe() == node.describe()

    def test_a_calendar_filter_is_expressible(self):
        """Le cas qui a motive ce noeud : ne trader que certains jours."""
        rule = Compare(when("weekday"), CompareOp.LE, const(4.0))
        assert rule(solo()) in (0.0, 1.0)


# ---------------------------------------------------------------------------
# Multi-instrument
# ---------------------------------------------------------------------------


class TestPeerNode:
    def test_it_reads_the_other_instrument_at_the_same_instant(self):
        panel = pair_panel()
        ctx = multi_at(panel, 50)
        assert peer("B", price("close"))(ctx["A"]) == pytest.approx(
            ctx["B"].value_of_close()
            if hasattr(ctx["B"], "value_of_close")
            else float(panel.stores["B"].close[50])
        )

    def test_a_spread_is_expressible(self):
        panel = pair_panel()
        ctx = multi_at(panel, 50)
        spread = Arith(price("close"), ArithOp.SUB, peer("B", price("close")))
        assert spread(ctx["A"]) == pytest.approx(
            float(panel.stores["A"].close[50]) - float(panel.stores["B"].close[50])
        )

    def test_an_absent_peer_is_undefined_not_an_error(self):
        """L'absence est un etat de marche, pas une faute."""
        panel = pair_panel(n_a=200, n_b=100)
        row = next(r for r in range(200) if "B" not in panel.present_symbols(r))
        assert peer("B", price("close"))(multi_at(panel, row)["A"]) is None

    def test_a_symbol_outside_the_panel_is_a_configuration_error(self):
        """Une faute de specification doit faire echouer, pas rendre None."""
        with pytest.raises(ConfigurationError, match="ne fait pas partie du panneau"):
            peer("ZZ", price("close"))(multi_at(pair_panel(), 50)["A"])

    def test_outside_a_panel_it_is_a_configuration_error(self):
        with pytest.raises(ConfigurationError, match="mono-instrument"):
            peer("B", price("close"))(solo())

    def test_a_peer_without_enough_history_is_undefined(self):
        """Un instrument qui demarre plus tard : « pas encore », pas une erreur."""
        panel = build_panel(
            {
                "A": store(synthetic.ramp(100, 100.0, 1.0), "A"),
                "B": store(
                    synthetic.ramp(100, 200.0, 1.0), "B", start=MONDAY + timedelta(days=50)
                ),
            }
        )
        row = next(r for r in range(150) if set(panel.present_symbols(r)) == {"A", "B"})
        assert peer("B", prim("sma@1", window=50))(multi_at(panel, row)["A"]) is None

    def test_the_peer_context_keeps_its_own_guards(self):
        """Un pair est un `Context` ordinaire : il ne montre que du passe."""
        from rsl.errors import LookAheadError

        ctx = multi_at(pair_panel(), 50)["A"]
        with pytest.raises(LookAheadError):
            ctx.peer("B").value(price("close").field, lag=-1)  # type: ignore[arg-type]

    def test_an_empty_symbol_is_refused(self):
        with pytest.raises(ConfigurationError, match="symbol"):
            peer("", price("close"))

    def test_it_round_trips(self):
        node = peer("B", price("close"))
        assert build_signal(node.describe()).describe() == node.describe()

    def test_the_peer_list_is_visible(self):
        assert multi_at(pair_panel(), 50)["A"].peers == ("A", "B")

    def test_outside_a_panel_there_are_no_peers(self):
        assert solo().peers == ()


# ---------------------------------------------------------------------------
# Statistique glissante d'un signal quelconque
# ---------------------------------------------------------------------------


class TestRollingNode:
    def test_mean_of_a_ramp_matches_the_closed_form(self):
        """Sur une rampe de pas 1, la moyenne sur w vaut close - (w-1)/2."""
        ctx = solo(index=40)
        value = rolling("mean", 10, price("close"))(ctx)
        assert value == pytest.approx(ctx.value(price("close").field) - 4.5)  # type: ignore[arg-type]

    def test_the_current_value_is_lag_zero(self):
        """`shifted(0)` est le present : la fenetre commence a maintenant."""
        ctx = solo(index=40)
        assert rolling("max", 10, price("close"))(ctx) == pytest.approx(
            ctx.value(price("close").field)  # type: ignore[arg-type]
        )

    def test_zscore_of_a_constant_is_undefined(self):
        ctx = solo(synthetic.constant(60, 100.0), index=40)
        assert rolling("zscore", 20, price("close"))(ctx) is None

    def test_stdev_of_a_ramp(self):
        ctx = solo(index=40)
        assert rolling("stdev", 3, price("close"))(ctx) == pytest.approx(1.0)

    def test_sum_and_min(self):
        ctx = solo(index=40)
        current = ctx.value(price("close").field)  # type: ignore[arg-type]
        assert rolling("sum", 3, price("close"))(ctx) == pytest.approx(3 * current - 3)
        assert rolling("min", 3, price("close"))(ctx) == pytest.approx(current - 2)

    def test_warmup_adds_the_window(self):
        assert rolling("mean", 10, prim("sma@1", window=20)).warmup_bars == 29

    def test_insufficient_history_is_undefined(self):
        assert rolling("mean", 50, price("close"))(solo(index=5)) is None

    def test_an_undefined_value_in_the_window_propagates(self):
        """Une moyenne sur une fenetre trouee ne serait pas la moyenne demandee."""
        ctx = solo(synthetic.constant(60, 100.0), index=40)
        assert rolling("mean", 5, prim("zscore@1", window=10))(ctx) is None

    def test_dispersion_needs_two_observations(self):
        for stat in ("stdev", "zscore"):
            with pytest.raises(ConfigurationError, match="window >= 2"):
                rolling(stat, 1, price("close"))

    def test_an_invalid_statistic_is_refused(self):
        with pytest.raises(ConfigurationError, match="statistique invalide"):
            build_signal(
                {
                    "type": "rolling",
                    "stat": "mediane",
                    "window": 5,
                    "inner": {"type": "constant", "value": 1.0},
                }
            )

    def test_every_statistic_is_reachable(self):
        ctx = solo(index=40)
        for stat in RollingStat:
            window = 5
            assert rolling(stat.value, window, price("close"))(ctx) is not None

    def test_it_round_trips(self):
        node = rolling("zscore", 20, price("close"))
        assert build_signal(node.describe()).describe() == node.describe()


# ---------------------------------------------------------------------------
# Les trois ensemble : une paire
# ---------------------------------------------------------------------------


SPREAD_ZSCORE: dict[str, object] = {
    "type": "rolling",
    "stat": "zscore",
    "window": 40,
    "inner": {
        "type": "arith",
        "op": "/",
        "left": {"type": "price", "field": "close"},
        "right": {
            "type": "peer",
            "symbol": "B",
            "inner": {"type": "price", "field": "close"},
        },
    },
}

PAIR_RULES: dict[str, object] = {
    "entry_long": {
        "type": "compare",
        "op": "<",
        "left": SPREAD_ZSCORE,
        "right": {"type": "constant", "value": -1.0},
    },
    "exit_long": {
        "type": "compare",
        "op": ">",
        "left": SPREAD_ZSCORE,
        "right": {"type": "constant", "value": 0.0},
    },
}


class TestPanelRuleStrategy:
    def test_the_spread_zscore_is_computable(self):
        panel = pair_panel()
        node = build_signal(SPREAD_ZSCORE)
        value = node(multi_at(panel, 100)["A"])
        assert value is not None

    def test_it_trades_a_pair_through_the_engine(self, spec):
        panel = pair_panel()
        specs = {
            name: spec.model_copy(update={"symbol": name, "root": name})
            for name in ("A", "B")
        }
        from rsl.engine.cross_sectional import CrossSectionalRunner
        from rsl.engine.execution import ExecutionConfig, ZeroFee, ZeroSlippage
        from rsl.engine.runner import RunConfig

        strategy = PanelRuleStrategy(
            inner=RuleStrategy.from_spec(
                {"symbol": "A", "quantity": 1, "rules": PAIR_RULES}
            )
        )
        result = CrossSectionalRunner(
            panel,
            specs,
            RunConfig(1_000_000.0, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())),
        ).run(strategy)

        assert len(result.fills) > 0
        assert all(fill.symbol == "A" for fill in result.fills), (
            "elle ne negocie QUE son instrument, meme si elle en lit deux"
        )

    def test_it_does_nothing_when_its_own_instrument_is_absent(self, spec):
        panel = build_panel(
            {
                "A": store(synthetic.random_walk(60, 100.0, seed=1), "A"),
                "B": store(synthetic.random_walk(200, 200.0, seed=2), "B"),
            }
        )
        strategy = PanelRuleStrategy(
            inner=RuleStrategy.from_spec(
                {"symbol": "A", "quantity": 1, "rules": PAIR_RULES}
            )
        )
        row = next(r for r in range(200) if "A" not in panel.present_symbols(r))
        assert strategy.on_rebalance(multi_at(panel, row)) == ()

    def test_it_delegates_its_warmup(self):
        inner = RuleStrategy.from_spec({"symbol": "A", "quantity": 1, "rules": PAIR_RULES})
        assert PanelRuleStrategy(inner=inner).warmup_bars == inner.warmup_bars

    def test_describe_is_serialisable(self):
        strategy = PanelRuleStrategy(
            inner=RuleStrategy.from_spec(
                {"symbol": "A", "quantity": 1, "rules": PAIR_RULES}
            )
        )
        assert json.loads(json.dumps(strategy.describe())) == strategy.describe()


class TestFromAConfigurationFile:
    """Une strategie de paires, entierement en JSON."""

    def _files(self, tmp_path: Path) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for i, root in enumerate(("ES", "NQ")):
            closes = synthetic.random_walk(300, 2000.0 * (i + 1), sigma=20.0, seed=10 + i)
            path = tmp_path / f"{root}_v0_1m.parquet"
            synthetic.make_frame(closes, granularity=DAY, start=MONDAY).write_parquet(path)
            out[root] = path
        return out

    def _spec(self, tmp_path: Path) -> BacktestSpec:
        rules = json.loads(json.dumps(PAIR_RULES).replace('"symbol": "B"', '"symbol": "NQ.v.0"'))
        return BacktestSpec.model_validate(
            {
                "name": "paire-sans-code",
                "initial_cash": 1_000_000.0,
                "data": [
                    {"root": r, "path": str(p)} for r, p in sorted(self._files(tmp_path).items())
                ],
                "execution": {"fees": {"kind": "zero"}, "slippage": {"kind": "zero"}},
                "strategy": {
                    "ref": "panel_rules@1",
                    "params": {"symbol": "ES.v.0", "quantity": 1, "rules": rules},
                },
            }
        )

    def test_it_runs_and_trades(self, tmp_path: Path):
        report = run_backtest(self._spec(tmp_path))
        assert report.cross_sectional
        assert report.metrics.n_trades > 0

    def test_it_only_trades_the_designated_instrument(self, tmp_path: Path):
        report = run_backtest(self._spec(tmp_path))
        positions = report.run["portfolio"]["positions"]
        assert set(positions) <= {"ES.v.0"}

    def test_it_is_deterministic(self, tmp_path: Path):
        spec = self._spec(tmp_path)
        assert run_backtest(spec).result_fingerprint == run_backtest(spec).result_fingerprint
