"""Allocation : comment REPARTIR, une fois qu'on sait quoi detenir.

Le pendant des contraintes, et pas la meme question
---------------------------------------------------
`engine/limites.py` dit ce qu'on s'INTERDIT : un plafond refuse un ordre. Rien
la-dedans ne dit combien mettre sur chaque nom. Un classement qui prend six
positions peut respecter tous les plafonds et rester absurde - c'est le cas du
defaut historique, `quantity` contrats par nom.

Pourquoi « un contrat chacun » n'est pas neutre
-----------------------------------------------
Un contrat ES vaut environ 50 x 5 000 = 250 000 $. Un contrat 6J vaut environ
12 500 000 x 0,0065 = 81 000 $. « Un contrat chacun » met donc trois fois plus
d'argent sur ES que sur 6J, et le resultat du portefeuille est domine par
l'instrument dont le contrat est gros - pour une raison qui n'a rien a voir
avec la strategie.

C'est une repartition, pas une absence de repartition. La nommer
(`ContratsFixes`) est le point : un defaut invisible ne se discute pas.

Ce qui exige de voir la COUPE, et ce qui n'en a pas besoin
-----------------------------------------------------------
Beaucoup de choses s'ecrivent deja avec une regle de dimensionnement, qui ne
voit qu'un instrument. `equity_fraction` cible un notionnel ; `vol_target`
donne une taille inversement proportionnelle a la volatilite. Si ces regles
suffisent, les utiliser - elles sont plus simples et deja eprouvees.

Une allocation ne se justifie que pour ce qu'une regle par instrument ne peut
pas faire : **normaliser**. Des poids qui somment a un garantissent que la
cible brute est atteinte quel que soit le nombre de noms selectionnes et quelles
que soient leurs volatilites. `vol_target` applique a six noms deploie six fois
son budget ; `VolatiliteInverse` en deploie un.

De l'argent aux contrats
------------------------
    budget      = equity x gross_target
    contrats_i  = trunc(budget x poids_i / valeur_du_contrat_i)

La valeur d'un contrat vient de `MultiContext.contract_value`, que le runner
alimente avec les specifications du run. La couche `strategies` ne consulte
donc aucune table d'instruments : il n'y a qu'une source.

Troncature, comme partout ailleurs dans le socle
-------------------------------------------------
Le nombre de contrats est TRONQUE vers zero, jamais arrondi
(`docs/execution-model.md` §6.2). Consequence a connaitre, et c'est la premiere
cause de « la strategie ne trade pas » : avec un budget modeste reparti sur six
noms, `trunc` peut rendre zero partout. Un million d'equity, `gross_target` de
1,0, six noms : 166 666 $ par nom, soit zero contrat ES. Le compteur
`n_noms_tronques` le dit plutot que de laisser chercher.

Ce que l'allocation ne garantit pas
------------------------------------
Les poids sont calcules sur les barres CLOSES de la coupe, et l'ordre est
rempli une barre plus tard, a un autre prix. La repartition realisee s'ecarte
donc un peu de la repartition voulue. Meme approximation structurelle que celle
des plafonds, et pour la meme raison : la connaitre exactement demanderait de
connaitre le prix de fill avant de le connaitre.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rsl.data.feed import Context, MultiContext
from rsl.errors import ConfigurationError, RslError
from rsl.primitives.registry import bind_primitive
from rsl.strategies.signals import Signal, SpecDict

DEFAUT_GROSS_TARGET = 1.0
"""Fraction de l'equity deployee en notionnel brut.

Un plutot que zero virgule quelque chose : c'est la valeur qui rend la mesure
lisible - le notionnel total egale l'equity. Sur des futures ce n'est PAS
« sans levier » : la marge initiale d'ES avoisine 6 % du notionnel, donc
`gross_target: 1.0` represente environ seize fois la marge. Choisir cette
valeur est une decision, pas un reglage par defaut a subir.
"""


@dataclass(slots=True)
class AllocationStats:
    """Ce que l'allocation a empeche. Publie dans `describe()` de la strategie.

    Un nom qui disparait sans compteur donne un portefeuille plus concentre que
    demande, sans rien qui le signale.
    """

    n_noms_tronques: int = 0
    """Noms dont la conversion en contrats a rendu zero. La premiere cause de
    « la strategie ne trade pas » : voir la note sur la troncature."""

    n_noms_sans_poids: int = 0
    """Noms dont le poids n'etait pas calculable - volatilite indefinie, signal
    `None`. Ils sont ECARTES, jamais dotes d'un poids par defaut."""

    n_rebalances_vides: int = 0
    """Rebalancements ou aucun nom n'a recu le moindre contrat."""

    def describe(self) -> SpecDict:
        return {
            "n_noms_tronques": self.n_noms_tronques,
            "n_noms_sans_poids": self.n_noms_sans_poids,
            "n_rebalances_vides": self.n_rebalances_vides,
        }


@runtime_checkable
class AllocationRule(Protocol):
    """Combien de contrats sur chaque nom retenu.

    Rend des MAGNITUDES, jamais un sens : la direction vient du classement, et
    un poids negatif ne doit pas pouvoir retourner une position. Meme convention
    que `SignalSizing` dans la couche risque.
    """

    @property
    def warmup_bars(self) -> int: ...

    def contrats(
        self, selection: Sequence[str], ctx: MultiContext, stats: AllocationStats
    ) -> dict[str, int]: ...

    def describe(self) -> SpecDict: ...


def _equity(ctx: MultiContext, selection: Sequence[str]) -> float:
    """L'equity du compte, lue par n'importe lequel des noms de la coupe.

    Le compte est COMMUN au panneau (`MultiContext` n'en tient qu'un) : lequel
    on interroge n'a donc aucune importance, et le premier nom trie rend le
    choix deterministe.
    """
    sub: Context = ctx[selection[0]]
    return sub.account_value("equity")


def _en_contrats(
    poids: dict[str, float],
    ctx: MultiContext,
    gross_target: float,
    stats: AllocationStats,
) -> dict[str, int]:
    """Convertit des poids NORMALISES en contrats entiers.

    Un seul endroit pour la conversion, donc une seule convention de troncature
    et un seul comptage. Trois regles la partagent ; l'ecrire trois fois en
    ferait trois occasions de diverger.
    """
    if not poids:
        return {}
    equity = _equity(ctx, sorted(poids))
    if equity <= 0.0:
        return {}
    budget = equity * gross_target
    contrats: dict[str, int] = {}
    for symbole in sorted(poids):
        valeur = ctx.contract_value(symbole)
        if valeur <= 0.0:
            stats.n_noms_sans_poids += 1
            continue
        n = int(budget * poids[symbole] / valeur)
        if n < 1:
            stats.n_noms_tronques += 1
            continue
        contrats[symbole] = n
    return contrats


def _normaliser(bruts: dict[str, float], stats: AllocationStats) -> dict[str, float]:
    """Ramene des poids bruts positifs a une somme de un.

    Les noms sans poids utilisable ont deja ete ecartes par l'appelant. La
    normalisation porte donc sur les SEULS noms restants : la cible brute est
    atteinte, au prix d'une concentration sur ceux qui ont pu etre evalues.

    L'autre choix - normaliser sur tous les noms selectionnes, et laisser le
    budget des noms ecartes non deploye - serait defendable, mais ferait
    dependre l'exposition totale d'un manque de donnees plutot que d'une
    decision. Le compteur `n_noms_sans_poids` rend le cas visible dans les deux
    cas.
    """
    total = sum(bruts.values())
    if total <= 0.0 or not math.isfinite(total):
        stats.n_noms_sans_poids += len(bruts)
        return {}
    return {symbole: valeur / total for symbole, valeur in bruts.items()}


def _valide_gross_target(valeur: float) -> None:
    if not valeur > 0.0:
        raise ConfigurationError(f"gross_target doit etre > 0, recu {valeur}")
    if not math.isfinite(valeur):
        raise ConfigurationError(f"gross_target doit etre fini, recu {valeur}")


@dataclass(frozen=True, slots=True)
class ContratsFixes:
    """`n` contrats par nom. Le comportement historique, enfin nomme.

    Ce n'est PAS une allocation neutre - voir l'en-tete du module : elle met
    autant d'argent sur un nom que son contrat est gros. Elle reste le defaut
    parce qu'en changer changerait silencieusement tout run existant, et parce
    qu'elle est la seule regle qui ne depende d'aucune estimation : c'est donc
    elle qui sert aux verifications analytiques.
    """

    n: int = 1

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ConfigurationError(f"n doit etre >= 1, recu {self.n}")

    @property
    def warmup_bars(self) -> int:
        return 0

    def contrats(
        self, selection: Sequence[str], ctx: MultiContext, stats: AllocationStats
    ) -> dict[str, int]:
        return dict.fromkeys(sorted(selection), self.n)

    def describe(self) -> SpecDict:
        return {"rule": "fixed_contracts", "n": self.n}


@dataclass(frozen=True, slots=True)
class PoidsEgaux:
    """Meme ARGENT sur chaque nom : `poids = 1/N`.

    A ne pas confondre avec `ContratsFixes`, qui met le meme NOMBRE sur chaque
    nom. Les deux s'appellent volontiers « equipondere » dans la conversation
    courante ; elles donnent des portefeuilles differents des que les contrats
    n'ont pas la meme taille, c'est-a-dire toujours.

    Se distingue aussi de `equity_fraction` dans la couche risque : celle-ci
    cible une fraction PAR INSTRUMENT, sans savoir combien de noms seront pris.
    Avec six noms, six fois `0,2` deploie 1,2 fois l'equity. Ici, `1/N` somme
    a un quel que soit N.
    """

    gross_target: float = DEFAUT_GROSS_TARGET

    def __post_init__(self) -> None:
        _valide_gross_target(self.gross_target)

    @property
    def warmup_bars(self) -> int:
        return 0

    def contrats(
        self, selection: Sequence[str], ctx: MultiContext, stats: AllocationStats
    ) -> dict[str, int]:
        if not selection:
            return {}
        part = 1.0 / len(selection)
        poids = dict.fromkeys(sorted(selection), part)
        return _en_contrats(poids, ctx, self.gross_target, stats)

    def describe(self) -> SpecDict:
        return {"rule": "equal_weight", "gross_target": self.gross_target}


@dataclass(frozen=True, slots=True)
class VolatiliteInverse:
    """`poids_i` proportionnel a `1 / volatilite_i`, puis normalise.

    La repartition dite « risk parity » dans sa forme naive : chaque nom
    contribue autant a la volatilite du portefeuille - a condition que les noms
    soient decorreles, ce qui est faux sur dix futures d'indices et de devises.
    L'appeler parite de risque serait donc exagere ; c'est une ponderation
    inverse a la volatilite, et rien de plus.

    La volatilite est celle des rendements LOG par barre, mesuree par
    `volatility@1` sur le `Context` de chaque nom - donc sur barres closes
    seulement, d'ou la garantie anti-look-ahead est heritee sans regle
    supplementaire.

    Un nom dont la volatilite n'est pas estimable, ou vaut zero, est ECARTE :
    une volatilite nulle donnerait un poids infini, et un poids par defaut
    reviendrait a inventer une mesure.
    """

    window: int = 20
    gross_target: float = DEFAUT_GROSS_TARGET

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ConfigurationError(
                f"window doit etre >= 2, recu {self.window} : un seul rendement "
                f"n'a pas de dispersion"
            )
        _valide_gross_target(self.gross_target)

    @property
    def warmup_bars(self) -> int:
        return self.window + 1

    def contrats(
        self, selection: Sequence[str], ctx: MultiContext, stats: AllocationStats
    ) -> dict[str, int]:
        mesure = bind_primitive("volatility@1", window=self.window, log=True)
        bruts: dict[str, float] = {}
        for symbole in sorted(selection):
            try:
                vol = mesure(ctx[symbole])
            except RslError:
                vol = None
            if vol is None or vol <= 0.0 or not math.isfinite(vol):
                stats.n_noms_sans_poids += 1
                continue
            bruts[symbole] = 1.0 / vol
        return _en_contrats(
            _normaliser(bruts, stats), ctx, self.gross_target, stats
        )

    def describe(self) -> SpecDict:
        return {
            "rule": "inverse_volatility",
            "window": self.window,
            "gross_target": self.gross_target,
        }


@dataclass(frozen=True, slots=True)
class PoidsParSignal:
    """Poids donnes par une EXPRESSION du vocabulaire, puis normalises.

    Les trois autres regles repondent chacune a une question precise. Celle-ci
    n'en pose aucune : elle evalue le signal sur le `Context` de chaque nom et
    prend le resultat pour un poids brut.

        allocation = {"kind": "signal",
                      "signal": { ... n'importe quel noeud ... },
                      "gross_target": 1.0}

    Trois conventions, identiques a celles de `SignalSizing` :

    - un signal indefini (`None`) ECARTE le nom - « je ne sais pas » n'est pas
      « un poids par defaut » ;
    - un poids negatif ou nul ecarte le nom lui aussi. Le SENS vient du
      classement ; un poids negatif ne retourne pas une position, il n'a
      simplement pas de sens comme part d'un budget ;
    - la normalisation rend l'echelle du signal indifferente. Un signal qui
      vaut 3, 30 ou 0,03 partout donne le meme portefeuille - ce qui compte est
      le rapport entre les noms.

    Pas de `max_contracts` ici, contrairement a `SignalSizing` : la
    normalisation borne deja chaque poids par un, et `gross_target` borne la
    somme. Une expression qui explose sur un nom le concentre, elle ne peut pas
    faire deborder le budget.
    """

    signal: Signal
    gross_target: float = DEFAUT_GROSS_TARGET

    def __post_init__(self) -> None:
        _valide_gross_target(self.gross_target)

    @property
    def warmup_bars(self) -> int:
        return self.signal.warmup_bars

    def contrats(
        self, selection: Sequence[str], ctx: MultiContext, stats: AllocationStats
    ) -> dict[str, int]:
        bruts: dict[str, float] = {}
        for symbole in sorted(selection):
            try:
                valeur = self.signal(ctx[symbole])
            except RslError:
                valeur = None
            if valeur is None or not math.isfinite(valeur) or valeur <= 0.0:
                stats.n_noms_sans_poids += 1
                continue
            bruts[symbole] = valeur
        return _en_contrats(
            _normaliser(bruts, stats), ctx, self.gross_target, stats
        )

    def describe(self) -> SpecDict:
        return {
            "rule": "signal",
            "gross_target": self.gross_target,
            "signal": self.signal.describe(),
        }


@dataclass(slots=True)
class Allocateur:
    """Une regle, plus les compteurs de ce qu'elle a ecarte.

    La regle est immuable ; le comptage ne l'est pas. Les separer evite de
    rendre les regles mutables pour la seule commodite d'un compteur.
    """

    regle: AllocationRule
    stats: AllocationStats = field(default_factory=AllocationStats)

    @property
    def warmup_bars(self) -> int:
        return self.regle.warmup_bars

    def reset(self) -> None:
        self.stats = AllocationStats()

    def contrats(self, selection: Sequence[str], ctx: MultiContext) -> dict[str, int]:
        obtenus = self.regle.contrats(selection, ctx, self.stats)
        if selection and not obtenus:
            self.stats.n_rebalances_vides += 1
        return obtenus

    def describe(self) -> SpecDict:
        return {**self.regle.describe(), "stats": self.stats.describe()}
