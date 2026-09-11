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


class TestFacadeDesSignaux:
    """`rsl.strategies.signals` est une FACADE depuis le 2026-09-11.

    Le code vit dans `rsl/strategies/noeuds/`, range par famille. La facade
    existe pour qu'aucun des trente et quelques fichiers qui importaient
    `from rsl.strategies.signals import ...` n'ait a changer.

    Une facade sans test est une facade qui perd des noms sans le dire : elle
    n'est qu'une liste d'imports, et un `ruff --fix` retire un import qui ne
    sert a rien d'autre qu'a etre reexporte. C'est arrive pendant le
    decoupage - `_NODES` a disparu, et seule la suite l'a signale.
    """

    def test_tout_ce_que_les_familles_definissent_passe_par_la_facade(self):
        """La garde qui compte, et elle est plus large qu'une liste de noeuds.

        On ne compare pas au registre - `NodeType` ne porte pas la classe - mais
        a ce que chaque module de famille DEFINIT reellement : classes et
        fonctions dont le `__module__` est le sien. Un noeud ajoute demain dans
        `feuilles.py` et oublie dans la facade fait echouer ce test, sans
        qu'aucune liste n'ait ete tenue a jour ici.
        """
        import importlib
        import inspect

        import rsl.strategies.signals as facade

        manquants: list[str] = []
        for famille in ("contrat", "feuilles", "fenetres", "operateurs", "raccourcis"):
            module = importlib.import_module(f"rsl.strategies.noeuds.{famille}")
            for nom, objet in vars(module).items():
                if nom.startswith("_") or not (
                    inspect.isclass(objet) or inspect.isfunction(objet)
                ):
                    continue
                if getattr(objet, "__module__", None) != module.__name__:
                    continue  # importe, pas defini ici
                if getattr(facade, nom, None) is not objet:
                    manquants.append(f"{famille}.{nom}")
        assert manquants == [], f"absents de la facade : {manquants}"

    def test_tout_ce_que_all_annonce_existe(self):
        """Un `__all__` qui ment casse `from ... import *` et trompe les
        outils, sans qu'aucun import ordinaire ne s'en apercoive."""
        import rsl.strategies.signals as facade

        manquants = [nom for nom in facade.__all__ if not hasattr(facade, nom)]
        assert manquants == [], manquants

    def test_les_familles_ne_se_connaissent_pas_entre_elles(self):
        """`contrat` est sous les autres ; les familles ne s'importent pas
        mutuellement. Sans cela, le decoupage n'aurait deplace le monolithe
        qu'en apparence."""
        import ast
        from pathlib import Path

        familles = {"feuilles", "fenetres", "operateurs"}
        racine = Path("src/rsl/strategies/noeuds")
        for nom in familles:
            arbre = ast.parse((racine / f"{nom}.py").read_text(encoding="utf-8"))
            importes = {
                noeud.module
                for noeud in ast.walk(arbre)
                if isinstance(noeud, ast.ImportFrom) and noeud.module
            }
            voisins = {
                m for m in importes
                if m.startswith("rsl.strategies.noeuds.")
                and m.rsplit(".", 1)[-1] in familles - {nom}
            }
            assert voisins == set(), f"{nom} importe {voisins}"

    def test_la_facade_ne_reexporte_pas_de_nom_prive(self):
        """Un nom prive qui transite par une facade est un nom prive qu'on
        croit public. `_NODES` s'importe depuis `noeuds.contrat`."""
        import rsl.strategies.signals as facade

        assert [nom for nom in facade.__all__ if nom.startswith("_")] == []
