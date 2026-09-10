"""Fixtures partagees.

Ce fichier place aussi `tests/` sur `sys.path` (effet de bord du mode d'import
`prepend` de pytest), ce qui rend `fixtures.synthetic` importable depuis
`tests/unit` et `tests/adversarial`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures import synthetic
from rsl.data.schema import BarStore, InstrumentSpec
from rsl.engine.execution import ExecutionConfig, ZeroFee, ZeroSlippage

TEST_SYMBOL = "TEST.v.0"


@pytest.fixture
def spec() -> InstrumentSpec:
    """Instrument de test : multiplicateur et tick d'ES, frais volontairement ronds."""
    return InstrumentSpec(
        symbol=TEST_SYMBOL,
        root="TEST",
        name="Instrument de test",
        exchange="CME",
        currency="USD",
        multiplier=50.0,
        tick_size=0.25,
        commission_per_contract=1.0,
        exchange_fee_per_contract=1.0,
        initial_margin=10_000.0,
        maintenance_margin=9_000.0,
    )


@pytest.fixture
def zero_cost() -> ExecutionConfig:
    """Sans friction, DECLAREE. Reserve aux verifications analytiques."""
    return ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage())


@pytest.fixture
def constant_store() -> BarStore:
    return synthetic.make_store(synthetic.constant(500, 100.0), symbol="CONST.v.0")


@pytest.fixture
def ramp_store() -> BarStore:
    return synthetic.make_store(synthetic.ramp(500, 100.0, 1.0), symbol="RAMP.v.0")


@pytest.fixture
def sine_store() -> BarStore:
    return synthetic.make_store(synthetic.sine(500, 100.0, 10.0, 64), symbol="SINE.v.0")


@pytest.fixture
def walk_store() -> BarStore:
    return synthetic.make_store(synthetic.random_walk(500, seed=42), symbol="WALK.v.0")


@pytest.fixture
def test_store() -> BarStore:
    """Marche aleatoire seedee, portant le symbole de `spec`."""
    return synthetic.make_store(synthetic.random_walk(400, seed=2024), symbol=TEST_SYMBOL)


@pytest.fixture
def parquet_path(tmp_path: Path) -> Path:
    frame = synthetic.make_frame(synthetic.ramp(300, 100.0, 0.5))
    path = tmp_path / "synth.parquet"
    frame.write_parquet(path)
    return path
