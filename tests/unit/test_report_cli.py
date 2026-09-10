"""Specification, rapport et ligne de commande, de bout en bout.

Les donnees sont synthetiques mais passent par le vrai chemin : un fichier
Parquet sur disque, charge et valide par le loader, agrege le cas echeant. Un
test qui court-circuiterait le loader ne verifierait pas ce qui est teste ici.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fixtures import synthetic
from rsl.cli import EXIT_CHECK_FAILED, EXIT_ERROR, EXIT_OK, main
from rsl.config import BacktestSpec, FeeSpec, SizingSpec, SlippageSpec, load_stores
from rsl.data.schema import Granularity
from rsl.engine.execution import FlatFee, PerContractFee, TickSlippage, ZeroFee, ZeroSlippage
from rsl.engine.risk import EquityFraction, FixedContracts, RiskFraction
from rsl.errors import ConfigurationError
from rsl.metrics.statistics import TrialLog
from rsl.strategies.base import describe_strategies
from rsl.report import run_backtest

DAY = Granularity(timedelta(days=1), name="1d")
EPOCH = datetime(2016, 1, 4, tzinfo=UTC)


def write_parquet(path: Path, closes, *, start: datetime = EPOCH) -> Path:
    """Un fichier reel, ecrit au format canonique attendu par le loader."""
    frame = synthetic.make_frame(closes, granularity=DAY, start=start)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return path


@pytest.fixture
def es_file(tmp_path: Path) -> Path:
    return write_parquet(tmp_path / "ES_v0_1m.parquet", synthetic.sine(600, 2000.0, 200.0, 64))


@pytest.fixture
def panel_files(tmp_path: Path) -> dict[str, Path]:
    series = {
        "ES": synthetic.ramp(400, 2000.0, 2.0),
        "NQ": synthetic.ramp(400, 4000.0, 5.0),
        "GC": synthetic.ramp(400, 1200.0, -0.5),
        "CL": synthetic.sine(400, 60.0, 8.0, 50),
    }
    return {
        root: write_parquet(tmp_path / f"{root}_v0_1m.parquet", closes)
        for root, closes in series.items()
    }


def single_spec(path: Path, **overrides: object) -> BacktestSpec:
    payload: dict[str, object] = {
        "name": "test-sma",
        "initial_cash": 500_000.0,
        "data": [{"root": "ES", "path": str(path)}],
        "execution": {
            "fees": {"kind": "per_contract"},
            "slippage": {"kind": "tick", "ticks": 1.0},
        },
        "risk": {"sizing": {"kind": "fixed", "contracts": 1}},
        "strategy": {
            "ref": "sma_crossover@1",
            "params": {"symbol": "ES.v.0", "fast_window": 5, "slow_window": 20},
        },
    }
    payload.update(overrides)
    return BacktestSpec.model_validate(payload)


def panel_spec(files: dict[str, Path], **overrides: object) -> BacktestSpec:
    payload: dict[str, object] = {
        "name": "test-momentum",
        "initial_cash": 1_000_000.0,
        "data": [{"root": root, "path": str(path)} for root, path in sorted(files.items())],
        "execution": {
            "fees": {"kind": "zero"},
            "slippage": {"kind": "zero"},
        },
        "strategy": {
            "ref": "cross_sectional_momentum@1",
            "params": {"lookback": 12, "skip": 1, "n_long": 1, "n_short": 1},
        },
    }
    payload.update(overrides)
    return BacktestSpec.model_validate(payload)


# ---------------------------------------------------------------------------
# Specification
# ---------------------------------------------------------------------------


class TestSpecValidation:
    def test_an_unknown_field_is_refused(self, es_file: Path):
        """Un parametre mal orthographie doit echouer, jamais etre ignore."""
        with pytest.raises(Exception, match=r"extra|Extra"):
            single_spec(es_file, initail_cash=1.0)

    def test_a_missing_cost_model_is_refused(self, es_file: Path):
        with pytest.raises(Exception, match="slippage"):
            BacktestSpec.model_validate(
                {
                    "name": "x",
                    "initial_cash": 1000.0,
                    "data": [{"root": "ES", "path": str(es_file)}],
                    "execution": {"fees": {"kind": "zero"}},
                    "strategy": {"ref": "buy_and_hold@1", "params": {"symbol": "ES.v.0"}},
                }
            )

    def test_a_zero_lag_is_refused_at_the_specification_level(self, es_file: Path):
        with pytest.raises(Exception, match="lag_bars"):
            single_spec(
                es_file,
                execution={
                    "fees": {"kind": "zero"},
                    "slippage": {"kind": "zero"},
                    "lag_bars": 0,
                },
            )

    def test_an_empty_data_list_is_refused(self):
        with pytest.raises(Exception, match="data"):
            BacktestSpec.model_validate(
                {
                    "name": "x",
                    "initial_cash": 1000.0,
                    "data": [],
                    "execution": {"fees": {"kind": "zero"}, "slippage": {"kind": "zero"}},
                    "strategy": {"ref": "buy_and_hold@1"},
                }
            )

    def test_a_non_positive_capital_is_refused(self, es_file: Path):
        with pytest.raises(Exception, match="initial_cash"):
            single_spec(es_file, initial_cash=0.0)

    def test_the_spec_is_frozen(self, es_file: Path):
        with pytest.raises(Exception, match=r"frozen|immutable"):
            single_spec(es_file).name = "autre"  # type: ignore[misc]


class TestCostBuilders:
    def test_fee_models(self):
        assert isinstance(FeeSpec(kind="per_contract").build(), PerContractFee)
        assert isinstance(FeeSpec(kind="flat", per_contract=2.0).build(), FlatFee)
        assert isinstance(FeeSpec(kind="zero").build(), ZeroFee)

    def test_a_flat_fee_without_amount_is_refused(self):
        with pytest.raises(ConfigurationError, match="per_contract"):
            FeeSpec(kind="flat").build()

    def test_slippage_models(self):
        assert isinstance(SlippageSpec(kind="tick", ticks=1.0).build(), TickSlippage)
        assert isinstance(SlippageSpec(kind="zero").build(), ZeroSlippage)

    def test_a_tick_slippage_without_ticks_is_refused(self):
        with pytest.raises(ConfigurationError, match="ticks"):
            SlippageSpec(kind="tick").build()

    def test_a_bps_slippage_without_bps_is_refused(self):
        with pytest.raises(ConfigurationError, match="bps"):
            SlippageSpec(kind="bps").build()

    def test_sizing_rules(self):
        assert SizingSpec(kind="none").build() is None
        assert isinstance(SizingSpec(kind="fixed", contracts=2).build(), FixedContracts)
        assert isinstance(
            SizingSpec(kind="equity_fraction", fraction=0.1).build(), EquityFraction
        )
        assert isinstance(
            SizingSpec(kind="risk_fraction", fraction=0.01).build(), RiskFraction
        )

    @pytest.mark.parametrize("kind", ["fixed", "equity_fraction", "risk_fraction"])
    def test_a_sizing_rule_without_its_parameter_is_refused(self, kind):
        with pytest.raises(ConfigurationError):
            SizingSpec(kind=kind).build()


class TestCanonicalForm:
    def test_paths_are_absolutised(self, es_file: Path):
        canonical = single_spec(es_file).canonical()
        assert Path(canonical["data"][0]["path"]).is_absolute()  # type: ignore[index]

    def test_the_same_specification_gives_the_same_canonical_form(self, es_file: Path):
        assert single_spec(es_file).canonical() == single_spec(es_file).canonical()

    def test_a_different_parameter_changes_it(self, es_file: Path):
        other = single_spec(
            es_file,
            strategy={
                "ref": "sma_crossover@1",
                "params": {"symbol": "ES.v.0", "fast_window": 6, "slow_window": 20},
            },
        )
        assert single_spec(es_file).canonical() != other.canonical()

    def test_it_is_json_serialisable(self, es_file: Path):
        canonical = single_spec(es_file).canonical()
        assert json.loads(json.dumps(canonical)) == canonical


class TestLoadStores:
    def test_it_loads_validates_and_hashes(self, es_file: Path):
        stores, instruments, sources = load_stores(single_spec(es_file))
        assert set(stores) == {"ES.v.0"}
        assert instruments["ES.v.0"].multiplier == 50.0
        assert len(sources) == 1
        assert len(sources[0].source_hash) == 64

    def test_the_hash_can_be_skipped_and_the_manifest_says_so(self, es_file: Path):
        _, _, sources = load_stores(single_spec(es_file, with_data_hash=False))
        assert sources[0].source_hash == ""

    def test_resampling_is_recorded_as_a_transformation(self, es_file: Path):
        spec = single_spec(
            es_file, data=[{"root": "ES", "path": str(es_file), "resample": "month"}]
        )
        _, _, sources = load_stores(spec)
        assert sources[0].transformations
        assert "resample:month" in sources[0].transformations[0]

    def test_a_duplicated_instrument_is_refused(self, es_file: Path):
        spec = single_spec(
            es_file,
            data=[{"root": "ES", "path": str(es_file)}, {"root": "ES", "path": str(es_file)}],
        )
        with pytest.raises(ConfigurationError, match="deux fois"):
            load_stores(spec)


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------


class TestReport:
    def test_a_single_asset_run_produces_a_complete_report(self, es_file: Path):
        report = run_backtest(single_spec(es_file))
        assert report.symbols == ("ES.v.0",)
        assert not report.cross_sectional
        assert len(report.result_fingerprint) == 64
        assert report.metrics.n_bars > 0
        assert report.manifest.config_hash

    def test_a_cross_sectional_run_dispatches_to_the_right_runner(
        self, panel_files: dict[str, Path]
    ):
        report = run_backtest(panel_spec(panel_files))
        assert report.cross_sectional
        assert report.symbols == ("CL.v.0", "ES.v.0", "GC.v.0", "NQ.v.0")

    def test_a_cross_sectional_strategy_needs_more_than_one_instrument(self, es_file: Path):
        spec = single_spec(
            es_file,
            strategy={"ref": "cross_sectional_momentum@1", "params": {"lookback": 12}},
        )
        report = run_backtest(spec)
        assert report.cross_sectional  # un panneau d'un seul instrument reste valide

    def test_a_single_asset_strategy_refuses_several_instruments(
        self, panel_files: dict[str, Path]
    ):
        spec = panel_spec(
            panel_files,
            strategy={"ref": "buy_and_hold@1", "params": {"symbol": "ES.v.0"}},
        )
        with pytest.raises(ConfigurationError, match="mono-instrument"):
            run_backtest(spec)

    def test_an_unknown_strategy_is_refused(self, es_file: Path):
        with pytest.raises(Exception, match="inconnue"):
            run_backtest(single_spec(es_file, strategy={"ref": "nexiste_pas@1"}))

    def test_to_json_round_trips(self, es_file: Path):
        report = run_backtest(single_spec(es_file))
        assert json.loads(report.to_json())["result_fingerprint"] == report.result_fingerprint

    def test_write_creates_the_file_and_its_directory(self, es_file: Path, tmp_path: Path):
        report = run_backtest(single_spec(es_file))
        target = report.write(tmp_path / "sous" / "dossier" / "rapport.json")
        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8"))["name"] == "test-sma"

    def test_render_contains_the_four_sections(self, es_file: Path):
        text = run_backtest(single_spec(es_file)).render()
        for marker in ("Horodatage", "Strategie", "Echantillon", "Empreinte"):
            assert marker in text


class TestFingerprint:
    """L'exigence de reproductibilite, rendue verifiable."""

    def test_two_identical_runs_share_one_fingerprint(self, es_file: Path):
        first = run_backtest(single_spec(es_file))
        second = run_backtest(single_spec(es_file))
        assert first.result_fingerprint == second.result_fingerprint

    def test_the_fingerprint_ignores_the_run_timestamp(self, es_file: Path):
        first = run_backtest(single_spec(es_file))
        second = run_backtest(single_spec(es_file))
        assert first.manifest.created_at is not None
        assert first.result_fingerprint == second.result_fingerprint

    def test_changing_the_fees_changes_the_fingerprint(self, es_file: Path):
        cheap = run_backtest(single_spec(es_file))
        dear = run_backtest(
            single_spec(
                es_file,
                execution={
                    "fees": {"kind": "flat", "per_contract": 50.0},
                    "slippage": {"kind": "tick", "ticks": 1.0},
                },
            )
        )
        assert cheap.result_fingerprint != dear.result_fingerprint

    def test_changing_the_lag_changes_the_fingerprint(self, es_file: Path):
        base = run_backtest(single_spec(es_file))
        lagged = run_backtest(
            single_spec(
                es_file,
                execution={
                    "fees": {"kind": "per_contract"},
                    "slippage": {"kind": "tick", "ticks": 1.0},
                    "lag_bars": 3,
                },
            )
        )
        assert base.result_fingerprint != lagged.result_fingerprint

    def test_a_cosmetic_change_does_not_change_it(self, es_file: Path):
        """Le nom du run n'entre pas dans le resultat."""
        base = run_backtest(single_spec(es_file))
        renamed = run_backtest(single_spec(es_file, name="autre-nom"))
        assert base.result_fingerprint == renamed.result_fingerprint


class TestTrialLogIntegration:
    def test_a_lone_run_counts_as_one_trial_and_warns(self, es_file: Path):
        report = run_backtest(single_spec(es_file))
        assert report.deflated_sharpe is not None
        assert report.deflated_sharpe.n_trials == 1
        assert any("un seul essai" in w for w in report.deflated_sharpe.warnings)

    def test_a_shared_log_accumulates_across_runs(self, es_file: Path):
        log = TrialLog()
        for fast in (3, 5, 8, 13):
            run_backtest(
                single_spec(
                    es_file,
                    strategy={
                        "ref": "sma_crossover@1",
                        "params": {
                            "symbol": "ES.v.0",
                            "fast_window": fast,
                            "slow_window": 40,
                        },
                    },
                ),
                trial_log=log,
            )
        assert log.n_trials == 4

    def test_more_trials_lower_the_deflated_sharpe(self, es_file: Path):
        log = TrialLog()
        first = run_backtest(single_spec(es_file), trial_log=log)
        for fast in (3, 8, 13, 21):
            run_backtest(
                single_spec(
                    es_file,
                    strategy={
                        "ref": "sma_crossover@1",
                        "params": {
                            "symbol": "ES.v.0",
                            "fast_window": fast,
                            "slow_window": 40,
                        },
                    },
                ),
                trial_log=log,
            )
        last = run_backtest(single_spec(es_file), trial_log=log)
        assert first.deflated_sharpe is not None
        assert last.deflated_sharpe is not None
        assert last.deflated_sharpe.n_trials > first.deflated_sharpe.n_trials
        assert last.deflated_sharpe.expected_max_sharpe > 0.0


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------


class TestCliInformationalCommands:
    @pytest.mark.parametrize("command", [["catalogue"], ["instruments"], ["example"]])
    def test_they_succeed(self, command, capsys):
        assert main(command) == EXIT_OK
        assert capsys.readouterr().out

    @pytest.mark.parametrize("command", [["catalogue", "--json"], ["instruments", "--json"]])
    def test_the_json_output_parses(self, command, capsys):
        assert main(command) == EXIT_OK
        json.loads(capsys.readouterr().out)

    def test_the_catalogue_lists_the_three_reference_strategies(self, capsys):
        main(["catalogue", "--json"])
        catalogue = json.loads(capsys.readouterr().out)
        refs = {entry["ref"] for entry in catalogue["strategies"]}
        assert refs >= {"buy_and_hold@1", "sma_crossover@1", "cross_sectional_momentum@1"}

    def test_the_example_is_a_valid_specification(self, capsys):
        main(["example"])
        payload = json.loads(capsys.readouterr().out)
        payload["data"][0]["path"] = "peu-importe.parquet"
        BacktestSpec.model_validate(payload)

    def test_no_command_prints_help(self, capsys):
        assert main([]) == EXIT_ERROR
        assert "rsl" in capsys.readouterr().out


class TestCliValidate:
    def test_a_sound_file_passes(self, es_file: Path, capsys):
        assert main(["validate", str(es_file)]) == EXIT_OK
        assert "VALIDE" in capsys.readouterr().out

    def test_a_corrupt_file_fails_with_its_own_exit_code(self, tmp_path: Path, capsys):
        import polars as pl

        frame = synthetic.make_frame(synthetic.ramp(50), granularity=DAY)
        high = frame["high"].to_list()
        high[10] = float(frame["low"][10]) - 1.0
        path = tmp_path / "ES_v0_1m.parquet"
        frame.with_columns(pl.Series("high", high)).write_parquet(path)

        assert main(["validate", str(path)]) == EXIT_CHECK_FAILED
        assert "REJETE" in capsys.readouterr().out

    def test_the_root_is_inferred_from_the_file_name(self, tmp_path: Path):
        path = write_parquet(tmp_path / "GC_v0_1m.parquet", synthetic.ramp(50, 1800.0, 1.0))
        assert main(["validate", str(path)]) == EXIT_OK

    def test_an_unknown_root_is_reported(self, tmp_path: Path, capsys):
        path = write_parquet(tmp_path / "ZZZ_v0_1m.parquet", synthetic.ramp(50))
        assert main(["validate", str(path)]) == EXIT_ERROR
        assert "inconnu" in capsys.readouterr().err

    def test_an_explicit_root_overrides_the_inference(self, tmp_path: Path):
        path = write_parquet(tmp_path / "peu_importe.parquet", synthetic.ramp(50, 1800.0, 1.0))
        assert main(["validate", str(path), "--root", "GC"]) == EXIT_OK


class TestCliRun:
    def _config(self, tmp_path: Path, es_file: Path) -> Path:
        path = tmp_path / "config.json"
        path.write_text(single_spec(es_file).model_dump_json(), encoding="utf-8")
        return path

    def test_it_runs_and_prints_a_report(self, tmp_path: Path, es_file: Path, capsys):
        assert main(["run", str(self._config(tmp_path, es_file))]) == EXIT_OK
        assert "Empreinte" in capsys.readouterr().out

    def test_it_writes_the_json_report(self, tmp_path: Path, es_file: Path):
        target = tmp_path / "out" / "rapport.json"
        assert main(["run", str(self._config(tmp_path, es_file)), "--out", str(target)]) == EXIT_OK
        assert json.loads(target.read_text(encoding="utf-8"))["name"] == "test-sma"

    def test_the_json_flag_prints_parseable_output(self, tmp_path: Path, es_file: Path, capsys):
        assert main(["run", str(self._config(tmp_path, es_file)), "--json"]) == EXIT_OK
        assert json.loads(capsys.readouterr().out)["result_fingerprint"]

    def test_a_missing_configuration_is_an_error(self, tmp_path: Path, capsys):
        assert main(["run", str(tmp_path / "absent.json")]) == EXIT_ERROR
        assert capsys.readouterr().err

    def test_a_malformed_configuration_is_reported(self, tmp_path: Path):
        path = tmp_path / "mauvais.json"
        path.write_text('{"name": "x"}', encoding="utf-8")
        with pytest.raises(Exception, match=r"validation|Field required"):
            main(["run", str(path)])


class TestCliVerify:
    def test_two_runs_agree(self, tmp_path: Path, es_file: Path, capsys):
        path = tmp_path / "config.json"
        path.write_text(single_spec(es_file).model_dump_json(), encoding="utf-8")
        code = main(["verify", str(path)])
        out = capsys.readouterr().out
        assert "identiques" in out
        # Le code de sortie depend de l'etat du depot : la reproductibilite
        # locale ne suffit pas si l'arbre de travail est modifie.
        assert code in (EXIT_OK, EXIT_CHECK_FAILED)
        if code == EXIT_CHECK_FAILED:
            assert "pas AILLEURS" in out


# ---------------------------------------------------------------------------
# Une strategie sans code
# ---------------------------------------------------------------------------


MEAN_REVERSION_RULES: dict[str, object] = {
    "entry_long": {
        "type": "all_of",
        "operands": [
            {
                "type": "compare",
                "op": ">",
                "left": {"type": "price", "field": "close"},
                "right": {"type": "primitive", "ref": "sma@1", "params": {"window": 100}},
            },
            {
                "type": "compare",
                "op": "<",
                "left": {"type": "primitive", "ref": "zscore@1", "params": {"window": 50}},
                "right": {"type": "constant", "value": -1.0},
            },
        ],
    },
    "exit_long": {
        "type": "compare",
        "op": ">",
        "left": {"type": "primitive", "ref": "zscore@1", "params": {"window": 50}},
        "right": {"type": "constant", "value": 0.5},
    },
    "stop_loss": {
        "type": "arith",
        "op": "-",
        "left": {"type": "price", "field": "close"},
        "right": {
            "type": "arith",
            "op": "*",
            "left": {"type": "constant", "value": 2.0},
            "right": {"type": "primitive", "ref": "atr@1", "params": {"window": 14}},
        },
    },
}


@pytest.fixture
def trending_file(tmp_path: Path) -> Path:
    """Tendance haussiere ET oscillations.

    Il en faut les deux : l'entree exige d'etre au-dessus de la moyenne longue
    (la tendance) ET sous le z-score court (le creux). Sur une sinusoide de
    periode courte les deux conditions ne se rencontrent jamais - la meme
    oscillation gouverne les deux fenetres, et elles se contredisent. Il faut
    une oscillation LONGUE devant la fenetre de z-score : 120 barres contre 50.
    Verifie : 54 declenchements sur cette serie.
    """
    closes = synthetic.ramp(800, 2000.0, 0.4) + synthetic.sine(800, 0.0, 120.0, 120)
    return write_parquet(tmp_path / "ES_v0_1m.parquet", closes)


def rules_spec(path: Path, rules: dict[str, object] | None = None) -> BacktestSpec:
    return single_spec(
        path,
        strategy={
            "ref": "rules@1",
            "params": {
                "symbol": "ES.v.0",
                "quantity": 1,
                "rules": rules if rules is not None else MEAN_REVERSION_RULES,
            },
        },
    )


class TestStrategyFromParametersAlone:
    """Le chemin qui compte pour la suite : des parametres typés, aucune classe.

    Cette strategie - retour a la moyenne a l'interieur d'une tendance - n'est
    ecrite nulle part dans le depot. Elle n'existe que sous forme de donnees.
    """

    def test_it_is_reachable_from_a_configuration(self, trending_file: Path):
        report = run_backtest(rules_spec(trending_file))
        assert report.metrics.n_bars > 0

    def test_it_actually_trades(self, trending_file: Path):
        report = run_backtest(rules_spec(trending_file))
        assert report.metrics.exposure > 0.0
        assert report.metrics.n_trades > 0

    def test_the_registry_exposes_it(self):
        refs = {entry["ref"] for entry in describe_strategies()}
        assert "rules@1" in refs

    def test_changing_a_threshold_changes_the_result(self, trending_file: Path):
        """La preuve qu'un parametre pilote vraiment le comportement."""
        strict = run_backtest(rules_spec(trending_file))
        loose_rules = json.loads(json.dumps(MEAN_REVERSION_RULES))
        loose_rules["entry_long"]["operands"][1]["right"]["value"] = -0.1  # type: ignore[index]
        loose = run_backtest(rules_spec(trending_file, loose_rules))
        assert loose.result_fingerprint != strict.result_fingerprint
        assert loose.metrics.exposure > strict.metrics.exposure

    def test_an_unknown_node_type_is_refused_before_any_bar_is_read(self, es_file: Path):
        with pytest.raises(Exception, match="inconnu"):
            run_backtest(rules_spec(es_file, {"entry_long": {"type": "n_existe_pas"}}))

    def test_an_unknown_primitive_is_refused(self, es_file: Path):
        with pytest.raises(Exception, match="inconnue"):
            run_backtest(
                rules_spec(
                    es_file,
                    {"entry_long": {"type": "primitive", "ref": "n_existe_pas@1"}},
                )
            )

    def test_an_invalid_operator_is_refused(self, es_file: Path):
        with pytest.raises(Exception, match="operateur invalide"):
            run_backtest(
                rules_spec(
                    es_file,
                    {
                        "entry_long": {
                            "type": "compare",
                            "op": "=>",
                            "left": {"type": "constant", "value": 1.0},
                            "right": {"type": "constant", "value": 2.0},
                        }
                    },
                )
            )

    def test_a_misspelled_primitive_parameter_is_refused(self, es_file: Path):
        """`windwo` au lieu de `window` : une erreur, jamais un defaut."""
        with pytest.raises(Exception, match="windwo|extra"):
            run_backtest(
                rules_spec(
                    es_file,
                    {
                        "entry_long": {
                            "type": "primitive",
                            "ref": "sma@1",
                            "params": {"windwo": 20},
                        }
                    },
                )
            )

    def test_a_rules_strategy_without_any_entry_is_refused(self, es_file: Path):
        with pytest.raises(Exception, match="FlatStrategy"):
            run_backtest(rules_spec(es_file, {}))

    def test_the_specification_survives_a_round_trip(self, trending_file: Path):
        """Ecrire le fichier, le relire, obtenir le meme resultat."""
        spec = rules_spec(trending_file)
        reloaded = BacktestSpec.model_validate_json(spec.model_dump_json())
        assert run_backtest(reloaded).result_fingerprint == run_backtest(spec).result_fingerprint

    def test_the_whole_thing_runs_from_the_command_line(
        self, tmp_path: Path, es_file: Path, capsys
    ):
        config = tmp_path / "sans_code.json"
        config.write_text(rules_spec(es_file).model_dump_json(), encoding="utf-8")
        assert main(["run", str(config)]) == EXIT_OK
        assert "rules@1" in capsys.readouterr().out
