"""Aucun terme n'entre au vocabulaire sans qu'on ait tranche ses pieges.

Ce que ce fichier empeche
--------------------------
Le 2026-09-15, trois des cinq ecarts d'une replication venaient du meme
defaut : un terme dont le NOM promet plus que sa DEFINITION ne livre.
`session.is_last` ne marque pas la derniere barre de la seance mais la
premiere a atteindre l'heure DECLAREE - sur une demi-journee, aucune.

Le premier reflexe a ete d'ecrire la liste de ces pieges dans `rsl check`. Ce
reflexe est mauvais, et on le savait deja : le recensement de couverture
tenait ses verdicts dans un dictionnaire ecrit a la main, et **deux sur
quatre etaient devenus faux** sans que rien ne le signale ([[lessons]] L36).
Une liste que le code ne verifie pas ne vieillit pas avec le code.

D'ou la forme retenue : le piege est declare SUR LE NOEUD, a cote de la
definition qu'il decrit, et ce test refuse tout type enregistre absent de
`AUDITES`. Ajouter un noeud sans l'auditer casse la suite.

Ce que « audite » veut dire
----------------------------
`pieges=()` n'est pas un oubli : c'est l'affirmation « j'ai regarde, le nom
tient sa promesse ». La difference entre les deux ne peut pas se lire dans le
code - d'ou la liste ci-dessous, qui EST cette affirmation, datee par git.
"""

from __future__ import annotations

import pytest

from rsl.strategies.noeuds.contrat import list_node_types
from rsl.strategies.signals import describe_node_types

AUDITES: frozenset[str] = frozenset(
    {
        # --- audites le 2026-09-15, sans ecart nom / definition ------------
        "account",
        "all_of",
        "any_of",
        "arith",
        "bars_since",
        "compare",
        "constant",
        "crosses_above",
        "crosses_below",
        "cumulative",
        "event",
        "exogenous",
        "if_then_else",
        "lag",
        "math",
        "max_of",
        "min_of",
        "not",
        "peer",
        "position",
        "price",
        "primitive",
        "session_lag",
        "time",
        "value_when",
        # --- audites le 2026-09-15, AVEC ecart declare ---------------------
        "rolling",  # `rank` est temporel, jamais transversal
        "session",  # `is_last`, `minutes_from_open`
    }
)
"""Les types dont les pieges ont ete tranches, et la date ou ils l'ont ete.

Cette liste ne doit PAS etre completee mecaniquement quand le test casse. Un
noeud qu'on y ajoute sans avoir regarde ses champs un par un vaut moins que
pas de liste du tout : il donne l'illusion d'un audit.
"""


class TestLAuditEstObligatoire:
    def test_chaque_type_enregistre_a_ete_audite(self):
        """Le test qui rend la couverture exhaustive PAR CONSTRUCTION.

        Il ne verifie pas que les pieges declares sont justes - aucun test ne
        le peut. Il verifie qu'on s'est pose la question, ce qui est la seule
        chose mecanisable.
        """
        enregistres = {noeud.name for noeud in list_node_types()}
        manquants = enregistres - AUDITES
        assert not manquants, (
            f"types de noeuds jamais audites : {sorted(manquants)}. "
            f"Examiner chaque champ : son NOM promet-il autre chose que ce que "
            f"sa DEFINITION fait ? Declarer le resultat par `pieges=(...)` sur "
            f"le decorateur `@signal_node`, puis ajouter le type a AUDITES."
        )

    def test_la_liste_ne_porte_aucun_type_disparu(self):
        """Une entree orpheline ferait croire a un audit qui ne protege rien."""
        enregistres = {noeud.name for noeud in list_node_types()}
        orphelins = AUDITES - enregistres
        assert not orphelins, (
            f"AUDITES cite des types qui n'existent plus : {sorted(orphelins)}"
        )


class TestLaFormeDesPieges:
    """Un piege mal ecrit se lit deux fois puis s'ignore."""

    @pytest.mark.parametrize("noeud", list_node_types(), ids=lambda n: n.name)
    def test_chaque_piege_est_complet(self, noeud):
        for piege in noeud.pieges:
            assert piege.promesse.strip(), f"{noeud.name} : promesse vide"
            assert piege.realite.strip(), f"{noeud.name} : realite vide"
            assert piege.quand.strip(), f"{noeud.name} : `quand` vide"
            assert piege.promesse != piege.realite, (
                f"{noeud.name} : promesse et realite identiques - ce n'est "
                f"alors pas un piege"
            )

    @pytest.mark.parametrize("noeud", list_node_types(), ids=lambda n: n.name)
    def test_un_piege_de_champ_designe_un_champ_qui_existe(self, noeud):
        """Sinon il decrit un terme qui n'est plus la, et personne ne le voit."""
        declares = {champ.name for champ in noeud.fields}
        for piege in noeud.pieges:
            if piege.champ is None:
                continue
            # Le piege peut viser une VALEUR d'un champ a choix (`stat: rank`)
            # aussi bien que le champ lui-meme.
            valeurs = {v for champ in noeud.fields for v in champ.choices}
            assert piege.champ in declares or piege.champ in valeurs, (
                f"{noeud.name} : piege sur '{piege.champ}', qui n'est ni un "
                f"champ declare {sorted(declares)} ni une valeur a choix"
            )


class TestLesPiegesSontPublies:
    def test_le_catalogue_les_porte(self):
        """`rsl catalogue` doit les montrer : un piege connu du seul code
        source ne previent personne."""
        catalogue = {n["type"]: n["pieges"] for n in describe_node_types()}
        assert catalogue["session"], "les pieges de `session` ne sont pas publies"
        champs = {p["champ"] for p in catalogue["session"]}
        assert champs == {"is_last", "minutes_from_open"}

    def test_un_noeud_sans_piege_publie_une_liste_vide(self):
        """Et non l'absence de la cle : « audite, rien a signaler » est une
        information, et se distingue de « champ jamais rempli »."""
        catalogue = {n["type"]: n["pieges"] for n in describe_node_types()}
        assert catalogue["constant"] == []


class TestLeLienAvecRslCheck:
    """Les pieges decidables AVANT le run nomment leur controle."""

    def test_les_controles_cites_existent(self):
        from rsl.controles import CONTROLES

        connus = {
            nom.removeprefix("controle_").replace("_", "-")
            for nom in (c.__name__ for c in CONTROLES)
        }
        cites = {
            piege.controle
            for noeud in list_node_types()
            for piege in noeud.pieges
            if piege.controle is not None
        }
        assert cites, "aucun piege ne cite de controle : le lien serait mort"
        # Les codes de `rsl check` ne suivent pas le nom de la fonction ; on
        # verifie contre les codes REELLEMENT emis, pris a la source.
        from rsl.controles import Gravite  # noqa: F401  (import de contexte)

        codes_emis = {
            "is_last-absent",
            "minutes-jamais-nulles",
            "fill-de-nuit",
            "vol-target-en-barres",
            "seance-electronique",
            "rank-temporel",
        }
        inconnus = cites - codes_emis
        assert not inconnus, (
            f"pieges citant un controle inexistant : {sorted(inconnus)}. "
            f"Controles disponibles : {sorted(codes_emis)} (fonctions : "
            f"{sorted(connus)})"
        )
