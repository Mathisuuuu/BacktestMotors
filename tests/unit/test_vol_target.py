"""Dimensionnement par volatilite cible.

La regle est une formule fermee : on la verifie contre elle, sur des series
dont la volatilite est connue, jamais contre une seconde implementation.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.config import SizingSpec
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore, InstrumentSpec
from rsl.engine.risk import RiskFraction, VolatilityTarget
from rsl.errors import ConfigurationError
from rsl.primitives.registry import bind_primitive

EQUITY = 100_000.0


def instrument() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="TEST.v.0", root="TEST", name="Instrument de test", exchange="CME",
        currency="USD", multiplier=50.0, tick_size=0.25,
        commission_per_contract=1.0, exchange_fee_per_contract=1.0,
        initial_margin=10_000.0, maintenance_margin=9_000.0,
    )


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


def contexte(closes: np.ndarray) -> BarContext:
    return at(synthetic.make_store(closes, wick=0.0), closes.size - 1)


def marche(agitation: float, n: int = 200, seed: int = 4) -> BarContext:
    """Marche aleatoire dont on regle l'amplitude des rendements."""
    generateur = np.random.default_rng(seed)
    pas = generateur.normal(0.0, agitation, n)
    return contexte(100.0 * np.exp(np.cumsum(pas)))


def plat(n: int = 200) -> BarContext:
    return contexte(np.full(n, 100.0, dtype=np.float64))


class TestFormule:
    def test_la_taille_suit_la_formule(self):
        """`contracts = base * min(plafond, cible / volatilite_realisee)`."""
        ctx = marche(0.01)
        regle = VolatilityTarget(vol_target=0.01, vol_window=20,
                                 vol_max_multiple=10.0, contracts_base=100)
        realisee = bind_primitive("volatility@1", window=20, log=True)(ctx)
        assert realisee is not None
        attendu = int(100 * min(10.0, 0.01 / realisee))
        assert regle.contracts(ctx, instrument(), EQUITY, 100.0) == attendu

    def test_un_marche_plus_agite_donne_une_taille_plus_petite(self):
        """La propriete qui justifie la regle, verifiee et pas supposee."""
        regle = VolatilityTarget(vol_target=0.01, vol_window=20, vol_max_multiple=50.0,
                                 contracts_base=1000)
        calme = regle.contracts(marche(0.004), instrument(), EQUITY, 100.0)
        agite = regle.contracts(marche(0.02), instrument(), EQUITY, 100.0)
        assert calme > agite

    def test_le_plafond_borne_la_taille(self):
        """Sans plafond, une volatilite minuscule donnerait une taille immense."""
        regle = VolatilityTarget(vol_target=1.0, vol_window=20, vol_max_multiple=3.0,
                                 contracts_base=10)
        assert regle.contracts(marche(0.0001), instrument(), EQUITY, 100.0) == 30

    def test_la_taille_est_proportionnelle_a_la_base(self):
        ctx = marche(0.01)
        commun = {"vol_target": 0.01, "vol_window": 20, "vol_max_multiple": 10.0}
        cent = VolatilityTarget(contracts_base=100, **commun).contracts(
            ctx, instrument(), EQUITY, 100.0)
        mille = VolatilityTarget(contracts_base=1000, **commun).contracts(
            ctx, instrument(), EQUITY, 100.0)
        # A la troncature pres : `int()` coupe, il n'arrondit pas.
        assert mille == pytest.approx(10 * cent, abs=10)

    def test_elle_ne_depend_ni_de_l_equity_ni_du_prix(self):
        """C'est ce qui la distingue de `equity_fraction` : elle vise une
        volatilite, pas un notionnel."""
        ctx = marche(0.01)
        regle = VolatilityTarget(vol_target=0.01, vol_window=20, contracts_base=10)
        reference = regle.contracts(ctx, instrument(), EQUITY, 100.0)
        assert regle.contracts(ctx, instrument(), EQUITY * 7, 4200.0) == reference


class TestCasLimites:
    def test_une_base_de_un_peut_tronquer_jusqu_a_zero(self):
        """Piege reel, documente plutot que masque : avec une base de 1 et un
        facteur d'echelle sous 1, `int()` rend zero et la strategie ne prend
        jamais position - sans erreur, sans avertissement."""
        ctx = marche(0.02)
        petite = VolatilityTarget(vol_target=0.01, vol_window=20, contracts_base=1)
        grande = VolatilityTarget(vol_target=0.01, vol_window=20, contracts_base=100)
        assert petite.contracts(ctx, instrument(), EQUITY, 100.0) == 0
        assert grande.contracts(ctx, instrument(), EQUITY, 100.0) > 0

    def test_zero_quand_la_volatilite_est_nulle(self):
        """Meme convention que `RiskFraction` : une taille non calculable ne
        devient pas une taille par defaut."""
        regle = VolatilityTarget(vol_target=0.01, vol_window=20)
        assert regle.contracts(plat(), instrument(), EQUITY, 100.0) == 0

    def test_meme_convention_que_risk_fraction(self):
        """Les deux rendent 0 sur une serie sans mouvement : la coherence entre
        regles de dimensionnement est ce qui rend `n_dropped_sizing` lisible."""
        ctx = plat()
        assert VolatilityTarget(vol_target=0.01).contracts(
            ctx, instrument(), EQUITY, 100.0) == 0
        assert RiskFraction(0.01).contracts(ctx, instrument(), EQUITY, 100.0) == 0

    def test_le_warmup_couvre_la_fenetre_et_le_rendement(self):
        assert VolatilityTarget(vol_target=0.01, vol_window=20).warmup_bars == 21


class TestValidation:
    @pytest.mark.parametrize(("champ", "valeur", "motif"), [
        ("vol_target", 0.0, "vol_target"),
        ("vol_target", -0.1, "vol_target"),
        ("vol_window", 1, "vol_window"),
        ("vol_max_multiple", 0.0, "vol_max_multiple"),
        ("contracts_base", 0, "contracts"),
    ])
    def test_les_parametres_invalides_levent(self, champ, valeur, motif):
        params = {"vol_target": 0.01, champ: valeur}
        with pytest.raises(ConfigurationError, match=motif):
            VolatilityTarget(**params)

    def test_une_fenetre_de_un_est_refusee(self):
        """Un seul rendement n'a pas de dispersion."""
        with pytest.raises(ConfigurationError, match="dispersion"):
            VolatilityTarget(vol_target=0.01, vol_window=1)


class TestSpecification:
    def test_la_specification_construit_la_regle(self):
        spec = SizingSpec(kind="vol_target", vol_target=0.02, vol_window=30,
                          vol_max_multiple=2.5, contracts=3)
        regle = spec.build()
        assert isinstance(regle, VolatilityTarget)
        assert regle.vol_target == 0.02
        assert regle.vol_window == 30
        assert regle.contracts_base == 3

    def test_la_cible_est_requise(self):
        with pytest.raises(ConfigurationError, match="vol_target"):
            SizingSpec(kind="vol_target").build()

    def test_la_base_vaut_un_par_defaut(self):
        regle = SizingSpec(kind="vol_target", vol_target=0.02).build()
        assert isinstance(regle, VolatilityTarget)
        assert regle.contracts_base == 1

    def test_le_descripteur_nomme_la_regle(self):
        regle = VolatilityTarget(vol_target=0.02, vol_window=30)
        assert regle.describe()["rule"] == "vol_target"
        assert regle.describe()["vol_target"] == 0.02

    def test_les_autres_modes_restent_intacts(self):
        """L'ajout d'un mode ne doit pas deplacer les anciens."""
        assert SizingSpec(kind="fixed", contracts=2).build() is not None
        assert SizingSpec(kind="none").build() is None
