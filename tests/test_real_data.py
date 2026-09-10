"""Integration : les fichiers reels passent la validation telle qu'elle est ecrite.

Marque `slow` et saute si le repertoire de cotations n'est pas la. Ces tests ne
remplacent pas les tests synthetiques - ils verifient seulement que les regles
ne sont ni trop laches (elles verraient tout passer) ni trop strictes (elles
rejetteraient des donnees saines).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from rsl.data.instruments import get_instrument, known_roots
from rsl.data.loader import build_panel, load_bar_store, validate_file
from rsl.data.schema import ABSENT, AlignPolicy, Granularity

DATA_ROOT = Path(os.environ.get("RSL_DATA_DIR", r"C:\Users\Mathis\Desktop\Cotations"))

RELATIVE_PATHS = {
    "NQ": "indices/NQ_v0_1m.parquet",
    "ES": "indices/ES_v0_1m.parquet",
    "YM": "indices/YM_v0_1m.parquet",
    "FDAX": "indices/FDAX_v0_1m.parquet",
    "GC": "metaux/GC_v0_1m.parquet",
    "CL": "energie/CL_v0_1m.parquet",
    "6E": "forex/6E_v0_1m.parquet",
    "6B": "forex/6B_v0_1m.parquet",
    "6J": "forex/6J_v0_1m.parquet",
    "6A": "forex/6A_v0_1m.parquet",
}

MINUTE = Granularity.minutes(1)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not DATA_ROOT.exists(), reason=f"donnees absentes : {DATA_ROOT}"),
]


def path_of(root: str) -> Path:
    return DATA_ROOT / RELATIVE_PATHS[root]


class TestEveryFileValidates:
    @pytest.mark.parametrize("root", sorted(RELATIVE_PATHS))
    def test_file_passes_validation(self, root: str):
        path = path_of(root)
        if not path.exists():
            pytest.skip(f"fichier absent : {path}")
        report = validate_file(path, symbol=get_instrument(root).symbol)
        assert report.is_valid, report.render()

    def test_instrument_table_covers_every_file(self):
        assert set(RELATIVE_PATHS) == set(known_roots())


class TestLoadedStoreIsSound:
    @pytest.mark.parametrize("root", ["ES", "FDAX"])
    def test_store_invariants(self, root: str):
        path = path_of(root)
        if not path.exists():
            pytest.skip(f"fichier absent : {path}")
        store, report = load_bar_store(
            path, symbol=get_instrument(root).symbol, granularity=MINUTE
        )
        assert report.is_valid
        assert store.n_bars > 0
        assert len(store.source_hash) == 64
        assert not store.close.flags.writeable
        assert bool((np.diff(store.ts_event) > 0).all())
        assert bool((store.high >= store.low).all())
        assert bool((store.close <= store.high).all())
        assert bool((store.close >= store.low).all())


class TestRealPanelAlignment:
    def test_late_instrument_is_absent_not_backfilled(self):
        """FDAX demarre en mars 2025 : il ne doit exister nulle part avant."""
        for root in ("ES", "FDAX"):
            if not path_of(root).exists():
                pytest.skip("donnees partielles")

        stores = {}
        for root in ("ES", "FDAX"):
            spec = get_instrument(root)
            store, _ = load_bar_store(
                path_of(root), symbol=spec.symbol, granularity=MINUTE, with_hash=False
            )
            stores[spec.symbol] = store

        panel = build_panel(stores, align_policy=AlignPolicy.DROP)
        fdax = panel.row_index["FDAX.v.0"]
        first_row = int(np.flatnonzero(fdax != ABSENT)[0])
        assert bool((fdax[:first_row] == ABSENT).all())
        assert panel.n_stale("FDAX.v.0") == 0
        assert panel.present_symbols(0) == ("ES.v.0",)
