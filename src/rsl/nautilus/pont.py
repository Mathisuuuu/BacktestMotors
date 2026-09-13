"""Le PONT : nos objets vers ceux de Nautilus.

Pourquoi un pont plutot qu'une reecriture
------------------------------------------
La migration decidee le 2026-09-13 delegue l'EXECUTION a `nautilus_trader` et
garde ce qui n'existe pas ailleurs : le vocabulaire declaratif, le registre des
essais, la comptabilite du surapprentissage. Ce module est la frontiere entre
les deux, et il ne fait qu'une chose - traduire.

Il ne contient donc aucune decision de marche. Tout ce qu'il fait doit pouvoir
se verifier terme a terme contre `rsl.data.instruments` et les parquet du
depot.

Les deux desaccords de modele, et comment ils sont traites
-----------------------------------------------------------
1. **Les frais.** Notre `InstrumentSpec` porte des frais PAR CONTRAT en dollars
   (`commission_per_contract` + `exchange_fee_per_contract`). Nautilus attend
   des `maker_fee` / `taker_fee` en POURCENTAGE de la valeur de l'ordre. Les
   deux ne se convertissent pas : un montant fixe par contrat n'est pas un
   pourcentage tant qu'on ne connait pas le prix.
   Traitement : les frais ne passent PAS par l'instrument. Ils seront portes
   par un `FeeModel` du venue, qui sait facturer par contrat. Mettre un
   pourcentage approche ici serait une erreur silencieuse sur chaque trade.

2. **La marge.** Meme probleme : nos marges sont en dollars par contrat
   (17 000 pour ES), Nautilus les veut en fraction de la valeur notionnelle.
   La conversion depend du prix, donc de la date. Traitement : converties au
   prix de REFERENCE passe en argument, et le fait est rapporte - c'est une
   approximation, pas une equivalence.

Ce que le pont ne traduit pas
------------------------------
Le `.v.0` de nos symboles designe une serie CONTINUE non ajustee au roulement,
pas un contrat livrable. Nautilus modelise un vrai `FuturesContract` avec
activation et expiration. On declare donc des bornes larges et on le dit : la
serie continue n'a pas d'expiration, et pretendre le contraire ferait expirer
des positions au milieu de l'echantillon.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AssetClass as NautilusAssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Price, Quantity

from rsl.data.instruments import get_instrument
from rsl.data.schema import AssetClass, BarStore
from rsl.errors import ConfigurationError

# Une seule place de cotation simulee : le venue Nautilus sert a router les
# ordres, pas a decrire le monde. Nos dix instruments partagent le meme moteur
# de simulation, donc le meme venue - en declarer un par bourse compliquerait
# la configuration sans rien changer aux fills.
VENUE = Venue("SIM")

_CLASSES: dict[AssetClass, NautilusAssetClass] = {
    AssetClass.INDICES: NautilusAssetClass.INDEX,
    AssetClass.METAUX: NautilusAssetClass.COMMODITY,
    AssetClass.ENERGIE: NautilusAssetClass.COMMODITY,
    AssetClass.FOREX: NautilusAssetClass.FX,
}
"""Nos quatre classes vers celles de Nautilus.

`metaux` et `energie` tombent toutes deux sur `COMMODITY` : Nautilus ne les
distingue pas. La perte est reelle mais sans consequence - la classe ne sert
chez nous qu'a `max_per_category`, qui reste calcule de notre cote."""

# Une serie continue `.v.0` n'expire pas. Les bornes sont volontairement
# absurdes pour que personne ne les prenne pour une date de contrat.
ACTIVATION = int(datetime(2000, 1, 1, tzinfo=UTC).timestamp()) * 1_000_000_000
EXPIRATION = int(datetime(2099, 1, 1, tzinfo=UTC).timestamp()) * 1_000_000_000


def precision_de(tick_size: float) -> int:
    """Nombre de decimales impose par le pas de cotation.

    Nautilus exige une precision ENTIERE et refuse tout prix qui n'y tient pas.
    Un tick de 0,25 demande deux decimales ; un tick de 0,00001 (6E) en demande
    cinq. La deduire du tick plutot que de la declarer evite une seconde source
    qui finirait par mentir.
    """
    texte = f"{tick_size:.10f}".rstrip("0")
    if "." not in texte:
        return 0
    return len(texte.split(".")[1])


def instrument_nautilus(root: str, *, prix_reference: float) -> FuturesContract:
    """Notre `InstrumentSpec` en `FuturesContract`.

    `prix_reference` sert UNIQUEMENT a convertir les marges, qui sont en
    dollars chez nous et en fraction du notionnel chez Nautilus. Le passer
    explicitement plutot que de le deviner rend l'approximation visible dans
    l'appel.
    """
    spec = get_instrument(root)
    if spec.category is None:
        raise ConfigurationError(
            f"'{root}' n'a pas de classe d'actif : le pont ne peut pas la deviner."
        )
    if prix_reference <= 0.0:
        raise ConfigurationError(
            f"prix_reference doit etre > 0, recu {prix_reference} : il sert a "
            f"convertir des marges en dollars vers des fractions de notionnel."
        )

    notionnel = prix_reference * spec.multiplier
    precision = precision_de(spec.tick_size)
    return FuturesContract(
        instrument_id=InstrumentId(Symbol(spec.symbol), VENUE),
        raw_symbol=Symbol(spec.symbol),
        asset_class=_CLASSES[spec.category],
        currency=USD,
        price_precision=precision,
        price_increment=Price(spec.tick_size, precision),
        multiplier=Quantity.from_int(int(spec.multiplier))
        if float(spec.multiplier).is_integer()
        else Quantity(spec.multiplier, 2),
        lot_size=Quantity.from_int(1),
        underlying=spec.root,
        activation_ns=ACTIVATION,
        expiration_ns=EXPIRATION,
        ts_event=ACTIVATION,
        ts_init=ACTIVATION,
        # Converties au prix de reference : c'est une APPROXIMATION, la marge
        # reelle etant un montant fixe par contrat chez nous.
        margin_init=Decimal(str(round(spec.initial_margin / notionnel, 6))),
        margin_maint=Decimal(str(round(spec.maintenance_margin / notionnel, 6))),
        exchange=spec.exchange,
    )


def frais_par_contrat(root: str) -> float:
    """Le cout ALLER d'un contrat, en dollars.

    Somme de la commission et des frais de bourse, exactement comme
    `PerContractFee` le facture de notre cote. Isolee ici parce que le venue
    Nautilus la recevra sous une autre forme, et que les deux doivent rester
    le meme nombre.
    """
    spec = get_instrument(root)
    return spec.commission_per_contract + spec.exchange_fee_per_contract


def type_de_barre(root: str, agregation: str) -> BarType:
    """`BarType` Nautilus pour cet instrument.

    `agregation` est une specification Nautilus, par exemple `1-MINUTE-LAST`
    ou `1-DAY-LAST`. Elle n'est pas traduite depuis notre `Period` : les deux
    vocabulaires ne se recouvrent pas (nous avons des tranches ancrees sur la
    seance, Nautilus a des agregations calendaires), et une traduction
    approximative serait pire qu'une declaration explicite.
    """
    spec = get_instrument(root)
    return BarType.from_str(f"{spec.symbol}.{VENUE}-{agregation}-EXTERNAL")


def barres_nautilus(
    store: BarStore, bar_type: BarType, *, precision: int
) -> list[Bar]:
    """Notre `BarStore` en liste de `Bar` Nautilus.

    `ts_event` ET `ts_init` prennent tous deux notre `ts_close`, et c'est la
    decision la plus importante de ce module.

    Nautilus livre une barre a la strategie a `ts_init`. Lui donner notre
    `ts_event` - l'OUVERTURE de la barre - rendrait la barre visible avant sa
    cloture, c'est-a-dire exactement le look-ahead que ce depot rend
    inexprimable. `ts_close` est l'instant ou la barre est CONNUE, et c'est
    celui qui doit gouverner la livraison.
    """
    opens = np.asarray(store.open, dtype=np.float64)
    highs = np.asarray(store.high, dtype=np.float64)
    lows = np.asarray(store.low, dtype=np.float64)
    closes = np.asarray(store.close, dtype=np.float64)
    volumes = np.asarray(store.volume, dtype=np.float64)
    ts_close = np.asarray(store.ts_close, dtype=np.int64)

    barres: list[Bar] = []
    for i in range(store.n_bars):
        instant = int(ts_close[i])
        barres.append(
            Bar(
                bar_type=bar_type,
                open=Price(float(opens[i]), precision),
                high=Price(float(highs[i]), precision),
                low=Price(float(lows[i]), precision),
                close=Price(float(closes[i]), precision),
                volume=Quantity(float(volumes[i]), 0),
                ts_event=instant,
                ts_init=instant,
            )
        )
    return barres
