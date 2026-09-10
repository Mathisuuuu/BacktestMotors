"""Test exige n° 1, applique a la troisieme strategie de reference.

Le momentum transversal est le cas le plus expose du lot : il lit plusieurs
instruments, les classe, et decide a partir du classement. Une fuite chez un
seul instrument suffirait a changer un tri, donc un portefeuille entier.

Protocole identique aux deux autres volets : bruiter toutes les barres apres
l'index `k`, arreter le backtest a `k`, exiger une empreinte identique.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from fixtures import synthetic
from rsl.data.loader import build_panel
from rsl.data.schema import BarStore, Granularity, InstrumentSpec, Panel
from rsl.engine.cross_sectional import (
    CrossSectionalRunner,
    CrossSectionalRunResult,
    EveryNRows,
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
from rsl.strategies.handwritten import CrossSectionalMomentum

pytestmark = pytest.mark.adversarial

CASH = 1_000_000.0
DAY = Granularity(timedelta(days=1), name="1d")
EPOCH = datetime(2021, 1, 1, tzinfo=UTC)
N_BARS = 200

SERIES = {
    "AAA": synthetic.random_walk(N_BARS, start=100.0, sigma=1.5, seed=11),
    "BBB": synthetic.random_walk(N_BARS, start=200.0, sigma=2.5, seed=22),
    "CCC": synthetic.sine(N_BARS, 150.0, 20.0, 40),
    "DDD": synthetic.ramp(N_BARS, 80.0, 0.4),
    "EEE": synthetic.ramp(N_BARS, 300.0, -0.5),
    "FFF": synthetic.random_walk(N_BARS, start=120.0, sigma=0.8, seed=33),
}

CUTS = [40, 90, 150, 198]


def stores_of(cut: int | None = None) -> dict[str, BarStore]:
    """Les six magasins, eventuellement bruites apres `cut`."""
    out: dict[str, BarStore] = {}
    for name, closes in SERIES.items():
        store = synthetic.make_store(closes, symbol=name, granularity=DAY, start=EPOCH)
        if cut is not None:
            # Une graine par instrument : sinon tous recevraient le meme bruit,
            # et le classement transversal pourrait rester accidentellement
            # inchange.
            store = synthetic.corrupt_future(
                store, after_index=cut, seed=987_654_321 + sum(map(ord, name))
            )
        out[name] = store
    return out


def specs_of(spec: InstrumentSpec) -> dict[str, InstrumentSpec]:
    return {
        name: spec.model_copy(update={"symbol": name, "root": name}) for name in SERIES
    }


def fingerprint(result: CrossSectionalRunResult) -> str:
    payload = {
        "equity": [e.hex() for e in result.equity.equity],
        "cash": [c.hex() for c in result.equity.cash],
        "ts": list(result.equity.ts_ns),
        "exposure": list(result.equity.exposure),
        "fills": [
            {
                "order_id": f.order_id,
                "symbol": f.symbol,
                "bar_index": f.bar_index,
                "side": f.side.value,
                "quantity": f.quantity,
                "price": f.price.hex(),
                "fee": f.fee.hex(),
                "tag": f.tag,
            }
            for f in result.fills
        ],
        "counters": result.counters.describe(),
        "trades": [
            (t.symbol, t.opened_bar, t.closed_bar, t.direction, t.gross_pnl.hex())
            for t in result.portfolio.closed_trades
        ],
        "report": result.describe(),
    }
    return json.dumps(payload, sort_keys=True)


def strategy() -> CrossSectionalMomentum:
    return CrossSectionalMomentum(lookback=12, skip=1, n_long=2, n_short=2, quantity=1)


def run_until(
    panel: Panel, spec: InstrumentSpec, cut: int, **kwargs: object
) -> CrossSectionalRunResult:
    execution = kwargs.pop(
        "execution", ExecutionConfig(fees=PerContractFee(), slippage=TickSlippage(1))
    )
    risk = kwargs.pop("risk", None)
    schedule = kwargs.pop("schedule", None)
    config = RunConfig(initial_cash=CASH, execution=execution, stop=cut + 1)  # type: ignore[arg-type]
    return CrossSectionalRunner(
        panel,
        specs_of(spec),
        config,
        risk=risk,  # type: ignore[arg-type]
        schedule=schedule,  # type: ignore[arg-type]
    ).run(strategy())


class TestFutureCorruption:
    @pytest.mark.parametrize("cut", CUTS)
    def test_a_run_stopped_at_k_ignores_everything_after_k(
        self, spec: InstrumentSpec, cut: int
    ):
        reference = run_until(build_panel(stores_of()), spec, cut)
        observed = run_until(build_panel(stores_of(cut)), spec, cut)
        assert fingerprint(observed) == fingerprint(reference)

    @pytest.mark.parametrize("cut", [60, 150])
    def test_it_holds_with_a_sizing_rule(self, spec: InstrumentSpec, cut: int):
        risk = RiskManager(sizing=FixedContracts(2))
        reference = run_until(build_panel(stores_of()), spec, cut, risk=risk)
        observed = run_until(build_panel(stores_of(cut)), spec, cut, risk=risk)
        assert fingerprint(observed) == fingerprint(reference)

    @pytest.mark.parametrize("cut", [60, 150])
    def test_it_holds_on_a_sparser_schedule(self, spec: InstrumentSpec, cut: int):
        schedule = EveryNRows(5)
        reference = run_until(build_panel(stores_of()), spec, cut, schedule=schedule)
        observed = run_until(build_panel(stores_of(cut)), spec, cut, schedule=schedule)
        assert fingerprint(observed) == fingerprint(reference)

    @pytest.mark.parametrize("cut", [60, 150])
    def test_it_holds_without_costs(self, spec: InstrumentSpec, cut: int):
        execution = ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())
        reference = run_until(build_panel(stores_of()), spec, cut, execution=execution)
        observed = run_until(build_panel(stores_of(cut)), spec, cut, execution=execution)
        assert fingerprint(observed) == fingerprint(reference)


class TestTheTestIsNotVacuous:
    """Un test de corruption qui passe pour de mauvaises raisons donne une
    garantie qui n'existe pas."""

    def test_the_strategy_actually_trades_and_rotates(self, spec: InstrumentSpec):
        result = run_until(build_panel(stores_of()), spec, 198)
        assert len(result.fills) > 20
        assert len(result.portfolio.closed_trades) > 5
        traded = {f.symbol for f in result.fills}
        assert len(traded) >= 4, "le classement ne tourne pas : le test serait creux"

    def test_running_past_the_cut_does_differ(self, spec: InstrumentSpec):
        reference = run_until(build_panel(stores_of()), spec, 198)
        observed = run_until(build_panel(stores_of(90)), spec, 198)
        assert fingerprint(observed) != fingerprint(reference)

    def test_the_corruption_reaches_every_instrument(self):
        clean, dirty = stores_of(), stores_of(90)
        for name in SERIES:
            assert float(clean[name].close[90]) == float(dirty[name].close[90])
            assert float(clean[name].close[91]) != float(dirty[name].close[91])

    def test_the_selection_itself_changes_after_the_cut(self):
        """Le bruit doit bouleverser le classement, pas seulement les prix."""
        from rsl.data.feed import MultiContext

        def targets(cut: int | None, row: int) -> dict[str, int]:
            panel = build_panel(stores_of(cut))
            ctx = MultiContext(panel)
            ctx._seek_row(row)
            momentum = strategy()
            return momentum._targets(momentum._scores(ctx))

        assert targets(None, 150) != targets(90, 150)


class TestAccountingUnderRotation:
    def test_the_invariant_holds_through_a_full_run(self, spec: InstrumentSpec):
        panel = build_panel(stores_of())
        result = run_until(panel, spec, N_BARS - 2)
        final = {s: float(panel.stores[s].close[N_BARS - 2]) for s in panel.symbols}
        assert result.portfolio.equity(final) == pytest.approx(
            result.portfolio.equity_incremental, rel=1e-12
        )

    def test_two_identical_runs_are_bit_identical(self, spec: InstrumentSpec):
        panel = build_panel(stores_of())
        first = run_until(panel, spec, N_BARS - 2)
        second = run_until(panel, spec, N_BARS - 2)
        assert fingerprint(first) == fingerprint(second)
