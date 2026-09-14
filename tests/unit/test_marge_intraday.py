"""La marge de JOUR, declaree par le run.

Ce qui est en jeu
------------------
La table des instruments porte des marges OVERNIGHT : ES 17 000, NQ 27 000.
Une strategie intraday ne les paie pas - son courtier lui accorde une marge de
jour, sensiblement plus faible, a charge pour elle d'etre plate a la cloture.

Sans moyen de le declarer, tout dimensionnement intraday etait trop contraint.
Mesure du 2026-09-13 : la strategie Zarattini demandait quatre contrats NQ, soit
108 000 de marge sur un compte de 100 000, et **5 080 ordres sur 5 084** etaient
refuses. Le -25,62 % affiche ne mesurait alors que deux trades.

Pourquoi un RATIO declare, et pas une table de marges de jour
--------------------------------------------------------------
La marge de jour est fixee par le COURTIER, pas par la place. Il n'existe aucun
chiffre publie a recopier, et en inventer un serait exactement ce que le socle
refuse - la table des marges overnight porte deja un avertissement sur son
caractere anachronique.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from rsl.config import BacktestSpec, ExecutionSpec
from rsl.data.instruments import get_instrument
from rsl.engine.portfolio import Portfolio
from rsl.errors import ConfigurationError
from rsl.manifest import canonical_hash
from rsl.orders import Fill, Side

SPEC = get_instrument("NQ")


def portefeuille(ratio: float = 1.0, cash: float = 100_000.0) -> Portfolio:
    return Portfolio(cash, {SPEC.symbol: SPEC}, ratio)


def acheter(pf: Portfolio, qty: int, prix: float = 15_000.0) -> None:
    pf.begin_bar()
    pf.apply_fill(Fill(order_id=0, symbol=SPEC.symbol, bar_index=0, ts_ns=0,
                       side=Side.BUY, quantity=qty, price=prix, fee=0.0,
                       slippage_cost=0.0, was_clamped=False, tag=""))


class TestLaMargeImmobilisee:
    def test_sans_allegement_c_est_la_marge_de_place(self):
        pf = portefeuille()
        acheter(pf, 2)
        assert pf.margin_required() == pytest.approx(2 * SPEC.initial_margin)

    def test_un_ratio_la_reduit_d_autant(self):
        pf = portefeuille(0.25)
        acheter(pf, 2)
        assert pf.margin_required() == pytest.approx(2 * SPEC.initial_margin * 0.25)

    def test_le_cas_qui_a_motive_le_champ(self):
        """Quatre contrats NQ sur un compte de 100 000.

        A la marge de place, 108 000 : infinancable, et les ordres refuses. A un
        quart, 27 000 : le compte les porte.
        """
        assert 4 * SPEC.initial_margin == pytest.approx(108_000.0)
        place, jour = portefeuille(), portefeuille(0.25)
        acheter(place, 4)
        acheter(jour, 4)
        assert place.margin_required() > 100_000.0
        assert jour.margin_required() == pytest.approx(27_000.0)

    @pytest.mark.parametrize("ratio", [0.0, -0.5, 1.5, 2.0])
    def test_un_ratio_hors_de_zero_un_est_refuse(self, ratio):
        """Au-dela de 1 il ne s'agirait plus d'un allegement mais d'une marge
        PLUS lourde que celle de la place, ce qu'aucun courtier ne pratique."""
        with pytest.raises(ConfigurationError, match="margin_ratio"):
            portefeuille(ratio)


class TestLaSpecification:
    BASE: ClassVar[dict] = {
        "fees": {"kind": "per_contract"},
        "slippage": {"kind": "tick", "ticks": 0.5},
    }

    def test_le_defaut_est_la_marge_de_place(self):
        assert ExecutionSpec.model_validate(self.BASE).margin_ratio == 1.0

    def test_le_ratio_declare_est_celui_qui_s_applique(self):
        spec = ExecutionSpec.model_validate({**self.BASE, "intraday_margin_ratio": 0.2})
        assert spec.margin_ratio == pytest.approx(0.2)
        assert spec.build().margin_ratio == pytest.approx(0.2)

    @pytest.mark.parametrize("ratio", [0.0, -0.1, 1.01, 3.0])
    def test_la_validation_borne_le_ratio(self, ratio):
        with pytest.raises(ValueError, match=r"intraday_margin_ratio|less than|greater"):
            ExecutionSpec.model_validate({**self.BASE, "intraday_margin_ratio": ratio})


class TestLeConfigHash:
    """Un champ laisse a `null` ne doit pas changer l'empreinte des runs passes."""

    def base(self) -> dict:
        return {
            "name": "x",
            "initial_cash": 100_000.0,
            "data": [{"root": "ES", "path": "indices/ES_v0_1m.parquet",
                      "granularity_minutes": 1, "resample": "day"}],
            "execution": {"fees": {"kind": "per_contract"},
                          "slippage": {"kind": "tick", "ticks": 1.0}},
            "strategy": {"ref": "rules@1",
                         "params": {"symbol": "ES.v.0", "rules": {}}},
        }

    def test_un_allegement_absent_ne_figure_pas_dans_la_forme_canonique(self):
        canonique = BacktestSpec.model_validate(self.base()).canonical()
        execution = canonique["execution"]
        assert isinstance(execution, dict)
        assert "intraday_margin_ratio" not in execution

    def test_un_allegement_absent_ne_change_pas_l_empreinte(self):
        """Le test qui compte : sans ce retrait, ajouter le champ changeait le
        `config_hash` des SEPT exemples archives, sans qu'aucune decision de
        strategie n'ait bouge."""
        sans = self.base()
        explicitement_nul = self.base()
        explicitement_nul["execution"]["intraday_margin_ratio"] = None
        a = canonical_hash(BacktestSpec.model_validate(sans).canonical())
        b = canonical_hash(BacktestSpec.model_validate(explicitement_nul).canonical())
        assert a == b

    def test_un_allegement_declare_change_l_empreinte(self):
        """Meme a 1.0 : c'est une instruction, et elle dit quelque chose de
        different de son absence - celui qui l'ecrit affirme avoir considere la
        question."""
        charge = self.base()
        charge["execution"]["intraday_margin_ratio"] = 1.0
        a = canonical_hash(BacktestSpec.model_validate(self.base()).canonical())
        b = canonical_hash(BacktestSpec.model_validate(charge).canonical())
        assert a != b
