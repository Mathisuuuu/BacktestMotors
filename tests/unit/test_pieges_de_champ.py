"""L'audit des pieges, etendu aux champs de SPECIFICATION.

Ce que ce fichier ferme
------------------------
`test_pieges.py` rend l'audit obligatoire pour les 27 types de NOEUDS. C'etait
la moitie du vocabulaire. L'autre moitie - ce qu'on ecrit dans `risk.sizing`,
`execution` et `data[]` - n'etait couverte par rien, et c'est pourtant la que
vit le piege qui a fait ecarter `vol_target` de la replication Zarattini le
2026-09-15 : **`vol_window` compte des BARRES**, donc sur du minute il mesure
une volatilite par minute, a un facteur vingt de ce qu'on croit ecrire.

Les modeles pydantic n'ont pas de decorateur ou declarer un piege. Ils passent
donc par le `json_schema_extra` de leur `Field`, ce qui garde la propriete qui
compte : **le piege vit a cote de la definition**, et bouge avec elle. Une
liste tenue ailleurs se perime sans prevenir ([[lessons]] L36).

Effet de bord voulu : les pieges entrent dans le JSON Schema publie. Un piege
connu du seul code source ne previent personne.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from rsl.config import DataSpec, ExecutionSpec, SizingSpec

MODELES: dict[str, type[BaseModel]] = {
    "risk.sizing": SizingSpec,
    "execution": ExecutionSpec,
    "data[]": DataSpec,
}

AUDITES: dict[str, frozenset[str]] = {
    # --- audites le 2026-09-15 ------------------------------------------
    "risk.sizing": frozenset(
        {
            "note",
            "kind",
            "contracts",  # BASE multipliee puis TRONQUEE sous `vol_target`
            "fraction",
            "atr_window",
            "atr_multiple",
            "vol_target",
            "vol_window",  # comptee en BARRES
            "vol_max_multiple",
            "signal",
            "max_contracts",
        }
    ),
    "execution": frozenset(
        {
            "note",
            "fees",
            "slippage",
            "lag_bars",
            "intrabar_priority",
            "max_fill_gap_seconds",
            "margin_policy",
            "intraday_margin_ratio",
        }
    ),
    "data[]": frozenset(
        {
            "note",
            "root",
            "path",
            "timestamp_column",
            "granularity_minutes",
            "resample",
            "resample_min_bars",
            "close_stamp",
            "max_gap_seconds",
            "allow_non_positive_prices",
            "session_only",  # sans lui, la seance court jusqu'au lendemain
            "session",
            "alias",
        }
    ),
}
"""Les champs dont les pieges ont ete tranches.

Ne PAS completer mecaniquement quand le test casse. Un champ qu'on y ajoute
sans avoir regarde ce que son nom promet vaut moins que pas de liste : il donne
l'illusion d'un audit.
"""


def piege_de(modele: type[BaseModel], champ: str) -> dict[str, object] | None:
    extra = modele.model_fields[champ].json_schema_extra
    if not isinstance(extra, dict):
        return None
    piege = extra.get("piege")
    return piege if isinstance(piege, dict) else None


class TestLAuditEstObligatoire:
    @pytest.mark.parametrize("nom", sorted(MODELES))
    def test_chaque_champ_a_ete_audite(self, nom: str):
        """Le test qui rend la couverture exhaustive PAR CONSTRUCTION.

        Il ne verifie pas que les pieges declares sont justes - aucun test ne
        le peut. Il verifie qu'on s'est pose la question pour chaque champ.
        """
        declares = set(MODELES[nom].model_fields)
        manquants = declares - AUDITES[nom]
        assert not manquants, (
            f"{nom} : champs jamais audites : {sorted(manquants)}. Pour chacun, "
            f"son NOM promet-il autre chose que ce que la SPECIFICATION en "
            f"fait ? Declarer le resultat par `json_schema_extra="
            f"piege_de_champ(...)` sur le `Field`, puis ajouter le champ a "
            f"AUDITES."
        )

    @pytest.mark.parametrize("nom", sorted(MODELES))
    def test_la_liste_ne_porte_aucun_champ_disparu(self, nom: str):
        """Une entree orpheline ferait croire a un audit qui ne protege rien."""
        orphelins = AUDITES[nom] - set(MODELES[nom].model_fields)
        assert not orphelins, f"{nom} : champs disparus : {sorted(orphelins)}"


class TestLesTroisPiegesConnus:
    """Chacun trace une erreur DATEE. La regle de [[lessons]] L37 : un controle
    sans trace decrit une peur, pas un fait."""

    def test_vol_window_compte_des_barres(self):
        piege = piege_de(SizingSpec, "vol_window")
        assert piege is not None, "le piege qui a fait ecarter `vol_target`"
        assert "BARRES" in str(piege["realite"])
        assert piege["controle"] == "vol-target-en-barres"

    def test_session_only_absent_laisse_la_nuit_entrer(self):
        piege = piege_de(DataSpec, "session_only")
        assert piege is not None
        assert "548" in str(piege["quand"]), "les seances de dimanche mesurees"
        assert piege["controle"] == "seance-electronique"

    def test_contracts_est_une_base_tronquee_sous_vol_target(self):
        piege = piege_de(SizingSpec, "contracts")
        assert piege is not None
        assert "TRONQUE" in str(piege["realite"])
        # Celui-ci n'a PAS de controle : il depend d'une valeur calculee au
        # run, donc indecidable depuis la specification seule.
        assert piege["controle"] is None


class TestLaFormeDesPieges:
    @pytest.mark.parametrize("nom", sorted(MODELES))
    def test_chaque_piege_declare_est_complet(self, nom: str):
        modele = MODELES[nom]
        for champ in modele.model_fields:
            piege = piege_de(modele, champ)
            if piege is None:
                continue
            for cle in ("promesse", "realite", "quand"):
                assert str(piege.get(cle, "")).strip(), f"{nom}.{champ} : {cle} vide"
            assert piege["promesse"] != piege["realite"], (
                f"{nom}.{champ} : promesse et realite identiques - ce n'est "
                f"alors pas un piege"
            )

    @pytest.mark.parametrize("nom", sorted(MODELES))
    def test_un_controle_cite_existe(self, nom: str):
        codes = {
            "is_last-absent",
            "minutes-jamais-nulles",
            "fill-de-nuit",
            "vol-target-en-barres",
            "seance-electronique",
            "rank-temporel",
        }
        modele = MODELES[nom]
        for champ in modele.model_fields:
            piege = piege_de(modele, champ)
            if piege is None or piege.get("controle") is None:
                continue
            assert piege["controle"] in codes, (
                f"{nom}.{champ} cite un controle inexistant : {piege['controle']}"
            )


class TestLesPiegesSontPublies:
    def test_le_json_schema_les_porte(self):
        """Le schema est ce que lit une machine qui ecrit une specification.
        Un piege absent du schema ne previent que ceux qui lisent le code."""
        schema = SizingSpec.model_json_schema()
        champ = schema["properties"]["vol_window"]
        assert "piege" in champ, "le piege n'a pas suivi jusqu'au schema publie"
        assert "BARRES" in str(champ["piege"]["realite"])

    def test_un_champ_sans_piege_n_en_publie_pas(self):
        """« Audite, rien a signaler » ne doit pas ressembler a un piege vide."""
        schema = SizingSpec.model_json_schema()
        assert "piege" not in schema["properties"]["atr_window"]
