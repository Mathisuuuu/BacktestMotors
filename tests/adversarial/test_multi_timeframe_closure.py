"""Le multi-timeframe ne doit pas faire entrer le futur.

C'est le piege classique du backtest : une barre hebdomadaire lue depuis une
barre quotidienne du MILIEU de cette semaine contient le prix de vendredi. Le
socle l'evite par construction - le panneau s'aligne sur l'union des CLOTURES,
et un report ne peut propager qu'une barre deja close - mais « par
construction » est une affirmation, et ce fichier est ce qui la verifie.

Deux gardes independantes :

1. **Horodatage** : aucune ligne ne voit une barre grossiere dont la cloture
   lui est posterieure. C'est la garantie sous sa forme la plus directe.
2. **Corruption du futur** : remplacer toutes les barres apres un point ne
   change aucune valeur lue avant ce point.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.loader import build_panel
from rsl.data.resample import Period, resample
from rsl.data.schema import ABSENT, AlignPolicy, BarStore, Granularity
from rsl.errors import ConfigurationError

JOUR = Granularity.minutes(60 * 24)
FIN = "FIN.v.0"
GROS = "GROS.v.0"
N = 400


def paire(seed: int = 5) -> dict[str, BarStore]:
    """Une meme serie, publiee en quotidien et en hebdomadaire.

    C'est exactement le montage qu'un `alias` permet de declarer : le meme
    instrument a deux granularites, sous deux noms.
    """
    fin = synthetic.make_store(
        synthetic.random_walk(N, seed=seed), symbol=FIN,
        granularity=JOUR, start=synthetic.EPOCH,
    )
    gros, _ = resample(fin, Period.WEEK)
    gros = BarStore.build(
        symbol=GROS, granularity=gros.granularity, ts_event=gros.ts_event,
        open_=gros.open, high=gros.high, low=gros.low, close=gros.close,
        volume=gros.volume, is_stale=gros.is_stale, ts_close=gros.ts_close,
    )
    return {FIN: fin, GROS: gros}


def panneau(stores: dict[str, BarStore]):
    return build_panel(
        stores, align_policy=AlignPolicy.FFILL, max_ffill_bars=10,
        allow_mixed_granularity=True,
    )


class TestGardeDeclarable:
    def test_les_granularites_melangees_sont_refusees_par_defaut(self):
        """Le garde-fou protege les strategies transversales : comparer un
        rendement hebdomadaire a un rendement quotidien n'a pas de sens."""
        with pytest.raises(ConfigurationError, match="granularites heterogenes"):
            build_panel(paire(), align_policy=AlignPolicy.FFILL, max_ffill_bars=10)

    def test_le_message_dit_comment_faire_si_c_est_voulu(self):
        with pytest.raises(ConfigurationError, match="allow_mixed_granularity"):
            build_panel(paire(), align_policy=AlignPolicy.FFILL, max_ffill_bars=10)

    def test_declare_explicitement_le_panneau_se_construit(self):
        assert panneau(paire()).n_rows > 0

    def test_la_granularite_annoncee_est_la_plus_fine(self):
        """Le calendrier est l'union des clotures : son pas effectif est celui
        de la serie la plus dense. Ce champ n'est lu nulle part, mais il ne
        doit pas mentir."""
        assert panneau(paire()).granularity == JOUR


class TestAucuneBarreDuFutur:
    """Garde n° 1 : le test le plus direct de la propriete."""

    @pytest.mark.adversarial
    def test_aucune_ligne_ne_voit_une_cloture_posterieure(self):
        stores = paire()
        p = panneau(stores)
        vus = 0
        for ligne in range(p.ts_close.size):
            instant = int(p.ts_close[ligne])
            index = int(p.row_index[GROS][ligne])
            if index == ABSENT:
                continue
            cloture = int(stores[GROS].ts_close[index])
            assert cloture <= instant, (
                f"ligne {ligne} : barre hebdomadaire cloturant a {cloture} "
                f"vue depuis {instant} - le futur est entre"
            )
            vus += 1
        assert vus > 50, "le montage doit exercer un nombre utile de lignes"

    @pytest.mark.adversarial
    def test_la_barre_vue_est_bien_la_derniere_close(self):
        """Non seulement pas le futur, mais le passe le PLUS RECENT : voir une
        barre plus ancienne que necessaire serait un defaut different, et tout
        aussi silencieux."""
        stores = paire()
        p = panneau(stores)
        clotures = stores[GROS].ts_close
        for ligne in range(p.ts_close.size):
            instant = int(p.ts_close[ligne])
            index = int(p.row_index[GROS][ligne])
            if index == ABSENT:
                continue
            attendu = int(np.searchsorted(clotures, instant, side="right")) - 1
            assert index == attendu, f"ligne {ligne} : barre {index}, attendu {attendu}"


class TestCorruptionDuFutur:
    """Garde n° 2 : la garantie du socle, appliquee au nouveau canal."""

    @pytest.mark.adversarial
    def test_corrompre_le_futur_ne_change_rien_avant_la_coupure(self):
        coupure = 250
        propre = paire()
        sale = dict(propre)
        sale[FIN] = synthetic.corrupt_future(propre[FIN], after_index=coupure)
        gros_sale, _ = resample(sale[FIN], Period.WEEK)
        sale[GROS] = BarStore.build(
            symbol=GROS, granularity=gros_sale.granularity, ts_event=gros_sale.ts_event,
            open_=gros_sale.open, high=gros_sale.high, low=gros_sale.low,
            close=gros_sale.close, volume=gros_sale.volume,
            is_stale=gros_sale.is_stale, ts_close=gros_sale.ts_close,
        )

        a, b = panneau(propre), panneau(sale)
        limite = int(propre[FIN].ts_close[coupure])
        compares = 0
        for ligne in range(min(a.ts_close.size, b.ts_close.size)):
            if int(a.ts_close[ligne]) > limite:
                break
            ia, ib = int(a.row_index[GROS][ligne]), int(b.row_index[GROS][ligne])
            if ia == ABSENT or ib == ABSENT:
                continue
            assert propre[GROS].close[ia] == pytest.approx(sale[GROS].close[ib]), (
                f"ligne {ligne} : la cloture hebdomadaire a change alors que seul "
                f"le futur a ete corrompu"
            )
            compares += 1
        assert compares > 30, "le test doit comparer un nombre utile de lignes"


class TestReportMarque:
    @pytest.mark.adversarial
    def test_une_valeur_reportee_est_signalee_stale(self):
        """Le report n'est jamais implicite : la strategie peut le lire.

        Sur un panneau quotidien/hebdomadaire, la quasi-totalite des lignes
        portent une valeur hebdomadaire reportee - c'est normal, et c'est
        precisement ce qui doit etre visible."""
        p = panneau(paire())
        reportees = int(np.count_nonzero(p.is_stale[GROS]))
        assert reportees > 0, "le report doit etre marque, pas silencieux"
        # La serie fine ne reporte que sur la QUEUE du calendrier : le panneau
        # s'aligne sur l'UNION des clotures, et la derniere barre hebdomadaire
        # ferme apres la derniere quotidienne. Un report au MILIEU, lui, serait
        # anormal - il signalerait un trou dans la serie qui donne le rythme.
        fines_reportees = np.flatnonzero(p.is_stale[FIN])
        interieures = fines_reportees[fines_reportees < p.ts_close.size - 2]
        assert interieures.size == 0, (
            f"report interieur sur la serie fine, lignes {interieures.tolist()}"
        )

    def test_le_report_reste_borne(self):
        """`max_ffill_bars` borne la duree de vie d'une barre reportee."""
        with pytest.raises(ConfigurationError, match="max_ffill_bars"):
            build_panel(paire(), align_policy=AlignPolicy.FFILL,
                        allow_mixed_granularity=True)


class TestValeursLues:
    def test_la_valeur_hebdomadaire_lue_est_celle_de_la_semaine_precedente(self):
        """Verification de bout en bout, en clair : au milieu d'une semaine, la
        barre hebdomadaire visible est celle qui a cloture AVANT."""
        stores = paire()
        p = panneau(stores)
        fin_ts = stores[FIN].ts_close
        gros_ts = stores[GROS].ts_close
        controles = 0
        for ligne in range(20, p.ts_close.size):
            index = int(p.row_index[GROS][ligne])
            if index == ABSENT:
                continue
            instant = int(p.ts_close[ligne])
            if instant in set(gros_ts.tolist()):
                continue  # jour de cloture hebdomadaire : la barre du jour vaut
            assert int(gros_ts[index]) < instant
            controles += 1
            if controles > 40:
                break
        assert controles > 0
        assert fin_ts.size > gros_ts.size
