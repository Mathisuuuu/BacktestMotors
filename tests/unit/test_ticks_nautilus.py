"""Les ticks SYNTHETIQUES : leur contrat, et ce qu'ils n'affirment pas.

Ce que ces tests fixent
------------------------
Le depot n'a aucune donnee de tick. Ce module en FABRIQUE a partir de l'OHLC,
ce qui est une supposition sur le chemin intra-barre. Les tests ne peuvent donc
pas verifier que le chemin est juste - il ne l'est pas, il est SUPPOSE. Ils
verifient les trois choses qui restent verifiables :

1. **La monotonie stricte des horodatages.** C'est le piege du dispositif :
   avec `close_stamp: period_end`, la cloture d'une barre et l'ouverture de la
   suivante portent le meme instant. Un tick d'ouverture pose la rendrait
   l'ordre des deux ambigu, et une decision prise a la cloture de `t` pourrait
   se voir remplie au meme nanoseconde.
2. **Les quatre prix sont bien ceux de la barre**, dans l'ordre declare.
3. **`intrabar_priority` gouverne l'ordre des extremes** - la MEME declaration
   que notre moteur, pour qu'aucune hypothese nouvelle n'entre.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest
from nautilus_trader.model.identifiers import InstrumentId

from fixtures import synthetic
from rsl.data.schema import BarStore, Granularity
from rsl.engine.execution import IntrabarPriority
from rsl.errors import ConfigurationError
from rsl.nautilus.ticks import (
    TICKS_PAR_BARRE,
    ordre_des_extremes,
    ticks_nautilus,
)

NS_MINUTE = 60_000_000_000
IID = InstrumentId.from_str("ES.v.0.SIM")


def magasin(n: int = 5) -> BarStore:
    """`n` barres d'une minute CONTIGUES : la cloture de l'une est
    l'horodatage d'ouverture de la suivante. C'est le cas qui piege."""
    ts = np.asarray([i * NS_MINUTE for i in range(n)], dtype=np.int64)
    closes = synthetic.random_walk(n, 4000.0, sigma=2.0, seed=11)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.004)
    return BarStore.build(
        symbol="ES.v.0", granularity=Granularity.minutes(1), ts_event=ts,
        open_=o, high=h, low=low, close=c,
        volume=np.full(n, 400.0), source_hash="synthetic",
    )


class TestLeNombreDeTicks:
    def test_quatre_par_barre(self):
        store = magasin(7)
        ticks = ticks_nautilus(store, IID, precision=2)
        assert len(ticks) == 7 * TICKS_PAR_BARRE

    def test_un_magasin_vide_rend_une_liste_vide(self):
        ts = np.zeros(0, dtype=np.int64)
        vide = BarStore.build(
            symbol="ES.v.0", granularity=Granularity.minutes(1), ts_event=ts,
            open_=np.zeros(0), high=np.zeros(0), low=np.zeros(0),
            close=np.zeros(0), volume=np.zeros(0), source_hash="vide",
        )
        assert ticks_nautilus(vide, IID, precision=2) == []


class TestLaMonotonieDesHorodatages:
    """Le piege du dispositif, et le seul qui puisse produire du look-ahead."""

    def test_les_instants_sont_strictement_croissants(self):
        ticks = ticks_nautilus(magasin(20), IID, precision=2)
        instants = [t.ts_event for t in ticks]
        assert all(b > a for a, b in pairwise(instants)), (
            "deux ticks au meme instant rendraient leur ordre ambigu"
        )

    def test_l_ouverture_tombe_apres_la_cloture_precedente(self):
        """Sans le decalage d'une nanoseconde, les deux coincideraient et une
        decision prise a la cloture de `t` pourrait se remplir au meme instant."""
        store = magasin(3)
        ticks = ticks_nautilus(store, IID, precision=2)
        for i in range(store.n_bars - 1):
            cloture = ticks[i * TICKS_PAR_BARRE + 3].ts_event
            ouverture_suivante = ticks[(i + 1) * TICKS_PAR_BARRE].ts_event
            assert ouverture_suivante > cloture

    def test_la_cloture_tombe_juste_avant_ts_close(self):
        """Le piege grave du dispositif, et la raison de sa forme.

        Ticks et barres circulent dans le MEME flux. Si le tick de cloture et
        la barre portaient le meme instant, l'ordre dans lequel Nautilus les
        traite deciderait si un ordre soumis dans `on_bar` peut se remplir au
        tick de cloture de la barre qui vient de le declencher - l'execution
        que `docs/execution-model.md` 2.1 declare inexprimable.

        A `ts_close - 1`, la barre arrive APRES son dernier tick, et le
        prochain tick disponible est l'ouverture de la barre suivante.
        """
        store = magasin(4)
        ticks = ticks_nautilus(store, IID, precision=2)
        attendus = [int(t) - 1 for t in np.asarray(store.ts_close, dtype=np.int64)]
        obtenus = [ticks[i * TICKS_PAR_BARRE + 3].ts_event
                   for i in range(store.n_bars)]
        assert obtenus == attendus

    def test_aucun_tick_ne_coincide_avec_la_livraison_d_une_barre(self):
        """La formulation directe de la garantie : un ordre soumis sur la barre
        `t` ne peut rencontrer aucun tick avant l'ouverture de `t+1`."""
        store = magasin(6)
        ticks = ticks_nautilus(store, IID, precision=2)
        livraisons = {int(t) for t in np.asarray(store.ts_close, dtype=np.int64)}
        for tick in ticks:
            assert tick.ts_event not in livraisons

    def test_tous_les_ticks_tiennent_dans_leur_barre(self):
        store = magasin(6)
        ticks = ticks_nautilus(store, IID, precision=2)
        debuts = np.asarray(store.ts_event, dtype=np.int64)
        fins = np.asarray(store.ts_close, dtype=np.int64)
        for i in range(store.n_bars):
            for rang in range(TICKS_PAR_BARRE):
                instant = ticks[i * TICKS_PAR_BARRE + rang].ts_event
                # Les DEUX bornes sont exclues : voir les deux tests ci-dessus.
                assert debuts[i] < instant < fins[i]

    def test_ts_init_vaut_ts_event(self):
        """Un tick est connu quand il a lieu - contrairement a une barre, qui
        n'est connue qu'a sa cloture."""
        for tick in ticks_nautilus(magasin(3), IID, precision=2):
            assert tick.ts_init == tick.ts_event


class TestLesPrix:
    def test_l_ouverture_puis_la_cloture_sont_celles_de_la_barre(self):
        store = magasin(5)
        ticks = ticks_nautilus(store, IID, precision=2)
        for i in range(store.n_bars):
            bloc = ticks[i * TICKS_PAR_BARRE:(i + 1) * TICKS_PAR_BARRE]
            assert float(bloc[0].price) == pytest.approx(float(store.open[i]))
            assert float(bloc[3].price) == pytest.approx(float(store.close[i]))

    def test_les_deux_extremes_sont_le_haut_et_le_bas(self):
        """A l'ARRONDI PRES : `Price` quantifie a la precision demandee.

        Les prix de ce decor viennent d'une marche aleatoire, donc hors de la
        grille de pas ; les vraies cotations y sont deja. La tolerance vaut
        donc un demi-pas de precision, et non zero.
        """
        store = magasin(5)
        ticks = ticks_nautilus(store, IID, precision=2)
        demi_pas = 0.5 * 10 ** -2
        for i in range(store.n_bars):
            bloc = ticks[i * TICKS_PAR_BARRE:(i + 1) * TICKS_PAR_BARRE]
            milieu = sorted(float(t.price) for t in bloc[1:3])
            attendu = sorted((float(store.high[i]), float(store.low[i])))
            assert milieu[0] == pytest.approx(attendu[0], abs=demi_pas)
            assert milieu[1] == pytest.approx(attendu[1], abs=demi_pas)

    def test_aucun_prix_ne_sort_de_la_barre(self):
        """Toujours a l'arrondi pres, et pour la meme raison."""
        store = magasin(8)
        ticks = ticks_nautilus(store, IID, precision=2)
        demi_pas = 0.5 * 10 ** -2
        for i in range(store.n_bars):
            for rang in range(TICKS_PAR_BARRE):
                prix = float(ticks[i * TICKS_PAR_BARRE + rang].price)
                assert float(store.low[i]) - demi_pas <= prix
                assert prix <= float(store.high[i]) + demi_pas


class TestLaPrioriteIntraBarre:
    """La MEME declaration que notre moteur : aucune hypothese nouvelle."""

    def test_pessimiste_pose_le_bas_en_premier(self):
        assert ordre_des_extremes(IntrabarPriority.PESSIMISTIC) == ("low", "high")

    def test_optimiste_pose_le_haut_en_premier(self):
        assert ordre_des_extremes(IntrabarPriority.OPTIMISTIC) == ("high", "low")

    def test_la_priorite_change_reellement_la_suite_de_ticks(self):
        store = magasin(4)
        pessimiste = ticks_nautilus(
            store, IID, precision=2, priorite=IntrabarPriority.PESSIMISTIC
        )
        optimiste = ticks_nautilus(
            store, IID, precision=2, priorite=IntrabarPriority.OPTIMISTIC
        )
        assert [float(t.price) for t in pessimiste] != [
            float(t.price) for t in optimiste
        ], "sinon la declaration ne servirait a rien"

    def test_seuls_les_extremes_permutent(self):
        store = magasin(4)
        a = ticks_nautilus(store, IID, precision=2,
                           priorite=IntrabarPriority.PESSIMISTIC)
        b = ticks_nautilus(store, IID, precision=2,
                           priorite=IntrabarPriority.OPTIMISTIC)
        for i in range(store.n_bars):
            base = i * TICKS_PAR_BARRE
            assert float(a[base].price) == float(b[base].price)
            assert float(a[base + 3].price) == float(b[base + 3].price)
            assert float(a[base + 1].price) == float(b[base + 2].price)


class TestCeQueLeModuleRefuse:
    def test_une_barre_trop_courte_leve(self):
        """Quatre ticks distincts exigent quatre nanosecondes. Aucune
        granularite reelle n'en est loin, mais le refus vaut mieux que deux
        ticks au meme instant."""
        ts = np.asarray([0, 3], dtype=np.int64)
        store = BarStore.build(
            symbol="ES.v.0", granularity=Granularity.minutes(1), ts_event=ts,
            open_=np.asarray([1.0, 1.0]), high=np.asarray([1.0, 1.0]),
            low=np.asarray([1.0, 1.0]), close=np.asarray([1.0, 1.0]),
            volume=np.asarray([1.0, 1.0]), source_hash="court",
            ts_close=np.asarray([3, 6], dtype=np.int64),
        )
        with pytest.raises(ConfigurationError, match="trop courte"):
            ticks_nautilus(store, IID, precision=2)


class TestLeVolume:
    def test_il_se_repartit_en_quatre_parts(self):
        store = magasin(3)
        ticks = ticks_nautilus(store, IID, precision=2)
        for i in range(store.n_bars):
            bloc = ticks[i * TICKS_PAR_BARRE:(i + 1) * TICKS_PAR_BARRE]
            total = sum(float(t.size) for t in bloc)
            assert total == pytest.approx(float(store.volume[i]), rel=1e-9)

    def test_un_volume_nul_ne_produit_pas_de_taille_nulle(self):
        """Nautilus refuse une taille nulle ; une seance creuse en produit."""
        ts = np.asarray([0, NS_MINUTE], dtype=np.int64)
        store = BarStore.build(
            symbol="ES.v.0", granularity=Granularity.minutes(1), ts_event=ts,
            open_=np.asarray([10.0, 10.0]), high=np.asarray([11.0, 11.0]),
            low=np.asarray([9.0, 9.0]), close=np.asarray([10.5, 10.5]),
            volume=np.zeros(2), source_hash="creux",
        )
        for tick in ticks_nautilus(store, IID, precision=2):
            assert float(tick.size) > 0.0
