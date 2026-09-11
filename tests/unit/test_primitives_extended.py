"""Primitives ajoutees au registre en second temps.

Chacune est verifiee sur une serie dont la reponse est connue analytiquement,
pas contre une seconde implementation du meme calcul. Les series constantes,
monotones et en dents de scie saturent les indicateurs et rendent leurs bornes
verifiables.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore
from rsl.primitives.builtin.momentum import ema_series
from rsl.primitives.builtin.wilder import wilder_smooth
from rsl.primitives.registry import get_primitive

PENTE = 1.0


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


def dernier(closes: np.ndarray) -> BarContext:
    store = synthetic.make_store(closes, wick=0.0)
    return at(store, closes.size - 1)


def monte(n: int = 400, depart: float = 100.0) -> BarContext:
    return dernier(np.asarray([depart + PENTE * i for i in range(n)], dtype=np.float64))


def descend(n: int = 400, depart: float = 600.0) -> BarContext:
    return dernier(np.asarray([depart - PENTE * i for i in range(n)], dtype=np.float64))


def plat(n: int = 400, valeur: float = 100.0) -> BarContext:
    return dernier(np.full(n, valeur, dtype=np.float64))


def val(ref: str, ctx: BarContext, **params: object) -> float | None:
    return get_primitive(ref).bind(**params)(ctx)


# ---------------------------------------------------------------------------
# Briques de lissage
# ---------------------------------------------------------------------------


class TestLissages:
    def test_wilder_d_une_serie_constante_vaut_la_constante(self):
        serie = np.full(50, 7.0, dtype=np.float64)
        assert wilder_smooth(serie, 14)[-1] == pytest.approx(7.0)

    def test_ema_d_une_serie_constante_vaut_la_constante(self):
        serie = np.full(50, 7.0, dtype=np.float64)
        assert ema_series(serie, 12)[-1] == pytest.approx(7.0)

    def test_les_deux_series_ont_la_longueur_annoncee(self):
        serie = np.arange(50, dtype=np.float64)
        assert wilder_smooth(serie, 14).size == 50 - 14 + 1
        assert ema_series(serie, 12).size == 50 - 12 + 1

    def test_wilder_est_plus_lent_qu_une_ema_de_meme_fenetre(self):
        """`alpha = 1/n` contre `2/(n+1)` : Wilder pese moins le present."""
        serie = np.asarray([100.0 + i for i in range(200)], dtype=np.float64)
        assert wilder_smooth(serie, 14)[-1] < ema_series(serie, 14)[-1]


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


class TestMacd:
    def test_sur_une_rampe_la_ligne_vaut_la_pente_fois_la_demi_difference(self):
        """Resultat analytique : sur une droite de pente `s`, une EMA de fenetre
        `w` retarde de `s * (w - 1) / 2`. La difference des deux EMA vaut donc
        `s * (slow - fast) / 2` - ici 1 * (26 - 12) / 2 = 7."""
        ligne = val("macd@1", monte(), fast=12, slow=26, signal=9, output="line")
        assert ligne == pytest.approx(PENTE * (26 - 12) / 2, abs=1e-6)

    def test_la_ligne_est_negative_en_tendance_baissiere(self):
        ligne = val("macd@1", descend(), fast=12, slow=26, output="line")
        assert ligne is not None and ligne < 0.0

    def test_l_histogramme_vaut_la_ligne_moins_le_signal(self):
        ctx = monte()
        commun = {"fast": 12, "slow": 26, "signal": 9}
        ligne = val("macd@1", ctx, output="line", **commun)
        signal = val("macd@1", ctx, output="signal", **commun)
        histogramme = val("macd@1", ctx, output="histogram", **commun)
        assert ligne is not None and signal is not None and histogramme is not None
        assert histogramme == pytest.approx(ligne - signal, abs=1e-9)

    def test_tout_est_nul_sur_une_serie_plate(self):
        for sortie in ("line", "signal", "histogram"):
            assert val("macd@1", plat(), output=sortie) == pytest.approx(0.0, abs=1e-9)

    def test_fast_doit_etre_strictement_inferieur_a_slow(self):
        """L'inverse produit un MACD de signe oppose : presque surement une faute."""
        with pytest.raises(ValueError, match="doit etre < slow"):
            get_primitive("macd@1").bind(fast=26, slow=12)

    def test_fenetres_positives(self):
        with pytest.raises(ValueError, match="signal doit etre >= 1"):
            get_primitive("macd@1").bind(signal=0)

    def test_le_warmup_couvre_l_amorce_et_la_ligne_de_signal(self):
        primitive = get_primitive("macd@1")
        params = primitive.parse_params({"fast": 12, "slow": 26, "signal": 9})
        assert primitive.warmup_bars(params) == 26 * 5 + 9


# ---------------------------------------------------------------------------
# Famille de Wilder
# ---------------------------------------------------------------------------


class TestWilder:
    def test_rsi_wilder_sature_a_cent_en_hausse_continue(self):
        assert val("rsi_wilder@1", monte(), window=14) == pytest.approx(100.0)

    def test_rsi_wilder_sature_a_zero_en_baisse_continue(self):
        assert val("rsi_wilder@1", descend(), window=14) == pytest.approx(0.0)

    def test_rsi_wilder_indefini_sur_une_serie_plate(self):
        """Ni force ni faiblesse relative : repondre 50 serait inventer."""
        assert val("rsi_wilder@1", plat(), window=14) is None

    def test_rsi_wilder_reste_borne(self):
        ctx = dernier(synthetic.random_walk(400, seed=7))
        valeur = val("rsi_wilder@1", ctx, window=14)
        assert valeur is not None and 0.0 <= valeur <= 100.0

    def test_atr_wilder_d_une_amplitude_constante_vaut_cette_amplitude(self):
        """Clotures constantes, meches nulles : le True Range vaut zero."""
        assert val("atr_wilder@1", plat(), window=14) == pytest.approx(0.0)

    def test_atr_wilder_proche_de_atr_sur_serie_reguliere(self):
        ctx = monte()
        wilder = val("atr_wilder@1", ctx, window=14)
        simple = val("atr@1", ctx, window=14)
        assert wilder is not None and simple is not None
        assert wilder == pytest.approx(simple, rel=0.05)

    def test_atr_wilder_est_positif(self):
        ctx = dernier(synthetic.random_walk(400, seed=3))
        valeur = val("atr_wilder@1", ctx, window=14)
        assert valeur is not None and valeur > 0.0


class TestAdx:
    def test_minus_di_est_nul_en_hausse_pure(self):
        assert val("adx@1", monte(), window=14, output="minus_di") == pytest.approx(0.0)

    def test_plus_di_est_nul_en_baisse_pure(self):
        assert val("adx@1", descend(), window=14, output="plus_di") == pytest.approx(0.0)

    def test_les_deux_di_sont_bornes(self):
        ctx = dernier(synthetic.random_walk(500, seed=11))
        for sortie in ("plus_di", "minus_di"):
            valeur = val("adx@1", ctx, window=14, output=sortie)
            assert valeur is not None and 0.0 <= valeur <= 100.0

    def test_adx_est_borne(self):
        ctx = dernier(synthetic.random_walk(500, seed=11))
        valeur = val("adx@1", ctx, window=14, output="adx")
        assert valeur is not None and 0.0 <= valeur <= 100.0

    def test_adx_sature_en_tendance_pure(self):
        """Aucun mouvement contraire : DX vaut 100 a chaque barre."""
        assert val("adx@1", monte(), window=14, output="adx") == pytest.approx(100.0)

    def test_indefini_sans_aucun_mouvement(self):
        assert val("adx@1", plat(), window=14, output="adx") is None

    def test_le_warmup_depasse_celui_des_composantes(self):
        primitive = get_primitive("adx@1")
        params = primitive.parse_params({"window": 14})
        assert primitive.warmup_bars(params) == 14 * 5 + 14 + 1


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


class TestCci:
    def test_positif_en_hausse(self):
        valeur = val("cci@1", monte(), window=20)
        assert valeur is not None and valeur > 0.0

    def test_negatif_en_baisse(self):
        valeur = val("cci@1", descend(), window=20)
        assert valeur is not None and valeur < 0.0

    def test_indefini_sur_une_serie_plate(self):
        assert val("cci@1", plat(), window=20) is None


class TestWilliamsR:
    def test_proche_de_zero_au_plus_haut(self):
        valeur = val("williams_r@1", monte(), window=20)
        assert valeur == pytest.approx(0.0, abs=1e-9)

    def test_proche_de_moins_cent_au_plus_bas(self):
        valeur = val("williams_r@1", descend(), window=20)
        assert valeur == pytest.approx(-100.0, abs=1e-9)

    def test_toujours_dans_ses_bornes(self):
        ctx = dernier(synthetic.random_walk(300, seed=5))
        valeur = val("williams_r@1", ctx, window=20)
        assert valeur is not None and -100.0 <= valeur <= 0.0

    def test_indefini_sur_amplitude_nulle(self):
        assert val("williams_r@1", plat(), window=20) is None


class TestEfficiencyRatio:
    def test_vaut_un_sur_un_chemin_droit(self):
        assert val("efficiency_ratio@1", monte(), window=20) == pytest.approx(1.0)

    def test_vaut_un_aussi_en_descente_droite(self):
        """Le ratio mesure l'efficience, pas la direction."""
        assert val("efficiency_ratio@1", descend(), window=20) == pytest.approx(1.0)

    def test_proche_de_zero_en_dents_de_scie(self):
        """Un aller-retour parfait parcourt du chemin sans avancer."""
        scie = np.asarray([100.0 + (i % 2) for i in range(100)], dtype=np.float64)
        valeur = val("efficiency_ratio@1", dernier(scie), window=20)
        assert valeur is not None and valeur < 0.1

    def test_toujours_entre_zero_et_un(self):
        ctx = dernier(synthetic.random_walk(300, seed=9))
        valeur = val("efficiency_ratio@1", ctx, window=20)
        assert valeur is not None and 0.0 <= valeur <= 1.0

    def test_indefini_sans_variation(self):
        assert val("efficiency_ratio@1", plat(), window=20) is None


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------


class TestVwap:
    def test_vaut_le_prix_typique_sur_serie_plate(self):
        """Volumes constants et prix constant : la moyenne ponderee vaut le prix."""
        assert val("vwap@1", plat(n=50, valeur=100.0), window=20) == pytest.approx(100.0)

    def test_reste_dans_l_amplitude_de_la_fenetre(self):
        ctx = monte(n=100)
        valeur = val("vwap@1", ctx, window=20)
        bas = val("rolling_low@1", ctx, window=20)
        haut = val("rolling_high@1", ctx, window=20)
        assert valeur is not None and bas is not None and haut is not None
        assert bas <= valeur <= haut


class TestObv:
    def test_vaut_la_somme_des_volumes_en_hausse_continue(self):
        """Volume synthetique constant a 1000 sur 20 barres montantes."""
        assert val("obv@1", monte(), window=20) == pytest.approx(20 * 1000.0)

    def test_est_l_oppose_en_baisse_continue(self):
        assert val("obv@1", descend(), window=20) == pytest.approx(-20 * 1000.0)

    def test_vaut_zero_sur_une_serie_plate(self):
        """Convention de Granville : une barre sans variation n'apporte rien."""
        assert val("obv@1", plat(), window=20) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Garde transversale
# ---------------------------------------------------------------------------


class TestRegistreComplet:
    NOUVELLES = (
        "macd@1", "atr_wilder@1", "rsi_wilder@1", "adx@1", "cci@1",
        "williams_r@1", "efficiency_ratio@1", "vwap@1", "obv@1",
    )

    @pytest.mark.parametrize("ref", NOUVELLES)
    def test_chacune_est_enregistree_et_decrite(self, ref):
        primitive = get_primitive(ref)
        assert primitive.summary, ref
        assert primitive.json_schema()["params"]

    @pytest.mark.parametrize("ref", NOUVELLES)
    def test_chacune_refuse_un_parametre_mal_orthographie(self, ref):
        """`extra="forbid"` : la premiere ligne de defense des specs machine."""
        with pytest.raises(ValueError, match=r"(?i)extra"):
            get_primitive(ref).bind(fenetre=14)

    def test_aucune_ne_masque_une_primitive_existante(self):
        """Un nom deja pris resoudrait vers la version la plus recente et
        changerait le sens des specifications non epinglees."""
        anciennes = {"sma", "ema", "rsi", "atr", "stdev", "zscore", "volatility",
                     "returns", "slope", "stochastic", "true_range",
                     "rolling_high", "rolling_low"}
        nouvelles = {ref.split("@")[0] for ref in self.NOUVELLES}
        assert anciennes.isdisjoint(nouvelles)
