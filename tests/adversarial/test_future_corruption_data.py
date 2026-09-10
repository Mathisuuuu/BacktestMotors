"""Test exige n° 1, volet couche de donnees.

Remplacer toutes les barres apres l'index `k` par du bruit ne doit rien changer
a ce qu'un `Context` observe jusqu'a `k`. C'est la version "socle de donnees"
du test de corruption du futur ; la version "moteur" (les trois strategies de
reference) viendra avec le runner.

Si ce test echoue, aucune garantie du dessus ne tient : le contexte lui-meme
laisse passer le futur.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarFeed, PanelFeed
from rsl.data.loader import build_panel
from rsl.data.schema import ALL_FIELDS, BarStore, Field

pytestmark = pytest.mark.adversarial

SERIES = {
    "constante": synthetic.constant(400, 100.0),
    "rampe": synthetic.ramp(400, 100.0, 0.5),
    "sinusoide": synthetic.sine(400, 100.0, 10.0, 64),
    "marche_aleatoire": synthetic.random_walk(400, seed=20240101),
}

CUTS = [1, 17, 200, 398]


def observe(store: BarStore, stop: int) -> list[tuple[float, ...]]:
    """Tout ce qu'un `Context` peut extraire, barre par barre, jusqu'a `stop`."""
    trace: list[tuple[float, ...]] = []
    for ctx in BarFeed(store, stop=stop):
        row = [ctx.ts.timestamp(), float(ctx.n_bars_seen)]
        row.extend(ctx.value(f) for f in ALL_FIELDS)
        depth = min(ctx.n_bars_seen, 20)
        row.extend(float(x) for x in ctx.values(Field.CLOSE, depth))
        row.extend(float(x) for x in ctx.history(depth).high)
        trace.append(tuple(row))
    return trace


@pytest.mark.parametrize("name", sorted(SERIES))
@pytest.mark.parametrize("cut", CUTS)
def test_corrupting_the_future_changes_nothing_before_the_cut(name: str, cut: int):
    store = synthetic.make_store(SERIES[name], symbol=f"{name.upper()}.v.0")
    corrupted = synthetic.corrupt_future(store, after_index=cut)

    reference = observe(store, stop=cut + 1)
    observed = observe(corrupted, stop=cut + 1)

    assert observed == reference, f"{name} : le futur a fuite avant l'index {cut}"


@pytest.mark.parametrize("name", sorted(SERIES))
def test_corruption_is_real(name: str):
    """Garde-fou : sans cette verification, un corrupteur inerte ferait passer le test."""
    store = synthetic.make_store(SERIES[name], symbol="X.v.0")
    corrupted = synthetic.corrupt_future(store, after_index=200)
    assert not np.allclose(store.close[201:], corrupted.close[201:])
    assert np.array_equal(store.close[:201], corrupted.close[:201])
    assert np.array_equal(store.ts_event, corrupted.ts_event)


def test_corrupted_store_stays_ohlc_valid():
    """Le bruit doit rester valide, sinon le test mesurerait la validation."""
    store = synthetic.make_store(SERIES["marche_aleatoire"], symbol="X.v.0")
    corrupted = synthetic.corrupt_future(store, after_index=50)
    assert (corrupted.high >= corrupted.low).all()
    assert (corrupted.close <= corrupted.high).all()
    assert (corrupted.close >= corrupted.low).all()
    assert (corrupted.open <= corrupted.high).all()
    assert (corrupted.open >= corrupted.low).all()
    assert (corrupted.volume >= 0).all()


def test_corrupt_future_rejects_out_of_range_cut():
    store = synthetic.make_store(SERIES["rampe"], symbol="X.v.0")
    with pytest.raises(ValueError, match="hors de"):
        synthetic.corrupt_future(store, after_index=10_000)


@pytest.mark.parametrize("cut", [5, 50, 150])
def test_panel_is_equally_immune(cut: int):
    """Meme garantie sur la coupe transversale."""

    def trace(stores: dict[str, BarStore]) -> list[tuple[object, ...]]:
        panel = build_panel(stores)
        out: list[tuple[object, ...]] = []
        for ctx in PanelFeed(panel, stop=cut + 1):
            row: list[object] = [ctx.ts.timestamp(), ctx.symbols]
            row.extend(ctx[s].value(Field.CLOSE) for s in ctx.symbols)
            out.append(tuple(row))
        return out

    clean = {
        "A": synthetic.make_store(SERIES["rampe"], symbol="A"),
        "B": synthetic.make_store(SERIES["sinusoide"], symbol="B"),
    }
    dirty = {sym: synthetic.corrupt_future(store, after_index=cut) for sym, store in clean.items()}

    assert trace(dirty) == trace(clean)
