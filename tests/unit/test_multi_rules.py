"""`multi_rules@1` : un jeu de regles PAR instrument, un seul portefeuille.

Avant ce moule, tenir ES sur une logique et NQ sur une autre demandait deux
runs - donc deux equity separees, deux drawdowns sans rapport, et aucune
contrainte de risque commune.

Ce qui est verifie ici tient en trois familles : chaque livre decide bien sur
SON instrument, l'ordre des livres ne depend pas de l'ordre des cles JSON, et
les erreurs de declaration levent au lieu de produire un comportement plausible
mais faux.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fixtures import synthetic
from rsl.data.feed import MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import BarStore, Granularity
from rsl.errors import ConfigurationError
from rsl.strategies.base import get_strategy
from rsl.strategies.rules import MultiRuleStrategy, RuleStrategy
from rsl.strategies.signals import TRUE, Compare, CompareOp, Peer, const, price

JOUR = Granularity.minutes(60 * 24)
EPOCH = synthetic.EPOCH


def magasins() -> dict[str, BarStore]:
    """A monte, B descend. C s'arrete a mi-parcours : instrument absent."""
    return {
        "A": synthetic.make_store(synthetic.ramp(40, 100.0, 1.0), symbol="A",
                                  granularity=JOUR, start=EPOCH),
        "B": synthetic.make_store(synthetic.ramp(40, 200.0, -1.0), symbol="B",
                                  granularity=JOUR, start=EPOCH),
    }


def contexte(ligne: int = 25, stores: dict[str, BarStore] | None = None) -> MultiContext:
    panneau = build_panel(stores if stores is not None else magasins())
    ctx = MultiContext(panneau)
    ctx._seek_row(ligne)
    return ctx


def livre(symbole: str, quantite: int = 1, **overrides: object) -> RuleStrategy:
    params: dict[str, object] = {
        "symbol": symbole, "quantity": quantite, "entry_long": const(TRUE),
    }
    params.update(overrides)
    return RuleStrategy(**params)  # type: ignore[arg-type]


def construire(books: dict[str, dict[str, object]]) -> MultiRuleStrategy:
    """Passe par le registre, comme une specification reelle."""
    entree = get_strategy("multi_rules", 1)
    strategie = entree.build({"books": books})
    assert isinstance(strategie, MultiRuleStrategy)
    return strategie


TOUJOURS = {"rules": {"entry_long": {"type": "constant", "value": 1.0}}}
"""Un livre est un jeu de parametres `rules@1` moins le symbole : les
regles se nichent sous `rules`, comme partout ailleurs."""


class TestDecision:
    def test_chaque_livre_agit_sur_son_instrument(self):
        strategie = MultiRuleStrategy(books=(livre("A"), livre("B", quantite=3)))
        ordres = list(strategie.on_rebalance(contexte()))
        assert {o.symbol for o in ordres} == {"A", "B"}
        assert {o.symbol: o.quantity for o in ordres} == {"A": 1, "B": 3}

    def test_un_livre_peut_ne_rien_faire(self):
        """Les livres sont independants : l'un entre, l'autre non."""
        jamais = livre("B", entry_long=Compare(const(1.0), CompareOp.GT, const(2.0)))
        strategie = MultiRuleStrategy(books=(livre("A"), jamais))
        ordres = list(strategie.on_rebalance(contexte()))
        assert [o.symbol for o in ordres] == ["A"]

    def test_un_instrument_absent_de_la_coupe_ne_donne_rien(self):
        """On ne decide pas sans barre - meme regle que `panel_rules@1`."""
        strategie = MultiRuleStrategy(books=(livre("A"), livre("ABSENT")))
        ordres = list(strategie.on_rebalance(contexte()))
        assert [o.symbol for o in ordres] == ["A"]

    def test_un_livre_peut_regarder_les_autres_par_peer(self):
        """Chaque livre recoit `ctx[symbole]`, donc `peer` fonctionne dedans :
        on negocie A en regardant B."""
        condition = Compare(price("close"), CompareOp.LT,
                            Peer("B", price("close")))
        strategie = MultiRuleStrategy(books=(livre("A", entry_long=condition),))
        # A vaut 125 a la ligne 25, B vaut 175 : la condition est vraie.
        assert [o.symbol for o in strategie.on_rebalance(contexte())] == ["A"]


class TestDeterminisme:
    def test_les_livres_sont_tries_par_symbole(self):
        """Deux specifications identiques a l'ordre des cles pres doivent
        produire la meme suite d'ordres, donc la meme empreinte."""
        avant = construire({"B": TOUJOURS, "A": TOUJOURS})
        apres = construire({"A": TOUJOURS, "B": TOUJOURS})
        assert [b.symbol for b in avant.books] == ["A", "B"]
        assert [b.symbol for b in apres.books] == ["A", "B"]

    def test_l_ordre_des_ordres_emis_ne_depend_pas_des_cles(self):
        emis = lambda s: [o.symbol for o in s.on_rebalance(contexte())]  # noqa: E731
        assert emis(construire({"B": TOUJOURS, "A": TOUJOURS})) == emis(
            construire({"A": TOUJOURS, "B": TOUJOURS})
        )


class TestEtat:
    def test_les_fills_atteignent_le_bon_livre(self):
        """Diffuses a tous ; chacun filtre deja sur son symbole."""
        a, b = livre("A"), livre("B")
        strategie = MultiRuleStrategy(books=(a, b))
        ordre = next(o for o in strategie.on_rebalance(contexte()) if o.symbol == "A")
        strategie.on_fill(synthetic_fill(ordre))
        assert a._position == 1
        assert b._position == 0

    def test_reset_remet_tous_les_livres_a_plat(self):
        a, b = livre("A"), livre("B")
        strategie = MultiRuleStrategy(books=(a, b))
        for ordre in strategie.on_rebalance(contexte()):
            strategie.on_fill(synthetic_fill(ordre))
        assert a._position != 0
        strategie.reset()
        assert a._position == 0 and b._position == 0

    def test_le_warmup_est_celui_du_livre_le_plus_exigeant(self):
        profond = livre("B", extra_warmup=300)
        strategie = MultiRuleStrategy(books=(livre("A"), profond))
        assert strategie.warmup_bars == 300

    def test_extra_warmup_global_s_ajoute(self):
        strategie = MultiRuleStrategy(books=(livre("A"),), extra_warmup=50)
        assert strategie.warmup_bars == livre("A").warmup_bars + 50


class TestDeclarationsInvalides:
    def test_books_vide_est_refuse(self):
        with pytest.raises(ConfigurationError, match="vide"):
            construire({})

    def test_un_symbole_en_double_est_refuse(self):
        """Deux jeux de regles sur le meme instrument se marcheraient dessus :
        leurs positions ne sont pas separables dans un portefeuille commun."""
        with pytest.raises(ConfigurationError, match="double"):
            MultiRuleStrategy(books=(livre("A"), livre("A")))

    def test_un_champ_symbol_dans_un_livre_est_refuse(self):
        """Le symbole est deja la cle : en declarer un second ouvrirait la
        porte a ce que les deux divergent."""
        with pytest.raises(ConfigurationError, match="`symbol`"):
            construire({"A": {**TOUJOURS, "symbol": "Z"}})

    def test_un_livre_non_objet_est_refuse(self):
        """Rejete par le TYPE de `books`, avant meme d'atteindre le
        constructeur - d'ou `ValidationError` et non `ConfigurationError`."""
        with pytest.raises(ValidationError, match="valid dictionary"):
            construire({"A": "des regles"})  # type: ignore[dict-item]

    def test_extra_warmup_negatif_est_refuse(self):
        with pytest.raises(ConfigurationError, match="extra_warmup"):
            MultiRuleStrategy(books=(livre("A"),), extra_warmup=-1)

    def test_un_livre_sans_entree_est_refuse_comme_ailleurs(self):
        """La garde de `RuleStrategy` s'applique a chaque livre."""
        with pytest.raises(ConfigurationError, match="FlatStrategy"):
            construire({"A": {"quantity": 1, "rules": {}}})


class TestDescription:
    def test_le_descripteur_porte_chaque_livre(self):
        strategie = construire({"A": TOUJOURS, "B": TOUJOURS})
        decrit = strategie.describe()
        assert set(decrit["books"]) == {"A", "B"}
        assert decrit["books"]["A"]["symbol"] == "A"

    def test_le_moule_est_declare_transversal(self):
        entree = get_strategy("multi_rules", 1)
        assert entree.cross_sectional is True


def synthetic_fill(order):
    """Fill complet de l'ordre, au prix de reference."""
    from rsl.engine.orders import Fill

    return Fill(
        order_id=id(order), symbol=order.symbol, side=order.side,
        quantity=order.quantity, price=100.0, fee=0.0, slippage_cost=0.0,
        ts_ns=0, bar_index=0, tag=order.tag,
    )
