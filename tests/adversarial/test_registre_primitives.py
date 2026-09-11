"""Les garanties qui doivent tenir pour TOUTE primitive, presente ou future.

Une bibliotheque d'indicateurs ne se verifie pas un indicateur a la fois. Le
cas particulier de chaque formule se teste dans `tests/unit/` ; ici on teste
ce qui ne depend d'aucune formule, sur le registre ENTIER, par parcours
automatique. Une primitive ajoutee demain est couverte sans qu'une ligne soit
ecrite ici - et si elle viole une de ces proprietes, c'est ce fichier qui le
dira, pas un backtest trois mois plus tard.

Quatre proprietes, dans l'ordre de gravite :

1. **Pas de look-ahead.** Corrompre tout ce qui suit la barre `n` ne doit
    changer aucune valeur lue en `n` ou avant. C'est LA garantie du socle
    (`docs/no-lookahead.md` §6), appliquee ici a chaque primitive.
2. **Warmup honnete.** A `warmup_bars` barres closes, l'appel ne leve pas.
    Sous-declarer son warmup fait lever `InsufficientHistoryError` en plein
    run ; le runner fait confiance a ce chiffre.
3. **Ni NaN ni infini.** Le contrat dit `float | None`. Un `NaN` se propage en
    silence et rend toute comparaison fausse ; un `None` force a decider.
4. **Determinisme.** Deux appels sur le meme contexte rendent la meme valeur.
"""

from __future__ import annotations

import math

import pytest

from fixtures import synthetic
from fixtures.registre import Cas, tous_les_cas
from rsl.data.feed import BarContext
from rsl.data.schema import BarStore
from rsl.errors import InsufficientHistoryError

pytestmark = pytest.mark.adversarial

N = 320
COUPURE = 200

CAS = tous_les_cas()
IDS = [str(c) for c in CAS]


def marche(seed: int = 20260911) -> BarStore:
    """Marche aleatoire a volume VARIABLE.

    Le volume constant de `make_store` rendrait vrais par accident tous les
    tests des indicateurs de volume : un `cmf` sur volume plat est insensible
    a presque tout.
    """
    closes = synthetic.random_walk(N, seed=seed)
    opens, highs, lows, closes_ = synthetic.ohlc_from_closes(closes)
    generateur = __import__("numpy").random.default_rng(seed)
    return BarStore.build(
        symbol="SYNTH.v.0",
        granularity=synthetic.MINUTE,
        ts_event=synthetic.timestamps(N),
        open_=opens, high=highs, low=lows, close=closes_,
        volume=generateur.uniform(500.0, 5_000.0, N),
        source_hash="synthetic",
    )


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    for _ in range(index + 1):
        ctx._advance()
    return ctx


def lie(cas: Cas, store: BarStore, index: int) -> float | None:
    return cas.primitive.bind(**cas.params)(at(store, index))


@pytest.mark.parametrize("cas", CAS, ids=IDS)
class TestToutesLesPrimitives:
    def test_le_futur_corrompu_ne_change_rien(self, cas: Cas):
        """Test adversarial n° 1, applique a chaque primitive du registre."""
        propre = marche()
        sale = synthetic.corrupt_future(propre, after_index=COUPURE)
        for index in (COUPURE - 60, COUPURE - 5, COUPURE):
            avant, apres = lie(cas, propre, index), lie(cas, sale, index)
            if avant is None or apres is None:
                assert avant is apres, f"barre {index} : {avant} vs {apres}"
                continue
            assert avant == pytest.approx(apres, rel=0, abs=0), (
                f"{cas} lit le futur : barre {index} vaut {avant} sur la serie "
                f"propre et {apres} apres corruption des barres > {COUPURE}"
            )

    def test_le_warmup_declare_suffit(self, cas: Cas):
        """A `warmup_bars` barres closes, l'appel aboutit.

        Sous-declarer fait lever en plein run : le runner saute exactement ce
        nombre de barres avant d'appeler la strategie.
        """
        chauffe = cas.primitive.bind(**cas.params).warmup_bars
        assert chauffe >= 1, f"{cas} declare un warmup de {chauffe}"
        try:
            lie(cas, marche(), chauffe - 1)
        except InsufficientHistoryError as erreur:
            pytest.fail(
                f"{cas} declare {chauffe} barres de warmup mais en exige "
                f"davantage : {erreur}"
            )

    def test_jamais_de_nan_ni_d_infini(self, cas: Cas):
        """`None` veut dire « pas calculable ». `NaN` ne veut rien dire."""
        store = marche()
        for index in (150, 200, N - 1):
            valeur = lie(cas, store, index)
            if valeur is None:
                continue
            assert math.isfinite(valeur), f"{cas} rend {valeur} a la barre {index}"

    def test_deux_appels_donnent_la_meme_valeur(self, cas: Cas):
        store = marche()
        assert lie(cas, store, 250) == lie(cas, store, 250)

    def test_elle_produit_une_valeur_au_moins_une_fois(self, cas: Cas):
        """Une primitive qui rend `None` a CHAQUE barre est morte.

        Elle passe tous les autres tests de ce fichier - elle ne leve pas, ne
        lit pas le futur, n'est ni NaN ni infinie - et n'est atteignable par
        personne. C'est le defaut de [[lessons]] L13 sous une autre forme, et
        il s'est produit pour de bon : `t3@1` empile SIX EMA et n'en recevait
        l'historique que pour cinq, donc rendait `None` partout des que la
        fenetre depassait 5.

        Le marche aleatoire suffit ici : une primitive saine y produit une
        valeur. Celles qui rendent legitimement `None` (division par zero,
        serie plate) ne le font pas sur une serie bruitee.
        """
        store = marche()
        chauffe = cas.primitive.bind(**cas.params).warmup_bars
        instants = [chauffe - 1, (chauffe + N) // 2, N - 1]
        valeurs = [lie(cas, store, index) for index in instants if index < N]
        assert any(v is not None for v in valeurs), (
            f"{cas} ne produit AUCUNE valeur sur un marche aleatoire "
            f"(barres {instants}). Warmup declare : {chauffe}."
        )

    def test_une_serie_plate_ne_fait_jamais_lever(self, cas: Cas):
        """Cas degenere le plus courant en donnees reelles : une seance sans
        echange. Rendre `None` est correct ; lever ne l'est pas, et une
        division par zero non gardee se manifeste ici."""
        plat = synthetic.make_store(synthetic.constant(N, 100.0), wick=0.0)
        valeur = cas.primitive.bind(**cas.params)(at(plat, N - 1))
        assert valeur is None or math.isfinite(valeur)


class TestContratDuRegistre:
    @pytest.mark.parametrize("cas", CAS, ids=IDS)
    def test_chaque_primitive_est_resumee(self, cas: Cas):
        """Le resume part dans `rsl catalogue` et dans le squelette : c'est ce
        qu'une machine lit pour choisir un indicateur."""
        resume = cas.primitive.summary.strip()
        assert len(resume) > 15, f"{cas} : resume trop court ({resume!r})"
        assert resume.endswith("."), f"{cas} : resume sans point final"

    @pytest.mark.parametrize("cas", CAS, ids=IDS)
    def test_un_parametre_inconnu_est_refuse(self, cas: Cas):
        """`extra=forbid` sur tous les modeles : une coquille est une erreur."""
        with pytest.raises(ValueError, match=r"(?i)extra|unexpected|permitted"):
            cas.primitive.bind(**cas.params, parametre_qui_nexiste_pas=1)
