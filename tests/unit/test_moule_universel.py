"""Le moule universel doit rester universel.

`examples/_moule_universel.json` sert de reference vivante du vocabulaire : on
y lit la forme reelle de chaque type de noeud. Une reference qui ne couvre plus
tout ne le dit pas d'elle-meme - elle se contente de vieillir. Ce test rend
l'oubli impossible : ajouter un type de noeud sans l'ajouter au moule echoue
ici, avec le nom du manquant.
"""

from __future__ import annotations

import json

import pytest

from fixtures.exemples import STRATEGIES, montage, specification
from rsl.composition import StrategyFile
from rsl.config import BacktestSpec
from rsl.strategies.base import get_strategy
from rsl.strategies.signals import build_signal, list_node_types

MOULE = STRATEGIES / "_moule_universel.json"
DEMARRAGE = STRATEGIES / "_moule.json"


@pytest.fixture(scope="module")
def moule() -> dict[str, object]:
    return json.loads(MOULE.read_text(encoding="utf-8"))


def types_utilises(noeud: object, vus: set[str] | None = None) -> set[str]:
    """Parcourt l'arbre et collecte chaque valeur du champ `type`."""
    vus = vus if vus is not None else set()
    if isinstance(noeud, dict):
        marque = noeud.get("type")
        if isinstance(marque, str):
            vus.add(marque)
        for valeur in noeud.values():
            types_utilises(valeur, vus)
    elif isinstance(noeud, list):
        for valeur in noeud:
            types_utilises(valeur, vus)
    return vus


def regles(moule: dict[str, object]) -> dict[str, object]:
    strategie = moule["strategy"]
    assert isinstance(strategie, dict)
    params = strategie["params"]
    assert isinstance(params, dict)
    regles_ = params["rules"]
    assert isinstance(regles_, dict)
    return regles_


class TestCouverture:
    def test_chaque_type_de_noeud_enregistre_est_utilise(self, moule):
        """Le message nomme les manquants : c'est ce qui rend l'echec actionnable."""
        utilises = types_utilises(regles(moule))
        enregistres = {noeud.name for noeud in list_node_types()}
        manquants = enregistres - utilises
        assert not manquants, (
            f"types de noeuds absents du moule universel : {sorted(manquants)}. "
            f"Ajoutez-les a {MOULE}, sinon la reference ment par omission."
        )

    def test_il_n_utilise_aucun_type_inconnu(self, moule):
        utilises = types_utilises(regles(moule))
        enregistres = {noeud.name for noeud in list_node_types()}
        assert utilises <= enregistres

    def test_les_six_cles_de_regles_sont_montrees(self, moule):
        """Long ET short, plus stop et objectif : le moule doit tout exposer."""
        attendues = {"entry_long", "exit_long", "entry_short", "exit_short",
                     "stop_loss", "take_profit"}
        assert set(regles(moule)) == attendues


class TestValidite:
    def test_le_fichier_de_strategie_est_valide(self, moule):
        """Pydantic en `extra=forbid` : un champ en trop ferait echouer ici.

        C'est un fichier de STRATEGIE depuis le 2026-09-12 : il ne porte plus
        ni actif, ni capital, ni couts.
        """
        assert StrategyFile.model_validate(moule) is not None

    def test_et_recolle_a_son_montage_il_donne_un_run_valide(self):
        """La verification qui compte vraiment : une strategie qui ne se
        compose pas est une strategie qu'on ne peut pas executer."""
        assert isinstance(specification("_moule_universel.json"), BacktestSpec)

    def test_chaque_regle_se_reconstruit_en_signal(self, moule):
        for nom, regle in regles(moule).items():
            assert build_signal(regle) is not None, nom

    def test_la_strategie_referencee_existe(self, moule):
        strategie = moule["strategy"]
        nom, _, version = str(strategie["ref"]).partition("@")
        assert get_strategy(nom, int(version)) is not None

    def test_le_moule_de_demarrage_reste_valide(self):
        """Le moule simple n'est pas remplace par l'universel : il demarre."""
        contenu = json.loads(DEMARRAGE.read_text(encoding="utf-8"))
        assert StrategyFile.model_validate(contenu) is not None
        assert specification("_moule.json") is not None


class TestLisibilite:
    def test_les_chemins_de_donnees_sont_relatifs(self):
        """Un chemin absolu rendrait le montage inutilisable chez un
        collaborateur ET ferait diverger le `config_hash` entre machines.

        Le chemin vit desormais dans le MONTAGE, pas dans la strategie : une
        strategie qui nommerait un fichier ne serait applicable a rien
        d'autre.
        """
        sources = montage("_moule_universel.json")["data"]
        assert isinstance(sources, list)
        for source in sources:
            assert isinstance(source, dict)
            chemin = str(source["path"])
            assert not chemin.startswith("/")
            assert ":" not in chemin
