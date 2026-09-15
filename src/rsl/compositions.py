"""Les grandeurs qui n'ont PAS de noeud, et comment on les ecrit.

Pourquoi ce module existe
--------------------------
Le squelette engendre par `rsl squelette` dit tout ce qu'on PEUT ecrire : 27
noeuds, 136 primitives, leurs champs et leurs valeurs. Il ne dit rien de la
facon dont on les ASSEMBLE, et c'est precisement ce qu'un auteur - humain ou
machine - ne peut pas deviner en lisant une liste de types.

Il n'existe aucun noeud `vwap`. Le VWAP ancre s'ecrit comme le quotient de
deux `cumulative`, l'un sur le prix typique fois le volume, l'autre sur le
volume seul. Personne ne trouve cette forme en lisant que `cumulative` accepte
un `inner` : il faut la connaitre, ou l'avoir vue.

Ce que ces recettes sont, et ne sont pas
-----------------------------------------
Ce sont des **formes verifiees**, pas des strategies. Chacune a ete ecrite
dans un exemple du depot ou dans une mesure datee, et
`tests/unit/test_compositions.py` les construit toutes par `build_signal` :
une recette qui cesserait d'etre exprimable casserait la suite.

C'est la parade a [[lessons]] L36. Le recensement de couverture tenait ses
verdicts dans un dictionnaire ecrit a la main, et **deux sur quatre etaient
devenus faux** sans que rien ne le signale. Une recette que le code construit
ne peut pas pourrir en silence.

Ce qu'elles ne remplacent pas : les `pieges` declares sur les noeuds. Une
recette montre une forme JUSTE ; un piege dit ou le nom d'un terme promet
autre chose que sa definition. Les deux sont publies par `rsl squelette`, et
aucun ne suffit seul.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

SpecDict = dict[str, object]


@dataclass(frozen=True, slots=True)
class Composition:
    """Une grandeur assemblee, avec ce qu'il faut savoir pour s'en servir."""

    nom: str
    resume: str
    """Ce que la forme calcule, en une phrase."""

    quand: str
    """Quand on s'en sert - la question a laquelle elle repond."""

    arbre: SpecDict
    """La forme, construite telle quelle par `build_signal`."""

    attention: str | None = None
    """Ce qui surprend. Absent quand rien ne surprend."""

    def describe(self) -> SpecDict:
        decrit: SpecDict = {
            "resume": self.resume,
            "quand": self.quand,
            "forme": self.arbre,
        }
        if self.attention is not None:
            decrit["attention"] = self.attention
        return decrit


# --- raccourcis d'ecriture, pour que les recettes restent lisibles ---------


def _prix(champ: str, lag: int = 0) -> SpecDict:
    return {"type": "price", "field": champ, "lag": lag}


def _cst(valeur: float) -> SpecDict:
    return {"type": "constant", "value": valeur}


def _arith(op: str, gauche: SpecDict, droite: SpecDict) -> SpecDict:
    return {"type": "arith", "op": op, "left": gauche, "right": droite}


def _cmp(op: str, gauche: SpecDict, droite: SpecDict) -> SpecDict:
    return {"type": "compare", "op": op, "left": gauche, "right": droite}


def _seance(champ: str, lag: int = 0) -> SpecDict:
    return {"type": "session", "field": champ, "lag": lag}


_PRIX_TYPIQUE: Final[SpecDict] = _arith(
    "/",
    _arith("+", _arith("+", _prix("high"), _prix("low")), _prix("close")),
    _cst(3.0),
)


COMPOSITIONS: Final[tuple[Composition, ...]] = (
    Composition(
        nom="rendement",
        resume="Rendement simple de la barre : close / close[-1] - 1.",
        quand="Des qu'on raisonne en pourcentage plutot qu'en points.",
        arbre=_arith(
            "-",
            _arith("/", _prix("close"), {"type": "lag", "bars": 1, "inner": _prix("close")}),
            _cst(1.0),
        ),
    ),
    Composition(
        nom="prix_typique",
        resume="(haut + bas + cloture) / 3.",
        quand="Brique du VWAP, et proxy du prix moyen d'une barre.",
        arbre=_PRIX_TYPIQUE,
    ),
    Composition(
        nom="vwap_de_seance",
        resume=(
            "VWAP ANCRE a l'ouverture de la seance : somme(prix typique x "
            "volume) / somme(volume), les deux depuis l'ouverture."
        ),
        quand=(
            "Filtre de sens du flux intra-journalier, et stop qui se resserre "
            "tout seul au fil de la seance."
        ),
        arbre=_arith(
            "/",
            {"type": "cumulative", "stat": "sum",
             "inner": _arith("*", _PRIX_TYPIQUE, _prix("volume"))},
            {"type": "cumulative", "stat": "sum", "inner": _prix("volume")},
        ),
        attention=(
            "Il n'existe AUCUN noeud `vwap`. `cumulative` remet a zero a "
            "chaque seance, ce qui donne l'ancrage sans qu'on ait a le "
            "demander - mais exige une `session` declaree dans `data[]`."
        ),
    ),
    Composition(
        nom="volume_en_dollars_moyen",
        resume="Moyenne sur N barres de cloture x volume - l'`adv{N}` usuel.",
        quand="Filtre de liquidite : ne negocier que ce qui s'echange.",
        arbre={"type": "rolling", "stat": "mean", "window": 20,
               "inner": _arith("*", _prix("close"), _prix("volume"))},
    ),
    Composition(
        nom="plus_haut_de_la_veille",
        resume="Le plus haut de la seance PRECEDENTE.",
        quand="Cassure de niveau : PDH / PDL.",
        arbre=_seance("high", lag=1),
        attention=(
            "Le `lag: 1` n'est pas un confort. `session.high` au lag 0 est "
            "REFUSE : le plus haut de la seance en cours est un fait futur "
            "tant qu'elle n'est pas close."
        ),
    ),
    Composition(
        nom="grille_semi_horaire",
        resume=(
            "Vrai aux points de controle toutes les 30 minutes, entre la 30e "
            "et la 360e minute de seance."
        ),
        quand=(
            "Strategies qui n'evaluent leurs signaux qu'a intervalles fixes "
            "plutot qu'a chaque barre."
        ),
        arbre={
            "type": "all_of",
            "operands": [
                _cmp(">=", _seance("minutes_from_open"), _cst(30.0)),
                _cmp("<=", _seance("minutes_from_open"), _cst(360.0)),
                _cmp("==",
                     _arith("%", _seance("minutes_from_open"), _cst(30.0)),
                     _cst(0.0)),
            ],
        },
        attention=(
            "`minutes_from_open` parcourt 1..N et ne vaut JAMAIS zero : une "
            "barre est horodatee a sa CLOTURE. Le point 30 minutes apres "
            "l'ouverture est la barre qui SE FERME a ce moment-la."
        ),
    ),
    Composition(
        nom="etendue_d_ouverture",
        resume=(
            "Le plus haut atteint pendant les N premieres minutes de la "
            "seance, fige pour le reste de la journee."
        ),
        quand="Opening range breakout.",
        arbre={
            "type": "cumulative", "stat": "max",
            "mask": _cmp("<=", _seance("minutes_from_open"), _cst(30.0)),
            "inner": _prix("high"),
        },
        attention=(
            "Le `mask` est ce qui fige la valeur : passe la 30e minute, "
            "aucune barre neuve n'entre dans l'agregat. Ecrire la meme chose "
            "avec `if_then_else(..., sentinelle)` rendrait la sentinelle sur "
            "une tranche vide ([[lessons]] L30)."
        ),
    ),
    Composition(
        nom="cloture_forcee",
        resume="Vrai a la barre qui atteint l'heure de fermeture DECLAREE.",
        quand="Sortir avant la nuit - ce qui fait d'une strategie une intraday.",
        arbre=_cmp("==", _seance("is_last"), _cst(1.0)),
        attention=(
            "DEUX pieges. `is_last` ne marque pas la derniere barre de la "
            "seance mais la premiere a ATTEINDRE l'heure declaree : une "
            "demi-journee n'en porte AUCUNE, et la regle n'y declenche jamais "
            "- mesure a 90 seances sur 2 748 sur NQ. Et avec `lag_bars: 1`, "
            "l'ordre se remplit a l'ouverture de la barre SUIVANTE, donc la "
            "seance d'apres : declarer `execution.max_fill_gap_seconds` ou "
            "sortir une barre plus tot. `rsl check` signale les deux."
        ),
    ),
    Composition(
        nom="dispersion_au_meme_rang",
        resume=(
            "Moyenne, sur les N seances precedentes, d'une grandeur prise au "
            "MEME rang intra-seance."
        ),
        quand=(
            "Enveloppe de volatilite intra-journaliere : de combien le prix "
            "s'ecarte-t-il de son ouverture, a cette heure-ci, un jour "
            "ordinaire ?"
        ),
        arbre={
            "type": "rolling", "stat": "mean", "window": 60, "across": "sessions",
            "inner": {
                "type": "session_lag", "sessions": 1,
                "inner": {
                    "type": "math", "op": "abs",
                    "inner": _arith("-",
                                    _arith("/", _prix("close"), _seance("open")),
                                    _cst(1.0)),
                },
            },
        },
        attention=(
            "`across: sessions` compte la fenetre en SEANCES au meme rang, par "
            "le calendrier declare - un `stride` en barres suppose des seances "
            "de longueur egale et ne tombe jamais sur le bon rang ([[lessons]] "
            "L29). `session_lag: 1` exclut la seance EN COURS, sans quoi on "
            "calibrerait sur le mouvement qu'on s'apprete a lui comparer. "
            "Une seance ECOURTEE n'a pas de barre au rang demande : la fenetre "
            "rend alors `None`."
        ),
    ),
    Composition(
        nom="pertes_nettes_de_la_seance",
        resume=(
            "Combien d'allers-retours se sont fermes EN PERTE NETTE depuis "
            "l'ouverture de la seance."
        ),
        quand="Garde : arreter apres N pertes dans la journee.",
        arbre={
            "type": "cumulative", "stat": "count_true",
            "mask": {"type": "position", "field": "closed_trade"},
            "inner": _cmp("<", {"type": "position", "field": "closed_pnl"},
                          _cst(0.0)),
        },
        attention=(
            "Le `mask` est OBLIGATOIRE : `closed_pnl` vaut zero par "
            "remplissage sur les barres ou aucun trade ne se ferme, et sans "
            "`closed_trade` pour dire quand ce zero a un sens, ce serait une "
            "sentinelle. Ecrire la meme garde avec `close < entry_price` "
            "ignore les FRAIS et le prix du fill de sortie : mesure, une garde "
            "une garde a UNE perte plafonnait a QUATRE pertes par seance."
        ),
    ),
    Composition(
        nom="stop_suiveur_sur_extreme",
        resume=(
            "Sortir quand la cloture retombe de N x ATR sous le plus haut "
            "atteint DEPUIS L'ENTREE."
        ),
        quand="Stop suiveur, evalue a la cloture.",
        arbre=_cmp(
            "<",
            _prix("close"),
            _arith("-",
                   {"type": "position", "field": "high_since_entry"},
                   _arith("*", _cst(2.0),
                          {"type": "primitive", "ref": "atr@1",
                           "params": {"window": 14}})),
        ),
    ),
    Composition(
        nom="filtre_par_un_autre_instrument",
        resume="Lire une grandeur d'un AUTRE instrument du panneau.",
        quand="Filtre de regime, ou ratio de paire.",
        arbre={"type": "peer", "symbol": "NQ.v.0", "inner": _prix("close")},
        attention=(
            "Exige que l'instrument soit declare dans `data[]` et que la "
            "strategie soit transversale (`panel_rules@1`). Un `peer` sous un "
            "noeud qui RECULE recule aussi le pair, par les regles du panneau."
        ),
    ),
    Composition(
        nom="donnee_exogene_fraiche",
        resume=(
            "Lire une serie exogene declaree, en refusant une valeur perimee."
        ),
        quand="COT, open interest, sentiment - tout ce qui ne vient pas du prix.",
        arbre={
            "type": "all_of",
            "operands": [
                _cmp("<", {"type": "exogenous", "name": "cot_net",
                           "field": "age_minutes"}, _cst(10080.0)),
                _cmp(">", {"type": "exogenous", "name": "cot_net"}, _cst(0.0)),
            ],
        },
        attention=(
            "Le controle d'age n'est pas un confort : une serie qui cesse "
            "d'etre alimentee rend sa DERNIERE valeur indefiniment, et la "
            "strategie tourne sur un fossile sans que rien ne le signale."
        ),
    ),
)


def describe_compositions() -> SpecDict:
    """Les recettes, pretes a entrer dans le squelette."""
    return {c.nom: c.describe() for c in COMPOSITIONS}
