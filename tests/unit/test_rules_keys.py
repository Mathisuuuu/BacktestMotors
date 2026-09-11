"""`RULE_KEYS` : une seule liste de cles de `rules`, et ce qu'elle garantit.

Elles etaient enumerees a la main en quatre endroits - champs de la classe,
`warmup_bars`, `describe()`, `from_spec` - plus une derivation de
contournement dans `rsl/skeleton.py`, qui construisait une strategie temoin
juste pour lire les cles de son descripteur.

Ajouter une dixieme regle demandait donc quatre modifications coordonnees, et
en oublier une echoue EN SILENCE. Ce fichier fixe les trois consequences.
"""

from __future__ import annotations

from dataclasses import fields

import pytest
from jsonschema import Draft202012Validator

from rsl.errors import ConfigurationError
from rsl.skeleton import build_skeleton
from rsl.strategies.base import describe_strategies
from rsl.strategies.rules import RULE_KEYS, RuleStrategy
from rsl.strategies.signals import const

ATTENDUES = [
    "entry_long", "exit_long", "entry_short", "exit_short",
    "stop_loss", "take_profit", "entry_limit", "entry_stop", "exit_quantity",
]


def temoin(**regles: object) -> RuleStrategy:
    return RuleStrategy.from_spec({"symbol": "X", "quantity": 1, "rules": regles})


UNE_ENTREE = {"entry_long": {"type": "constant", "value": 1.0}}


def schema_de(ref: str) -> dict[str, object]:
    entree = next(e for e in describe_strategies() if e["ref"] == ref)
    schema = entree["params"]
    assert isinstance(schema, dict)
    return schema


@pytest.fixture(scope="module")
def valideur() -> Draft202012Validator:
    schema = schema_de("rules@1")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


class TestLaListe:
    def test_elle_est_celle_qu_on_croit(self):
        """La derivation lit l'annotation ecrite (`Signal | None`). Ce test
        existe pour qu'un champ de ce type ajoute un jour sans etre une regle
        ne s'y glisse pas sans qu'on le voie."""
        assert list(RULE_KEYS) == ATTENDUES

    def test_elle_suit_l_ordre_des_champs(self):
        declares = [c.name for c in fields(RuleStrategy) if c.type == "Signal | None"]
        assert list(RULE_KEYS) == declares

    def test_chaque_cle_est_un_champ_facultatif(self):
        """Une regle non declaree ne declenche rien : c'est ce qui rend toutes
        les cles facultatives, et `from_spec` uniforme."""
        par_nom = {c.name: c for c in fields(RuleStrategy)}
        for cle in RULE_KEYS:
            assert par_nom[cle].default is None, cle


class TestLesTroisConsommateurs:
    """Un oubli dans l'un des trois etait invisible. Ils lisent la meme liste."""

    def test_describe_publie_exactement_ces_cles(self):
        assert list(temoin(**UNE_ENTREE).describe()["rules"]) == list(RULE_KEYS)

    def test_le_warmup_compte_chaque_regle(self):
        """Une regle oubliee dans `warmup_bars` ferait lire son indicateur
        avant qu'il soit defini. On declare la regle la plus exigeante sur
        CHAQUE cle tour a tour, et le warmup doit la voir a chaque fois."""
        profond = {"type": "rolling", "stat": "mean", "window": 77,
                   "inner": {"type": "price", "field": "close"}}
        for cle in RULE_KEYS:
            regles = {**UNE_ENTREE, cle: profond}
            assert temoin(**regles).warmup_bars == 77, cle

    def test_le_squelette_publie_la_meme_liste(self):
        """`rsl squelette` est le document qu'une machine lit pour ecrire une
        specification : une cle absente ici est une cle qui n'existe pas."""
        assert build_skeleton()["cles_de_rules"] == list(RULE_KEYS)


class TestCleInconnue:
    """Le trou que la source unique permet enfin de boucher.

    `rules` est un `dict[str, object]` : pydantic n'y applique pas
    `extra="forbid"`, parce que son contenu est valide par `build_signal` et
    non par un schema fige. Une cle mal orthographiee etait donc IGNOREE, et
    la strategie tournait sans la regle qu'on croyait lui avoir donnee.
    """

    def test_une_faute_de_frappe_est_refusee(self):
        with pytest.raises(ConfigurationError, match="exit_lng"):
            temoin(**UNE_ENTREE, exit_lng={"type": "constant", "value": 1.0})

    def test_le_message_enumere_les_cles_acceptees(self):
        with pytest.raises(ConfigurationError, match="entry_long"):
            temoin(**UNE_ENTREE, nimporte_quoi={"type": "constant", "value": 1.0})

    def test_le_cas_qui_passait_en_silence(self):
        """Avant : cette specification donnait une strategie qui entre mais ne
        sort JAMAIS - un backtest faux, sans une ligne d'avertissement."""
        with pytest.raises(ConfigurationError):
            temoin(
                entry_long={"type": "constant", "value": 1.0},
                exit_lon={"type": "constant", "value": 1.0},
            )

    @pytest.mark.parametrize("exclusive", ["entry_limit", "entry_stop"])
    def test_les_cles_valides_passent_toutes(self, exclusive):
        """Toutes sauf l'autre membre de la paire exclusive : `entry_limit` et
        `entry_stop` ne peuvent pas coexister - un ordre a un seul type."""
        niveau = {"type": "price", "field": "close"}
        autre = {"entry_limit", "entry_stop"} - {exclusive}
        cles = [c for c in RULE_KEYS if c not in autre]
        assert temoin(**dict.fromkeys(cles, niveau)) is not None


class TestAucunChangementDeComportement:
    def test_une_regle_absente_reste_absente_et_non_une_erreur(self):
        assert temoin(**UNE_ENTREE).exit_long is None

    def test_le_descripteur_garde_son_ordre_historique(self):
        """Cet ordre part dans le rapport de run et dans le squelette : le
        changer changerait la sortie sans changer un comportement."""
        assert list(temoin(**UNE_ENTREE).describe()["rules"]) == ATTENDUES

    def test_construire_en_direct_reste_possible(self):
        """`RULE_KEYS` sert a `from_spec`, pas au constructeur : le code qui
        instancie la classe a la main n'est pas touche."""
        assert RuleStrategy(symbol="X", quantity=1, entry_long=const(1.0)) is not None


class TestLeSchemaPublieLaMemeContrainte:
    """Le schema engendre et `from_spec` doivent refuser LES MEMES choses.

    Principe pose par `test_schema_publication.py` : un schema plus permissif
    que le constructeur laisse passer des specifications qui exploseront a
    l'execution. `rules` annoncait `additionalProperties: true` - donc
    n'importe quelle cle - alors que `from_spec` les refuse desormais. Un
    editeur validant contre le schema publie aurait dit « valide ».
    """

    def parametres(self, **regles: object) -> dict[str, object]:
        return {"symbol": "X", "quantity": 1, "rules": regles}

    def test_le_schema_enumere_les_cles(self):
        noms = schema_de("rules@1")["properties"]["rules"]["propertyNames"]
        assert noms == {"enum": list(RULE_KEYS)}

    def test_les_deux_acceptent_une_cle_valide(self, valideur):
        params = self.parametres(**UNE_ENTREE)
        assert valideur.is_valid(params)
        assert RuleStrategy.from_spec(params) is not None

    def test_les_deux_refusent_une_cle_inconnue(self, valideur):
        params = self.parametres(**UNE_ENTREE, exit_lng={"type": "constant",
                                                         "value": 1.0})
        assert not valideur.is_valid(params)
        with pytest.raises(ConfigurationError):
            RuleStrategy.from_spec(params)

    def test_panel_rules_porte_la_meme_contrainte(self):
        """Il enveloppe `RuleStrategy` et partage son modele de parametres :
        une divergence ici voudrait dire que le partage a ete rompu."""
        noms = schema_de("panel_rules@1")["properties"]["rules"]["propertyNames"]
        assert noms == {"enum": list(RULE_KEYS)}
