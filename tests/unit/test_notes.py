"""Le champ `note` : dire POURQUOI, sans changer ce qui est mesure.

Pourquoi il existe
------------------
JSON n'a pas de commentaires. Une specification declarait `-1.5` et `120` sans
pouvoir dire d'ou ils viennent, et `extra="forbid"` interdisait meme d'ajouter
un champ pour le faire.

C'est le seul manque reel de JSON face a YAML, mesure le 2026-09-12 : le reste
du proces ne tenait pas ici. Les modeles stricts attrapent les coercions de
YAML (`17:00` -> `1020`, `NO` -> `False` sont refuses), et cinq des dix
operateurs du vocabulaire entrent en collision avec sa syntaxe - `>` devient
meme la chaine vide SANS erreur.

Les trois proprietes que ce fichier garde
-----------------------------------------
1. **Une note ne change aucun chiffre.** Ni le `config_hash`, ni l'empreinte
   de resultat. Corriger une faute de frappe dans un commentaire ne doit pas
   rendre un run incomparable a un run archive.
2. **Elle n'est pas une porte ouverte.** `extra="forbid"` reste entier : une
   coquille est toujours une erreur. Seul `note` passe, et sa FORME est
   verifiee.
3. **Le schema publie et le code s'accordent.** Un schema plus strict que le
   constructeur ferait signaler une erreur la ou il n'y en a pas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from rsl.config import BacktestSpec
from rsl.errors import ConfigurationError
from rsl.manifest import canonical_hash
from rsl.skeleton import build_skeleton
from rsl.strategies.signals import build_signal, signal_json_schema

BASE = json.loads(Path("examples/sma_es_daily.json").read_text(encoding="utf-8"))

UNE_NOTE = "seuil a 20 parce que c'est la convention du papier d'origine"
PLUSIEURS = ["premiere ligne", "seconde ligne", "troisieme"]


def spec(**ajouts: object) -> BacktestSpec:
    return BacktestSpec.model_validate({**BASE, **ajouts})


@pytest.fixture(scope="module")
def valideur() -> Draft202012Validator:
    schema = signal_json_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def squelette() -> dict[str, object]:
    return build_skeleton()


class TestUneNoteNeChangeAucunChiffre:
    """La garantie centrale, et la raison du `exclude=True`."""

    @pytest.mark.parametrize("valeur", [UNE_NOTE, PLUSIEURS])
    def test_le_config_hash_est_inchange(self, valeur):
        assert canonical_hash(spec().canonical()) == canonical_hash(
            spec(note=valeur).canonical()
        )

    def test_deux_notes_differentes_donnent_le_meme_hash(self):
        """Le cas qui compte en pratique : reformuler un commentaire ne doit
        pas rendre un run incomparable a celui d'hier."""
        assert canonical_hash(spec(note="version A").canonical()) == canonical_hash(
            spec(note="version B").canonical()
        )

    def test_la_note_n_apparait_pas_dans_la_forme_canonique(self):
        """`canonical()` est ce qui est hache ET ce qui part dans le rapport :
        une note y figurerait comme si elle avait gouverne le calcul."""
        assert "note" not in spec(note=UNE_NOTE).canonical()

    def test_mais_elle_reste_lisible_sur_l_objet(self):
        """Exclue de la serialisation, pas de la specification : un outil qui
        voudrait afficher les notes doit pouvoir les lire."""
        assert spec(note=PLUSIEURS).note == PLUSIEURS

    def test_un_noeud_annote_construit_le_meme_signal(self):
        arbre = {"type": "compare", "op": "<",
                 "left": {"type": "price", "field": "close"},
                 "right": {"type": "constant", "value": 10.0}}
        nu = build_signal(arbre)
        annote = build_signal({**arbre, "note": UNE_NOTE})
        assert nu.describe() == annote.describe()

    def test_la_note_d_un_noeud_ne_survit_pas_a_describe(self):
        """Un commentaire decrit l'INTENTION de qui a ecrit la specification ;
        le rapport decrit ce qui a TOURNE. Les deux ne se confondent pas."""
        noeud = build_signal({"type": "constant", "value": 1.0, "note": UNE_NOTE})
        assert "note" not in noeud.describe()


class TestOuLaNoteEstAcceptee:
    """Partout ou un humain ecrit un chiffre qu'il faudra expliquer."""

    def test_a_la_racine_de_la_specification(self):
        assert spec(note=UNE_NOTE) is not None

    def test_sur_un_bloc_de_donnees(self):
        entree = {**BASE["data"][0], "note": "reechantillonne en quotidien"}
        assert spec(data=[entree]) is not None

    def test_sur_les_parametres_d_une_strategie(self):
        strategie = {**BASE["strategy"]}
        strategie["params"] = {**strategie["params"], "note": "quantite a 1 pour ..."}
        assert spec(strategy=strategie) is not None

    @pytest.mark.parametrize("type_de_noeud", [
        {"type": "constant", "value": 1.0},
        {"type": "price", "field": "close"},
        {"type": "primitive", "ref": "sma@1", "params": {"window": 20}},
        {"type": "rolling", "stat": "mean", "window": 5,
         "inner": {"type": "price", "field": "close"}},
    ])
    def test_sur_n_importe_quel_noeud(self, type_de_noeud):
        assert build_signal({**type_de_noeud, "note": UNE_NOTE}) is not None

    def test_sur_un_noeud_profondement_imbrique(self):
        """C'est la que la note sert le plus : un seuil enfoui a la profondeur
        dix est celui dont on a le plus oublie la raison."""
        arbre = {
            "type": "compare", "op": "<", "note": "regle d'entree",
            "left": {"type": "rolling", "stat": "zscore", "window": 120,
                     "note": "120 jours ~ six mois de seances",
                     "inner": {"type": "price", "field": "close"}},
            "right": {"type": "constant", "value": -1.5, "note": "-1,5 ecart-type"},
        }
        assert build_signal(arbre) is not None


class TestCeQuiResteRefuse:
    """L'echappatoire ne doit pas devenir un trou."""

    def test_une_coquille_est_toujours_une_erreur(self):
        with pytest.raises(ConfigurationError, match="nte"):
            build_signal({"type": "constant", "value": 1.0, "nte": "coquille"})

    def test_un_champ_inconnu_sur_la_specification_aussi(self):
        with pytest.raises(ValueError, match=r"(?i)extra"):
            spec(nte="coquille")

    @pytest.mark.parametrize("mauvaise", [
        {"pourquoi": "un objet"},
        42,
        ["texte", 3],
        True,
    ])
    def test_une_note_mal_formee_est_refusee_sur_un_noeud(self, mauvaise):
        """Un champ qu'on ne valide pas du tout est un champ ou une coquille
        passe : `{"note": {"pourquoi": "..."}}` serait accepte en silence, et
        le jour ou quelqu'un affichera les notes il trouvera des formes
        inattendues."""
        with pytest.raises(ConfigurationError, match="note"):
            build_signal({"type": "constant", "value": 1.0, "note": mauvaise})

    @pytest.mark.parametrize("mauvaise", [{"a": 1}, 42, ["texte", 3]])
    def test_une_note_mal_formee_est_refusee_sur_la_specification(self, mauvaise):
        with pytest.raises(ValueError, match=r"(?i)note|valid"):
            spec(note=mauvaise)


class TestLeSchemaPublieEtLeCodeSAccordent:
    """Un schema plus STRICT que le constructeur signalerait une erreur la ou
    il n'y en a pas - le defaut symetrique de celui que `build_signal` evite.
    """

    def test_le_schema_accepte_une_note_textuelle(self, valideur):
        assert valideur.is_valid({"type": "constant", "value": 1.0, "note": UNE_NOTE})

    def test_le_schema_accepte_une_note_en_plusieurs_lignes(self, valideur):
        assert valideur.is_valid({"type": "constant", "value": 1.0, "note": PLUSIEURS})

    def test_le_schema_refuse_ce_que_le_code_refuse(self, valideur):
        assert not valideur.is_valid({"type": "constant", "value": 1.0, "note": 42})

    def test_le_schema_refuse_toujours_une_coquille(self, valideur):
        assert not valideur.is_valid({"type": "constant", "value": 1.0, "nte": "x"})


class TestCeQueLeSquelettePublie:
    """Une machine qui ecrit une specification doit savoir qu'elle peut
    s'expliquer - et ne pas avoir a lire vingt-deux fois la meme ligne."""

    def test_la_regle_est_dite_dans_les_contraintes(self, squelette):
        contraintes = " ".join(str(x) for x in squelette["contraintes"])
        assert "`note`" in contraintes
        assert "config_hash" in contraintes

    def test_elle_n_est_pas_repetee_sur_chaque_noeud(self, squelette):
        """Vingt-deux repetitions noieraient ce qui distingue un noeud d'un
        autre. La regle vaut pour tous : elle se dit une fois."""
        noeuds = squelette["noeuds"]
        assert isinstance(noeuds, dict)
        avec_note = [nom for nom, corps in noeuds.items() if "note" in corps["champs"]]
        assert avec_note == [], avec_note

    def test_ni_sur_chaque_bloc_de_la_specification(self, squelette):
        specification = squelette["specification"]
        assert isinstance(specification, dict)
        assert "note" not in specification


class TestUnExempleReelEstAnnote:
    """Sans cela, la fonctionnalite serait publiee et jamais exercee - le
    defaut de [[lessons]] L13, sous une forme plus benigne."""

    def test_paire_es_nq_porte_des_notes(self):
        spec_brute = json.loads(
            Path("examples/paire_es_nq.json").read_text(encoding="utf-8")
        )
        assert "note" in spec_brute
        regles = spec_brute["strategy"]["params"]["rules"]
        assert "note" in regles["entry_long"]

    def test_et_il_reste_valide(self):
        BacktestSpec.model_validate_json(
            Path("examples/paire_es_nq.json").read_text(encoding="utf-8")
        )

    def test_ses_notes_ne_figurent_pas_dans_sa_forme_canonique(self):
        """Le test qui a trouve le defaut : les notes de NOEUDS vivent dans
        `strategy.params.rules`, une region libre que `model_dump` recopie
        telle quelle. Elles entraient donc dans le `config_hash`
        (`c686c31f` -> `bf0f2f3f`), exactement la ou la garantie comptait le
        plus. `canonical()` les retire desormais a toute profondeur."""
        depuis = BacktestSpec.model_validate_json(
            Path("examples/paire_es_nq.json").read_text(encoding="utf-8")
        )
        assert "note" not in json.dumps(depuis.canonical())

    def test_son_config_hash_est_celui_d_avant_les_notes(self):
        """La verification decisive : annoter un exemple ne doit pas le rendre
        incomparable au run archive avant l'annotation."""
        archive = json.loads(
            Path("tests/fixtures/empreintes_attendues.json").read_text(encoding="utf-8")
        )["paire_es_nq.json"]["config_hash"]
        depuis = BacktestSpec.model_validate_json(
            Path("examples/paire_es_nq.json").read_text(encoding="utf-8")
        )
        assert canonical_hash(depuis.canonical()) == archive
