"""Table statique des specifications de contrats.

AVERTISSEMENT (`docs/execution-model.md` §6.1). Les marges sont des valeurs
courantes (2025-2026). Appliquees a un echantillon qui demarre en 2016, elles
sont ANACHRONIQUES : la marge initiale de ES a varie d'un facteur trois sur la
periode, et a triple en mars 2020 - exactement quand une strategie en a le plus
besoin. Un backtest qui contraint la marge avec cette table sous-estime la
contrainte dans les periodes agitees. Le manifeste de run reporte cet
avertissement.

Les `tick_size` et `multiplier`, eux, sont exacts : les pas de cotation ont ete
verifies contre les donnees (plus petit mouvement de prix observe sur les
200 000 dernieres barres de chaque serie), et le produit
`multiplier x tick_size` retombe sur la valeur du tick publiee par la place
(12,50 $ pour ES, 6,25 $ pour 6E/6B/6J, 5 $ pour NQ/YM/6A, 10 $ pour GC/CL,
12,50 EUR pour FDAX).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from rsl.data.schema import InstrumentSpec
from rsl.errors import RegistryError

_SPECS: Final[tuple[InstrumentSpec, ...]] = (
    InstrumentSpec(
        symbol="ES.v.0", root="ES", name="S&P 500", exchange="CME", currency="USD",
        multiplier=50.0, tick_size=0.25,
        commission_per_contract=0.85, exchange_fee_per_contract=1.45,
        initial_margin=17_000.0, maintenance_margin=15_500.0,
    ),
    InstrumentSpec(
        symbol="NQ.v.0", root="NQ", name="Nasdaq 100", exchange="CME", currency="USD",
        multiplier=20.0, tick_size=0.25,
        commission_per_contract=0.85, exchange_fee_per_contract=1.45,
        initial_margin=27_000.0, maintenance_margin=24_500.0,
    ),
    InstrumentSpec(
        symbol="YM.v.0", root="YM", name="Dow Jones", exchange="CBOT", currency="USD",
        multiplier=5.0, tick_size=1.0,
        commission_per_contract=0.85, exchange_fee_per_contract=1.45,
        initial_margin=11_000.0, maintenance_margin=10_000.0,
    ),
    InstrumentSpec(
        symbol="FDAX.v.0", root="FDAX", name="DAX 40", exchange="EUREX", currency="EUR",
        multiplier=25.0, tick_size=0.5,
        commission_per_contract=1.00, exchange_fee_per_contract=0.50,
        initial_margin=33_000.0, maintenance_margin=30_000.0,
    ),
    InstrumentSpec(
        symbol="GC.v.0", root="GC", name="Or", exchange="COMEX", currency="USD",
        multiplier=100.0, tick_size=0.1,
        commission_per_contract=0.85, exchange_fee_per_contract=1.60,
        initial_margin=15_000.0, maintenance_margin=13_500.0,
    ),
    InstrumentSpec(
        symbol="CL.v.0", root="CL", name="Petrole WTI", exchange="NYMEX", currency="USD",
        multiplier=1_000.0, tick_size=0.01,
        commission_per_contract=0.85, exchange_fee_per_contract=1.60,
        initial_margin=6_500.0, maintenance_margin=5_900.0,
    ),
    InstrumentSpec(
        symbol="6E.v.0", root="6E", name="EUR/USD", exchange="CME", currency="USD",
        multiplier=125_000.0, tick_size=0.00005,
        commission_per_contract=0.85, exchange_fee_per_contract=1.60,
        initial_margin=3_000.0, maintenance_margin=2_700.0,
    ),
    InstrumentSpec(
        symbol="6B.v.0", root="6B", name="GBP/USD", exchange="CME", currency="USD",
        multiplier=62_500.0, tick_size=0.0001,
        commission_per_contract=0.85, exchange_fee_per_contract=1.60,
        initial_margin=2_500.0, maintenance_margin=2_250.0,
    ),
    InstrumentSpec(
        symbol="6J.v.0", root="6J", name="USD/JPY", exchange="CME", currency="USD",
        multiplier=12_500_000.0, tick_size=0.0000005,
        commission_per_contract=0.85, exchange_fee_per_contract=1.60,
        initial_margin=4_000.0, maintenance_margin=3_600.0,
    ),
    InstrumentSpec(
        symbol="6A.v.0", root="6A", name="AUD/USD", exchange="CME", currency="USD",
        multiplier=100_000.0, tick_size=0.00005,
        commission_per_contract=0.85, exchange_fee_per_contract=1.60,
        initial_margin=2_000.0, maintenance_margin=1_800.0,
    ),
)

INSTRUMENTS: Final[MappingProxyType[str, InstrumentSpec]] = MappingProxyType(
    {spec.symbol: spec for spec in _SPECS}
)

BY_ROOT: Final[MappingProxyType[str, InstrumentSpec]] = MappingProxyType(
    {spec.root: spec for spec in _SPECS}
)

MARGIN_CAVEAT: Final[str] = (
    "Marges statiques 2025-2026 appliquees a tout l'echantillon : anachroniques "
    "avant 2025, et notablement sous-estimees pendant mars 2020."
)


def get_instrument(key: str) -> InstrumentSpec:
    """Resout un symbole continu ('ES.v.0') ou une racine ('ES')."""
    if key in INSTRUMENTS:
        return INSTRUMENTS[key]
    if key in BY_ROOT:
        return BY_ROOT[key]
    known = ", ".join(sorted(BY_ROOT))
    raise RegistryError(f"instrument inconnu : '{key}'. Connus : {known}")


def known_roots() -> tuple[str, ...]:
    """Racines triees : l'ordre ne depend d'aucun parcours de `set`."""
    return tuple(sorted(BY_ROOT))
