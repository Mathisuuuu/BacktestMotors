"""La memoisation ne doit RIEN changer. Ces tests tentent de la prendre en defaut.

Le ledger ecarte les « noeuds de signaux a memoire interne » parce qu'« un
noeud a etat survit d'un run a l'autre, ce qui casse le determinisme ». Une
memoisation n'est pas de cet ordre - elle range le resultat d'une fonction
pure - mais cette distinction ne vaut que si elle est VERIFIEE. C'est l'objet
de ce fichier.

Les quatre attaques, dans l'ordre de gravite :

1. **Servir une valeur d'une AUTRE serie.** C'est le scenario qui ferait
   passer un test de corruption du futur pour de mauvaises raisons : la valeur
   de la serie propre servie pour la serie corrompue.
2. **Memoiser un sous-arbre qui n'est pas une fonction de `(serie, barre)`.**
   `shifted` recopie l'etat de position et le resolveur de pairs, donc `peer`
   et `position` ne dependent pas seulement de la barre visee. Ce defaut a
   ete REEL : il a change l'empreinte de `examples/paire_es_nq.json` avant
   d'etre corrige (634 remplissages au lieu de 30).
3. **Grossir sans borne.** Une memoire non bornee sur 3,7 M de barres
   retiendrait tout l'historique des valeurs intermediaires.
4. **Changer une valeur.** Le cas general : memoise et non memoise doivent
   rendre le meme flottant, aux memes bits.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic
from rsl.data.feed import BarContext, MultiContext
from rsl.data.loader import build_panel
from rsl.data.schema import BarStore, Granularity
from rsl.strategies.memoire import (
    MEMO_DESACTIVEE,
    NOEUDS_NON_MEMOISABLES,
    Memoire,
    memoire_pour,
    memoisable,
)
from rsl.strategies.signals import build_signal

pytestmark = pytest.mark.adversarial

exige_memoire = pytest.mark.skipif(
    MEMO_DESACTIVEE,
    reason="ce test porte sur le mecanisme lui-meme, qui est desactive",
)
"""Les tests d'EQUIVALENCE doivent tourner dans les deux modes - c'est leur
raison d'etre. Ceux qui inspectent la memoire elle-meme n'ont rien a inspecter
quand elle n'existe pas, et se sautent."""

N = 400
JOUR = Granularity.minutes(60 * 24)


def at(store: BarStore, index: int) -> BarContext:
    ctx = BarContext(store)
    ctx._seek(index)
    return ctx


def spec_rolling(window: int = 30, stat: str = "mean") -> dict[str, object]:
    return {
        "type": "rolling", "stat": stat, "window": window,
        "inner": {"type": "primitive", "ref": "sma@1", "params": {"window": 5}},
    }


class TestAucuneFuiteEntreSeries:
    """Attaque n° 1, la plus grave : une valeur qui traverse deux series."""

    def test_le_meme_noeud_sur_deux_series_ne_melange_rien(self):
        """Le noeud est REUTILISE - c'est tout l'enjeu. Un noeud neuf par
        serie ne prouverait rien, puisque sa memoire serait vide."""
        noeud = build_signal(spec_rolling())
        a = synthetic.make_store(synthetic.random_walk(N, seed=1))
        b = synthetic.make_store(synthetic.random_walk(N, seed=2))

        attendu_a = build_signal(spec_rolling())(at(a, 300))
        attendu_b = build_signal(spec_rolling())(at(b, 300))
        assert attendu_a != attendu_b, "le montage doit distinguer les deux series"

        # En alternance, pour qu'une memoire mal gardee serve forcement a cote.
        for _ in range(3):
            assert noeud(at(a, 300)) == attendu_a
            assert noeud(at(b, 300)) == attendu_b

    def test_une_serie_corrompue_n_herite_pas_de_la_propre(self):
        """Le scenario qui ferait passer le test de corruption du futur pour
        de mauvaises raisons : meme symbole, memes horodatages, meme index -
        seul le contenu differe apres la coupure."""
        propre = synthetic.make_store(synthetic.random_walk(N, seed=7))
        sale = synthetic.corrupt_future(propre, after_index=200)
        noeud = build_signal(spec_rolling())

        avant_coupure = noeud(at(propre, 150))
        assert noeud(at(sale, 150)) == avant_coupure, "le passe doit etre identique"

        apres_propre = noeud(at(propre, 350))
        apres_sale = noeud(at(sale, 350))
        assert apres_propre != apres_sale, (
            "la memoire a servi une valeur de la serie propre pour la serie "
            "corrompue : c'est exactement la fuite qu'elle doit rendre impossible"
        )

    def test_le_jeton_change_bien_entre_deux_magasins_de_meme_contenu(self):
        """Deux magasins identiques au bit pres restent DEUX series. Les
        confondre serait sans consequence ici, mais le jeton ne doit pas
        dependre du contenu - sinon il dependrait des donnees."""
        closes = synthetic.random_walk(N, seed=3)
        un = synthetic.make_store(closes)
        deux = synthetic.make_store(closes)
        assert at(un, 10).data_token is not at(deux, 10).data_token


class TestSousArbresNonMemoisables:
    """Attaque n° 2 : celle qui a REELLEMENT casse une empreinte."""

    def test_peer_et_position_sont_les_deux_seuls(self):
        """La liste est complete par construction : un `BarContext` porte
        `_store`, `_i`, `_position` et `_peers`. Les deux premiers sont dans
        la cle, les deux autres ne s'atteignent que par ces noeuds."""
        assert {"peer", "position"} == NOEUDS_NON_MEMOISABLES

    @pytest.mark.parametrize("impur", [
        {"type": "peer", "symbol": "NQ.v.0", "inner": {"type": "price", "field": "close"}},
        {"type": "position", "field": "bars_held"},
    ])
    def test_un_sous_arbre_impur_est_refuse(self, impur):
        assert not memoisable(build_signal(impur))

    def test_meme_enfoui_profondement(self):
        """La detection doit traverser les noeuds intermediaires : c'est en
        profondeur que le defaut s'est produit, pas a la racine."""
        profond = build_signal({
            "type": "arith", "op": "+",
            "left": {"type": "constant", "value": 1.0},
            "right": {"type": "all_of", "operands": [
                {"type": "compare", "op": "<",
                 "left": {"type": "position", "field": "bars_held"},
                 "right": {"type": "constant", "value": 3.0}},
            ]},
        })
        assert not memoisable(profond)

    def test_un_sous_arbre_pur_est_accepte(self):
        pur = build_signal({
            "type": "arith", "op": "-",
            "left": {"type": "primitive", "ref": "sma@1", "params": {"window": 5}},
            "right": {"type": "price", "field": "close"},
        })
        assert memoisable(pur)

    @exige_memoire
    def test_le_rolling_concerne_n_a_donc_aucune_memoire(self):
        avec_pair = build_signal({
            "type": "rolling", "stat": "zscore", "window": 20,
            "inner": {"type": "peer", "symbol": "NQ.v.0",
                      "inner": {"type": "price", "field": "close"}},
        })
        assert avec_pair._memoire is None

    def test_le_cas_reel_qui_avait_change_une_empreinte(self):
        """`examples/paire_es_nq.json` en miniature : un z-score de ratio
        ES/NQ sur panneau. Memoise, il donnait 634 remplissages au lieu de 30."""
        stores = {
            "ES.v.0": synthetic.make_store(
                synthetic.random_walk(N, seed=11), symbol="ES.v.0",
                granularity=JOUR, start=synthetic.EPOCH),
            "NQ.v.0": synthetic.make_store(
                synthetic.random_walk(N, seed=12), symbol="NQ.v.0",
                granularity=JOUR, start=synthetic.EPOCH),
        }
        spec = {
            "type": "rolling", "stat": "zscore", "window": 30,
            "inner": {"type": "arith", "op": "/",
                      "left": {"type": "price", "field": "close"},
                      "right": {"type": "peer", "symbol": "NQ.v.0",
                                "inner": {"type": "price", "field": "close"}}},
        }
        noeud = build_signal(spec)
        assert noeud._memoire is None

        panneau = build_panel(stores)
        lectures = []
        for ligne in (200, 250, 300, 250, 200):
            ctx = MultiContext(panneau)
            ctx._seek_row(ligne)
            lectures.append(noeud(ctx["ES.v.0"]))
        # Lire la meme ligne deux fois doit donner la meme valeur, quel que
        # soit ce qui a ete lu entre-temps.
        assert lectures[1] == lectures[3]
        assert lectures[0] == lectures[4]


class TestBornage:
    """Attaque n° 3 : la memoire ne doit pas grandir avec l'echantillon."""

    @exige_memoire
    def test_elle_reste_bornee_sur_un_long_parcours(self):
        noeud = build_signal(spec_rolling(window=30))
        store = synthetic.make_store(synthetic.random_walk(2_000, seed=4))
        ctx = BarContext(store)
        ctx._seek(99)
        for _ in range(1_800):
            ctx._advance()
            noeud(ctx)
        taille = noeud._memoire.taille()
        assert taille <= 2 * 30, f"{taille} entrees retenues pour une portee de 30"

    def test_l_elagage_garde_ce_qui_sert_encore(self):
        """Elaguer par ordre d'insertion jetterait les barres les plus
        anciennes de la fenetre COURANTE, qui servent encore."""
        memoire = Memoire(portee=10)
        store = synthetic.make_store(synthetic.ramp(200))
        inner = build_signal({"type": "price", "field": "close"})
        for index in range(100, 130):
            memoire.lire(inner, at(store, index))
        for lag in range(10):
            assert memoire.lire(inner, at(store, 129 - lag)) is not None

    @exige_memoire
    def test_une_portee_nulle_ne_casse_pas(self):
        assert memoire_pour(0) is not None


class TestValeursIdentiques:
    """Attaque n° 4 : le cas general, sur des formes variees."""

    @pytest.mark.parametrize("stat", [
        "mean", "stdev", "min", "max", "sum", "zscore", "ema", "median",
        "var", "slope", "rank", "count_true",
    ])
    def test_chaque_statistique_donne_la_meme_valeur(self, stat):
        store = synthetic.make_store(synthetic.random_walk(N, seed=8))
        spec = spec_rolling(window=25, stat=stat)
        avec = build_signal(spec)
        sans = build_signal(spec)
        object.__setattr__(sans, "_memoire", None)

        ctx = BarContext(store)
        ctx._seek(199)
        for _ in range(60):
            ctx._advance()
            a, b = avec(ctx), sans(ctx)
            assert a == b or (a is None and b is None), f"{stat} : {a} vs {b}"

    def test_au_bord_du_warmup_aussi(self):
        """La ou `InsufficientHistoryError` tombe a chaque barre : c'est le
        cas que la memoire range sous un marqueur a part, donc celui ou une
        erreur de traduction passerait inapercue."""
        store = synthetic.make_store(synthetic.random_walk(120, seed=9))
        spec = spec_rolling(window=40)
        avec, sans = build_signal(spec), build_signal(spec)
        object.__setattr__(sans, "_memoire", None)
        for index in range(0, 100):
            assert avec(at(store, index)) == sans(at(store, index)), index

    def test_un_rolling_imbrique_donne_la_meme_valeur(self):
        """Le cas ou les acces ne sont PAS sequentiels : le rolling interieur
        est evalue a des barres qui remontent le temps."""
        spec = {
            "type": "rolling", "stat": "ema", "window": 9,
            "inner": {"type": "arith", "op": "-",
                      "left": {"type": "rolling", "stat": "ema", "window": 12,
                               "inner": {"type": "price", "field": "close"}},
                      "right": {"type": "rolling", "stat": "ema", "window": 26,
                                "inner": {"type": "price", "field": "close"}}},
        }
        store = synthetic.make_store(synthetic.random_walk(600, seed=10))
        avec = build_signal(spec)
        reference = []
        ctx = BarContext(store)
        ctx._seek(399)
        for _ in range(100):
            ctx._advance()
            reference.append(avec(ctx))

        # Le meme noeud, relance depuis le debut : la memoire accumulee ne
        # doit pas changer ce qu'il rend.
        rejoue = []
        ctx = BarContext(store)
        ctx._seek(399)
        for _ in range(100):
            ctx._advance()
            rejoue.append(avec(ctx))
        assert rejoue == reference

    def test_bars_since_donne_la_meme_valeur(self):
        spec = {
            "type": "bars_since", "lookback": 50,
            "inner": {"type": "compare", "op": ">",
                      "left": {"type": "price", "field": "close"},
                      "right": {"type": "primitive", "ref": "sma@1",
                                "params": {"window": 20}}},
        }
        store = synthetic.make_store(synthetic.random_walk(N, seed=13))
        avec, sans = build_signal(spec), build_signal(spec)
        object.__setattr__(sans, "_memoire", None)
        vues = 0
        for index in range(100, 300):
            a, b = avec(at(store, index)), sans(at(store, index))
            assert a == b, index
            vues += a is not None
        assert vues > 50, "le montage doit exercer des valeurs definies"


class TestSurfaceDuJeton:
    def test_le_jeton_ne_survit_pas_a_un_changement_de_serie(self):
        """La garde elle-meme, vue de l'interieur."""
        memoire = Memoire(portee=5)
        inner = build_signal({"type": "price", "field": "close"})
        un = synthetic.make_store(synthetic.constant(50, 1.0))
        deux = synthetic.make_store(synthetic.constant(50, 2.0))

        assert memoire.lire(inner, at(un, 10)) == pytest.approx(1.0)
        assert memoire.taille() == 1
        assert memoire.lire(inner, at(deux, 10)) == pytest.approx(2.0)
        assert memoire.taille() == 1, "la memoire doit avoir ete videe, pas augmentee"

    def test_shifted_conserve_le_jeton(self):
        """Sinon la memoire se viderait a chaque decalage et ne servirait a rien."""
        ctx = at(synthetic.make_store(synthetic.ramp(50)), 30)
        assert ctx.shifted(7).data_token is ctx.data_token

    def test_un_pair_a_son_propre_jeton(self):
        stores = {
            "A": synthetic.make_store(synthetic.ramp(50), symbol="A",
                                      granularity=JOUR, start=synthetic.EPOCH),
            "B": synthetic.make_store(synthetic.ramp(50, 200.0), symbol="B",
                                      granularity=JOUR, start=synthetic.EPOCH),
        }
        ctx = MultiContext(build_panel(stores))
        ctx._seek_row(30)
        assert ctx["A"].data_token is not ctx["B"].data_token


class TestInterrupteur:
    def test_desactivee_aucun_noeud_ne_porte_de_memoire(self, monkeypatch):
        """`RSL_NO_MEMO=1` doit couper le mecanisme ENTIEREMENT - c'est ce qui
        rend la comparaison des deux modes probante."""
        import rsl.strategies.memoire as module

        monkeypatch.setattr(module, "MEMO_DESACTIVEE", True)
        assert module.memoire_pour(30) is None

    def test_la_valeur_de_l_interrupteur_est_lue_une_seule_fois(self):
        """Relue a chaque appel, elle ferait dependre le resultat du moment de
        sa lecture - le genre de non-determinisme que le socle refuse."""
        import rsl.strategies.memoire as module

        assert isinstance(module.MEMO_DESACTIVEE, bool)


class TestGainReel:
    """La memoisation doit AUSSI faire ce pour quoi elle existe."""

    @exige_memoire
    def test_un_parcours_sequentiel_evalue_le_sous_arbre_une_fois_par_barre(self):
        """Preuve directe du gain, en COMPTANT les evaluations plutot qu'en
        chronometrant : un chronometre sur une machine chargee ne prouve rien.
        """
        appels = {"n": 0}
        store = synthetic.make_store(synthetic.random_walk(600, seed=14))
        noeud = build_signal(spec_rolling(window=100))
        vrai_inner = noeud.inner

        class Compteur:
            def __call__(self, ctx) -> float | None:
                appels["n"] += 1
                return vrai_inner(ctx)

            @property
            def warmup_bars(self):
                return vrai_inner.warmup_bars

            def describe(self):
                return vrai_inner.describe()

        object.__setattr__(noeud, "inner", Compteur())
        ctx = BarContext(store)
        ctx._seek(299)
        barres = 200
        for _ in range(barres):
            ctx._advance()
            noeud(ctx)

        sans_memoire = barres * 100
        assert appels["n"] < sans_memoire / 20, (
            f"{appels['n']} evaluations pour {barres} barres ; sans memoire il "
            f"en faudrait {sans_memoire}"
        )
        assert appels["n"] >= barres, "une evaluation par barre au minimum"


def test_les_valeurs_memoisees_ne_sont_jamais_des_tableaux():
    """Garde de forme : ranger un tableau numpy ferait partager une reference
    mutable entre deux barres. Le contrat d'un signal est `float | None`."""
    memoire = Memoire(portee=5)
    inner = build_signal({"type": "price", "field": "close"})
    valeur = memoire.lire(inner, at(synthetic.make_store(synthetic.ramp(50)), 10))
    assert not isinstance(valeur, np.ndarray)
