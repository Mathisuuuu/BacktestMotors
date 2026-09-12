"""La sortie de la CLI ne doit pas dependre de la machine qui l'execute.

Le defaut, mesure le 2026-09-12
--------------------------------
Sous Windows, `sys.stdout` prend l'encodage de la locale des qu'il est REDIRIGE.
`rsl schema --what all > contrat.json` ecrivait donc du `cp1252` : octet `0xa7`
la ou le texte porte un `§`, et plus aucun lecteur JSON n'ouvrait le fichier en
UTF-8. `--out` n'etait pas touche - il ouvre son fichier en UTF-8
explicitement - donc le defaut ne se voyait que par le chemin le plus naturel.

Pourquoi ces tests passent par un SOUS-PROCESSUS
------------------------------------------------
Parce que le defaut n'est pas dans le code appele, il est dans le flux de
sortie. Dans le processus de pytest, `sys.stdout` est un objet de capture deja
en UTF-8 : appeler `main()` en direct ne reproduit rien et passerait quoi qu'il
arrive.

`PYTHONIOENCODING=cp1252` impose la condition du defaut sur N'IMPORTE QUELLE
machine, y compris une chaine d'integration sous Linux. Sans cela, ces tests
seraient verts partout sauf la ou le probleme existe.

Ce que six commandes sur neuf cachaient
----------------------------------------
Avant la correction, trois commandes etaient cassees : `schema --what all`,
`--what spec` et `--what strategies`. Les six autres passaient parce que leur
sortie se trouvait etre purement ASCII - c'est-a-dire par chance, et jusqu'au
premier caractere accentue ajoute a une docstring.

Le compte lui-meme illustre le point : la premiere mesure n'en avait trouve
que deux, parce qu'elle avait oublie `--what spec`. D'ou le BALAYAGE ci-dessous
plutot que des tests cibles - ce qui doit etre garanti est la propriete, pas
l'inventaire des endroits ou elle est violee aujourd'hui.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]

COMMANDES: tuple[tuple[str, ...], ...] = (
    ("schema", "--what", "all"),
    ("schema", "--what", "signals"),
    ("schema", "--what", "strategies"),
    ("schema", "--what", "spec"),
    ("squelette",),
    ("catalogue",),
    ("example",),
    ("example", "--what", "settings"),
    ("instruments",),
)
"""Toutes les commandes qui ecrivent sur la sortie standard.

`run`, `walkforward` et `verify` en sont absentes : elles lisent des centaines
de Mo de donnees, et elles n'ecrivent rien qu'une autre commande de cette liste
n'ecrive deja."""


def lancer(*args: str, encodage: str = "cp1252") -> bytes:
    """Execute la CLI dans un interpreteur separe, sortie REDIRIGEE.

    Rend les octets bruts : les decoder ici supposerait deja connaitre la
    reponse a la question posee.
    """
    resultat = subprocess.run(
        [sys.executable, "-m", "rsl.cli", *args],
        capture_output=True, check=True, cwd=RACINE,
        env={**os.environ, "PYTHONIOENCODING": encodage},
    )
    return resultat.stdout


@pytest.fixture(scope="module")
def sorties() -> dict[tuple[str, ...], bytes]:
    """Chaque commande executee UNE fois pour tout le fichier.

    Neuf interpreteurs a demarrer, chacun important le registre complet : les
    relancer par test multiplierait le cout par le nombre d'assertions."""
    return {commande: lancer(*commande) for commande in COMMANDES}


@pytest.mark.parametrize("commande", COMMANDES, ids=lambda c: " ".join(c))
class TestTouteSortieEstDeLUtf8:
    def test_elle_se_decode_en_utf8(self, sorties, commande):
        """La propriete, sur toutes les commandes et pas seulement sur celles
        qui portent aujourd'hui un caractere accentue."""
        octets = sorties[commande]
        try:
            octets.decode("utf-8")
        except UnicodeDecodeError as erreur:  # pragma: no cover - le test echoue
            pytest.fail(
                f"sortie non-UTF-8 : octet {octets[erreur.start]:#04x} en "
                f"position {erreur.start}. La locale de la machine a fuit dans "
                f"le flux de sortie."
            )

    def test_et_ne_contient_aucun_caractere_de_remplacement(self, sorties, commande):
        """Un `?` ou un `�` a la place d'un caractere signalerait une
        degradation silencieuse - pire qu'une erreur, parce qu'un fichier
        degrade se lit."""
        texte = sorties[commande].decode("utf-8")
        assert "�" not in texte


class TestLesCommandesQuiPortaientLeDefaut:
    """Les trois qui saignaient reellement, nommees.

    Le balayage ci-dessus garantit la propriete ; celles-ci garantissent que le
    cas d'origine est bien celui qu'on a corrige, et pas un voisin.
    """

    def test_schema_all_porte_toujours_son_paragraphe(self, sorties):
        """`§` est l'octet `0xa7` en cp1252 : le caractere par lequel le defaut
        a ete trouve.

        L'assertion porte sur sa PRESENCE : s'il disparaissait du texte, un
        test qui se contenterait de verifier l'encodage deviendrait vert sans
        rien garantir."""
        assert "§" in sorties[("schema", "--what", "all")].decode("utf-8")

    def test_schema_strategies_porte_toujours_ses_guillemets(self, sorties):
        texte = sorties[("schema", "--what", "strategies")].decode("utf-8")
        assert "«" in texte and "»" in texte

    def test_schema_spec_aussi(self, sorties):
        """La troisieme, oubliee de la premiere mesure - c'est ce qui a fait
        ecrire « deux commandes » la ou il y en avait trois."""
        assert "§" in sorties[("schema", "--what", "spec")].decode("utf-8")


class TestLesDeuxChemminsDEcritureSAccordent:
    """`> fichier` et `--out fichier` doivent donner le meme contenu.

    Ils ne donnaient pas le meme : l'un passait par la locale, l'autre non.
    C'est ce desaccord qui rendait le defaut difficile a croire - le fichier
    « marchait » chez qui utilisait `--out`.
    """

    def test_le_json_est_identique(self, tmp_path: Path):
        redirige = lancer("schema", "--what", "all").decode("utf-8")
        fichier = tmp_path / "par_out.json"
        lancer("schema", "--what", "all", "--out", str(fichier))
        assert json.loads(redirige) == json.loads(fichier.read_text(encoding="utf-8"))

    def test_a_la_fin_de_ligne_pres_les_octets_aussi(self, tmp_path: Path):
        """Le seul ecart tolere est le saut de ligne final qu'ajoute `print`,
        qui est le comportement attendu d'une commande."""
        redirige = lancer("schema", "--what", "signals")
        fichier = tmp_path / "par_out.json"
        lancer("schema", "--what", "signals", "--out", str(fichier))
        ecrit = fichier.read_bytes()
        assert redirige.rstrip(b"\r\n") == ecrit.rstrip(b"\r\n")


class TestUnCaractereAbsentDeLaLocaleNeFaitPlusEchouer:
    """Le cas le plus grave, et celui qu'aucune donnee actuelle ne declenche.

    Un `§` produisait un fichier illisible. Un caractere ABSENT de cp1252 -
    une fleche, un `>=` typographique - ne se degradait pas : il levait
    `UnicodeEncodeError`, code de sortie 1, sortie tronquee en plein milieu.
    Verifie le 2026-09-12 AVANT la correction.

    Aucune docstring du depot n'en porte aujourd'hui. Ce test-ci fabrique donc
    la condition plutot que de l'attendre : c'est la seule facon de garder une
    propriete que les donnees actuelles n'exercent pas.
    """

    PROGRAMME = (
        "from rsl.cli import sortie_en_utf8;"
        "sortie_en_utf8();"
        "print('fleche \\u2192 superieur \\u2265')"
    )

    def lancer_avec(self, programme: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, "-c", programme],
            capture_output=True, check=False, cwd=RACINE,
            env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        )

    def test_sans_la_correction_la_sortie_echoue(self):
        """Le temoin. Sans lui, on ne saurait pas que la condition du defaut
        est bien reproduite, et le test suivant serait vert pour rien."""
        resultat = self.lancer_avec("print('fleche \\u2192')")
        assert resultat.returncode != 0
        assert b"UnicodeEncodeError" in resultat.stderr

    def test_avec_la_correction_elle_reussit(self):
        resultat = self.lancer_avec(self.PROGRAMME)
        assert resultat.returncode == 0, resultat.stderr.decode(errors="replace")
        assert "→" in resultat.stdout.decode("utf-8")

    def test_et_stderr_est_couvert_aussi(self):
        """Les messages d'erreur passent par `stderr`. Une erreur qui ne peut
        pas s'afficher est le pire moment pour decouvrir un probleme
        d'encodage."""
        resultat = self.lancer_avec(
            "import sys;"
            "from rsl.cli import sortie_en_utf8;"
            "sortie_en_utf8();"
            "print('erreur \\u2192', file=sys.stderr)"
        )
        assert resultat.returncode == 0
        assert "→" in resultat.stderr.decode("utf-8")


class TestLaFonctionEstSureLaOuElleEstAppelee:
    def test_elle_ne_leve_pas_quand_le_flux_n_est_pas_reconfigurable(self):
        """Sous pytest, `sys.stdout` est un objet de capture sans
        `reconfigure`. Une correction qui ferait tomber la suite de tests au
        premier appel de `main()` ne serait pas une correction."""
        from rsl.cli import sortie_en_utf8

        sortie_en_utf8()

    def test_main_l_appelle(self):
        """Sinon la correction dormirait : elle ne vaut que si elle est sur le
        chemin de CHAQUE commande."""
        import inspect

        from rsl.cli import main

        assert "sortie_en_utf8()" in inspect.getsource(main)
