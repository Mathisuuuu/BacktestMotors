"""Ce qu'on peut dire d'une specification AVANT de la faire tourner.

Pourquoi ce module existe
--------------------------
Le 2026-09-15, la replication de Zarattini a coute une matinee. Cinq ecarts
ont ete trouves ; **trois venaient du meme defaut**, et ce defaut n'est ni un
bug du moteur ni une negligence de lecture :

    plusieurs termes du vocabulaire ont un NOM qui promet plus que leur
    DEFINITION ne livre.

`is_last` ne veut pas dire « la derniere barre de la seance » : il veut dire
« la premiere barre a atteindre l'heure de fermeture DECLAREE ». Sur une
seance pleine les deux coincident ; sur une demi-journee, aucune barre
n'atteint l'heure declaree et **aucune n'est marquee**. Une regle de securite
adossee a `is_last` n'y declenche jamais.

Ce n'est pas un accident de nommage rattrapable par un meilleur nom. « La
derniere barre » est un fait FUTUR - pour le savoir il faudrait regarder la
barre suivante. Le champ ne peut donc pas tenir la promesse de son nom, et
c'est la garantie anti-look-ahead qui remonte a la surface.

Le remede n'est pas de deviner a la place de l'utilisateur. C'est de le DIRE,
avant le run, quand la correction coute une minute plutot qu'un quart d'heure
de calcul suivi d'une enquete.

Ce que ce module n'est pas
---------------------------
Ce n'est pas un validateur : la specification est deja validee par pydantic et
par le JSON Schema, et ce qui est invalide LEVE. Ce sont des controles de
COHERENCE entre une specification valide et les donnees qu'elle designe -
exactement la zone ou le socle ne peut ni refuser ni deviner.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from rsl.config import BacktestSpec
from rsl.data.schema import BarStore

SpecDict = dict[str, Any]


class Gravite(StrEnum):
    """Trois niveaux, et un seul arrete le run.

    `ERREUR` n'est pas « invalide » - la specification tourne. C'est
    « le resultat ne mesurera pas ce que la specification a l'air de dire ».
    """

    INFO = "info"
    AVERTISSEMENT = "avertissement"
    ERREUR = "erreur"


_MARQUES = {
    Gravite.INFO: "note ",
    Gravite.AVERTISSEMENT: "ATTN ",
    Gravite.ERREUR: "ERR  ",
}


@dataclass(frozen=True, slots=True)
class Constat:
    """Un controle qui a mordu.

    `remede` n'est pas decoratif : un constat sans geste a faire se lit deux
    fois puis s'ignore. C'est la lecon que le ledger impose aux idees
    abandonnees, appliquee aux avertissements.
    """

    gravite: Gravite
    code: str
    message: str
    remede: str

    def render(self) -> list[str]:
        return [
            f"{_MARQUES[self.gravite]}[{self.code}] {self.message}",
            f"       -> {self.remede}",
        ]


# ---------------------------------------------------------------------------
# Parcours de l'arbre
# ---------------------------------------------------------------------------


def noeuds(arbre: object) -> Iterator[SpecDict]:
    """Tous les dictionnaires de noeud de l'arbre, en profondeur."""
    if isinstance(arbre, list):
        for element in arbre:
            yield from noeuds(element)
        return
    if not isinstance(arbre, dict):
        return
    if isinstance(arbre.get("type"), str):
        yield arbre
    for valeur in arbre.values():
        yield from noeuds(valeur)


def regles_de(spec: BacktestSpec) -> Mapping[str, object]:
    """Les regles nommees de la strategie, quel que soit le moule."""
    params = spec.strategy.params
    regles = params.get("rules") if isinstance(params, dict) else None
    return regles if isinstance(regles, dict) else {}


def cite(arbre: object, type_: str, **champs: object) -> bool:
    """L'arbre contient-il un noeud de ce type avec ces champs ?"""
    for noeud in noeuds(arbre):
        if noeud.get("type") != type_:
            continue
        if all(noeud.get(cle) == valeur for cle, valeur in champs.items()):
            return True
    return False


# ---------------------------------------------------------------------------
# Les controles
# ---------------------------------------------------------------------------


def _seances_sans_cloture(stores: Mapping[str, BarStore]) -> tuple[int, int]:
    total = manquantes = 0
    for store in stores.values():
        index = store.sessions
        if index is None:
            continue
        total += int(index.n_sessions)
        manquantes += int(index.n_sessions) - int(
            np.count_nonzero(np.asarray(index.is_last))
        )
    return total, max(manquantes, 0)


def controle_is_last(
    spec: BacktestSpec, stores: Mapping[str, BarStore]
) -> list[Constat]:
    """Une regle citant `is_last` sur un echantillon qui en manque.

    Trace du 2026-09-15 : **90 seances sur 2 748** de NQ - les demi-journees
    de 13:00 et 13:15 - n'ont aucune barre marquee, et la cloture forcee de
    Zarattini ne s'y declenchait jamais.
    """
    regles = regles_de(spec)
    citantes = [
        nom
        for nom, regle in regles.items()
        if cite(regle, "session", field="is_last")
    ]
    if not citantes:
        return []
    total, manquantes = _seances_sans_cloture(stores)
    if manquantes == 0:
        return []
    part = manquantes / total * 100 if total else 0.0
    return [
        Constat(
            gravite=Gravite.ERREUR,
            code="is_last-absent",
            message=(
                f"{', '.join(sorted(citantes))} cite `session.is_last`, mais "
                f"{manquantes} seance(s) sur {total} ({part:.1f} %) n'en "
                f"portent AUCUNE : la regle n'y declenchera jamais."
            ),
            remede=(
                "`is_last` marque la PREMIERE barre atteignant l'heure de "
                "fermeture DECLAREE, pas la derniere barre de la seance - une "
                "seance ecourtee n'en a donc aucune. Soit sortir sur "
                "`minutes_from_open >= N`, soit accepter ces seances en le "
                "declarant dans une `note`."
            ),
        )
    ]


def controle_fill_de_nuit(
    spec: BacktestSpec, stores: Mapping[str, BarStore]
) -> list[Constat]:
    """Une sortie a la derniere barre se remplit la seance SUIVANTE.

    Trace du 2026-09-15 : 17 fills de Zarattini franchissaient une frontiere
    de seance, avec 31 points de gap moyen contre 0,28 sur une barre
    ordinaire.
    """
    regles = regles_de(spec)
    sorties = [
        nom
        for nom, regle in regles.items()
        if nom.startswith("exit") and cite(regle, "session", field="is_last")
    ]
    if not sorties or spec.execution.lag_bars < 1:
        return []
    if spec.execution.max_fill_gap_seconds is not None:
        return []
    return [
        Constat(
            gravite=Gravite.AVERTISSEMENT,
            code="fill-de-nuit",
            message=(
                f"{', '.join(sorted(sorties))} sort sur la derniere barre de "
                f"seance ; avec `lag_bars: {spec.execution.lag_bars}`, l'ordre "
                f"se remplira a l'ouverture de la barre SUIVANTE - la premiere "
                f"de la seance d'apres."
            ),
            remede=(
                "Declarer `execution.max_fill_gap_seconds` pour faire EXPIRER "
                "un ordre dont le fill traverserait la nuit, ou sortir une "
                "barre plus tot. Le rapport compte ces franchissements et leur "
                "gap sous « Nuit »."
            ),
        )
    ]


def controle_vol_target(
    spec: BacktestSpec, stores: Mapping[str, BarStore]
) -> list[Constat]:
    """`vol_target` compte sa fenetre en BARRES, pas en seances.

    Trace du 2026-09-15 : sur des barres d'une minute, `vol_window: 60`
    mesure une volatilite PAR MINUTE. L'ecart avec une volatilite de seance
    est d'un facteur `sqrt(390)`, soit pres de vingt (ledger, 2026-09-15).
    """
    if spec.risk.sizing.kind != "vol_target":
        return []
    # `Granularity.minutes` est un CONSTRUCTEUR, pas la duree : celle-ci se
    # lit dans `nanoseconds`. Le nom promet ici aussi autre chose que ce
    # qu'il livre - le defaut que ce module entier sert a signaler.
    ns_par_minute = 60_000_000_000
    durees = {
        store.granularity.nanoseconds // ns_par_minute
        for store in stores.values()
        if store.granularity.nanoseconds >= ns_par_minute
    }
    intra = sorted(m for m in durees if m < 1440)
    if not intra:
        return []
    fenetre = spec.risk.sizing.vol_window
    return [
        Constat(
            gravite=Gravite.AVERTISSEMENT,
            code="vol-target-en-barres",
            message=(
                f"`risk.sizing.vol_target` avec `vol_window: {fenetre}` sur des "
                f"barres de {intra[0]} min : la fenetre compte des BARRES, donc "
                f"elle mesure une volatilite par {intra[0]} min - pas par seance."
            ),
            remede=(
                "Pour une volatilite de SEANCE, ecrire le dimensionnement en "
                "`risk.sizing.kind = \"signal\"` avec "
                "`rolling(stdev, N, across: \"sessions\")`. C'est ce que fait "
                "`nq_zarattini_60_30_15`."
            ),
        )
    ]


def controle_minutes_from_open(
    spec: BacktestSpec, stores: Mapping[str, BarStore]
) -> list[Constat]:
    """`minutes_from_open` parcourt 1..N et ne vaut JAMAIS zero.

    Une barre est horodatee a sa CLOTURE : la premiere barre d'une seance
    d'une minute clot une minute apres l'ouverture. Comparer a zero donne une
    regle qui ne peut pas se declencher.
    """
    constats: list[Constat] = []
    for nom, regle in regles_de(spec).items():
        for noeud in noeuds(regle):
            if noeud.get("type") != "compare":
                continue
            gauche, droite = noeud.get("left"), noeud.get("right")
            if not isinstance(gauche, dict) or not isinstance(droite, dict):
                continue
            vise_ouverture = (
                gauche.get("type") == "session"
                and gauche.get("field") == "minutes_from_open"
            )
            if not vise_ouverture or droite.get("type") != "constant":
                continue
            if droite.get("value") == 0.0 and noeud.get("op") in ("==", "<"):
                constats.append(
                    Constat(
                        gravite=Gravite.ERREUR,
                        code="minutes-jamais-nulles",
                        message=(
                            f"{nom} compare `minutes_from_open` a zero avec "
                            f"`{noeud.get('op')}` : ce champ parcourt 1..N et ne "
                            f"vaut JAMAIS zero. La regle ne declenchera jamais."
                        ),
                        remede=(
                            "Une barre est horodatee a sa CLOTURE. La barre « a "
                            "l'ouverture » porte `minutes_from_open == 1` sur des "
                            "barres d'une minute. Utiliser `session.is_first`."
                        ),
                    )
                )
    return constats


def controle_rolling_rank(
    spec: BacktestSpec, stores: Mapping[str, BarStore]
) -> list[Constat]:
    """`rolling.rank` est TEMPOREL, jamais transversal."""
    citantes = [
        nom
        for nom, regle in regles_de(spec).items()
        if cite(regle, "rolling", stat="rank")
    ]
    if not citantes:
        return []
    return [
        Constat(
            gravite=Gravite.INFO,
            code="rank-temporel",
            message=(
                f"{', '.join(sorted(citantes))} utilise `rolling.rank` : c'est le "
                f"rang de la valeur COURANTE dans sa propre fenetre de temps, pas "
                f"un rang parmi les instruments du panneau."
            ),
            remede=(
                "Pour classer des instruments entre eux, passer par le moule "
                "`ranking@1`. Il n'existe aucun rang transversal dans le "
                "vocabulaire des signaux."
            ),
        )
    ]


def controle_seance_electronique(
    spec: BacktestSpec, stores: Mapping[str, BarStore]
) -> list[Constat]:
    """Une seance declaree sans `session_only` court jusqu'a l'ouverture suivante.

    Trace du 2026-09-14 : sans filtre, NQ rendait **3 314 seances dont 548 de
    DIMANCHE (16,5 %)** et 1 362 barres par seance au lieu de 390.
    """
    concernees = [
        entree.root
        for entree in spec.data
        if entree.session is not None and not entree.session_only
    ]
    if not concernees:
        return []
    return [
        Constat(
            gravite=Gravite.AVERTISSEMENT,
            code="seance-electronique",
            message=(
                f"{', '.join(sorted(set(concernees)))} declare une `session` sans "
                f"`session_only` : la seance court alors jusqu'a l'OUVERTURE "
                f"SUIVANTE et contient les barres de nuit."
            ),
            remede=(
                "Poser `session_only: true` pour ne garder que les barres dont la "
                "cloture tombe dans la seance declaree. Mesure sur NQ sans le "
                "filtre : 1 362 barres par seance au lieu de 390, et 548 seances "
                "de DIMANCHE sur 3 314."
            ),
        )
    ]


CONTROLES = (
    controle_is_last,
    controle_fill_de_nuit,
    controle_minutes_from_open,
    controle_vol_target,
    controle_seance_electronique,
    controle_rolling_rank,
)


def controler(
    spec: BacktestSpec, stores: Mapping[str, BarStore]
) -> list[Constat]:
    """Tous les controles, dans l'ordre : ce qui arrete d'abord."""
    constats: list[Constat] = []
    for controle in CONTROLES:
        constats.extend(controle(spec, stores))
    ordre = {Gravite.ERREUR: 0, Gravite.AVERTISSEMENT: 1, Gravite.INFO: 2}
    constats.sort(key=lambda c: (ordre[c.gravite], c.code))
    return constats


def render(constats: list[Constat]) -> str:
    """Le rapport texte. Le silence est un resultat, et il se dit."""
    if not constats:
        return "Aucun constat : la specification et les donnees s'accordent."
    lignes: list[str] = []
    for constat in constats:
        lignes.extend(constat.render())
    erreurs = sum(1 for c in constats if c.gravite is Gravite.ERREUR)
    attn = sum(1 for c in constats if c.gravite is Gravite.AVERTISSEMENT)
    infos = sum(1 for c in constats if c.gravite is Gravite.INFO)
    lignes.append("")
    lignes.append(f"{erreurs} erreur(s), {attn} avertissement(s), {infos} note(s)")
    return "\n".join(lignes)
