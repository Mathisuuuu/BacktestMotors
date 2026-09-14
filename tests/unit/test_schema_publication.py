"""Le vocabulaire publie son contrat, et ce contrat est verifie.

Un schema recopie a la main derive de son constructeur au premier changement,
et un schema faux est pire que pas de schema : une machine lui fait confiance.
Deux garanties sont donc testees ici.

**Le schema est engendre**, pas saisi : il derive de la declaration de champs
de chaque type de noeud.

**Le schema et `from_spec` s'accordent** : pour chaque cas malforme, on verifie
que les DEUX refusent. Un schema plus permissif que le constructeur laisserait
passer des specifications qui exploseraient a l'execution ; un schema plus
strict rejetterait des specifications valides.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from jsonschema import Draft202012Validator

from fixtures.exemples import noms
from rsl.config import BacktestSpec
from rsl.strategies.base import describe_strategies
from rsl.strategies.signals import (
    Compare,
    CompareOp,
    CrossesAbove,
    FieldKind,
    NodeField,
    Not,
    all_of,
    build_signal,
    const,
    describe_node_types,
    get_node_type,
    list_node_types,
    price,
    prim,
    signal_json_schema,
)


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = signal_json_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def tree() -> dict[str, object]:
    return all_of(
        CrossesAbove(prim("sma@1", window=10), prim("sma@1", window=50)),
        Compare(prim("zscore@1", window=100), CompareOp.LT, const(2.0)),
        Not(Compare(price("volume"), CompareOp.EQ, const(0.0))),
    ).describe()


class TestSchemaDocument:
    def test_it_is_a_valid_json_schema(self):
        Draft202012Validator.check_schema(signal_json_schema())

    def test_it_covers_every_registered_node(self):
        branches = signal_json_schema()["$defs"]["node"]["oneOf"]  # type: ignore[index]
        titles = {branch["title"] for branch in branches}
        assert titles == {node.ref for node in list_node_types()}

    def test_it_is_json_serialisable(self):
        schema = signal_json_schema()
        assert json.loads(json.dumps(schema)) == schema

    def test_sub_nodes_point_back_to_the_recursion(self):
        """C'est ce `$ref` qui rend un arbre entier validable, pas un noeud isole."""
        compare = get_node_type("compare").json_schema()
        assert compare["properties"]["left"] == {"$ref": "#/$defs/node"}  # type: ignore[index]

    def test_the_catalogue_carries_the_schemas(self):
        entry = next(e for e in describe_node_types() if e["type"] == "compare")
        assert "schema" in entry
        assert entry["schema"]["required"] == ["type", "op", "left", "right"]  # type: ignore[index]


class TestSchemaAcceptsRealSpecifications:
    def test_a_composed_tree_validates(self, validator: Draft202012Validator):
        validator.validate(tree())

    def test_every_node_type_has_at_least_one_valid_instance(
        self, validator: Draft202012Validator
    ):
        """Un schema qui n'accepte rien serait vert sur tous les tests de rejet."""
        leaf: dict[str, object] = {"type": "constant", "value": 1.0}
        instances: dict[str, dict[str, object]] = {
            "constant": leaf,
            "primitive": {"type": "primitive", "ref": "sma@1", "params": {"window": 5}},
            "price": {"type": "price", "field": "close", "lag": 2},
            "lag": {"type": "lag", "bars": 3, "inner": leaf},
            "compare": {"type": "compare", "op": ">", "left": leaf, "right": leaf},
            "arith": {"type": "arith", "op": "+", "left": leaf, "right": leaf},
            "all_of": {"type": "all_of", "operands": [leaf]},
            "any_of": {"type": "any_of", "operands": [leaf]},
            "not": {"type": "not", "inner": leaf},
            "crosses_above": {"type": "crosses_above", "fast": leaf, "slow": leaf},
            "crosses_below": {"type": "crosses_below", "fast": leaf, "slow": leaf},
            "position": {"type": "position", "field": "bars_held"},
            "account": {"type": "account", "field": "drawdown"},
            "time": {"type": "time", "field": "weekday"},
            "peer": {"type": "peer", "symbol": "NQ.v.0", "inner": leaf},
            "rolling": {"type": "rolling", "stat": "mean", "window": 5, "inner": leaf},
            "if_then_else": {
                "type": "if_then_else", "condition": leaf, "then": leaf, "otherwise": leaf,
            },
            "math": {"type": "math", "op": "abs", "inner": leaf},
            "min_of": {"type": "min_of", "operands": [leaf, leaf]},
            "max_of": {"type": "max_of", "operands": [leaf, leaf]},
            "bars_since": {"type": "bars_since", "lookback": 10, "inner": leaf},
            "session": {"type": "session", "field": "high", "lag": 1},
            "cumulative": {"type": "cumulative", "stat": "sum", "inner": leaf},
            "session_lag": {"type": "session_lag", "sessions": 1, "inner": leaf},
            "event": {"type": "event", "name": "fomc",
                      "field": "minutes_since"},
            "value_when": {"type": "value_when", "lookback": 10,
                           "when": leaf, "inner": leaf},
        }
        assert set(instances) == {node.name for node in list_node_types()}
        for name, instance in instances.items():
            assert validator.is_valid(instance), name
            assert build_signal(instance) is not None, name

    def test_the_version_may_be_omitted_or_pinned(self, validator: Draft202012Validator):
        assert validator.is_valid({"type": "constant", "value": 1.0})
        assert validator.is_valid({"type": "constant", "version": 1, "value": 1.0})
        assert not validator.is_valid({"type": "constant", "version": 2, "value": 1.0})


MALFORMED: dict[str, dict[str, object]] = {
    "type inconnu": {"type": "n_existe_pas"},
    "operateur invalide": {
        "type": "compare",
        "op": "=>",
        "left": {"type": "constant", "value": 1.0},
        "right": {"type": "constant", "value": 2.0},
    },
    "champ en trop": {"type": "constant", "value": 1.0, "coquille": 3},
    "champ manquant": {
        "type": "compare",
        "op": ">",
        "left": {"type": "constant", "value": 1.0},
    },
    "lag negatif": {"type": "price", "field": "close", "lag": -1},
    "champ de prix inconnu": {"type": "price", "field": "vwap"},
    "operandes vides": {"type": "all_of", "operands": []},
    "enfant mal forme": {"type": "not", "inner": 3},
    "constante textuelle": {"type": "constant", "value": "beaucoup"},
    "erreur en profondeur": {
        "type": "not",
        "inner": {"type": "not", "inner": {"type": "constant", "value": "texte"}},
    },
    "bars nul": {"type": "lag", "bars": 0, "inner": {"type": "constant", "value": 1.0}},
}


class TestSchemaAndBuilderAgree:
    """La garantie qui compte : les deux refusent les memes choses."""

    @pytest.mark.parametrize("label", sorted(MALFORMED))
    def test_the_schema_refuses(self, validator: Draft202012Validator, label: str):
        assert not validator.is_valid(MALFORMED[label])

    @pytest.mark.parametrize("label", sorted(MALFORMED))
    def test_the_builder_refuses_too(self, label: str):
        with pytest.raises(Exception):  # noqa: B017, PT011
            build_signal(MALFORMED[label])

    def test_the_schema_catches_an_error_the_builder_would_only_see_at_run_time(
        self, validator: Draft202012Validator
    ):
        """L'interet du schema : refuser AVANT d'ouvrir un fichier de donnees."""
        assert not validator.is_valid({"type": "price", "field": "close", "lag": -5})


class TestFieldDeclarations:
    def test_every_node_declares_its_fields(self):
        """Un noeud sans champs declares publierait un schema qui ment par omission,
        et verrait ses propres champs refuses a la construction."""
        for node in list_node_types():
            assert node.fields, f"{node.name} ne declare aucun champ"
        assert [f.name for f in get_node_type("constant").fields] == ["value"]

    def test_a_node_field_renders_its_own_schema(self):
        assert NodeField("x", FieldKind.NODE).json_schema() == {"$ref": "#/$defs/node"}
        assert NodeField("xs", FieldKind.NODE_LIST).json_schema()["minItems"] == 1
        assert NodeField("n", FieldKind.INTEGER, minimum=0).json_schema()["minimum"] == 0
        assert NodeField("s", FieldKind.STRING, choices=("a", "b")).json_schema()["enum"] == [
            "a",
            "b",
        ]

    def test_optional_fields_are_not_required(self):
        price_schema = get_node_type("price").json_schema()
        assert price_schema["required"] == ["type"]

    def test_defaults_are_published(self):
        price_schema = get_node_type("price").json_schema()
        assert price_schema["properties"]["field"]["default"] == "close"  # type: ignore[index]


class TestStrategyAndSpecSchemas:
    def test_every_registered_strategy_publishes_its_parameters(self):
        for entry in describe_strategies():
            schema = entry["params"]
            assert isinstance(schema, dict)
            Draft202012Validator.check_schema(schema)

    def test_the_rules_strategy_exposes_its_rules_field(self):
        entry = next(e for e in describe_strategies() if e["ref"] == "rules@1")
        assert "rules" in entry["params"]["properties"]  # type: ignore[index]

    def test_the_backtest_specification_publishes_a_schema(self):
        schema = BacktestSpec.model_json_schema()
        Draft202012Validator.check_schema(schema)
        assert "execution" in schema["properties"]


class TestCli:
    def test_the_signal_schema_is_printed_and_parses(self, capsys):
        from rsl.cli import EXIT_OK, main

        assert main(["schema"]) == EXIT_OK
        Draft202012Validator.check_schema(json.loads(capsys.readouterr().out))

    @pytest.mark.parametrize("what", ["signals", "strategies", "spec", "all"])
    def test_every_section_parses(self, what, capsys):
        from rsl.cli import EXIT_OK, main

        assert main(["schema", "--what", what]) == EXIT_OK
        json.loads(capsys.readouterr().out)

    def test_it_writes_to_a_file(self, tmp_path, capsys):
        from rsl.cli import EXIT_OK, main

        target = tmp_path / "sous" / "schema.json"
        assert main(["schema", "--out", str(target)]) == EXIT_OK
        Draft202012Validator.check_schema(json.loads(target.read_text(encoding="utf-8")))

    def test_the_all_section_bundles_the_three(self, capsys):
        from rsl.cli import main

        main(["schema", "--what", "all"])
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {"signals", "strategies", "backtest_spec"}


class TestExamplesValidate:
    """Les strategies versionnees doivent passer le schema qu'elles publient.

    Un schema qui refuserait les exemples du depot serait faux ; des exemples
    que le schema refuse seraient faux. On ne sait pas lequel des deux sans le
    verifier, et c'est tout l'objet de ce test.
    """

    @pytest.mark.parametrize("exemple", noms())
    def test_every_rule_of_every_example_validates(
        self, validator: Draft202012Validator, exemple: str
    ):
        from fixtures.exemples import strategie

        regles = strategie(exemple).strategy.params.get("rules")
        if not isinstance(regles, dict):
            pytest.skip("ce moule ne s'ecrit pas en regles nommees")
        for regle in regles.values():
            validator.validate(regle)


class TestCommittedSchemasStayInSync:
    """Les schemas versionnes dans `schemas/` ne doivent pas deriver du code.

    Un fichier de schema commite qui ne correspond plus au registre est le pire
    cas de tous : il a l'air officiel, un editeur le charge, une machine s'y
    fie, et il ment. Ce test le rattrape des qu'un noeud est ajoute sans que le
    fichier soit regenere.
    """

    SIGNALS = pathlib.Path("schemas/signals.schema.json")
    BUNDLE = pathlib.Path("schemas/rsl.schema.json")

    def test_the_signal_schema_file_matches_the_registry(self):
        if not self.SIGNALS.exists():
            pytest.skip("schema non publie")
        committed = json.loads(self.SIGNALS.read_text(encoding="utf-8"))
        assert committed == signal_json_schema(), (
            "schemas/signals.schema.json a derive du registre. "
            "Regenerer : rsl schema --out schemas/signals.schema.json"
        )

    def test_the_bundle_matches_too(self):
        if not self.BUNDLE.exists():
            pytest.skip("schema non publie")
        committed = json.loads(self.BUNDLE.read_text(encoding="utf-8"))
        assert committed["signals"] == signal_json_schema(), (
            "schemas/rsl.schema.json a derive du registre. "
            "Regenerer : rsl schema --what all --out schemas/rsl.schema.json"
        )
        assert set(committed) == {"signals", "strategies", "backtest_spec"}

    def test_the_committed_file_is_a_valid_schema(self):
        if not self.SIGNALS.exists():
            pytest.skip("schema non publie")
        Draft202012Validator.check_schema(
            json.loads(self.SIGNALS.read_text(encoding="utf-8"))
        )
