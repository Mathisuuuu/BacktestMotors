"""Deux garanties du pipeline de run, faciles a perdre sans s'en apercevoir.

1. **Valider avant de lire.** Une specification fausse doit etre refusee sans
   qu'un octet de donnee ait ete lu. Mesure avant correction sur un univers de
   dix instruments : 6,1 s ; apres : 0,1 ms.
2. **Rapporter ce qu'on compte.** Les compteurs du moteur d'execution etaient
   incrementes puis jetes - `ExecutionStats.describe()` n'etait appele nulle
   part. Un ordre a limite jamais touche ne laissait aucune trace nommee.

Le test n° 1 n'a besoin d'AUCUNE donnee, et c'est ce qui le rend sur : il
pointe vers un fichier inexistant. Si la validation passe en premier, l'erreur
parle de la strategie ; si le chargement passe en premier, elle parle du
fichier. L'ordre des deux etapes se lit donc dans le message.
"""

from __future__ import annotations

import pytest

from rsl.config import BacktestSpec
from rsl.errors import RegistryError
from rsl.report import run_backtest


def specification(ref_primitive: str, **params: object) -> BacktestSpec:
    """Chemin de donnees volontairement inexistant."""
    return BacktestSpec.model_validate({
        "name": "fail-fast",
        "initial_cash": 100_000.0,
        "data": [{
            "root": "ES",
            "path": "/inexistant/jamais/ES_v0_1m.parquet",
            "granularity_minutes": 1,
        }],
        "execution": {
            "fees": {"kind": "zero"},
            "slippage": {"kind": "zero"},
            "lag_bars": 1,
        },
        "strategy": {
            "ref": "rules@1",
            "params": {
                "symbol": "ES.v.0", "quantity": 1,
                "rules": {"entry_long": {
                    "type": "primitive", "ref": ref_primitive, "params": dict(params),
                }},
            },
        },
    })


class TestValiderAvantDeLire:
    def test_une_primitive_inconnue_est_refusee_sans_toucher_aux_donnees(self):
        """Si le chargement passait en premier, l'erreur serait un
        `FileNotFoundError` sur un chemin qui n'existe pas."""
        with pytest.raises(RegistryError, match="primitive inconnue"):
            run_backtest(specification("nexiste_pas@1"))

    def test_le_message_enumere_ce_qui_existe(self):
        """Une erreur actionnable nomme les choix, elle ne dit pas seulement
        que le choix est faux."""
        with pytest.raises(RegistryError, match="sma"):
            run_backtest(specification("nexiste_pas@1"))

    def test_un_parametre_manquant_est_aussi_refuse_avant_lecture(self):
        """`sma@1` exige `window` : l'omission est attrapee au meme endroit,
        par le modele de parametres de la primitive."""
        with pytest.raises(ValueError, match=r"(?i)window"):
            run_backtest(specification("sma@1"))

    def test_une_specification_valide_atteint_bien_le_chargement(self):
        """Le pendant du precedent : la correction ne doit pas court-circuiter
        le chargement pour une specification correcte."""
        with pytest.raises((FileNotFoundError, OSError)):
            run_backtest(specification("sma@1", window=20))


class TestStatistiquesDExecutionRapportees:
    def test_le_bloc_existe_dans_la_description_d_un_run(self):
        from rsl.engine.runner import RunResult

        assert "execution_stats" in RunResult.__dataclass_fields__

    def test_il_est_separe_des_compteurs(self):
        """`counters` entre dans l'empreinte de resultat. Y fusionner les
        statistiques d'execution changerait l'empreinte de tous les runs deja
        archives, pour une information qui decrit le MOTEUR et non la decision.

        Ce test garde cette separation : la fusionner casserait la
        rejouabilite sans qu'aucun autre test ne s'en apercoive.
        """
        from rsl.engine.runner import RunCounters

        champs = set(RunCounters.__dataclass_fields__)
        assert not {"n_limit_not_touched", "n_stop_not_triggered"} & champs

    def test_les_deux_runners_le_portent(self):
        """Un run transversal doit diagnostiquer aussi bien qu'un mono."""
        from rsl.engine.cross_sectional import CrossSectionalRunResult
        from rsl.engine.runner import RunResult

        for classe in (RunResult, CrossSectionalRunResult):
            assert "execution_stats" in classe.__dataclass_fields__, classe.__name__
