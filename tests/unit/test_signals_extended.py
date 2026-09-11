"""Noeuds et statistiques ajoutes au vocabulaire en second temps.

Verifies contre des valeurs calculees a la main sur des series courtes, jamais
contre une reimplementation du meme calcul.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore
from rsl.errors import ConfigurationError
from rsl.strategies.signals import (
    FALSE,
    TRUE,
    BarsSince,
    Compare,
    CompareOp,
    IfThenElse,
    MathNode,
    MathOp,
    MaxOf,
    MinOf,
    RollingStat,
    bars_since,
    build_signal,
    const,
    max_of,
    min_of,
    price,
    rolling,
    unary,
)


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


def rampe(n: int = 12) -> BarStore:
    """Clotures 10, 11, 12, ... : pente exactement 1 par barre."""
    return synthetic.make_store(np.asarray([10.0 + i for i in range(n)], dtype=np.float64))


def dernier(store: BarStore) -> BarContext:
    return at(store, store.close.size - 1)


# ---------------------------------------------------------------------------
# Statistiques glissantes ajoutees
# ---------------------------------------------------------------------------


class TestRollingAjoutees:
    def ctx(self) -> BarContext:
        return dernier(rampe(12))

    def test_median(self):
        """Fenetre de 5 sur une rampe : [17, 18, 19, 20, 21], mediane 19."""
        assert rolling("median", 5, price("close"))(self.ctx()) == pytest.approx(19.0)

    def test_var_est_la_variance_non_biaisee(self):
        """Variance de cinq entiers consecutifs, ddof=1 : 2.5."""
        assert rolling("var", 5, price("close"))(self.ctx()) == pytest.approx(2.5)

    def test_slope_rend_la_pente_par_barre(self):
        """La rampe monte de 1 par barre : la pente vaut 1, quel que soit le point."""
        assert rolling("slope", 6, price("close"))(self.ctx()) == pytest.approx(1.0)

    def test_slope_est_negative_sur_une_descente(self):
        descente = synthetic.make_store(
            np.asarray([50.0 - i for i in range(12)], dtype=np.float64)
        )
        assert rolling("slope", 6, price("close"))(dernier(descente)) == pytest.approx(-1.0)

    def test_rank_vaut_un_au_plus_haut(self):
        """La cloture courante est la plus haute de sa fenetre sur une rampe."""
        assert rolling("rank", 5, price("close"))(self.ctx()) == pytest.approx(1.0)

    def test_rank_vaut_le_minimum_au_plus_bas(self):
        descente = synthetic.make_store(
            np.asarray([50.0 - i for i in range(12)], dtype=np.float64)
        )
        assert rolling("rank", 5, price("close"))(dernier(descente)) == pytest.approx(0.2)

    def test_count_true_compte_les_conditions_vraies(self):
        """Sur une rampe, `close > 18` est vrai pour 18 exclu... soit 3 des 5 dernieres."""
        condition = Compare(price("close"), CompareOp.GT, const(18.0))
        assert rolling("count_true", 5, condition)(self.ctx()) == pytest.approx(3.0)

    def test_count_true_vaut_zero_si_jamais_vrai(self):
        condition = Compare(price("close"), CompareOp.GT, const(1000.0))
        assert rolling("count_true", 5, condition)(self.ctx()) == pytest.approx(0.0)

    def test_ema_d_une_serie_constante_vaut_la_constante(self):
        """Le seul cas ou l'EMA a une valeur analytique evidente."""
        plat = synthetic.make_store(np.full(20, 42.0, dtype=np.float64))
        assert rolling("ema", 9, price("close"))(dernier(plat)) == pytest.approx(42.0)

    def test_ema_pese_davantage_le_present_que_la_moyenne(self):
        """Sur une serie croissante, l'EMA depasse la moyenne simple."""
        ctx = self.ctx()
        moyenne = rolling("mean", 9, price("close"))(ctx)
        exponentielle = rolling("ema", 9, price("close"))(ctx)
        assert moyenne is not None and exponentielle is not None
        assert exponentielle > moyenne

    def test_ema_reste_dans_les_bornes_de_la_fenetre(self):
        ctx = self.ctx()
        valeur = rolling("ema", 5, price("close"))(ctx)
        bas = rolling("min", 5, price("close"))(ctx)
        haut = rolling("max", 5, price("close"))(ctx)
        assert bas is not None and haut is not None and valeur is not None
        assert bas <= valeur <= haut

    @pytest.mark.parametrize("stat", ["var", "slope", "stdev", "zscore"])
    def test_les_statistiques_de_dispersion_exigent_deux_observations(self, stat):
        with pytest.raises(ConfigurationError, match="window >= 2"):
            rolling(stat, 1, price("close"))

    @pytest.mark.parametrize("stat", ["mean", "median", "ema", "rank", "count_true", "min"])
    def test_les_autres_acceptent_une_fenetre_de_un(self, stat):
        assert rolling(stat, 1, price("close")) is not None

    def test_toutes_les_statistiques_declarees_sont_calculables(self):
        """Un membre d'enum ajoute sans branche dans `__call__` rendrait `None`
        en silence - ce test le rend impossible."""
        ctx = dernier(rampe(30))
        for stat in RollingStat:
            fenetre = 1 if stat in ("mean", "median", "ema", "rank", "count_true") else 5
            valeur = rolling(stat.value, max(fenetre, 5), price("close"))(ctx)
            assert valeur is not None, stat.value


# ---------------------------------------------------------------------------
# if_then_else
# ---------------------------------------------------------------------------


class TestIfThenElse:
    def test_prend_la_branche_vraie(self):
        noeud = IfThenElse(const(TRUE), const(10.0), const(20.0))
        assert noeud(dernier(rampe())) == pytest.approx(10.0)

    def test_prend_la_branche_fausse(self):
        noeud = IfThenElse(const(FALSE), const(10.0), const(20.0))
        assert noeud(dernier(rampe())) == pytest.approx(20.0)

    def test_une_condition_indefinie_rend_indefini(self):
        """`None` ne choisit pas une branche par defaut : il se propage."""
        indefini = rolling("mean", 500, price("close"))
        noeud = IfThenElse(indefini, const(10.0), const(20.0))
        assert noeud(dernier(rampe())) is None

    def test_le_warmup_couvre_les_trois_branches(self):
        # Le noeud price demande deja une barre : 1 + 30 - 1 = 30, pas 29.
        noeud = IfThenElse(const(1.0), rolling("mean", 30, price("close")), const(0.0))
        assert noeud.warmup_bars == 30

    def test_aller_retour_declaratif(self):
        noeud = IfThenElse(const(1.0), const(2.0), const(3.0))
        assert build_signal(noeud.describe())(dernier(rampe())) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# math
# ---------------------------------------------------------------------------


class TestMath:
    @pytest.mark.parametrize(("op", "entree", "attendu"), [
        ("abs", -3.0, 3.0),
        ("neg", 3.0, -3.0),
        ("sign", -7.0, -1.0),
        ("sign", 0.0, 0.0),
        ("sign", 7.0, 1.0),
        ("sqrt", 9.0, 3.0),
        ("inverse", 4.0, 0.25),
        ("floor", 2.7, 2.0),
        ("ceil", 2.1, 3.0),
    ])
    def test_operations(self, op, entree, attendu):
        assert unary(op, const(entree))(dernier(rampe())) == pytest.approx(attendu)

    @pytest.mark.parametrize(("op", "entree"), [
        ("log", 0.0), ("log", -1.0), ("sqrt", -1.0), ("inverse", 0.0), ("exp", 1000.0),
    ])
    def test_les_domaines_invalides_rendent_none_jamais_nan(self, op, entree):
        """Un `NaN` se propagerait en silence dans une comparaison, qui vaudrait
        `False` : "pas de signal" au lieu de "erreur"."""
        assert unary(op, const(entree))(dernier(rampe())) is None

    def test_operation_inconnue_refusee(self):
        with pytest.raises(ConfigurationError, match="operation invalide"):
            build_signal({"type": "math", "op": "racine_cubique",
                          "inner": {"type": "constant", "value": 1.0}})

    def test_aller_retour_declaratif(self):
        noeud = MathNode(MathOp.ABS, const(-5.0))
        assert build_signal(noeud.describe())(dernier(rampe())) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# min_of / max_of
# ---------------------------------------------------------------------------


class TestExtremesNAires:
    def test_min_of(self):
        noeud = MinOf((const(3.0), const(1.0), const(2.0)))
        assert noeud(dernier(rampe())) == pytest.approx(1.0)

    def test_max_of(self):
        noeud = MaxOf((const(3.0), const(1.0), const(2.0)))
        assert noeud(dernier(rampe())) == pytest.approx(3.0)

    def test_un_operande_indefini_rend_indefini(self):
        indefini = rolling("mean", 500, price("close"))
        assert min_of(const(1.0), indefini)(dernier(rampe())) is None
        assert max_of(const(1.0), indefini)(dernier(rampe())) is None

    def test_bornage_par_composition(self):
        """`min_of(max_of(x, bas), haut)` borne une expression."""
        borne = min_of(max_of(const(42.0), const(0.0)), const(10.0))
        assert borne(dernier(rampe())) == pytest.approx(10.0)

    def test_le_warmup_est_le_maximum(self):
        noeud = max_of(const(1.0), rolling("mean", 40, price("close")))
        assert noeud.warmup_bars == 40


# ---------------------------------------------------------------------------
# bars_since
# ---------------------------------------------------------------------------


class TestBarsSince:
    def test_zero_si_vrai_maintenant(self):
        toujours = Compare(price("close"), CompareOp.GT, const(0.0))
        assert bars_since(10, toujours)(dernier(rampe(20))) == pytest.approx(0.0)

    def test_compte_les_barres_jusqu_au_dernier_vrai(self):
        """Sur la rampe 10..29, `close < 27` a ete vrai il y a 3 barres."""
        condition = Compare(price("close"), CompareOp.LT, const(27.0))
        assert bars_since(10, condition)(dernier(rampe(20))) == pytest.approx(3.0)

    def test_none_si_jamais_vrai_dans_la_fenetre(self):
        """`None` plutot qu'une sentinelle : une sentinelle se compare sans
        lever et ferait passer "jamais vu" pour "vu il y a longtemps"."""
        jamais = Compare(price("close"), CompareOp.GT, const(10_000.0))
        assert bars_since(5, jamais)(dernier(rampe(20))) is None

    def test_lookback_doit_etre_positif(self):
        with pytest.raises(ConfigurationError, match="lookback"):
            BarsSince(0, const(TRUE))

    def test_lookback_non_entier_refuse(self):
        with pytest.raises(ConfigurationError, match="lookback"):
            build_signal({"type": "bars_since", "lookback": 2.5,
                          "inner": {"type": "constant", "value": 1.0}})

    def test_le_warmup_couvre_la_fenetre(self):
        assert bars_since(10, const(TRUE)).warmup_bars == 9

    def test_aller_retour_declaratif(self):
        noeud = bars_since(4, Compare(price("close"), CompareOp.GT, const(0.0)))
        assert build_signal(noeud.describe())(dernier(rampe(20))) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Pas d'echantillonnage de `rolling`
# ---------------------------------------------------------------------------


class TestStride:
    def ctx(self) -> BarContext:
        return dernier(rampe(12))

    def test_le_defaut_ne_change_rien(self):
        """Aucune specification ecrite avant l'ajout ne change de sens."""
        ctx = self.ctx()
        assert rolling("mean", 5, price("close"))(ctx) == pytest.approx(
            rolling("mean", 5, price("close"), 1)(ctx)
        )

    def test_il_echantillonne_une_barre_sur_n(self):
        """Rampe 10..21 : lags 0, 2, 4 valent 21, 19, 17 -> moyenne 19."""
        assert rolling("mean", 3, price("close"), 2)(self.ctx()) == pytest.approx(19.0)

    def test_un_pas_de_trois(self):
        """Lags 0, 3, 6 valent 21, 18, 15 -> moyenne 18."""
        assert rolling("mean", 3, price("close"), 3)(self.ctx()) == pytest.approx(18.0)

    def test_le_warmup_suit_le_pas(self):
        sans = rolling("mean", 5, price("close")).warmup_bars
        avec = rolling("mean", 5, price("close"), 4).warmup_bars
        assert avec == sans + 4 * (5 - 1) - (5 - 1)
        assert avec == 1 + (5 - 1) * 4

    def test_la_pente_est_par_echantillon_pas_par_barre(self):
        """Piege documente : sur une rampe de +1/barre et un pas de 2, `slope`
        vaut 2. Diviser par `stride` pour revenir a des unites par barre."""
        assert rolling("slope", 4, price("close"), 2)(self.ctx()) == pytest.approx(2.0)

    def test_un_pas_nul_ou_negatif_est_refuse(self):
        with pytest.raises(ConfigurationError, match="stride"):
            rolling("mean", 3, price("close"), 0)

    def test_un_pas_non_entier_est_refuse(self):
        with pytest.raises(ConfigurationError, match="stride"):
            build_signal({"type": "rolling", "stat": "mean", "window": 3, "stride": 2.5,
                          "inner": {"type": "constant", "value": 1.0}})

    def test_aller_retour_declaratif(self):
        noeud = rolling("mean", 3, price("close"), 2)
        assert noeud.describe()["stride"] == 2
        assert build_signal(noeud.describe())(self.ctx()) == pytest.approx(19.0)

    def test_historique_insuffisant_rend_none(self):
        """Un pas large epuise l'historique plus vite qu'une fenetre serree."""
        assert rolling("mean", 5, price("close"), 50)(self.ctx()) is None
