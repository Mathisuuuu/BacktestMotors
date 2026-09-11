"""Bout en bout sur DONNEES REELLES : ce que la suite rapide ne peut pas voir.

La suite rapide tourne sur des series synthetiques. Elle verifie que le moteur
est juste ; elle ne peut pas verifier qu'un run complet - chargement,
resample, warmup, execution, comptabilite, metriques, manifeste - produit
encore ce qu'il produisait hier sur les 33 M de barres du depot.

Ce fichier comble ce trou. Il etait le seul point de l'audit A-P3 a porter un
RISQUE plutot qu'une dette de forme : jusqu'ici, la non-regression de bout en
bout etait verifiee **a la main**, en relancant les exemples et en comparant
les empreintes a l'oeil. Ce qui n'est pas verifie par une machine n'est pas
verifie.

Marque `slow` et saute si les cotations sont absentes - un collaborateur sans
les donnees doit pouvoir lancer `pytest` sans echec.

Lire `tests/fixtures/empreintes_attendues.json` avant de le modifier
--------------------------------------------------------------------
Ce fichier est la VERITE TERRAIN des sept exemples. Une empreinte qui change
signale l'une de deux choses, et il faut trancher laquelle AVANT de le
regenerer :

- un changement de comportement **voulu** - alors le regenerer fait partie du
  travail, et le commit doit dire pourquoi ;
- un changement de comportement **subi** - alors c'est le code qui a tort.

Le regenerer par reflexe pour faire passer la suite supprime la seule garde
qui distingue les deux cas.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rsl.config import BacktestSpec
from rsl.env import data_root
from rsl.manifest import canonical_hash
from rsl.primitives.registry import describe_registry
from rsl.report import run_backtest, run_backtest_detailed

_RACINE = data_root()
DONNEES = _RACINE if _RACINE is not None else Path("cotations-absentes")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not DONNEES.exists(), reason=f"donnees absentes : {DONNEES}"),
]

EXEMPLES = Path("examples")
ATTENDUES = json.loads(
    (Path(__file__).parent / "fixtures" / "empreintes_attendues.json").read_text(
        encoding="utf-8"
    )
)


def spec_de(nom: str) -> BacktestSpec:
    return BacktestSpec.model_validate_json(
        (EXEMPLES / nom).read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def rapports() -> dict[str, dict[str, object]]:
    """Chaque exemple execute UNE fois pour tout le fichier.

    Un run par test multiplierait par cinq une suite qui lit deja des
    centaines de Mo de parquet.
    """
    return {nom: run_backtest(spec_de(nom)).to_dict() for nom in sorted(ATTENDUES)}


@pytest.mark.parametrize("nom", sorted(ATTENDUES))
class TestNonRegressionDesExemples:
    """La garde centrale : les sept exemples doivent rendre les memes chiffres."""

    def test_l_empreinte_de_resultat_est_celle_archivee(self, rapports, nom):
        attendu = ATTENDUES[nom]["result_fingerprint"]
        obtenu = rapports[nom]["result_fingerprint"]
        assert obtenu == attendu, (
            f"{nom} : le resultat a change. Si c'est VOULU, regenerer "
            f"tests/fixtures/empreintes_attendues.json et dire pourquoi dans le "
            f"commit. Sinon, c'est le code qui a tort."
        )

    def test_le_hash_de_configuration_est_celui_archive(self, rapports, nom):
        """Distinct de l'empreinte de resultat : il ne depend QUE de la
        specification. Les deux qui bougent ensemble signalent un changement
        de spec ; l'empreinte seule, un changement de moteur."""
        manifeste = rapports[nom]["manifest"]
        assert isinstance(manifeste, dict)
        assert manifeste["config_hash"] == ATTENDUES[nom]["config_hash"]

    def test_le_nombre_de_trades_est_celui_archive(self, rapports, nom):
        """Redondant avec l'empreinte, et c'est voulu : quand elle change,
        celui-ci dit en un coup d'oeil si la strategie negocie differemment ou
        si seule la comptabilite a bouge."""
        metriques = rapports[nom]["metrics"]
        assert isinstance(metriques, dict)
        assert metriques["activity"]["n_trades"] == ATTENDUES[nom]["n_trades"]

    def test_le_run_est_declare_rejouable(self, rapports, nom):
        """`is_reproducible` est le champ que [[concepts/determinisme]] designe
        comme le seul qui compte. Il vaut `False` des qu'une source de donnees
        manque - ce qui est exactement ce qu'on veut savoir ici."""
        manifeste = rapports[nom]["manifest"]
        assert isinstance(manifeste, dict)
        assert manifeste["data_sources"], "aucune source enregistree"
        assert all(s["source_hash"] for s in manifeste["data_sources"])


class TestDeterminisme:
    """Deux executions de la meme specification donnent la meme empreinte.

    C'est ce que fait `rsl verify` ; le verifier ici garantit qu'il continue
    de le faire sur de VRAIES donnees, ou l'ordre de lecture, le resample et
    les trous jouent un role que le synthetique ne reproduit pas.
    """

    def test_deux_runs_du_meme_exemple_coincident(self):
        spec = spec_de("sma_es_daily.json")
        un, deux = run_backtest(spec), run_backtest(spec)
        assert un.result_fingerprint == deux.result_fingerprint

    def test_deux_specifications_identiques_ont_le_meme_config_hash(self):
        """Le hash porte sur `canonical()`, pas sur le texte du fichier : deux
        lectures du meme JSON doivent donner le meme, et deux JSON identiques a
        l'ordre des cles pres aussi."""
        un, deux = spec_de("sma_es_daily.json"), spec_de("sma_es_daily.json")
        assert canonical_hash(un.canonical()) == canonical_hash(deux.canonical())

    def test_le_config_hash_ne_depend_pas_du_chemin_absolu(self):
        """Le collaborateur n'a pas les donnees au meme endroit. Si le hash
        de configuration en dependait, deux machines ne pourraient jamais
        comparer un run - c'est le defaut corrige le 2026-09-11."""
        spec = spec_de("sma_es_daily.json")
        canonique = spec.data[0].canonical_path()
        assert not Path(canonique).is_absolute(), canonique
        assert "\\" not in canonique, "un chemin canonique est en POSIX"


class TestMemoisationSurDonneesReelles:
    """La memoisation ne doit rien changer, y compris la ou ca compte.

    Les tests synthetiques le verifient deja. Celui-ci le verifie sur les
    series reelles, dans un interpreteur SEPARE : `RSL_NO_MEMO` est lu a
    l'import, donc le basculer dans le processus courant ne ferait rien.
    """

    def test_sans_memoisation_l_empreinte_est_la_meme(self):
        nom = "retour_moyenne_dans_tendance.json"
        programme = (
            "import json;"
            "from pathlib import Path;"
            "from rsl.config import BacktestSpec;"
            "from rsl.report import run_backtest;"
            f"spec = BacktestSpec.model_validate_json(Path(r'{EXEMPLES / nom}')"
            ".read_text(encoding='utf-8'));"
            "print(run_backtest(spec).result_fingerprint)"
        )
        resultat = subprocess.run(
            [sys.executable, "-c", programme],
            capture_output=True, text=True, check=True,
            env={**os.environ, "RSL_NO_MEMO": "1"},
        )
        assert resultat.stdout.strip() == ATTENDUES[nom]["result_fingerprint"]


@pytest.fixture(scope="module")
def contexte_reel():
    """Derniere barre d'une vraie serie ES quotidienne."""
    from fixtures.registre import FENETRE
    from rsl.data.feed import BarContext

    artefacts = run_backtest_detailed(spec_de("sma_es_daily.json"))
    magasin = next(iter(artefacts.stores.values()))
    assert magasin.n_bars > 10 * FENETRE, "serie trop courte pour ce test"
    ctx = BarContext(magasin)
    ctx._seek(magasin.n_bars - 1)
    return ctx


class TestLesPrimitivesSurDesSeriesReelles:
    """Les 136 primitives, appliquees a une vraie serie.

    Le parcours du registre
    (`tests/adversarial/test_registre_primitives.py`) tourne sur du
    synthetique : marche aleatoire bien elevee, volumes tires d'une uniforme,
    aucun trou. Les series du depot ont des week-ends de 49 h, une coupure
    quotidienne, des volumes qui sautent au roulement et des barres reportees.

    Ce test ne verifie aucune VALEUR - il verifie qu'aucune primitive ne leve
    ni ne rend un NaN sur des donnees qui existent vraiment.
    """

    @pytest.mark.parametrize(
        "ref", sorted(str(e["ref"]) for e in describe_registry())
    )
    def test_elle_ne_leve_ni_ne_rend_de_nan(self, contexte_reel, ref):
        from fixtures.registre import parametres_de
        from rsl.primitives.registry import bind_primitive

        obtenue = bind_primitive(ref, **parametres_de(ref))(contexte_reel)
        assert obtenue is None or math.isfinite(obtenue), f"{ref} rend {obtenue}"


class TestLeCatalogueDecritCeQuiTourne:
    def test_le_manifeste_epingle_chaque_primitive_utilisee(self):
        """Un rapport archive doit pouvoir etre rejoue des annees plus tard :
        il epingle donc les versions, pas les noms."""
        rapport = run_backtest(spec_de("sma_es_daily.json")).to_dict()
        manifeste = rapport["manifest"]
        assert isinstance(manifeste, dict)
        epinglees = manifeste["primitives"]
        assert epinglees, "aucune primitive enregistree au manifeste"
        assert all("@" in str(ref) for ref in epinglees), epinglees
