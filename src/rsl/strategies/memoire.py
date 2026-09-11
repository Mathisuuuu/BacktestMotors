"""Memoisation des sous-arbres reevalues a plusieurs decalages.

Le probleme, mesure et non suppose
----------------------------------
`rolling(stat, w, inner)` evalue `inner` sur `ctx.shifted(k)` pour k de 0 a
w-1. Le profil du 2026-09-11 montre que le cout est EXACTEMENT
`w x cout(inner)` : `shifted` ne pese que 0,34 us, il n'y a aucun gaspillage
cache a recuperer. Sur `rolling(zscore, 120)` d'un `arith` de deux `sma@1`,
cela fait 1 427 us par barre - 1,6 h pour UN signal sur les 3,7 M de barres
minute d'ES.

La redondance n'est donc pas DANS une barre, elle est ENTRE les barres. La
valeur de `inner` a la barre j est calculee a la barre j, puis de nouveau a
j+1, ... jusqu'a j+w-1 : w fois au lieu d'une. C'est le seul gisement, et le
recuperer demande de se souvenir d'une barre a l'autre.

Pourquoi ce n'est pas le « noeud a memoire » ecarte au ledger
-------------------------------------------------------------
Le ledger (2026-09-10) ecarte les « noeuds de signaux a memoire interne », au
motif qu'« un noeud a etat survit d'un run a l'autre, ce qui casse le
determinisme et donc la reproductibilite bit-a-bit ».

Ce motif vise une memoire qui PORTE DU SENS - l'etat de position, dont la
valeur depend de l'ordre des appels. Une memoisation n'en porte aucun : elle
range le resultat d'une fonction pure de `(sous-arbre, serie, barre)`, et
rendre une valeur rangee ou la recalculer donne le meme flottant, aux memes
bits. Le noeud reste sans etat au sens qui compte : sa SORTIE ne depend que du
contexte recu.

Cette distinction ne se decrete pas, elle se verifie. Trois preuves :

1. **Les empreintes d'exemples sont inchangees** apres l'ajout. Une memoire
   qui changerait un resultat le montrerait la.
2. **Les suites adversariales passent inchangees**, corruption du futur
   comprise - et une memoire qui survivrait d'une serie a l'autre ferait
   precisement echouer celle-la, puisqu'elle servirait une valeur calculee sur
   la serie propre.
3. **`RSL_NO_MEMO=1` desactive entierement le mecanisme**, et la suite passe a
   l'identique dans les deux modes. C'est la preuve la plus directe qu'aucun
   resultat n'en depend.

Ce qui reste vrai du motif d'origine : une memoire MAL BORNEE serait un
defaut. D'ou les deux gardes ci-dessous, et les tests qui les attaquent
(`tests/adversarial/test_memoisation.py`).

La troisieme garde, et la seule qui ait coute une empreinte
-----------------------------------------------------------
Memoiser suppose que la valeur du sous-arbre ne depend QUE de la serie et de
la barre. Cette hypothese est fausse pour deux noeuds, et l'empreinte de
`examples/paire_es_nq.json` l'a dit immediatement : 634 remplissages au lieu
de 30.

La cause est dans `BarContext.shifted`, qui recopie l'etat de la vue
d'origine :

    sub._set_position(self._position)
    sub._set_peers(self._peers)

Un `BarContext` porte exactement QUATRE choses : `_store`, `_i`, `_position`
et `_peers`. La cle en couvre deux. Les deux autres ne sont atteignables que
par les noeuds `peer` et `position`, et aucun des deux n'est une fonction de
`(serie, barre)` :

- `_peers` designe un PANNEAU, que la cle n'identifie pas. Deux panneaux
  partageant le meme magasin d'ES donneraient des valeurs differentes a la
  meme cle ;
- `_position` est l'etat COURANT, recopie tel quel par `shifted` - le runner
  ne conserve aucun historique de positions a reculer.

D'ou la regle, qui n'est pas une precaution mais une demonstration : un
sous-arbre est memoisable si et seulement s'il ne contient ni `peer` ni
`position`. La liste est COMPLETE parce que la liste des attributs d'un
`BarContext` l'est.

Ce travail a mis au jour un defaut qui lui preexistait : le terme distant ne
glissait pas avec la fenetre. **Corrige le meme jour** - `shifted` recule
desormais aussi le resolveur de pairs. Le critere ci-dessus ne change pas pour
autant : la valeur d'un `peer` depend maintenant de `(serie, barre, PANNEAU)`,
et la cle de memoisation n'identifie pas le panneau. Le refus subsiste, pour
une raison plus nette qu'avant.

Les deux autres gardes
----------------------
**Changement de serie.** La memoire s'accroche a un jeton opaque
(`Context.data_token`). Des qu'on lui presente un autre jeton, elle se vide.
Une serie propre et sa version corrompue sont deux magasins distincts, donc
deux jetons : aucune valeur ne peut passer de l'une a l'autre. Le jeton est le
magasin lui-meme, ce qui le garde vivant - un entier d'identite pourrait etre
reattribue apres ramassage et confondre deux series en silence.

**Taille.** La memoire garde au plus `2 x portee` entrees, ou `portee` est le
nombre de barres que le noeud consulte. Au-dela, elle jette ce qui est hors de
portee de la barre courante. Une memoire non bornee sur 3,7 M de barres
tiendrait tout l'historique des valeurs intermediaires.
"""

from __future__ import annotations

import os
from typing import Final, Protocol

from rsl.data.feed import Context
from rsl.errors import InsufficientHistoryError

MEMO_DESACTIVEE: Final[bool] = os.environ.get("RSL_NO_MEMO", "") not in ("", "0")
"""Interrupteur de secours, lu UNE FOIS a l'import.

Il n'existe pas pour regler un comportement - les deux modes donnent le meme
resultat, c'est tout l'enjeu - mais pour que cette egalite soit VERIFIABLE :
`RSL_NO_MEMO=1 pytest` rejoue la suite entiere sans memoisation.

Lu a l'import et fige : une variable relue a chaque appel ferait dependre le
resultat du moment de sa lecture, exactement le genre de non-determinisme que
le socle refuse.
"""


class Evaluable(Protocol):
    """Ce qu'un sous-arbre sait faire, vu d'ici.

    Declare en local plutot qu'importe depuis `signals` : ce module est
    importe PAR `signals`, et l'importer en retour fermerait un cycle. Le
    protocole dit exactement ce dont la memoire a besoin, et rien de plus.
    """

    def __call__(self, ctx: Context) -> float | None: ...


class Leve:
    """« L'evaluation a leve `InsufficientHistoryError` », range comme une valeur.

    Au bord du warmup, cette exception tombe a chaque barre pour les memes
    decalages. La relever coute le prix du calcul qu'elle interrompt : c'est
    souvent le cas le PLUS cher, donc celui qu'il faut le plus memoiser.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "<historique insuffisant>"


class Absent:
    """« Pas encore calcule », distinct de `None`.

    `None` est une valeur LEGITIME - « pas calculable a cette barre » - et se
    memoise comme les autres. Sans ce second marqueur, un `None` range serait
    relu comme une absence et recalcule a chaque fois.
    """

    __slots__ = ()


LEVE: Final = Leve()
ABSENT: Final = Absent()

Resultat = float | None | Leve
"""Ce qu'une case de memoire peut contenir."""


class Memoire:
    """Souvenir des valeurs d'UN sous-arbre, pour UNE serie a la fois.

    Volontairement une classe ordinaire, mutable et assumee comme telle : la
    deguiser en `dataclass(frozen=True)` avec des `object.__setattr__`
    masquerait ce qu'elle est. Elle est detenue par un noeud gele, et elle est
    la seule chose mutable du montage.
    """

    __slots__ = ("_ancre", "_portee", "_valeurs")

    def __init__(self, portee: int) -> None:
        self._portee = max(portee, 1)
        self._ancre: object = None
        self._valeurs: dict[int, Resultat] = {}

    def taille(self) -> int:
        """Nombre d'entrees retenues. Existe pour les tests de bornage."""
        return len(self._valeurs)

    def lire(self, inner: Evaluable, vue: Context) -> Resultat:
        """La valeur de `inner` a la barre de `vue`, retrouvee ou calculee."""
        jeton = vue.data_token
        if jeton is not self._ancre:
            # Changement de serie : tout ce qui est range vient d'ailleurs.
            self._ancre = jeton
            self._valeurs.clear()

        cle = vue.n_bars_seen
        rangee = self._valeurs.get(cle, ABSENT)
        if not isinstance(rangee, Absent):
            return rangee

        calculee = _calculer(inner, vue)
        if len(self._valeurs) >= 2 * self._portee:
            self._elaguer(cle)
        self._valeurs[cle] = calculee
        return calculee

    def _elaguer(self, cle_courante: int) -> None:
        """Jette ce qui est hors de portee de la barre courante.

        Par DISTANCE a la barre courante, et non par ordre d'insertion : les
        acces ne sont pas strictement sequentiels - un `rolling` imbrique dans
        un autre remonte le temps - et un ordre d'insertion jetterait alors ce
        dont on a encore besoin.
        """
        limite = cle_courante - self._portee
        perimees = [k for k in self._valeurs if k < limite or k > cle_courante]
        for cle in perimees:
            del self._valeurs[cle]


def _vue_et_valeur(
    memoire: Memoire | None, inner: Evaluable, ctx: Context, lag: int
) -> Resultat:
    """Recule le contexte PUIS evalue, les deux sous la meme garde.

    `ctx.shifted(lag)` leve `InsufficientHistoryError` de son propre chef des
    que le decalage depasse l'historique - c'est le cas au bord du warmup, et
    c'est frequent. Le sortir de la garde faisait remonter l'exception jusqu'a
    la strategie au lieu de rendre `None` : neuf tests l'ont dit aussitot.
    """
    try:
        vue = ctx.shifted(lag) if lag else ctx
    except InsufficientHistoryError:
        return LEVE
    if memoire is None:
        return _calculer(inner, vue)
    return memoire.lire(inner, vue)


def _calculer(inner: Evaluable, vue: Context) -> Resultat:
    try:
        return inner(vue)
    except InsufficientHistoryError:
        return LEVE


NOEUDS_NON_MEMOISABLES: Final[frozenset[str]] = frozenset({"peer", "position"})
"""Les seuls noeuds dont la valeur depend d'autre chose que `(serie, barre)`.

La liste est complete, et demontrable : un `BarContext` porte `_store`, `_i`,
`_position` et `_peers`. Les deux premiers sont dans la cle ; les deux autres
ne s'atteignent que par ces deux noeuds. Un noeud ajoute demain qui lirait un
cinquieme attribut devrait etre ajoute ici - et il n'y a pas de cinquieme
attribut.
"""


def _contient_noeud_impur(descripteur: object) -> bool:
    """Cherche `peer` ou `position` A N'IMPORTE QUELLE PROFONDEUR.

    Passe par `describe()` plutot que par les types : tout signal sait se
    decrire, y compris ceux qu'on n'a pas encore ecrits, donc la detection ne
    demande ni visiteur ni liste de classes a tenir a jour.
    """
    if isinstance(descripteur, dict):
        if descripteur.get("type") in NOEUDS_NON_MEMOISABLES:
            return True
        return any(_contient_noeud_impur(v) for v in descripteur.values())
    if isinstance(descripteur, list):
        return any(_contient_noeud_impur(v) for v in descripteur)
    return False


def memoisable(inner: object) -> bool:
    """`True` si la valeur de ce sous-arbre ne depend que de la serie et de la barre."""
    decrire = getattr(inner, "describe", None)
    if decrire is None:
        return False
    return not _contient_noeud_impur(decrire())


def memoire_pour(portee: int, inner: object = None) -> Memoire | None:
    """La memoire d'un noeud, ou `None` si elle ne serait pas correcte.

    Trois raisons de rendre `None`, toutes silencieuses par construction :
    le mecanisme est desactive, le sous-arbre n'est pas memoisable, ou il ne
    sait pas se decrire. Dans les trois cas le noeud recalcule - plus lent,
    jamais faux.
    """
    if MEMO_DESACTIVEE:
        return None
    if inner is not None and not memoisable(inner):
        return None
    return Memoire(portee)


def valeurs_de_fenetre(
    memoire: Memoire | None, inner: Evaluable, ctx: Context, lags: range
) -> list[float] | None:
    """Les valeurs de `inner` aux decalages demandes, le PRESENT en tete.

    Rend `None` des qu'une valeur manque : une seule valeur indefinie rend
    toute la fenetre indefinie. Regle inchangee et voulue - une moyenne sur une
    fenetre trouee ne serait pas la moyenne demandee.

    Forme fonctionnelle deliberee : le noeud appelant reste
    `dataclass(frozen=True)`, et ne detient de mutable que l'objet `Memoire`.
    """
    valeurs: list[float] = []
    for lag in lags:
        obtenue = _vue_et_valeur(memoire, inner, ctx, lag)
        if obtenue is None or isinstance(obtenue, Leve):
            return None
        valeurs.append(obtenue)
    return valeurs


def valeur_a(
    memoire: Memoire | None, inner: Evaluable, ctx: Context, lag: int
) -> Resultat:
    """Une seule valeur, pour les noeuds qui s'arretent des qu'ils l'ont.

    `bars_since` remonte le temps jusqu'a trouver sa condition vraie : lui
    faire construire toute la fenetre annulerait l'interet de son arret.
    """
    return _vue_et_valeur(memoire, inner, ctx, lag)
