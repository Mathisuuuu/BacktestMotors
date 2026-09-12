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

import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.exemples import attendues, specification
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

ATTENDUES = attendues()


def spec_de(nom: str) -> BacktestSpec:
    """L'exemple RECOLLE : strategie + montage.

    Depuis le 2026-09-12 il n'existe plus de specification complete sur le
    disque. Ce que ces tests verrouillent n'a pas change pour autant - ils
    verifient toujours qu'un run reel rend les memes chiffres qu'hier ; ils
    verifient en plus, desormais, que la COMPOSITION les rend.
    """
    return specification(nom)


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
        # L'interpreteur fils recompose l'exemple par le MEME chemin que le
        # reste de la suite : `tests/` sur le chemin, puis `specification()`.
        programme = (
            "import sys; sys.path.insert(0, 'tests');"
            "from fixtures.exemples import specification;"
            "from rsl.report import run_backtest;"
            f"print(run_backtest(specification({nom!r})).result_fingerprint)"
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


PLAFONNE = "momentum_12_1_mensuel.json"
"""Le seul exemple transversal : dix instruments, quatre classes d'actif.

C'est le seul endroit du depot ou un plafond de PORTEFEUILLE veut dire quelque
chose - sur un mono-instrument, brut et net coincident et le compte de
positions ne depasse jamais un.
"""


def spec_plafonnee(**limites: object) -> BacktestSpec:
    """Le montage de l'exemple, plus des plafonds.

    L'exemple sur DISQUE n'est pas touche : sa verite terrain doit rester
    comparable a ce qu'elle etait, et un exemple modifie pour porter une
    contrainte serait une strategie differente presentee sous le meme nom.
    """
    from fixtures.exemples import montage, strategie
    from rsl.composition import compose

    reglages = montage(PLAFONNE)
    risque = reglages["risk"]
    assert isinstance(risque, dict)
    return compose(
        strategie(PLAFONNE),
        {**reglages, "risk": {**risque, "limits": limites}},
        symbol=None,
    )


@pytest.fixture(scope="module")
def sous_plafond():
    """Un seul run pour toute la classe : l'univers fait dix parquets."""
    return run_backtest_detailed(spec_plafonnee(max_positions=2))


class TestLesPlafondsDePortefeuilleSurDonneesReelles:
    """Les plafonds de `engine/limites.py`, sur les dix instruments du momentum.

    Ce n'est PAS un essai de strategie, et rien ici ne doit etre lu comme tel :
    aucun Sharpe, aucun rendement, aucune conclusion sur `momentum_12_1`. La
    strategie ne sert que de generateur d'ordres sur un univers reel a quatre
    classes d'actif - le seul exemple du depot ou un plafond de portefeuille
    veut dire quelque chose. Le compteur d'essais du Deflated Sharpe n'a donc
    pas a s'incrementer (voir CLAUDE.md, « unite de travail : l'essai »).

    Ce que ces tests etablissent, et que le synthetique ne peut pas montrer :
    le plafond mord sur un vrai flux d'ordres, et il change le resultat.
    """

    NOM = PLAFONNE
    PLAFOND = 2


    def test_le_plafond_refuse_reellement_des_ordres(self, sous_plafond):
        """Sans refus, tous les tests suivants passeraient pour rien : ils
        verifieraient un plafond qui n'a jamais eu l'occasion de mordre."""
        stats = sous_plafond.result.risk_stats
        assert stats["n_rejected_positions"] > 0, stats

    def test_et_il_le_dit_dans_le_rapport(self, sous_plafond):
        """Un ordre disparu sans compteur donne « la strategie ne trade pas »
        sans explication. Le compteur doit survivre jusqu'au rapport."""
        run = sous_plafond.report.to_dict()["run"]
        assert isinstance(run, dict)
        stats = run["risk_stats"]
        assert isinstance(stats, dict)
        assert stats["n_rejected_positions"] > 0

    def test_le_nombre_d_instruments_detenus_ne_depasse_jamais_le_plafond(
        self, sous_plafond
    ):
        """La seule des quatre limites qui soit EXACTE, et c'est pourquoi
        c'est elle qu'on rejoue ici.

        Les plafonds en argent sont evalues sur les marques de la barre
        courante alors que le fill a lieu a la suivante : l'exposition realisee
        peut les depasser un peu, et le module le dit. Un COMPTE d'instruments,
        lui, ne bouge qu'aux fills et la projection le predit exactement - il
        n'y a donc aucune tolerance a accorder.

        Rejoue les fills dans l'ordre plutot que de lire l'etat final : un
        depassement transitoire, referme avant la fin, serait invisible
        autrement.
        """
        quantites: dict[str, int] = {}
        pire = 0
        for fill in sous_plafond.result.fills:
            signe = 1 if fill.side.value == "buy" else -1
            quantites[fill.symbol] = (
                quantites.get(fill.symbol, 0) + signe * fill.quantity
            )
            pire = max(pire, sum(1 for q in quantites.values() if q != 0))
        assert 0 < pire <= self.PLAFOND, f"jusqu'a {pire} instruments detenus"

    def test_un_plafond_qui_mord_change_le_resultat(self, sous_plafond):
        """La verification qui rend les autres credibles : si l'empreinte etait
        la meme qu'sans plafond, la contrainte serait decorative."""
        assert (
            sous_plafond.report.result_fingerprint
            != ATTENDUES[self.NOM]["result_fingerprint"]
        )

    def test_un_plafond_declare_change_le_config_hash(self):
        """Deux runs aux contraintes differentes ne doivent pas se confondre.
        Le pendant du test unitaire qui verifie qu'un plafond ABSENT, lui, ne
        change rien."""
        obtenu = canonical_hash(spec_plafonnee(max_positions=self.PLAFOND).canonical())
        assert obtenu != ATTENDUES[self.NOM]["config_hash"]

    def test_un_plafond_par_classe_d_actif_mord_aussi(self):
        """L'univers couvre quatre classes - quatre forex, quatre indices, un
        metal, une energie. Un seul instrument par classe doit refuser des
        ordres que `max_positions=4` aurait laisse passer."""
        artefacts = run_backtest_detailed(spec_plafonnee(max_per_category=1))
        assert artefacts.result.risk_stats["n_rejected_per_category"] > 0
