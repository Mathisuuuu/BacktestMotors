"""Le decoupage en couches, verifie plutot qu'affirme.

`rsl.strategies` DECIDE, `rsl.engine` EXECUTE. Les deux se parlent par
`Order` et `Fill`, qui vivent sous elles dans `rsl/orders.py`.

Jusqu'au 2026-09-11, `rsl/orders.py` etait `rsl/engine/orders.py` et la
dependance partait donc dans les deux sens : importer `rsl.strategies`
chargeait sept modules de moteur. Ce cycle ne plantait pas - `orders` est une
feuille, `from rsl.engine.orders import X` se resout meme quand `rsl.engine`
n'est qu'a moitie initialise, et trois tentatives de le casser en reordonnant
les imports ont echoue. Il empechait simplement de raisonner sur une couche
sans l'autre.

Un test d'import est le seul moyen de garder ce sens unique : rien dans
`ruff` ni dans `mypy --strict` ne signale un cycle de paquets, et la facade
`rsl.engine` continue de reexporter `Order`, donc un `from rsl.engine import
Order` ecrit un jour dans `rsl/strategies/` passerait les deux.
"""

from __future__ import annotations

import subprocess
import sys

PROGRAMME = """
import sys
import rsl.strategies  # noqa: F401
fuites = sorted(m for m in sys.modules if m.startswith("rsl.engine"))
print(",".join(fuites))
"""


def modules_charges_par(programme: str) -> list[str]:
    """Dans un interpreteur NEUF : le processus de test a deja tout importe."""
    resultat = subprocess.run(
        [sys.executable, "-c", programme],
        capture_output=True, text=True, check=True,
    )
    return [m for m in resultat.stdout.strip().split(",") if m]


class TestSensUnique:
    def test_importer_les_strategies_ne_charge_pas_le_moteur(self):
        fuites = modules_charges_par(PROGRAMME)
        assert fuites == [], (
            f"la couche decision tire la couche execution : {fuites}. Le cycle "
            f"est revenu - chercher un `from rsl.engine...` dans rsl/strategies/."
        )

    def test_le_moteur_tire_les_strategies_lui(self):
        """Le sens ATTENDU. Sans cette moitie, le test precedent passerait
        aussi si les deux couches avaient cesse de se connaitre."""
        charges = modules_charges_par(
            "import sys\n"
            "import rsl.engine\n"
            "print(','.join(sorted(m for m in sys.modules "
            "if m.startswith('rsl.strategies'))))\n"
        )
        assert "rsl.strategies.base" in charges


class TestOrdersEstUneFeuille:
    def test_orders_ne_dependant_que_des_erreurs(self):
        """Ce qui rend le placement a la racine legitime : si `orders` tirait
        une couche, il appartiendrait a cette couche."""
        charges = modules_charges_par(
            "import sys\n"
            "import rsl.orders\n"
            "print(','.join(sorted(m for m in sys.modules "
            "if m.startswith('rsl.') and m != 'rsl.orders')))\n"
        )
        assert charges == ["rsl.errors"], charges

    def test_la_facade_du_moteur_les_nomme_toujours(self):
        """Le moteur travaille sur des ordres : sa facade a le droit de les
        exposer. C'est le test d'import ci-dessus qui ferme le cycle, pas le
        retrait de ce reexport."""
        import rsl.engine

        for nom in ("Order", "Fill", "OrderType", "Side"):
            assert nom in rsl.engine.__all__
            assert getattr(rsl.engine, nom) is getattr(
                __import__("rsl.orders", fromlist=[nom]), nom
            )
