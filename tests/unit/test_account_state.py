"""Etat de COMPTE expose au `Context` : ce qu'il debloque, et ses limites.

La question qui a motive cette brique : la gestion du risque pilotee par la
PERFORMANCE n'etait pas exprimable. La couche risque voyait l'equity -
`RiskManager.contracts` la recoit - mais la DECISION non. Le dimensionnement
pouvait composer avec le capital ; aucune regle ne pouvait y reagir.

La reponse choisie est celle de `PositionState`, et c'est delibere : le RUNNER
calcule l'etat et le depose dans le `Context`. Un noeud a memoire aurait
survecu d'un run a l'autre ; le runner repart de zero par construction.

Deux differences avec `position`, toutes deux verifiees ici :

1. **Il n'y a pas d'etat par defaut.** Hors runner, une position est plate PAR
   DEDUCTION ; une equity est INCONNUE. Rendre zero ferait d'un `drawdown` une
   division par zero silencieuse - on leve, comme `session` sans calendrier.
2. **Un seul compte pour tout le portefeuille.** Deux instruments d'un meme
   run n'ont pas deux equities, la ou ils ont bien deux positions.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext, MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import ACCOUNT_FIELDS, AccountState, BarStore, Granularity, InstrumentSpec
from rsl.engine.execution import ExecutionConfig, ZeroFee, ZeroSlippage
from rsl.engine.runner import RunConfig, SingleAssetRunner
from rsl.errors import ConfigurationError, InsufficientHistoryError
from rsl.strategies.handwritten import BuyAndHold
from rsl.strategies.signals import account, build_signal, rolling

SYMBOL = "TEST.v.0"
CASH = 500_000.0
JOUR = Granularity.minutes(60 * 24)


def store_of(closes=None) -> BarStore:
    if closes is None:
        closes = synthetic.sine(400, 100.0, 12.0, 64)
    return synthetic.make_store(closes, symbol=SYMBOL)


def config() -> RunConfig:
    return RunConfig(CASH, ExecutionConfig(fees=ZeroFee(), slippage=ZeroSlippage()))


@pytest.fixture(scope="module")
def spec() -> InstrumentSpec:
    return InstrumentSpec(
        symbol=SYMBOL, root="TEST", name="Instrument de test", exchange="CME",
        currency="USD", multiplier=50.0, tick_size=0.25,
        commission_per_contract=0.0, exchange_fee_per_contract=0.0,
        initial_margin=10_000.0, maintenance_margin=9_000.0,
    )


class TestLaValeurElleMeme:
    """`AccountState` est du calcul pur : il se verifie a la main."""

    def etat(self, equity: float) -> AccountState:
        return AccountState(
            equity=equity, cash=equity, peak_equity=110_000.0, initial_equity=100_000.0
        )

    def test_le_drawdown_est_une_fraction_negative(self):
        assert self.etat(95_000.0).drawdown == pytest.approx(-15_000.0 / 110_000.0)

    def test_il_vaut_zero_au_sommet(self):
        assert self.etat(110_000.0).drawdown == pytest.approx(0.0)

    def test_le_rendement_se_compte_depuis_le_depart_pas_depuis_le_sommet(self):
        """Distinction qui compte : a 95 000 on est en repli de 13,6 % sous le
        sommet, mais de 5 % seulement sous le capital de depart."""
        etat = self.etat(95_000.0)
        assert etat.total_return == pytest.approx(-0.05)
        assert etat.drawdown != pytest.approx(etat.total_return)

    @pytest.mark.parametrize("nom", ACCOUNT_FIELDS)
    def test_chaque_champ_publie_est_lisible(self, nom):
        assert isinstance(self.etat(105_000.0).field(nom), float)

    def test_un_champ_inconnu_est_refuse(self):
        with pytest.raises(ValueError, match="champ de compte inconnu"):
            self.etat(1.0).field("prix_de_reve")

    def test_un_sommet_nul_ne_divise_pas_par_zero(self):
        """Cas degenere, atteignable si le capital de depart est nul."""
        vide = AccountState(equity=0.0, cash=0.0, peak_equity=0.0, initial_equity=0.0)
        assert vide.drawdown == 0.0
        assert vide.total_return == 0.0


class TestHorsRunnerCaLeve:
    """La difference avec `position`, et la raison de ce choix."""

    def test_un_contexte_nu_ne_connait_aucune_equity(self):
        ctx = BarContext(store_of())
        ctx._advance()
        with pytest.raises(ConfigurationError, match="aucun compte n'est tenu"):
            ctx.account_value("equity")

    def test_le_message_dit_pourquoi_et_non_seulement_quoi(self):
        ctx = BarContext(store_of())
        ctx._advance()
        with pytest.raises(ConfigurationError, match="n'en invente pas"):
            ctx.account_value("equity")

    def test_alors_que_la_position_vaut_plat_par_deduction(self):
        """Le contraste, pour que le choix soit lisible : hors runner personne
        n'a pris de position - c'est deductible. Une equity ne l'est pas."""
        ctx = BarContext(store_of())
        ctx._advance()
        assert ctx.position.is_flat

    def test_c_est_une_methode_et_non_une_propriete(self):
        """Comme `session_value`, et pour la meme raison : `isinstance` sur un
        `Protocol` evalue les proprietes, donc une propriete qui leve rendrait
        `isinstance(ctx, Context)` impossible."""
        from rsl.data.feed import Context

        ctx = BarContext(store_of())
        ctx._advance()
        assert isinstance(ctx, Context)


class TestLeRunnerLeRemplit:
    """La preuve qui compte : les valeurs lues doivent egaler celles du run."""

    def observer(self, spec: InstrumentSpec, champ: str):
        vus: list[float] = []
        noeud = account(champ)

        class Watcher(BuyAndHold):
            def on_bar(self, ctx):  # type: ignore[override]
                valeur = noeud(ctx)
                assert valeur is not None
                vus.append(valeur)
                return super().on_bar(ctx)

        resultat = SingleAssetRunner(store_of(), spec, config()).run(Watcher(SYMBOL, 1))
        return vus, resultat

    def test_l_equity_lue_est_celle_du_run(self, spec):
        """Verifiee contre la courbe d'equity enregistree par le moteur, et
        non contre une seconde implementation."""
        vus, resultat = self.observer(spec, "equity")
        enregistree = list(resultat.equity.equity)
        assert len(vus) == len(enregistree)
        for lue, attendue in zip(vus, enregistree, strict=True):
            assert lue == pytest.approx(attendue)

    def test_elle_commence_au_capital_de_depart(self, spec):
        vus, _ = self.observer(spec, "equity")
        assert vus[0] == pytest.approx(CASH, rel=1e-3)

    def test_le_sommet_ne_redescend_jamais(self, spec):
        vus, _ = self.observer(spec, "peak_equity")
        assert vus == sorted(vus), "un sommet qui baisse n'est pas un sommet"

    def test_le_drawdown_reste_negatif_ou_nul(self, spec):
        vus, _ = self.observer(spec, "drawdown")
        assert max(vus) <= 0.0
        assert min(vus) < 0.0, "le montage doit produire un repli"

    def test_le_drawdown_atteint_celui_que_le_rapport_annonce(self, spec):
        """Egalite entre ce que la STRATEGIE a vu et ce que le RAPPORT publie :
        si les deux divergeaient, l'un des deux mentirait."""
        vus, resultat = self.observer(spec, "drawdown")
        courbe = np.asarray(resultat.equity.equity, dtype=np.float64)
        sommets = np.maximum.accumulate(courbe)
        attendu = float(np.min((courbe - sommets) / sommets))
        assert min(vus) == pytest.approx(attendu)

    def test_le_capital_de_depart_est_constant(self, spec):
        vus, _ = self.observer(spec, "initial_equity")
        assert set(vus) == {CASH}

    def test_les_valeurs_varient_vraiment(self, spec):
        """La garde de [[lessons]] L18 : un terme present mais constant est un
        terme inerte, et rien d'autre ne le signalerait."""
        vus, _ = self.observer(spec, "drawdown")
        # Trente valeurs distinctes suffisent a exclure un terme constant ;
        # exiger davantage ne mesurerait que la forme de la serie de test.
        assert len(set(vus)) > 30, f"seulement {len(set(vus))} valeurs distinctes"


class TestUneVueReculeeLitSaPropreBarre:
    """Meme regle que `position` depuis le 2026-09-11."""

    def test_une_fenetre_sur_l_equity_voit_la_courbe_bouger(self, spec):
        """Si `shifted` rendait l'equity COURANTE, cette moyenne vaudrait
        l'equity elle-meme - le defaut que `peer` et `position` portaient."""
        moyenne = rolling("mean", 10, account("equity"))
        courante = account("equity")
        ecarts: list[float] = []

        class Watcher(BuyAndHold):
            @property
            def warmup_bars(self) -> int:
                return 20

            def on_bar(self, ctx):  # type: ignore[override]
                lissee, brute = moyenne(ctx), courante(ctx)
                if lissee is not None and brute is not None:
                    ecarts.append(abs(lissee - brute))
                return super().on_bar(ctx)

        SingleAssetRunner(store_of(), spec, config()).run(Watcher(SYMBOL, 1))
        assert ecarts, "le montage doit produire des lectures"
        assert max(ecarts) > 1.0, "la fenetre lit dix fois la valeur courante"

    def test_avant_la_premiere_barre_du_run_l_etat_se_deduit(self, spec):
        """Le runner n'appelle pas la strategie pendant le prechauffage : aucun
        ordre n'a pu etre emis, donc l'equity vaut le capital de depart. C'est
        une deduction, pas un defaut choisi."""
        recule = build_signal({
            "type": "lag", "bars": 3,
            "inner": {"type": "account", "field": "equity"},
        })
        vus: list[float] = []

        class Watcher(BuyAndHold):
            @property
            def warmup_bars(self) -> int:
                return 5

            def on_bar(self, ctx):  # type: ignore[override]
                valeur = recule(ctx)
                if valeur is not None:
                    vus.append(valeur)
                return super().on_bar(ctx)

        SingleAssetRunner(store_of(), spec, config()).run(Watcher(SYMBOL, 1))
        assert vus[0] == pytest.approx(CASH), "le prechauffage doit valoir le depart"

    def test_au_dela_de_la_profondeur_declaree_ca_leve(self):
        """Meme bornage que l'historique de positions, meme message."""
        from rsl.data.feed import AccountHistory

        histoire = AccountHistory()
        histoire.set_initial(CASH)
        histoire.set_depth(5)
        for instant in range(100, 140):
            histoire.record(instant, AccountState(
                equity=float(instant), cash=0.0, peak_equity=200.0, initial_equity=CASH,
            ))
        assert histoire.at(138).equity == pytest.approx(138.0)
        with pytest.raises(InsufficientHistoryError, match="etat de compte"):
            histoire.at(110)

    def test_l_historique_reste_borne(self):
        from rsl.data.feed import AccountHistory

        histoire = AccountHistory()
        histoire.set_initial(CASH)
        histoire.set_depth(10)
        for instant in range(5_000):
            histoire.record(instant, AccountState(
                equity=1.0, cash=1.0, peak_equity=1.0, initial_equity=1.0,
            ))
        assert histoire.taille() <= 12


class TestUnSeulCompteParPortefeuille:
    """La difference avec les positions, qui sont par instrument."""

    def panneau(self):
        stores = {
            s: synthetic.make_store(synthetic.ramp(120), symbol=s,
                                    granularity=JOUR, start=synthetic.EPOCH)
            for s in ("A", "B")
        }
        return build_panel(stores)

    def test_deux_instruments_partagent_la_meme_equity(self):
        multi = MultiContext(self.panneau())
        multi._context_of("A")._set_position_depth(10)
        multi._account_history().set_initial(CASH)
        multi._seek_row(40)
        multi._set_account(AccountState(
            equity=123_456.0, cash=1.0, peak_equity=200_000.0, initial_equity=CASH,
        ))
        assert multi["A"].account_value("equity") == pytest.approx(123_456.0)
        assert multi["B"].account_value("equity") == pytest.approx(123_456.0)

    def test_un_pair_voit_le_meme_compte(self):
        """`peer("B", account("equity"))` doit rendre l'equity du
        PORTEFEUILLE, pas une equity propre a B qui n'existe pas."""
        multi = MultiContext(self.panneau())
        multi._account_history().set_initial(CASH)
        multi._seek_row(40)
        multi._set_account(AccountState(
            equity=77_000.0, cash=1.0, peak_equity=90_000.0, initial_equity=CASH,
        ))
        noeud = build_signal({
            "type": "peer", "symbol": "B",
            "inner": {"type": "account", "field": "equity"},
        })
        assert noeud(multi["A"]) == pytest.approx(77_000.0)


class TestLeNoeud:
    def test_le_champ_par_defaut_est_l_equity(self):
        assert build_signal({"type": "account"}).field == "equity"

    def test_un_champ_inconnu_est_refuse_a_la_construction(self):
        """Avant le run, pas pendant : une coquille ne doit pas attendre la
        premiere barre pour se manifester."""
        with pytest.raises(ConfigurationError, match="champ inconnu"):
            build_signal({"type": "account", "field": "profit"})

    def test_il_ne_demande_aucun_prechauffage(self):
        assert account("drawdown").warmup_bars == 0

    def test_il_se_decrit_et_se_reconstruit(self):
        noeud = account("total_return")
        assert build_signal(noeud.describe()).describe() == noeud.describe()

    def test_il_n_est_pas_memoisable(self):
        """Sa valeur depend du RUN, que la cle de memoisation n'identifie
        pas - meme raison que `peer` et `position`."""
        from rsl.strategies.memoire import memoisable

        assert not memoisable(account("equity"))
