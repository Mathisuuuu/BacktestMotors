"""Separer la STRATEGIE de son montage, sans relacher la reproductibilite.

Une `BacktestSpec` melangeait deux choses de nature differente : la decision
(`strategy`) et le montage (`data`, `initial_cash`, `execution`, `risk`). Une
meme strategie appliquee a ES et a NQ demandait donc deux fichiers presque
identiques, et rien ne disait lequel des deux mots avait change.

Depuis le 2026-09-12, un fichier de strategie ne porte que la decision. Le
reste se choisit au moment du run - dans la fenetre, ou par
`rsl run --settings`.

Les deux garanties que ce fichier verrouille
---------------------------------------------
1. **Le `config_hash` couvre toujours le TOUT.** C'est le point non
   negociable : deux runs de la meme strategie avec des capitaux differents
   sont deux runs differents. La separation est une commodite d'ecriture,
   jamais un relachement de la reproductibilite.
2. **La composition reproduit la specification complete au bit pres.** Sinon
   les deux chemins d'ecriture donneraient deux backtests, et il faudrait
   savoir lequel croire.
"""

from __future__ import annotations

import json

import pytest

from fixtures.exemples import attendues, montage, noms, specification, strategie
from rsl.composition import (
    FORMAT,
    StrategyFile,
    attend_un_symbole,
    compose,
    est_fichier_de_strategie,
)
from rsl.errors import ConfigurationError
from rsl.manifest import canonical_hash

STRATEGIE: dict[str, object] = {
    "format": FORMAT,
    "name": "sma-croisement",
    "strategy": {
        "ref": "rules@1",
        "params": {
            "quantity": 1,
            "rules": {
                "entry_long": {
                    "type": "crosses_above",
                    "fast": {"type": "primitive", "ref": "sma@1", "params": {"window": 20}},
                    "slow": {"type": "primitive", "ref": "sma@1", "params": {"window": 50}},
                }
            },
        },
    },
}


def reglages(root: str = "ES", capital: float = 1_000_000.0, ticks: float = 1.0):
    return {
        "initial_cash": capital,
        "data": [{"root": root, "path": f"indices/{root}_v0_1m.parquet",
                  "resample": "day", "resample_min_bars": 200}],
        "execution": {"fees": {"kind": "per_contract"},
                      "slippage": {"kind": "tick", "ticks": ticks}},
        "risk": {"sizing": {"kind": "fixed", "contracts": 1}},
    }


def fichier(**ajouts: object) -> StrategyFile:
    return StrategyFile.model_validate({**STRATEGIE, **ajouts})


def hache(spec) -> str:
    return canonical_hash(spec.canonical())


class TestLeHashCouvreLesDeuxMoities:
    """La garantie non negociable."""

    def test_deux_compositions_identiques_donnent_le_meme_hash(self):
        un = compose(fichier(), reglages(), symbol="ES.v.0")
        deux = compose(fichier(), reglages(), symbol="ES.v.0")
        assert hache(un) == hache(deux)

    @pytest.mark.parametrize(("quoi", "autres"), [
        ("l'actif", {"root": "NQ"}),
        ("le capital", {"capital": 500_000.0}),
        ("le glissement", {"ticks": 2.0}),
    ])
    def test_changer_le_montage_change_le_hash(self, quoi, autres):
        """Sans cela, deux runs differents se confondraient dans les archives."""
        base = compose(fichier(), reglages(), symbol="ES.v.0")
        symbole = "NQ.v.0" if autres.get("root") == "NQ" else "ES.v.0"
        autre = compose(fichier(), reglages(**autres), symbol=symbole)
        assert hache(base) != hache(autre), quoi

    def test_changer_la_strategie_change_le_hash(self):
        modifiee = json.loads(json.dumps(STRATEGIE))
        regles = modifiee["strategy"]["params"]["rules"]["entry_long"]
        regles["fast"]["params"]["window"] = 21
        base = compose(fichier(), reglages(), symbol="ES.v.0")
        autre = compose(StrategyFile.model_validate(modifiee), reglages(), symbol="ES.v.0")
        assert hache(base) != hache(autre)

    def test_le_nom_vient_de_la_strategie(self):
        spec = compose(fichier(name="autre-nom"), reglages(), symbol="ES.v.0")
        assert spec.name == "autre-nom"


class TestLaCompositionReproduitLaSpecComplete:
    """Les deux chemins d'ecriture doivent donner le MEME run."""

    @pytest.mark.parametrize("exemple", noms())
    def test_chaque_exemple_retrouve_son_config_hash_archive(self, exemple):
        """La garantie qui a remplace l'aller-retour, et qui vaut mieux.

        Jusqu'au 2026-09-12, `examples/` portait aussi les specifications
        COMPLETES, et ce test comparait la composition a l'une d'elles. Elles
        ont ete supprimees - le fichier que l'on ecrit est une strategie.

        Comparer a une archive vaut mieux que comparer a un fichier voisin :
        `empreintes_attendues.json` porte le `config_hash` mesure AVANT la
        separation. Le retrouver prouve que recoller les deux morceaux redonne
        exactement le run d'origine, et pas seulement qu'ils sont coherents
        entre eux.

        Sans donnees reelles : un `config_hash` ne depend que de la
        specification.
        """
        assert canonical_hash(specification(exemple).canonical()) == (
            attendues()[exemple]["config_hash"]
        )

    @pytest.mark.parametrize("exemple", noms())
    def test_aucune_strategie_ne_nomme_son_actif(self, exemple):
        """Le point de la separation : un fichier qui nomme son instrument
        n'est pas applicable a un autre."""
        assert "symbol" not in strategie(exemple).strategy.params

    @pytest.mark.parametrize("exemple", noms())
    def test_aucun_montage_ne_porte_de_regle(self, exemple):
        reglage = montage(exemple)
        assert "strategy" not in reglage
        assert "name" not in reglage

    def test_le_symbole_est_bien_injecte(self):
        spec = compose(fichier(), reglages(), symbol="ES.v.0")
        assert spec.strategy.params["symbol"] == "ES.v.0"

    def test_le_fichier_de_strategie_ne_le_portait_pas(self):
        """C'est tout l'interet : la meme strategie s'applique ailleurs."""
        assert "symbol" not in STRATEGIE["strategy"]["params"]  # type: ignore[index]

    def test_la_meme_strategie_s_applique_a_un_autre_actif(self):
        nq = compose(fichier(), reglages(root="NQ"), symbol="NQ.v.0")
        assert nq.strategy.params["symbol"] == "NQ.v.0"
        assert nq.data[0].root == "NQ"


class TestQuiRecoitUnSymbole:
    """Lu sur le MODELE du moule, jamais sur une liste tenue a la main."""

    @pytest.mark.parametrize("ref", ["rules@1", "panel_rules@1", "buy_and_hold@1"])
    def test_les_moules_mono_instrument_en_attendent_un(self, ref):
        assert attend_un_symbole(ref)

    @pytest.mark.parametrize("ref", ["ranking@1", "multi_rules@1"])
    def test_les_moules_transversaux_non(self, ref):
        assert not attend_un_symbole(ref)

    def test_sans_symbole_un_moule_mono_instrument_refuse(self):
        with pytest.raises(ConfigurationError, match="UN instrument"):
            compose(fichier(), reglages())

    def test_avec_symbole_un_moule_transversal_refuse(self):
        """Se tromper d'instrument sur un classement d'univers ne doit pas
        s'ignorer : le silence ferait croire que le choix a ete pris en compte.
        """
        transversal = fichier(strategy={"ref": "ranking@1", "params": {
            "quantity": 1, "n_long": 2,
            "score": {"type": "primitive", "ref": "returns@1", "params": {"window": 20}},
        }})
        with pytest.raises(ConfigurationError, match="UNIVERS"):
            compose(transversal, reglages(), symbol="ES.v.0")

    def test_une_strategie_qui_nomme_deja_son_symbole_est_refusee(self):
        """Elle n'est alors pas applicable a un autre actif - ce qui est tout
        l'interet de la separation."""
        fige = json.loads(json.dumps(STRATEGIE))
        fige["strategy"]["params"]["symbol"] = "ES.v.0"
        with pytest.raises(ConfigurationError, match="Retirez-le"):
            compose(StrategyFile.model_validate(fige), reglages(), symbol="NQ.v.0")


class TestLesDeuxMoitiesNeSeRecouvrentPas:
    @pytest.mark.parametrize("interdit", ["name", "strategy"])
    def test_les_reglages_ne_peuvent_pas_redeclarer_la_strategie(self, interdit):
        """Deux sources pour la meme chose, c'est une divergence en attente."""
        with pytest.raises(ConfigurationError, match=interdit):
            compose(fichier(), {**reglages(), interdit: "quoi que ce soit"},
                    symbol="ES.v.0")

    def test_un_reglage_inconnu_est_refuse_par_la_specification(self):
        """`compose` ne redeclare aucun champ : c'est le meme `extra=forbid`
        que partout ailleurs qui attrape la coquille."""
        with pytest.raises(ValueError, match=r"(?i)extra"):
            compose(fichier(), {**reglages(), "capitale": 1.0}, symbol="ES.v.0")

    def test_un_champ_de_montage_dans_la_strategie_est_refuse(self):
        with pytest.raises(ValueError, match=r"(?i)extra"):
            StrategyFile.model_validate({**STRATEGIE, "initial_cash": 1.0})


class TestReconnaitreLeFormat:
    """Au MARQUEUR, jamais d'apres les champs presents.

    Deviner marcherait presque toujours, et c'est le « presque » qui coute.
    """

    def test_un_fichier_de_strategie_est_reconnu(self):
        assert est_fichier_de_strategie(STRATEGIE)

    def test_une_specification_complete_ne_l_est_pas(self):
        """Une specification complete reste lisible - `rsl run` l'accepte
        toujours - elle n'est simplement plus ce qu'on ECRIT."""
        complet = {**reglages(), "name": "x", "strategy": STRATEGIE["strategy"]}
        assert not est_fichier_de_strategie(complet)

    def test_un_format_inconnu_est_refuse(self):
        with pytest.raises(ValueError, match=r"(?i)format|literal"):
            StrategyFile.model_validate({**STRATEGIE, "format": "rsl-strategy@2"})

    def test_le_format_est_obligatoire(self):
        sans = {k: v for k, v in STRATEGIE.items() if k != "format"}
        with pytest.raises(ValueError, match=r"(?i)format|missing|required"):
            StrategyFile.model_validate(sans)


class TestLaStrategieEstPauvre:
    """Elle ne porte QUE la decision : c'est ce qui la rend reutilisable."""

    def test_elle_ne_porte_que_la_decision(self):
        """Les deux champs en plus des trois du debut ne sont pas du montage.

        `note` dit POURQUOI, `definitions` evite de se repeter : tous deux
        `exclude=True`, donc absents du `config_hash`. Ni l'un ni l'autre ne
        decrit sur quoi la strategie tourne, ce qui est le critere.
        """
        assert set(StrategyFile.model_fields) == {
            "format", "name", "strategy", "note", "definitions",
        }

    @pytest.mark.parametrize("montage", [
        "initial_cash", "data", "execution", "risk", "seed", "stop",
    ])
    def test_aucun_champ_de_montage_n_y_figure(self, montage):
        assert montage not in StrategyFile.model_fields

    def test_elle_accepte_des_definitions(self):
        """Factoriser une grandeur fait partie de l'ECRITURE de la decision."""
        strategie = StrategyFile.model_validate({
            **STRATEGIE,
            "definitions": {"vingt": {"type": "constant", "value": 20.0}},
            "strategy": {
                "ref": "rules@1",
                "params": {
                    "symbol": None,
                    "quantity": 1,
                    "rules": {
                        "entry_long": {
                            "type": "compare", "op": ">",
                            "left": {"type": "price", "field": "close"},
                            "right": {"$ref": "vingt"},
                        }
                    },
                },
            },
        })
        regle = strategie.strategy.params["rules"]["entry_long"]
        assert regle["right"] == {"type": "constant", "value": 20.0}

    def test_elle_accepte_une_note(self):
        """Un `note` reste possible : dire pourquoi fait partie de la decision."""
        assert fichier(note="croisement 20/50, convention du papier").note is not None
