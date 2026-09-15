"""Des TICKS synthetiques, pour que les deux moteurs remplissent au meme instant.

CE QU'IL FAUT SAVOIR AVANT DE S'EN SERVIR
==========================================
**Le depot ne possede aucune donnee de tick.** La racine de cotations porte dix
instruments, tous en barres d'une MINUTE. Ce module ne lit donc pas des ticks :
il en FABRIQUE a partir de l'OHLC, en supposant un chemin intra-barre.

Ce n'est pas un detail de mise en oeuvre, c'est la limite du dispositif, et
elle doit etre dite chaque fois qu'on lit un chiffre qui en sort.

Pourquoi le faire quand meme
-----------------------------
La divergence mesuree entre nos deux moteurs le 2026-09-13 n'etait PAS une
divergence d'arithmetique :

    _moule                        152 692  ->  189 099   +23,84 %
    rsi_survendu_hors_lundi       607 025  ->  712 877   +17,44 %

Elle venait d'une convention. Nous servons a `open[t+1]`, Nautilus recevant des
BARRES remplit a `close[t+1]` - une barre entiere d'ecart, qui se COMPOSE a
chaque trade. Tant qu'elle subsiste, les deux moteurs ne peuvent pas se
confronter : leurs chiffres ne mesurent pas la meme chose.

Un tick pose a l'OUVERTURE de chaque barre supprime cet ecart. Un ordre au
marche en attente depuis la barre precedente se remplit alors au premier tick
de la suivante - c'est-a-dire a `open[t+1]`, exactement comme chez nous.

Ce que la comparaison VALIDERA, et ce qu'elle ne validera pas
--------------------------------------------------------------
VALIDE : le cycle de vie des ordres, le choix du prix de remplissage, la
comptabilite des positions, l'application des frais, la courbe d'equity. C'est
l'essentiel du moteur, et c'est ce qu'aucun test du depot ne prouve
aujourd'hui - la forme fermee ne couvre que buy & hold, et la corruption du
futur ne prouve que la causalite.

NE VALIDE PAS : le comportement INTRA-BARRE. Les deux moteurs partageront
desormais le meme chemin SUPPOSE - le meme `intrabar_priority` - donc leur
accord sur ce point ne prouvera rien. Une convergence y serait une tautologie,
pas une preuve.

C'est une limite assumee et elle ne peut pas etre levee sans donnees de tick
reelles.

L'ordre des quatre ticks
-------------------------
`open`, puis les deux extremes, puis `close`. L'ordre des extremes suit
`intrabar_priority`, la MEME declaration que notre moteur utilise - aucune
hypothese nouvelle n'est introduite ici :

- `PESSIMISTIC` (defaut) : l'extreme DEFAVORABLE d'abord. Sans position
  declaree, le convention retenue est `low` puis `high`, celle de notre
  moteur pour un long.
- `OPTIMISTIC` : `high` puis `low`. A n'utiliser qu'en sensibilite.

Les horodatages, et les DEUX pieges qu'ils evitent
---------------------------------------------------
**Premier piege.** Avec `close_stamp: period_end`, la cloture d'une barre et
l'ouverture de la suivante portent le MEME instant. Poser le tick d'ouverture
la rendrait l'ordre des deux ambigu. Il est donc pose a `ts_event + 1 ns`,
strictement APRES la barre precedente.

**Second piege, et c'est le grave.** Les ticks et les barres circulent dans le
MEME flux : la strategie decide sur les barres, le simulateur remplit sur les
ticks. Si le tick de cloture et la barre portaient le meme instant, l'ordre
dans lequel Nautilus les traite deciderait si un ordre soumis dans `on_bar`
peut se remplir **au tick de cloture de la barre qui vient de le declencher**.

Ce serait exactement l'execution que `docs/execution-model.md` §2.1 declare
inexprimable :

    « Il n'existe aucun mode, aucun flag, aucun chemin de code permettant
      d'executer a la cloture de la barre qui a produit le signal. »

Le tick de cloture est donc pose a `ts_close - 1 ns`, strictement AVANT la
barre. La suite devient, pour chaque barre :

    ticks O, extreme, extreme, C   puis   la BARRE   puis   tick O suivant
    a+1    ...             b-1           b                 b+1

Un ordre soumis sur la barre a `b` ne peut donc rencontrer aucun tick avant
`b+1`, c'est-a-dire l'ouverture de la barre suivante. C'est notre semantique,
obtenue par la seule chronologie - pas par une regle qu'il faudrait faire
respecter.

Accessoirement c'est plus juste physiquement : la derniere transaction d'une
barre a lieu JUSTE AVANT sa cloture, pas a l'instant meme ou elle se ferme.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from nautilus_trader.model.data import TradeTick
from nautilus_trader.model.enums import AggressorSide
from nautilus_trader.model.identifiers import InstrumentId, TradeId
from nautilus_trader.model.objects import Price, Quantity

from rsl.data.schema import BarStore
from rsl.engine.execution import IntrabarPriority
from rsl.errors import ConfigurationError

TICKS_PAR_BARRE: Final[int] = 4
"""Ouverture, deux extremes, cloture. Pas davantage : chaque tick
supplementaire serait une invention de plus sur un chemin qu'on ne connait
pas."""


def _instants(ts_event: int, ts_close: int) -> tuple[int, int, int, int]:
    """Quatre instants strictement croissants dans `]ts_event, ts_close[`.

    Les DEUX bornes sont exclues, et chacune pour une raison differente :
    l'ouverture pour ne pas coincider avec la barre precedente, la cloture pour
    que la BARRE arrive apres son dernier tick. Voir l'en-tete du module.
    """
    duree = ts_close - ts_event
    if duree < TICKS_PAR_BARRE + 1:
        raise ConfigurationError(
            f"barre trop courte pour porter {TICKS_PAR_BARRE} ticks distincts "
            f"strictement entre ses bornes : {duree} ns. Il en faut au moins "
            f"{TICKS_PAR_BARRE + 1}, ce que toute granularite reelle depasse."
        )
    pas = duree // 3
    return (ts_event + 1, ts_event + pas, ts_event + 2 * pas, ts_close - 1)


def ordre_des_extremes(
    priorite: IntrabarPriority,
) -> tuple[str, str]:
    """Lequel des deux extremes est repute touche en premier.

    Aucune hypothese nouvelle : c'est la declaration que notre moteur applique
    deja, relue ici pour que les deux moteurs voient le meme chemin.
    """
    if priorite is IntrabarPriority.PESSIMISTIC:
        return ("low", "high")
    return ("high", "low")


def ticks_nautilus(
    store: BarStore,
    instrument_id: InstrumentId,
    *,
    precision: int,
    priorite: IntrabarPriority = IntrabarPriority.PESSIMISTIC,
) -> list[TradeTick]:
    """Un `BarStore` en ticks SYNTHETIQUES, quatre par barre.

    Le volume de la barre est reparti en quatre parts egales. C'est une
    convention, pas une mesure : elle sert a ce que la somme des tailles
    redonne le volume de la barre, et rien d'autre ne doit en etre deduit.

    `ts_event` et `ts_init` portent le meme instant : un tick est connu quand
    il a lieu, contrairement a une barre qui n'est connue qu'a sa cloture.
    """
    ouvre = np.asarray(store.open, dtype=np.float64)
    haut = np.asarray(store.high, dtype=np.float64)
    bas = np.asarray(store.low, dtype=np.float64)
    close = np.asarray(store.close, dtype=np.float64)
    volume = np.asarray(store.volume, dtype=np.float64)
    debuts = np.asarray(store.ts_event, dtype=np.int64)
    fins = np.asarray(store.ts_close, dtype=np.int64)

    premier, second = ordre_des_extremes(priorite)
    extremes = {"high": haut, "low": bas}

    ticks: list[TradeTick] = []
    for i in range(store.n_bars):
        instants = _instants(int(debuts[i]), int(fins[i]))
        prix = (
            float(ouvre[i]),
            float(extremes[premier][i]),
            float(extremes[second][i]),
            float(close[i]),
        )
        # Une taille nulle est refusee par Nautilus ; un volume de barre nul
        # existe pourtant (seance creuse). Le plancher a 1 est une convention
        # de PRESENCE, pas une mesure de flux.
        part = max(float(volume[i]) / TICKS_PAR_BARRE, 1.0)
        for rang in range(TICKS_PAR_BARRE):
            ticks.append(
                TradeTick(
                    instrument_id=instrument_id,
                    price=Price(prix[rang], precision),
                    size=Quantity(part, 0),
                    aggressor_side=AggressorSide.NO_AGGRESSOR,
                    trade_id=TradeId(f"{i}-{rang}"),
                    ts_event=instants[rang],
                    ts_init=instants[rang],
                )
            )
    return ticks
