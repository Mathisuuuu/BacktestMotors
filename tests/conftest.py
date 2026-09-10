"""Fixtures partagees.

Ce fichier place aussi `tests/` sur `sys.path` (effet de bord du mode d'import
`prepend` de pytest), ce qui rend `fixtures.synthetic` importable depuis
`tests/unit` et `tests/adversarial`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures import synthetic
from rsl.data.schema import BarStore


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
def parquet_path(tmp_path: Path) -> Path:
    frame = synthetic.make_frame(synthetic.ramp(300, 100.0, 0.5))
    path = tmp_path / "synth.parquet"
    frame.write_parquet(path)
    return path
