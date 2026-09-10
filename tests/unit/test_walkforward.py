"""Evaluation par fenetres successives : plis, agregats, garde-fous."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fixtures import synthetic
from rsl.cli import EXIT_OK, main
from rsl.config import BacktestSpec
from rsl.data.schema import Granularity
from rsl.errors import ConfigurationError
from rsl.manifest import RunManifest
from rsl.metrics.performance import PerformanceMetrics
from rsl.metrics.statistics import AnchoredWalkForward, RollingWalkForward, Split
from rsl.walkforward import Fold, WalkForwardReport, run_walk_forward

DAY = Granularity(timedelta(days=1), name="1d")
EPOCH = datetime(2016, 1, 4, tzinfo=UTC)
CASH = 500_000.0


def write_parquet(path: Path, closes) -> Path:
    frame = synthetic.make_frame(closes, granularity=DAY, start=EPOCH)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return path


@pytest.fixture
def es_file(tmp_path: Path) -> Path:
    return write_parquet(tmp_path / "ES_v0_1m.parquet", synthetic.sine(1200, 2000.0, 200.0, 90))


@pytest.fixture
def panel_files(tmp_path: Path) -> dict[str, Path]:
    series = {
        "ES": synthetic.sine(600, 2000.0, 150.0, 70),
        "NQ": synthetic.sine(600, 4000.0, 400.0, 55),
        "GC": synthetic.ramp(600, 1200.0, 0.4),
        "CL": synthetic.ramp(600, 60.0, -0.02),
    }
    return {
        root: write_parquet(tmp_path / f"{root}_v0_1m.parquet", closes)
        for root, closes in series.items()
    }


def single_spec(path: Path, **overrides: object) -> BacktestSpec:
    payload: dict[str, object] = {
        "name": "wf-sma",
        "initial_cash": CASH,
        "data": [{"root": "ES", "path": str(path)}],
        "execution": {"fees": {"kind": "zero"}, "slippage": {"kind": "zero"}},
        "risk": {"sizing": {"kind": "fixed", "contracts": 1}},
        "strategy": {
            "ref": "sma_crossover@1",
            "params": {"symbol": "ES.v.0", "fast_window": 5, "slow_window": 20},
        },
    }
    payload.update(overrides)
    return BacktestSpec.model_validate(payload)


def panel_spec(files: dict[str, Path]) -> BacktestSpec:
    return BacktestSpec.model_validate(
        {
            "name": "wf-momentum",
            "initial_cash": 1_000_000.0,
            "data": [{"root": r, "path": str(p)} for r, p in sorted(files.items())],
            "execution": {"fees": {"kind": "zero"}, "slippage": {"kind": "zero"}},
            "strategy": {
                "ref": "cross_sectional_momentum@1",
                "params": {"lookback": 12, "skip": 1, "n_long": 1, "n_short": 1},
            },
        }
    )


# ---------------------------------------------------------------------------
# Agregats, sur des plis fabriques
# ---------------------------------------------------------------------------


def metrics_stub(
    *, total_return: float, sharpe: float | None, exposure: float = 0.5, n_trades: int = 3
) -> PerformanceMetrics:
    """Metriques minimales : seuls les champs lus par les agregats comptent."""
    return PerformanceMetrics(
        n_bars=100, n_daily_points=100, span_years=1.0, periods_per_year=252.0,
        annualisation_factor=15.87, risk_free_annual=0.0,
        initial_equity=CASH, final_equity=CASH * (1 + total_return),
        total_return=total_return, cagr=total_return,
        volatility_annual=0.1, downside_deviation_annual=0.1,
        sharpe=sharpe, sortino=sharpe, sharpe_per_period=None if sharpe is None else sharpe / 15.87,
        n_returns=99, returns_skewness=0.0, returns_kurtosis=3.0,
        drawdown_daily=None, drawdown_full=None,
        n_trades=n_trades, hit_rate=0.5, profit_factor=1.2,
        average_win=1.0, average_loss=-1.0, turnover_annual=1.0,
        exposure=exposure, average_gross_contracts=1.0, fees_paid=0.0, slippage_paid=0.0,
        is_ruined=False,
    )


def fabricated_report(returns_and_sharpes: list[tuple[float, float | None]]) -> WalkForwardReport:
    folds = tuple(
        Fold(
            index=i,
            split=Split(0, 100 + i, 100 + i, 200 + i),
            metrics=metrics_stub(total_return=r, sharpe=s),
            fingerprint=f"{i:064d}",
        )
        for i, (r, s) in enumerate(returns_and_sharpes)
    )
    return WalkForwardReport(
        name="fabrique",
        symbols=("X",),
        cross_sectional=False,
        splitter={"splitter": "rolling"},
        folds=folds,
        manifest=RunManifest.capture(config={}, seed=0),
        specification={},
    )


class TestAggregates:
    def test_sharpe_statistics(self):
        report = fabricated_report([(0.1, 1.0), (0.2, 2.0), (-0.1, 0.0)])
        assert report.sharpe_mean == pytest.approx(1.0)
        assert report.sharpe_median == pytest.approx(1.0)
        assert report.sharpe_spread == pytest.approx(1.0)

    def test_folds_without_a_sharpe_are_excluded(self):
        report = fabricated_report([(0.1, 1.0), (0.0, None), (0.3, 3.0)])
        assert report.sharpes == (1.0, 3.0)
        assert report.sharpe_mean == pytest.approx(2.0)

    def test_a_single_fold_has_no_spread(self):
        assert fabricated_report([(0.1, 1.0)]).sharpe_spread is None

    def test_positive_share(self):
        report = fabricated_report([(0.1, 1.0), (-0.2, -1.0), (0.3, 2.0), (0.0, 0.0)])
        assert report.positive_share == pytest.approx(0.5)

    def test_extremes(self):
        report = fabricated_report([(0.1, 1.0), (-0.2, -1.0), (0.3, 2.0)])
        assert report.worst_fold is not None and report.worst_fold.index == 1
        assert report.best_fold is not None and report.best_fold.index == 2

    def test_compounded_return(self):
        report = fabricated_report([(0.1, 1.0), (0.1, 1.0)])
        assert report.compounded_return == pytest.approx(1.1 * 1.1 - 1.0)

    def test_concentration_when_one_fold_carries_everything(self):
        report = fabricated_report([(0.0, 0.0), (0.0, 0.0), (0.2, 2.0)])
        assert report.concentration == pytest.approx(1.0)

    def test_concentration_exceeds_one_when_the_others_lose(self):
        """Le cas qui merite d'etre visible : un pli porte tout, les autres coulent."""
        report = fabricated_report([(-0.05, -1.0), (-0.05, -1.0), (0.2, 2.0)])
        assert report.concentration is not None
        assert report.concentration > 1.0

    def test_concentration_is_undefined_without_a_winning_fold(self):
        assert fabricated_report([(-0.1, -1.0), (-0.2, -2.0)]).concentration is None

    def test_an_idle_fold_is_detected_by_exposure_not_by_trades(self):
        """Une entree sans sortie donne zero trade mais une exposition reelle."""
        held = Fold(
            index=0,
            split=Split(0, 10, 10, 20),
            metrics=metrics_stub(total_return=0.1, sharpe=1.0, exposure=0.8, n_trades=0),
            fingerprint="x",
        )
        idle = Fold(
            index=1,
            split=Split(0, 10, 10, 20),
            metrics=metrics_stub(total_return=0.0, sharpe=None, exposure=0.0, n_trades=0),
            fingerprint="y",
        )
        assert not held.was_idle
        assert idle.was_idle

    def test_describe_is_serialisable(self):
        report = fabricated_report([(0.1, 1.0), (-0.1, -1.0)])
        assert json.loads(json.dumps(report.describe())) == report.describe()

    def test_render_shows_every_fold(self):
        text = fabricated_report([(0.1, 1.0), (-0.1, -1.0), (0.3, 2.0)]).render()
        assert text.count("pli ") >= 3
        assert "dispersion" in text


# ---------------------------------------------------------------------------
# Execution reelle
# ---------------------------------------------------------------------------


class TestRunWalkForward:
    def test_fold_count_and_windows_follow_the_splitter(self, es_file: Path):
        splitter = RollingWalkForward(train_bars=300, test_bars=200)
        report = run_walk_forward(single_spec(es_file), splitter)
        assert report.n_folds == 4
        assert [f.split.test_start for f in report.folds] == [300, 500, 700, 900]
        assert [f.split.test_stop for f in report.folds] == [500, 700, 900, 1100]

    def test_each_fold_starts_from_the_initial_capital(self, es_file: Path):
        report = run_walk_forward(
            single_spec(es_file), RollingWalkForward(train_bars=300, test_bars=200)
        )
        for fold in report.folds:
            assert fold.metrics.initial_equity == pytest.approx(CASH)

    def test_a_fold_only_trades_inside_its_window(self, es_file: Path):
        """Les barres d'apprentissage alimentent l'historique, pas le portefeuille."""
        report = run_walk_forward(
            single_spec(es_file), RollingWalkForward(train_bars=300, test_bars=200)
        )
        for fold in report.folds:
            assert fold.metrics.n_bars == fold.split.test_stop - fold.split.test_start

    def test_the_strategy_is_rebuilt_for_each_fold(self, es_file: Path):
        """Sinon le pli suivant heriterait de la position du precedent."""
        report = run_walk_forward(
            single_spec(es_file),
            RollingWalkForward(train_bars=300, test_bars=200),
            liquidate_folds=False,
        )
        # Chaque pli commence plat : son premier point d'equity vaut le capital.
        for fold in report.folds:
            assert fold.metrics.initial_equity == pytest.approx(CASH)

    def test_folds_are_liquidated_by_default(self, es_file: Path):
        report = run_walk_forward(
            single_spec(es_file), RollingWalkForward(train_bars=300, test_bars=200)
        )
        assert report.liquidate_folds
        assert not any("position ouverte" in w for w in report.warnings)

    def test_keeping_folds_open_is_flagged_when_it_happens(self, es_file: Path):
        report = run_walk_forward(
            single_spec(es_file),
            RollingWalkForward(train_bars=300, test_bars=200),
            liquidate_folds=False,
        )
        assert not report.liquidate_folds
        unclosed = [f for f in report.folds if f.metrics.n_trades == 0 and not f.was_idle]
        if unclosed:
            assert any("position ouverte" in w for w in report.warnings)

    def test_liquidating_changes_the_measured_returns(self, es_file: Path):
        splitter = RollingWalkForward(train_bars=300, test_bars=200)
        closed = run_walk_forward(single_spec(es_file), splitter, liquidate_folds=True)
        opened = run_walk_forward(single_spec(es_file), splitter, liquidate_folds=False)
        assert [f.fingerprint for f in closed.folds] != [f.fingerprint for f in opened.folds]

    def test_an_impossible_split_is_refused(self, es_file: Path):
        with pytest.raises(ConfigurationError, match="aucun pli"):
            run_walk_forward(
                single_spec(es_file), RollingWalkForward(train_bars=5000, test_bars=200)
            )

    def test_too_few_folds_warns(self, es_file: Path):
        report = run_walk_forward(
            single_spec(es_file), RollingWalkForward(train_bars=800, test_bars=350)
        )
        assert report.n_folds < 3
        assert any("pli(s) seulement" in w for w in report.warnings)

    def test_an_idle_fold_is_reported(self, es_file: Path):
        """Une strategie sans signal sur une fenetre ne mesure rien."""
        report = run_walk_forward(
            single_spec(
                es_file,
                strategy={
                    "ref": "sma_crossover@1",
                    "params": {"symbol": "ES.v.0", "fast_window": 100, "slow_window": 250},
                },
            ),
            RollingWalkForward(train_bars=300, test_bars=150),
        )
        idle = [f for f in report.folds if f.was_idle]
        if idle:
            assert any("sans aucune position" in w for w in report.warnings)

    def test_anchored_and_rolling_agree_while_nothing_is_optimised(self, es_file: Path):
        """Propriete honnete du dispositif actuel, plutot que deux mesures feintes."""
        spec = single_spec(es_file)
        rolling = run_walk_forward(spec, RollingWalkForward(train_bars=300, test_bars=200))
        anchored = run_walk_forward(
            spec, AnchoredWalkForward(initial_train_bars=300, test_bars=200)
        )
        assert [f.fingerprint for f in rolling.folds] == [f.fingerprint for f in anchored.folds]

    def test_it_is_deterministic(self, es_file: Path):
        splitter = RollingWalkForward(train_bars=300, test_bars=200)
        first = run_walk_forward(single_spec(es_file), splitter)
        second = run_walk_forward(single_spec(es_file), splitter)
        assert [f.fingerprint for f in first.folds] == [f.fingerprint for f in second.folds]

    def test_the_manifest_covers_the_splitter_too(self, es_file: Path):
        report = run_walk_forward(
            single_spec(es_file), RollingWalkForward(train_bars=300, test_bars=200)
        )
        other = run_walk_forward(
            single_spec(es_file), RollingWalkForward(train_bars=400, test_bars=200)
        )
        assert report.manifest.config_hash != other.manifest.config_hash

    def test_describe_is_serialisable(self, es_file: Path):
        report = run_walk_forward(
            single_spec(es_file), RollingWalkForward(train_bars=300, test_bars=200)
        )
        assert json.loads(json.dumps(report.describe())) == report.describe()


class TestCrossSectionalWalkForward:
    def test_it_splits_on_the_common_calendar(self, panel_files: dict[str, Path]):
        report = run_walk_forward(
            panel_spec(panel_files), RollingWalkForward(train_bars=200, test_bars=100)
        )
        assert report.cross_sectional
        assert report.n_folds == 4
        assert report.symbols == ("CL.v.0", "ES.v.0", "GC.v.0", "NQ.v.0")

    def test_each_fold_trades(self, panel_files: dict[str, Path]):
        report = run_walk_forward(
            panel_spec(panel_files), RollingWalkForward(train_bars=200, test_bars=100)
        )
        assert all(not f.was_idle for f in report.folds)


class TestCli:
    def _config(self, tmp_path: Path, es_file: Path) -> Path:
        path = tmp_path / "config.json"
        path.write_text(single_spec(es_file).model_dump_json(), encoding="utf-8")
        return path

    def test_it_runs(self, tmp_path: Path, es_file: Path, capsys):
        code = main(
            ["walkforward", str(self._config(tmp_path, es_file)), "--train", "300", "--test", "200"]
        )
        assert code == EXIT_OK
        out = capsys.readouterr().out
        assert "walk-forward" in out
        assert "dispersion" in out

    def test_the_anchored_flag_is_accepted(self, tmp_path: Path, es_file: Path, capsys):
        code = main(
            [
                "walkforward", str(self._config(tmp_path, es_file)),
                "--train", "300", "--test", "200", "--anchored",
            ]
        )
        assert code == EXIT_OK
        assert "anchored" in capsys.readouterr().out

    def test_the_json_output_parses(self, tmp_path: Path, es_file: Path, capsys):
        main(
            [
                "walkforward", str(self._config(tmp_path, es_file)),
                "--train", "300", "--test", "200", "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["aggregate"]["n_folds"] == 4

    def test_it_writes_the_report(self, tmp_path: Path, es_file: Path):
        target = tmp_path / "out" / "wf.json"
        main(
            [
                "walkforward", str(self._config(tmp_path, es_file)),
                "--train", "300", "--test", "200", "--out", str(target),
            ]
        )
        assert json.loads(target.read_text(encoding="utf-8"))["name"] == "wf-sma"

    def test_keep_open_is_accepted(self, tmp_path: Path, es_file: Path, capsys):
        code = main(
            [
                "walkforward", str(self._config(tmp_path, es_file)),
                "--train", "300", "--test", "200", "--keep-open",
            ]
        )
        assert code == EXIT_OK
        assert "laisses ouverts" in capsys.readouterr().out
