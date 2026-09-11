"""Runner transversal : calendrier de rebalancement, absences, comptabilite."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from fixtures import synthetic
from rsl.data.feed import MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import Granularity, InstrumentSpec, Panel
from rsl.engine.cross_sectional import (
    CrossSectionalRunner,
    EveryNRows,
    EveryRow,
    RebalanceSchedule,
)
from rsl.engine.execution import (
    ExecutionConfig,
    PerContractFee,
    TickSlippage,
    ZeroFee,
    ZeroSlippage,
)
from rsl.engine.risk import FixedContracts, RiskManager
from rsl.engine.runner import RunConfig
from rsl.errors import ConfigurationError
from rsl.orders import Fill, Order, Side
from rsl.strategies.base import CrossSectionalStrategy

CASH = 1_000_000.0
DAY = Granularity(timedelta(days=1), name="1d")
EPOCH = datetime(2021, 1, 1, tzinfo=UTC)


def spec_named(symbol: str, spec: InstrumentSpec) -> InstrumentSpec:
    return spec.model_copy(update={"symbol": symbol, "root": symbol})


@pytest.fixture
def panel_specs(spec: InstrumentSpec) -> tuple[Panel, dict[str, InstrumentSpec]]:
    """Trois instruments quotidiens ; C s'arrete a la moitie de l'echantillon."""
    stores = {
        "A": synthetic.make_store(
            synthetic.ramp(40, 100.0, 1.0), symbol="A", granularity=DAY, start=EPOCH
        ),
        "B": synthetic.make_store(
            synthetic.ramp(40, 200.0, -1.0), symbol="B", granularity=DAY, start=EPOCH
        ),
        "C": synthetic.make_store(
            synthetic.constant(20, 50.0), symbol="C", granularity=DAY, start=EPOCH
        ),
    }
    specs = {name: spec_named(name, spec) for name in stores}
    return build_panel(stores), specs


def config(**kwargs: object) -> RunConfig:
    execution = kwargs.pop(
        "execution", ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())
    )
    return RunConfig(initial_cash=CASH, execution=execution, **kwargs)  # type: ignore[arg-type]


@dataclass(eq=False)
class ScriptedCrossSectional(CrossSectionalStrategy):
    """Emet des ordres a des lignes precises. Sert a tester le runner."""

    script: dict[int, list[Order]] = field(default_factory=dict)
    warmup: int = 0
    rows: list[int] = field(default_factory=list)
    universes: list[tuple[str, ...]] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)

    @property
    def warmup_bars(self) -> int:
        return self.warmup

    def reset(self) -> None:
        self.rows = []
        self.universes = []
        self.fills = []

    def on_fill(self, fill: Fill) -> None:
        self.fills.append(fill)

    def on_rebalance(self, ctx: MultiContext) -> Sequence[Order]:
        row = ctx._row
        self.rows.append(row)
        self.universes.append(ctx.symbols)
        return self.script.get(row, [])


def buy(symbol: str, quantity: int = 1) -> Order:
    return Order(symbol=symbol, side=Side.BUY, quantity=quantity, tag="entry")


def close(symbol: str, quantity: int = 1) -> Order:
    return Order(
        symbol=symbol, side=Side.SELL, quantity=quantity, reduce_only=True, tag="exit"
    )


class TestConstruction:
    def test_missing_spec_refused(self, panel_specs):
        panel, specs = panel_specs
        del specs["C"]
        with pytest.raises(ConfigurationError, match="specification manquante"):
            CrossSectionalRunner(panel, specs, config())

    def test_order_outside_the_panel_is_a_configuration_error(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({0: [buy("ZZ")]})
        with pytest.raises(ConfigurationError, match="hors du panneau"):
            CrossSectionalRunner(panel, specs, config()).run(strategy)


class TestSchedules:
    def test_every_row_is_the_default(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional()
        CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert strategy.rows == list(range(panel.n_rows))

    def test_every_n_rows(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional()
        CrossSectionalRunner(
            panel, specs, config(), schedule=EveryNRows(5, offset=2)
        ).run(strategy)
        assert strategy.rows == [2, 7, 12, 17, 22, 27, 32, 37]

    def test_schedules_satisfy_the_protocol(self):
        assert isinstance(EveryRow(), RebalanceSchedule)
        assert isinstance(EveryNRows(3), RebalanceSchedule)

    @pytest.mark.parametrize("kwargs", [{"n": 0}, {"n": 2, "offset": -1}])
    def test_invalid_schedule_refused(self, kwargs):
        with pytest.raises(ConfigurationError):
            EveryNRows(**kwargs)

    def test_describe_is_serialisable(self):
        import json

        for schedule in (EveryRow(), EveryNRows(4, 1)):
            assert json.loads(json.dumps(schedule.describe())) == schedule.describe()


class TestUniverse:
    def test_the_strategy_only_sees_quoting_instruments(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional()
        CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert strategy.universes[0] == ("A", "B", "C")
        assert strategy.universes[-1] == ("A", "B")

    def test_warmup_skips_the_first_rows(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional(warmup=10)
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert strategy.rows[0] == 10
        assert result.counters.n_rows == panel.n_rows - 10
        assert result.counters.warmup_rows == 10


class TestExecution:
    def test_an_order_fills_at_the_next_row_open(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("A")]})
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert len(result.fills) == 1
        fill = result.fills[0]
        assert fill.bar_index == 6
        assert fill.price == pytest.approx(float(panel.stores["A"].open[6]))

    def test_positions_accumulate_across_instruments(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("A", 2), buy("B", 3)]})
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert result.portfolio.quantity_of("A") == 2
        assert result.portfolio.quantity_of("B") == 3

    def test_the_risk_manager_sizes_each_leg(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("A"), buy("B")]})
        result = CrossSectionalRunner(
            panel, specs, config(), risk=RiskManager(sizing=FixedContracts(4))
        ).run(strategy)
        assert result.portfolio.quantity_of("A") == 4
        assert result.portfolio.quantity_of("B") == 4

    def test_fills_are_notified_to_the_strategy(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("A")]})
        CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert len(strategy.fills) == 1
        assert strategy.fills[0].symbol == "A"

    def test_order_ids_are_sequential(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("A"), buy("B")], 8: [buy("A")]})
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        ids = [f.order_id for f in result.fills]
        assert ids == sorted(ids)


class TestAbsentInstruments:
    def test_an_entry_on_an_absent_instrument_is_dropped(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({25: [buy("C")]})
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert result.counters.n_orders_dropped_absent == 1
        assert result.fills == ()

    def test_an_exit_on_an_absent_instrument_waits_and_is_not_lost(self, panel_specs):
        """Une position orpheline doit pouvoir se fermer.

        C est detenu, puis cesse de coter. L'ordre de sortie emis pendant
        l'absence reste au carnet ; ici il ne se remplira jamais faute de
        barre, et il est compte comme non execute plutot que perdu en silence.
        """
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("C")], 25: [close("C")]})
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert result.portfolio.quantity_of("C") == 1
        assert result.counters.n_orders_dropped_absent == 0
        assert result.counters.n_orders_cancelled_unfilled == 1

    def test_an_exit_emitted_while_absent_fills_when_the_instrument_returns(
        self, spec: InstrumentSpec
    ):
        """Meme scenario, mais l'instrument revient : la sortie s'execute."""
        gap_store = synthetic.make_gapped_store(
            synthetic.ramp(40, 50.0, 0.5),
            gap_after=19,
            gap=timedelta(days=5),
            symbol="C",
            granularity=DAY,
            start=EPOCH,
        )
        stores = {
            "A": synthetic.make_store(
                synthetic.ramp(40, 100.0, 1.0), symbol="A", granularity=DAY, start=EPOCH
            ),
            "C": gap_store,
        }
        specs = {name: spec_named(name, spec) for name in stores}
        panel = build_panel(stores)

        held_row = 5
        absent_row = next(
            r for r in range(panel.n_rows) if "C" not in panel.present_symbols(r)
        )
        strategy = ScriptedCrossSectional(
            {held_row: [buy("C")], absent_row: [close("C")]}
        )
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)

        assert result.portfolio.quantity_of("C") == 0
        assert result.counters.n_forced_liquidations == 1

    def test_the_marks_only_use_quoting_instruments(self, panel_specs):
        """L'invariante doit tenir alors qu'un instrument cesse de coter."""
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("C")]})
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert result.counters.n_rows == panel.n_rows
        final = {s: float(panel.stores[s].close[-1]) for s in ("A", "B")}
        assert result.portfolio.equity(final) == pytest.approx(
            result.portfolio.equity_incremental, rel=1e-12
        )


class TestResult:
    def test_describe_is_serialisable(self, panel_specs):
        import json

        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("A")]})
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        described = result.describe()
        assert json.loads(json.dumps(described)) == described
        assert described["symbols"] == ["A", "B", "C"]

    def test_equity_curve_is_stamped_on_panel_closes(self, panel_specs):
        panel, specs = panel_specs
        result = CrossSectionalRunner(panel, specs, config()).run(ScriptedCrossSectional())
        assert result.equity.ts_ns == list(panel.ts_close)

    def test_exposure_is_the_gross_contract_count(self, panel_specs):
        panel, specs = panel_specs
        strategy = ScriptedCrossSectional({5: [buy("A", 2), buy("B", 3)]})
        result = CrossSectionalRunner(panel, specs, config()).run(strategy)
        assert result.equity.exposure[0] == 0
        assert result.equity.exposure[-1] == 5

    def test_stale_bars_are_reported(self, panel_specs):
        panel, specs = panel_specs
        result = CrossSectionalRunner(panel, specs, config()).run(ScriptedCrossSectional())
        assert result.stale_bars == {"A": 0, "B": 0, "C": 0}


class TestDeterminism:
    def test_two_runs_are_bit_identical(self, panel_specs):
        panel, specs = panel_specs
        execution = ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(1))
        script = {5: [buy("A"), buy("B", 2)], 12: [close("A")], 20: [buy("A", 3)]}

        def once() -> tuple[list[str], list[tuple[object, ...]]]:
            strategy = ScriptedCrossSectional(dict(script))
            result = CrossSectionalRunner(panel, specs, config(execution=execution)).run(
                strategy
            )
            return (
                [e.hex() for e in result.equity.equity],
                [(f.order_id, f.symbol, f.bar_index, f.price.hex()) for f in result.fills],
            )

        assert once() == once()

    def test_a_reused_runner_resets_everything(self, panel_specs):
        panel, specs = panel_specs
        runner = CrossSectionalRunner(panel, specs, config())
        strategy = ScriptedCrossSectional({5: [buy("A")]})
        first = runner.run(strategy)
        second = runner.run(strategy)
        assert first.final_equity == second.final_equity
        assert len(first.fills) == len(second.fills) == 1
