"""La table des contrats, et le chemin de leurs donnees.

Depuis le 2026-09-12, `InstrumentSpec` porte une classe d'actif et en derive
`data_path`. Avant, l'arborescence etait recopiee dans `gui/montage.py` - une
seconde source, qu'un instrument range ailleurs ou simplement oublie aurait
fait mentir sans prevenir.

Ce que ce fichier garde
-----------------------
1. **Chaque contrat de la table a une classe.** Un instrument ajoute demain
   sans classe n'aurait pas de chemin, et l'echec tomberait au moment du run
   plutot qu'ici.
2. **Un instrument SYNTHETIQUE n'a pas de chemin, et le dit.** Il n'existe sur
   aucun disque ; rendre un chemin plausible serait pire qu'un refus.
3. **La convention de nommage est ecrite une seule fois.** Ce test la constate
   plutot que de la reecrire - le reecrire ici en ferait une troisieme source.
"""

from __future__ import annotations

import pytest

from rsl.data.instruments import INSTRUMENTS, get_instrument, known_roots
from rsl.data.schema import AssetClass, InstrumentSpec
from rsl.errors import ConfigurationError


class TestChaqueContratEstClasse:
    @pytest.mark.parametrize("racine", sorted(known_roots()))
    def test_il_a_une_classe_d_actif(self, racine: str):
        """Sans elle, pas de chemin - et l'echec tomberait au run."""
        assert get_instrument(racine).category is not None

    @pytest.mark.parametrize("racine", sorted(known_roots()))
    def test_et_donc_un_chemin(self, racine: str):
        chemin = get_instrument(racine).data_path
        assert chemin.endswith(".parquet")
        assert racine in chemin

    def test_les_quatre_classes_sont_toutes_employees(self):
        """Une classe declaree que personne n'utilise est une classe qu'on ne
        saurait pas verifier."""
        employees = {spec.category for spec in INSTRUMENTS.values()}
        assert employees == set(AssetClass)


class TestLeCheminEstUtilisable:
    @pytest.mark.parametrize("racine", sorted(known_roots()))
    def test_il_est_relatif(self, racine: str):
        """Un chemin absolu ferait diverger le `config_hash` entre deux
        machines - le defaut corrige le 2026-09-10."""
        from pathlib import Path

        chemin = get_instrument(racine).data_path
        assert not Path(chemin).is_absolute()
        assert "\\" not in chemin, "un chemin canonique est en POSIX"

    @pytest.mark.parametrize("racine", sorted(known_roots()))
    def test_le_dossier_est_la_classe_d_actif(self, racine: str):
        """La convention, constatee et non reecrite : la reecrire ici en ferait
        une troisieme source."""
        spec = get_instrument(racine)
        assert spec.category is not None
        assert spec.data_path.startswith(spec.category.value + "/")


class TestUnInstrumentSynthetiqueNAPasDeChemin:
    """La distinction qui compte : « je n'en ai pas » n'est pas « en voici un »."""

    def synthetique(self) -> InstrumentSpec:
        return InstrumentSpec(
            symbol="TEST.v.0", root="TEST", name="Instrument de test",
            exchange="CME", currency="USD", multiplier=50.0, tick_size=0.25,
            commission_per_contract=0.0, exchange_fee_per_contract=0.0,
            initial_margin=10_000.0, maintenance_margin=9_000.0,
        )

    def test_sa_classe_est_absente_par_defaut(self):
        """Et ce n'est pas un oubli : lui en inventer une laisserait croire
        qu'il a un fichier."""
        assert self.synthetique().category is None

    def test_demander_son_chemin_leve(self):
        with pytest.raises(ConfigurationError, match="synthetique"):
            _ = self.synthetique().data_path

    def test_le_message_dit_pourquoi(self):
        with pytest.raises(ConfigurationError, match="pire qu'un refus"):
            _ = self.synthetique().data_path

    def test_il_reste_utilisable_pour_tout_le_reste(self):
        """Le refus porte sur le chemin SEUL : un instrument synthetique doit
        continuer de servir aux tests du moteur."""
        spec = self.synthetique()
        assert spec.multiplier == 50.0
        assert spec.tick_size == 0.25
