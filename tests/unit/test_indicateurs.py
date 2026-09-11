"""Valeurs des indicateurs : ce que le parcours du registre ne peut pas voir.

`tests/adversarial/test_registre_primitives.py` verifie ce qui vaut pour
TOUTES les primitives - pas de look-ahead, warmup honnete, ni NaN ni infini.
Aucun de ces tests ne remarquerait qu'une moyenne ponderee utilise les mauvais
poids : elle resterait finie, deterministe et aveugle au futur.

Ce fichier repond a l'autre question - « la formule est-elle la bonne ? » - par
deux moyens, et jamais par une seconde implementation de la meme formule :

1. **Forme fermee.** Sur une rampe arithmetique ou une serie constante, la
   valeur attendue se calcule a la main. C'est la preuve la plus forte.
2. **Equivalence avec du code deja eprouve.** `bollinger(middle)` DOIT valoir
   `sma@1` ; `variance@1` DOIT valoir le carre de `stdev@1`. Ces egalites
   rattachent le code neuf a du code que la suite couvre depuis longtemps.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, Field
from rsl.primitives.registry import bind_primitive

PAS = 1.0
DEPART = 100.0
N = 300


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


@pytest.fixture(scope="module")
def rampe() -> BarContext:
    """Rampe arithmetique sans meche : toutes les formes fermees sont exactes."""
    store = synthetic.make_store(synthetic.ramp(N, DEPART, PAS), wick=0.0)
    return at(store, 250)


@pytest.fixture(scope="module")
def plat() -> BarContext:
    return at(synthetic.make_store(synthetic.constant(N, 42.0), wick=0.0), 250)


@pytest.fixture(scope="module")
def volumes_nuls() -> BarContext:
    """Volume a zero : une seance sans echange, ca existe."""
    closes = synthetic.random_walk(N, seed=5)
    ouvertures, hauts, bas, clotures = synthetic.ohlc_from_closes(closes)
    store = BarStore.build(
        symbol="Z.v.0", granularity=synthetic.MINUTE,
        ts_event=synthetic.timestamps(N),
        open_=ouvertures, high=hauts, low=bas, close=clotures,
        volume=np.zeros(N), source_hash="z",
    )
    return at(store, 250)


@pytest.fixture(scope="module")
def marche() -> BarContext:
    """Marche aleatoire a volume variable, pour les equivalences."""
    closes = synthetic.random_walk(N, seed=99)
    ouvertures, hauts, bas, clotures = synthetic.ohlc_from_closes(closes)
    generateur = np.random.default_rng(99)
    store = BarStore.build(
        symbol="S.v.0", granularity=synthetic.MINUTE,
        ts_event=synthetic.timestamps(N),
        open_=ouvertures, high=hauts, low=bas, close=clotures,
        volume=generateur.uniform(500.0, 5_000.0, N), source_hash="s",
    )
    return at(store, 250)


def lire(ctx: BarContext, ref: str, **params: object) -> float | None:
    return bind_primitive(ref, **params)(ctx)


PRIX_COURANT = DEPART + 250 * PAS  # 350.0 a la barre 250


# ---------------------------------------------------------------------------
# 1. Formes fermees sur une rampe : le retard de chaque moyenne
# ---------------------------------------------------------------------------


class TestRetardDesMoyennes:
    """Sur une rampe de pas `d`, chaque moyenne accuse un retard CONNU.

    C'est la propriete qui distingue reellement ces indicateurs les uns des
    autres, et la seule qu'on puisse verifier sans reimplementer la formule.
    """

    @pytest.mark.parametrize(("ref", "fenetre", "retard"), [
        ("sma@1", 20, 19 / 2),      # (w-1)/2
        ("wma@1", 20, 19 / 3),      # (w-1)/3 : deux fois moins
        ("trima@1", 21, 10.0),      # deux SMA de 11 : 2 * (11-1)/2
        ("swma@1", 21, 10.0),       # poids symetriques : (w-1)/2
    ])
    def test_le_retard_est_celui_annonce(self, rampe, ref, fenetre, retard):
        attendu = PRIX_COURANT - PAS * retard
        assert lire(rampe, ref, window=fenetre) == pytest.approx(attendu)

    @pytest.mark.parametrize("ref", ["dema@1", "tema@1"])
    def test_les_ema_multiples_annulent_le_retard(self, rampe, ref):
        """Sur une serie LINEAIRE, la correction de retard est exacte.

        C'est leur raison d'etre, et c'est verifiable au flottant pres : la
        DEMA extrapole la pente, et une rampe n'a qu'une pente.
        """
        assert lire(rampe, ref, window=10) == pytest.approx(PRIX_COURANT, abs=1e-9)

    def test_hma_reduit_le_retard_sans_l_annuler(self, rampe):
        """La Hull est souvent presentee comme « sans retard ». Elle ne l'est
        pas : mesure ici, il reste 0,67 barre contre 7,5 pour une SMA de meme
        fenetre. C'est une reduction d'un facteur onze, pas une annulation."""
        hull = lire(rampe, "hma@1", window=16)
        simple = lire(rampe, "sma@1", window=16)
        assert PRIX_COURANT - hull == pytest.approx(2 / 3, abs=1e-9)
        assert PRIX_COURANT - simple == pytest.approx(7.5)

    def test_zlema_reduit_le_retard_de_moitie_environ(self, rampe):
        reste = PRIX_COURANT - lire(rampe, "zlema@1", window=10)
        assert 0.0 < reste < 1.0

    @pytest.mark.parametrize("ref", [
        "sma@1", "wma@1", "trima@1", "swma@1", "pwma@1", "alma@1", "smma@1",
        "dema@1", "tema@1", "t3@1", "zlema@1", "hma@1", "kama@1", "vwma@1",
        "midpoint@1", "linreg@1", "linreg_forecast@1", "linreg_intercept@1",
        "median@1", "ema@1",
    ])
    def test_toute_moyenne_d_une_constante_vaut_la_constante(self, plat, ref):
        """Propriete definitionnelle : si elle echoue, les poids ne somment
        pas a 1, ce qu'aucun test de forme ne verrait."""
        assert lire(plat, ref, window=10) == pytest.approx(42.0, abs=1e-9)


class TestRegressionLineaire:
    """Sur une rampe, la regression est EXACTE : ecart nul, pente = pas."""

    def test_linreg_vaut_le_prix_courant(self, rampe):
        assert lire(rampe, "linreg@1", window=20) == pytest.approx(PRIX_COURANT)

    def test_la_projection_avance_d_un_pas(self, rampe):
        assert lire(rampe, "linreg_forecast@1", window=20) == pytest.approx(
            PRIX_COURANT + PAS
        )

    def test_l_ordonnee_est_la_premiere_barre_de_la_fenetre(self, rampe):
        assert lire(rampe, "linreg_intercept@1", window=20) == pytest.approx(
            PRIX_COURANT - 19 * PAS
        )

    def test_la_correlation_au_temps_est_parfaite(self, rampe):
        assert lire(rampe, "cti@1", window=20) == pytest.approx(1.0)
        assert lire(rampe, "linreg_r2@1", window=20) == pytest.approx(1.0)

    def test_l_angle_est_l_arctangente_du_pas(self, rampe):
        assert lire(rampe, "linreg_angle@1", window=20) == pytest.approx(45.0)

    def test_une_rampe_descendante_donne_une_correlation_de_moins_un(self):
        descente = synthetic.make_store(synthetic.ramp(N, 400.0, -1.0), wick=0.0)
        assert lire(at(descente, 250), "cti@1", window=20) == pytest.approx(-1.0)

    def test_l_ecart_a_la_regression_est_nul_sur_une_rampe(self, rampe):
        """`cfo@1` mesure cet ecart : sur une droite, il vaut zero."""
        assert lire(rampe, "cfo@1", window=20) == pytest.approx(0.0, abs=1e-9)


class TestBornesEtSaturation:
    """Sur une rampe strictement croissante, les oscillateurs saturent."""

    @pytest.mark.parametrize(("ref", "attendu"), [
        ("psl@1", 100.0),              # 100 % de barres en hausse
        ("cmo@1", 100.0),              # aucune baisse
        ("percentile_rank@1", 100.0),  # la barre courante est la plus haute
        ("max_drawdown@1", 0.0),       # aucun repli
        ("ulcer_index@1", 0.0),        # aucune douleur
        ("rsi@1", 100.0),              # deja couvert, verifie comme temoin
    ])
    def test_saturation_haute(self, rampe, ref, attendu):
        assert lire(rampe, ref, window=20) == pytest.approx(attendu)

    def test_aroon_sur_une_rampe(self, rampe):
        """Le plus haut est la barre courante (`up = 100`) ; le plus bas est la
        plus ancienne de la fenetre, donc `down` vaut `100/window`."""
        assert lire(rampe, "aroon@1", window=20, output="up") == pytest.approx(100.0)
        assert lire(rampe, "aroon@1", window=20, output="down") == pytest.approx(5.0)

    def test_max_drawdown_mesure_le_repli(self):
        """Une serie qui monte a 200 puis redescend a 150 : -25 %."""
        closes = np.concatenate([
            np.linspace(100.0, 200.0, 50), np.linspace(200.0, 150.0, 50)
        ])
        ctx = at(synthetic.make_store(closes, wick=0.0), 99)
        assert lire(ctx, "max_drawdown@1", window=100) == pytest.approx(-25.0)

    @pytest.mark.parametrize("ref", ["bop@1", "cmf@1"])
    def test_les_oscillateurs_bornes_le_restent(self, marche, ref):
        valeur = lire(marche, ref, window=20)
        assert valeur is None or -1.0 <= valeur <= 1.0

    @pytest.mark.parametrize("ref", [
        "mfi@1", "stoch@1", "stoch_rsi@1", "rvi_volatility@1",
        "psl@1", "percentile_rank@1", "aroon@1", "chop@1",
    ])
    def test_les_oscillateurs_en_pourcentage_restent_dans_zero_cent(self, marche, ref):
        valeur = lire(marche, ref, window=14)
        assert valeur is None or 0.0 <= valeur <= 100.0

    def test_l_oscillateur_ultime_aussi(self, marche):
        """A part : ses trois horizons se nomment `fast`/`medium`/`slow`, pas
        `window` - et `extra=forbid` refuse le mauvais nom, comme il doit."""
        valeur = lire(marche, "ultimate@1")
        assert valeur is None or 0.0 <= valeur <= 100.0


# ---------------------------------------------------------------------------
# 2. Equivalences : rattacher le code neuf a du code deja eprouve
# ---------------------------------------------------------------------------


class TestEquivalences:
    """Chaque egalite doit tenir a l'ECART NUL, pas approximativement.

    Une tolerance large masquerait une erreur de convention - un `ddof`
    different, une amorce differente - qui est exactement ce qu'on cherche.
    """

    def test_le_milieu_de_bollinger_est_une_sma(self, marche):
        assert lire(marche, "bollinger@1", window=20, output="middle") == lire(
            marche, "sma@1", window=20
        )

    def test_le_milieu_de_keltner_est_une_ema(self, marche):
        """Verifie aussi que les DEUX partagent la meme convention d'amorce :
        une amorce differente donnerait un ecart petit mais non nul."""
        assert lire(marche, "keltner@1", window=20, output="middle") == lire(
            marche, "ema@1", window=20
        )

    def test_la_variance_est_le_carre_de_l_ecart_type(self, marche):
        carre = lire(marche, "stdev@1", window=20) ** 2
        assert lire(marche, "variance@1", window=20) == pytest.approx(carre, abs=1e-12)

    def test_natr_est_atr_rapporte_a_la_cloture(self, marche):
        attendu = 100.0 * lire(marche, "atr@1", window=14) / marche.value(Field.CLOSE)
        assert lire(marche, "natr@1", window=14) == pytest.approx(attendu, abs=1e-12)

    def test_roc_est_mom_rapporte_a_l_ancien_prix(self, marche):
        ancien = marche.value(Field.CLOSE, lag=10)
        attendu = 100.0 * lire(marche, "mom@1", window=10) / ancien
        assert lire(marche, "roc@1", window=10) == pytest.approx(attendu, abs=1e-12)

    def test_le_stochastique_non_lisse_est_le_stochastique_brut(self, marche):
        """`stoch@1` avec des lissages de 1 doit retomber sur `stochastic@1`.

        C'est le test qui garantit que le lissage a ete AJOUTE et que la
        formule de base n'a pas ete reecrite au passage.
        """
        assert lire(
            marche, "stoch@1", window=14, smooth_k=1, smooth_d=1, output="k"
        ) == lire(marche, "stochastic@1", window=14)

    def test_midprice_est_le_milieu_du_canal(self, marche):
        haut = lire(marche, "rolling_high@1", window=20)
        bas = lire(marche, "rolling_low@1", window=20)
        assert lire(marche, "midprice@1", window=20) == pytest.approx((haut + bas) / 2)

    def test_r2_est_le_carre_de_la_correlation(self, marche):
        assert lire(marche, "linreg_r2@1", window=20) == pytest.approx(
            lire(marche, "cti@1", window=20) ** 2, abs=1e-12
        )

    def test_le_prix_typique_est_la_moyenne_des_trois(self, marche):
        attendu = (
            marche.value(Field.HIGH) + marche.value(Field.LOW) + marche.value(Field.CLOSE)
        ) / 3.0
        assert lire(marche, "typical_price@1") == pytest.approx(attendu, abs=1e-12)

    def test_vwma_a_volume_constant_est_une_sma(self):
        """Le volume ne peut peser que s'il varie. A volume plat, la moyenne
        ponderee DOIT retomber sur la moyenne simple."""
        store = synthetic.make_store(synthetic.random_walk(N, seed=3), volume=1_000.0)
        ctx = at(store, 250)
        assert lire(ctx, "vwma@1", window=20) == pytest.approx(
            lire(ctx, "sma@1", window=20), abs=1e-9
        )

    def test_le_lissage_de_wilder_differe_de_l_ema(self, marche):
        """Le pendant des tests precedents : deux choses differentes doivent
        RESTER differentes. Sans cela, une equivalence accidentelle passerait
        pour une equivalence voulue."""
        assert lire(marche, "smma@1", window=14) != lire(marche, "ema@1", window=14)


class TestSortiesCoherentes:
    """Les sorties multiples d'un meme indicateur sont liees par identite.

    Elles sont calculees dans le meme appel : ces tests garantissent que les
    derivees le sont vraiment, et ne sont pas recalculees a cote.
    """

    def test_l_histogramme_est_la_ligne_moins_le_signal(self, marche):
        commun = {"window": 12, "slow_window": 26}
        assert lire(marche, "ppo@1", **commun, output="histogram") == pytest.approx(
            lire(marche, "ppo@1", **commun, output="line")
            - lire(marche, "ppo@1", **commun, output="signal"),
            abs=1e-12,
        )

    def test_l_oscillateur_aroon_est_la_difference_des_deux_branches(self, marche):
        assert lire(marche, "aroon@1", window=14, output="oscillator") == pytest.approx(
            lire(marche, "aroon@1", window=14, output="up")
            - lire(marche, "aroon@1", window=14, output="down")
        )

    def test_le_vortex_diff_est_la_difference_des_deux_branches(self, marche):
        assert lire(marche, "vortex@1", window=14, output="diff") == pytest.approx(
            lire(marche, "vortex@1", window=14, output="plus")
            - lire(marche, "vortex@1", window=14, output="minus"),
            abs=1e-12,
        )

    @pytest.mark.parametrize("ref", ["bollinger@1", "keltner@1", "donchian@1", "envelope@1"])
    def test_les_trois_lignes_d_une_bande_sont_ordonnees(self, marche, ref):
        haut = lire(marche, ref, window=20, output="upper")
        milieu = lire(marche, ref, window=20, output="middle")
        bas = lire(marche, ref, window=20, output="lower")
        assert bas <= milieu <= haut, f"{ref} : {bas} / {milieu} / {haut}"

    def test_percent_b_vaut_zero_sur_la_borne_basse_et_un_sur_la_haute(self, marche):
        """Definition du %B, verifiee en reconstruisant la position du prix."""
        haut = lire(marche, "bollinger@1", window=20, output="upper")
        bas = lire(marche, "bollinger@1", window=20, output="lower")
        prix = marche.value(Field.CLOSE)
        attendu = (prix - bas) / (haut - bas)
        assert lire(marche, "bollinger@1", window=20, output="percent") == pytest.approx(
            attendu, abs=1e-12
        )

    def test_psar_et_supertrend_donnent_un_sens_franc(self, marche):
        for ref in ("psar@1", "supertrend@1"):
            sens = lire(marche, ref, output="direction") if ref == "psar@1" else lire(
                marche, ref, window=10, output="direction"
            )
            assert sens in (1.0, -1.0), f"{ref} rend {sens}"


class TestDegenerescences:
    """Ce que chaque indicateur rend quand il n'y a rien a mesurer.

    Le socle exige `None` plutot qu'une valeur inventee. Un oscillateur qui
    repondrait 50 sur une serie plate affirmerait un equilibre qu'il n'a pas
    mesure - et cette valeur traverserait ensuite une comparaison sans que
    rien ne la signale.
    """

    @pytest.mark.parametrize("ref", [
        "cmo@1", "rsi@1", "stoch@1", "bop@1", "rvi_volatility@1", "entropy@1",
        "hurst@1", "autocorrelation@1", "skew@1", "kurtosis@1",
    ])
    def test_une_serie_plate_ne_donne_pas_de_valeur(self, plat, ref):
        assert lire(plat, ref, window=20) is None

    @pytest.mark.parametrize("ref", ["sma@1", "median@1", "midpoint@1", "quantile@1"])
    def test_mais_une_moyenne_reste_definie(self, plat, ref):
        """Distinction qui compte : l'absence de MOUVEMENT n'est pas l'absence
        de NIVEAU. Une moyenne de 42 vaut 42, meme sans variation."""
        assert lire(plat, ref, window=20) == pytest.approx(42.0)

    def test_la_largeur_d_une_bande_plate_est_nulle_pas_indefinie(self, plat):
        assert lire(plat, "bollinger@1", window=20, output="width") == pytest.approx(0.0)

    def test_mais_la_position_dans_une_bande_plate_est_indefinie(self, plat):
        """Diviser par une largeur nulle n'a pas de reponse. `None`, pas 0,5."""
        assert lire(plat, "bollinger@1", window=20, output="percent") is None


class TestStatistiques:
    """Les descripteurs se verifient contre des valeurs calculees a la main."""

    def test_la_mediane_d_une_rampe_est_son_milieu(self, rampe):
        assert lire(rampe, "median@1", window=21) == pytest.approx(PRIX_COURANT - 10.0)

    def test_les_quantiles_encadrent_la_fenetre(self, rampe):
        assert lire(rampe, "quantile@1", window=20, q=0.0) == pytest.approx(
            PRIX_COURANT - 19.0
        )
        assert lire(rampe, "quantile@1", window=20, q=1.0) == pytest.approx(PRIX_COURANT)

    def test_le_quantile_median_est_la_mediane(self, marche):
        assert lire(marche, "quantile@1", window=21, q=0.5) == pytest.approx(
            lire(marche, "median@1", window=21)
        )

    def test_l_ecart_absolu_moyen_d_une_rampe(self, rampe):
        """Sur 0..w-1 centre, la moyenne des ecarts absolus vaut `w/4` pour w
        pair : ici 20 barres de pas 1 donnent 5."""
        assert lire(rampe, "mad@1", window=20) == pytest.approx(5.0)

    def test_l_erreur_type_decroit_en_racine_de_la_fenetre(self, marche):
        ecart = lire(marche, "stdev@1", window=36)
        assert lire(marche, "stderr@1", window=36) == pytest.approx(ecart / 6.0, abs=1e-12)

    def test_l_autocorrelation_d_une_serie_alternee_est_negative(self):
        """Une serie qui monte et descend alternativement a une
        autocorrelation de -1 au decalage 1. C'est le cas extreme du retour a
        la moyenne, et il doit se lire tel quel."""
        closes = 100.0 + np.tile([0.0, 1.0], 100)
        ctx = at(synthetic.make_store(closes, wick=0.0), 199)
        assert lire(ctx, "autocorrelation@1", window=40, lag=1) == pytest.approx(
            -1.0, abs=1e-6
        )

    def test_la_correlation_d_un_champ_avec_lui_meme_vaut_un(self, marche):
        assert lire(
            marche, "correlation@1", window=30, field="close", other="close"
        ) == pytest.approx(1.0)

    def test_l_entropie_est_normalisee_entre_zero_et_un(self, marche):
        valeur = lire(marche, "entropy@1", window=60, bins=8)
        assert valeur is not None
        assert 0.0 <= valeur <= 1.0

    def test_le_kurtosis_est_excedentaire(self):
        """Sur des rendements gaussiens, il doit tourner autour de 0 et non
        de 3 : c'est la convention annoncee par le resume."""
        generateur = np.random.default_rng(11)
        closes = 100.0 * np.exp(np.cumsum(generateur.normal(0.0, 0.002, 4000)))
        ctx = at(synthetic.make_store(closes, wick=0.0), 3999)
        valeur = lire(ctx, "kurtosis@1", window=3000)
        assert valeur is not None
        assert abs(valeur) < 1.0, valeur


class TestTransformations:
    """Recombinaisons d'une barre : verifiables champ par champ."""

    def test_les_quatre_prix_composites(self, marche):
        haut, bas = marche.value(Field.HIGH), marche.value(Field.LOW)
        ouverture, cloture = marche.value(Field.OPEN), marche.value(Field.CLOSE)
        assert lire(marche, "median_price@1") == pytest.approx((haut + bas) / 2)
        assert lire(marche, "weighted_close@1") == pytest.approx(
            (haut + bas + 2 * cloture) / 4
        )
        assert lire(marche, "average_price@1") == pytest.approx(
            (ouverture + haut + bas + cloture) / 4
        )
        assert lire(marche, "bar_range@1") == pytest.approx(haut - bas)

    def test_le_pivot_utilise_la_barre_precedente(self, marche):
        """Le point qui fait toute la difference : un pivot calcule sur la
        barre COURANTE utiliserait son high et son low, connus seulement a sa
        cloture. C'est la fuite la plus repandue dans les implementations de
        pivots, et ce test est ce qui l'empeche de revenir."""
        attendu = (
            marche.value(Field.HIGH, lag=1)
            + marche.value(Field.LOW, lag=1)
            + marche.value(Field.CLOSE, lag=1)
        ) / 3.0
        assert lire(marche, "pivot@1", output="pp") == pytest.approx(attendu)

    def test_les_niveaux_de_pivot_sont_ordonnes(self, marche):
        niveaux = [
            lire(marche, "pivot@1", output=nom)
            for nom in ("s3", "s2", "s1", "pp", "r1", "r2", "r3")
        ]
        assert niveaux == sorted(niveaux), niveaux

    def test_body_ratio_vaut_un_sur_un_marubozu(self):
        """Corps egal a l'amplitude : la bougie n'a pas de meche."""
        store = synthetic.make_store(synthetic.ramp(50, 100.0, 1.0), wick=0.0)
        assert lire(at(store, 40), "body_ratio@1") == pytest.approx(1.0)

    def test_close_location_vaut_un_quand_on_ferme_au_plus_haut(self):
        store = synthetic.make_store(synthetic.ramp(50, 100.0, 1.0), wick=0.0)
        assert lire(at(store, 40), "close_location@1") == pytest.approx(1.0)

    def test_heikin_ashi_lisse_la_cloture(self, marche):
        """La cloture Heikin-Ashi est la moyenne des quatre prix : verifiable
        directement, contrairement a son ouverture qui est recursive."""
        attendu = (
            marche.value(Field.OPEN) + marche.value(Field.HIGH)
            + marche.value(Field.LOW) + marche.value(Field.CLOSE)
        ) / 4.0
        assert lire(marche, "heikin_ashi@1", output="close") == pytest.approx(attendu)

    def test_la_bougie_heikin_ashi_est_coherente(self, marche):
        lecture = {
            nom: lire(marche, "heikin_ashi@1", output=nom)
            for nom in ("open", "high", "low", "close")
        }
        assert lecture["low"] <= lecture["open"] <= lecture["high"]
        assert lecture["low"] <= lecture["close"] <= lecture["high"]


class TestVolume:
    """Les indicateurs de flux exigent un volume VARIABLE pour dire quoi que
    ce soit. A volume constant, la plupart degenerent - et c'est verifiable."""

    def test_le_flux_de_chaikin_suit_la_position_des_clotures(self):
        """Sur une rampe sans meche, chaque barre ferme a son plus haut : le
        flux vaut donc exactement 1, sa borne."""
        store = synthetic.make_store(synthetic.ramp(N, 100.0, 1.0), wick=0.0)
        assert lire(at(store, 250), "cmf@1", window=20) == pytest.approx(1.0)

    def test_le_volume_en_valeur_est_prix_typique_fois_volume(self, marche):
        typique = lire(marche, "typical_price@1")
        volume = marche.value(Field.VOLUME)
        mesure = lire(marche, "dollar_volume@1", window=1)
        assert mesure == pytest.approx(typique * volume, rel=1e-12)

    def test_nvi_et_pvi_se_partagent_toutes_les_barres(self, marche):
        """Chaque barre est soit a volume en hausse, soit en baisse, soit
        inchange. Sur une serie a volumes tous distincts, la somme des deux
        doit donc valoir le rendement cumule total."""
        fenetre = 30
        clotures = marche.values(Field.CLOSE, fenetre + 1)
        total = float(np.sum(100.0 * np.diff(clotures) / clotures[:-1]))
        somme = lire(marche, "nvi@1", window=fenetre) + lire(marche, "pvi@1", window=fenetre)
        assert somme == pytest.approx(total, abs=1e-9)

    def test_force_index_change_de_signe_avec_le_prix(self):
        montee = synthetic.make_store(synthetic.ramp(100, 100.0, 1.0), wick=0.0)
        descente = synthetic.make_store(synthetic.ramp(100, 300.0, -1.0), wick=0.0)
        assert lire(at(montee, 90), "force_index@1", window=10) > 0.0
        assert lire(at(descente, 90), "force_index@1", window=10) < 0.0


class TestVolatilite:
    """Les estimateurs de volatilite se verifient par comparaison ENTRE eux."""

    def test_une_serie_sans_amplitude_a_une_volatilite_nulle(self, plat):
        for ref in ("parkinson@1", "rogers_satchell@1"):
            valeur = lire(plat, ref, window=20)
            assert valeur is None or valeur == pytest.approx(0.0, abs=1e-12)

    def test_les_estimateurs_sur_extremes_sont_du_meme_ordre(self, marche):
        """Parkinson, Garman-Klass et Rogers-Satchell estiment la MEME
        quantite par des chemins differents. Un ecart d'un ordre de grandeur
        signalerait une erreur de formule ; un ecart d'un facteur deux est
        normal et attendu."""
        mesures = [
            lire(marche, ref, window=40)
            for ref in ("parkinson@1", "garman_klass@1", "rogers_satchell@1")
        ]
        assert all(v is not None and v > 0.0 for v in mesures), mesures
        assert max(mesures) / min(mesures) < 5.0, mesures

    def test_le_rapport_de_volatilites_vaut_un_en_regime_stable(self):
        """Sur une serie dont la volatilite ne change pas, le rapport court /
        long doit tourner autour de 1."""
        generateur = np.random.default_rng(7)
        closes = 100.0 * np.exp(np.cumsum(generateur.normal(0.0, 0.01, 2000)))
        ctx = at(synthetic.make_store(closes, wick=0.0), 1999)
        rapport = lire(ctx, "volatility_ratio@1", window=100, slow_window=1000)
        assert rapport is not None
        assert 0.5 < rapport < 2.0, rapport

    def test_l_ecart_type_a_la_baisse_ignore_les_hausses(self):
        """Sur une rampe strictement croissante, il n'y a aucun rendement
        negatif : l'ecart-type a la baisse vaut exactement zero, alors que
        l'ecart-type ordinaire ne le vaut pas."""
        store = synthetic.make_store(synthetic.ramp(N, 100.0, 1.0), wick=0.0)
        ctx = at(store, 250)
        assert lire(ctx, "downside_deviation@1", window=20) == pytest.approx(0.0)
        assert lire(ctx, "upside_deviation@1", window=20) > 0.0

    def test_chop_est_borne_et_se_lit_a_l_envers_de_la_tendance(self):
        """Une rampe parfaite est le contraire d'un marche lateral : l'indice
        de choppiness doit y etre au plus bas."""
        rampe_store = synthetic.make_store(synthetic.ramp(N, 100.0, 1.0), wick=0.0)
        valeur = lire(at(rampe_store, 250), "chop@1", window=20)
        assert valeur is not None
        assert valeur < 30.0, valeur


class TestPasDeNaNDansLesCasTordus:
    """Series conçues pour casser une division : ce sont elles qu'on rencontre
    en donnees reelles, pas les marches aleatoires bien eleves."""

    @pytest.mark.parametrize("ref", [
        "cmf@1", "mfi@1", "eom@1", "ad@1", "vwma@1", "vwap@1", "dollar_volume@1",
        "force_index@1", "pvt@1", "obv@1",
    ])
    def test_volume_nul(self, volumes_nuls, ref):
        valeur = lire(volumes_nuls, ref, window=20)
        assert valeur is None or math.isfinite(valeur)

    def test_une_barre_sans_amplitude_ne_divise_pas_par_zero(self):
        """`wick=0` sur une serie constante : high == low == close."""
        ctx = at(synthetic.make_store(synthetic.constant(50, 10.0), wick=0.0), 40)
        for ref in ("body_ratio@1", "close_location@1", "bar_range_pct@1"):
            valeur = lire(ctx, ref)
            assert valeur is None or math.isfinite(valeur), ref
