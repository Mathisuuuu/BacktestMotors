"""Le squelette a trous doit rester vrai, complet, et surtout SUFFISANT.

Trois exigences distinctes, testees separement :

1. **Vrai** : ce qu'il annonce correspond aux registres.
2. **Complet** : aucun type de noeud, aucune primitive, aucune strategie ne
   manque, et le fichier versionne n'a pas derive du generateur.
3. **Suffisant** : un lecteur qui n'aurait QUE ce document doit pouvoir en
   tirer une specification valide. C'est la seule exigence qui compte
   vraiment, et la derniere classe la met a l'epreuve en construisant une
   specification uniquement a partir des choix qu'il enumere.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from rsl.config import BacktestSpec
from rsl.data.instruments import known_roots
from rsl.primitives.registry import describe_registry, get_primitive
from rsl.skeleton import FORMAT, build_skeleton
from rsl.strategies.base import describe_strategies
from rsl.strategies.signals import build_signal, list_node_types

PUBLIE = pathlib.Path("schemas/squelette.json")


@pytest.fixture(scope="module")
def squelette() -> dict[str, object]:
    return build_skeleton()


def champs(squelette: dict[str, object], *chemin: str) -> dict[str, object]:
    """Descend dans le document par une suite de cles, en verifiant le type."""
    courant: object = squelette
    for cle in chemin:
        assert isinstance(courant, dict), chemin
        courant = courant[cle]
    assert isinstance(courant, dict)
    return courant


# ---------------------------------------------------------------------------
# Vrai
# ---------------------------------------------------------------------------


class TestFidelite:
    def test_le_format_est_annonce(self, squelette):
        assert squelette["format"] == FORMAT

    def test_les_instruments_sont_ceux_du_registre(self, squelette):
        assert squelette["instruments"] == sorted(known_roots())

    def test_root_propose_exactement_ces_instruments(self, squelette):
        racine = champs(squelette, "specification", "data", "element", "champs", "root")
        assert racine["type"] == "choix"
        assert racine["choix"] == squelette["instruments"]

    def test_strategy_ref_propose_les_strategies_enregistrees(self, squelette):
        reference = champs(squelette, "specification", "strategy", "champs", "ref")
        assert reference["choix"] == [str(e["ref"]) for e in describe_strategies()]

    def test_primitive_ref_propose_les_primitives_enregistrees(self, squelette):
        reference = champs(squelette, "noeuds", "primitive", "champs", "ref")
        assert reference["choix"] == [str(e["ref"]) for e in describe_registry()]

    def test_les_cles_de_rules_sont_derivees_pas_recopiees(self, squelette):
        assert squelette["cles_de_rules"] == [
            "entry_long", "exit_long", "entry_short", "exit_short",
            "stop_loss", "take_profit",
        ]

    def test_les_choix_de_rolling_suivent_l_enum(self, squelette):
        stat = champs(squelette, "noeuds", "rolling", "champs", "stat")
        assert "ema" in stat["choix"]
        assert set(stat["choix"]) == {
            "mean", "stdev", "min", "max", "sum", "zscore",
            "ema", "median", "var", "slope", "rank", "count_true",
        }


# ---------------------------------------------------------------------------
# Complet
# ---------------------------------------------------------------------------


class TestExhaustivite:
    def test_tous_les_noeuds_sont_decrits(self, squelette):
        noeuds = squelette["noeuds"]
        assert isinstance(noeuds, dict)
        assert set(noeuds) == {n.name for n in list_node_types()}

    def test_toutes_les_primitives_sont_decrites(self, squelette):
        primitives = squelette["primitives"]
        assert isinstance(primitives, dict)
        assert set(primitives) == {str(e["ref"]) for e in describe_registry()}

    def test_toutes_les_strategies_sont_decrites(self, squelette):
        strategies = squelette["strategies"]
        assert isinstance(strategies, dict)
        assert set(strategies) == {str(e["ref"]) for e in describe_strategies()}

    def test_chaque_noeud_porte_un_resume(self, squelette):
        for nom, corps in squelette["noeuds"].items():
            assert corps["resume"], nom

    def test_les_champs_requis_de_la_specification_sont_marques(self, squelette):
        attendus = set(BacktestSpec.model_json_schema().get("required", []))
        marques = {
            nom for nom, slot in squelette["specification"].items()
            if isinstance(slot, dict) and slot.get("requis")
        }
        assert attendus <= marques

    def test_le_fichier_versionne_n_a_pas_derive(self, squelette):
        """Meme garde que pour `schemas/` : un document engendre qui dort dans
        le depot vieillit en silence."""
        publie = json.loads(PUBLIE.read_text(encoding="utf-8"))
        assert publie == json.loads(json.dumps(squelette, sort_keys=True)), (
            "schemas/squelette.json a derive des registres. "
            "Regenerer : rsl squelette --out schemas/squelette.json"
        )

    def test_le_document_est_en_ascii_pur(self):
        """Il sera lu par des outils au hasard des encodages. `rsl schema`
        redirige avec `>` sort en CP1252 sur Windows ; l'ASCII y echappe."""
        assert PUBLIE.read_bytes().decode("ascii")


# ---------------------------------------------------------------------------
# Suffisant : l'exigence qui compte
# ---------------------------------------------------------------------------


class TestSuffisance:
    """Construire une specification en n'utilisant QUE ce que le squelette dit."""

    def premier_choix(self, slot: dict[str, object]) -> object:
        assert slot["type"] == "choix"
        choix = slot["choix"]
        assert isinstance(choix, list) and choix
        return choix[0]

    def test_une_specification_se_construit_depuis_les_seuls_choix(self, squelette):
        spec = squelette["specification"]
        instrument = self.premier_choix(
            champs(squelette, "specification", "data", "element", "champs", "root")
        )
        construite = {
            "name": "issu-du-squelette",
            "initial_cash": 100_000.0,
            "data": [{
                "root": instrument,
                "path": f"indices/{instrument}_v0_1m.parquet",
                "granularity_minutes": 1,
            }],
            "execution": {
                "fees": {"kind": self.premier_choix(
                    champs(squelette, "specification", "execution", "champs",
                           "fees", "champs", "kind"))},
                "slippage": {"kind": "zero"},
                "lag_bars": spec["execution"]["champs"]["lag_bars"]["defaut"],
            },
            "strategy": {
                "ref": "buy_and_hold@1",
                "params": {"symbol": f"{instrument}.v.0"},
            },
        }
        assert BacktestSpec.model_validate(construite) is not None

    def test_chaque_noeud_se_construit_depuis_sa_description(self, squelette):
        """Pour chaque type de noeud, on remplit ses champs selon ce que le
        squelette annonce, et `build_signal` doit accepter le resultat."""
        feuille = {"type": "constant", "value": 1.0}
        for nom, corps in squelette["noeuds"].items():
            instance: dict[str, object] = {"type": nom}
            for champ, slot in corps["champs"].items():
                assert isinstance(slot, dict)
                if not slot.get("requis") and "defaut" in slot:
                    continue
                instance[champ] = self.valeur_pour(slot, feuille)
            assert build_signal(instance) is not None, nom

    def valeur_pour(self, slot: dict[str, object], feuille: dict[str, object]) -> object:
        genre = slot["type"]
        if genre == "noeud":
            return feuille
        if genre == "liste":
            return [feuille]
        if genre == "choix":
            return self.premier_choix(slot)
        if genre == "entier":
            return max(int(slot.get("min", 1) or 1), 2)
        if genre == "nombre":
            return 1.0
        if genre == "texte":
            return "sma@1"
        if genre == "objet":
            return {"window": 5}
        raise AssertionError(f"type de slot non gere par le test : {genre}")

    def test_chaque_primitive_se_construit_avec_ses_defauts(self, squelette):
        """Un parametre requis sans defaut se verrait ici : la primitive
        refuserait d'etre instanciee."""
        for ref, corps in squelette["primitives"].items():
            valeurs = {
                nom: 14 if slot.get("type") == "entier" else slot.get("defaut")
                for nom, slot in corps["params"].items()
                if slot.get("requis")
            }
            assert get_primitive(ref).bind(**valeurs) is not None, ref

    def test_le_squelette_lui_meme_n_est_pas_une_specification(self, squelette):
        """Garde-fou de lecture : les descripteurs ne sont pas des valeurs.

        Si le document passait pour une specification valide, un lecteur
        pourrait croire qu'il suffit de le soumettre tel quel.
        """
        with pytest.raises(ValueError, match=r"(?i)valid"):
            BacktestSpec.model_validate(squelette["specification"])
