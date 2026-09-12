"""Construire la matrice que la CSCV attend, a partir de vraies specifications.

Le calcul est dans `metrics/surapprentissage.py` ; ce module fournit ce qu'on
lui donne a manger. La separation n'est pas cosmetique : l'estimateur est une
fonction pure sur une matrice, testable sans donnees, et c'est ICI que vivent
les decisions discutables - comment decouper, quoi mesurer par sous-periode, et
quoi refuser.

Ce que la grille doit respecter
--------------------------------
Toutes les configurations doivent etre evaluees sur le MEME echantillon. C'est
la condition sans laquelle la CSCV ne veut rien dire : comparer une
configuration mesuree sur 2016-2026 a une autre mesuree sur 2018-2024 ne
compare pas des strategies, mais des epoques. Le module le verifie plutot que
de l'esperer - deux courbes d'equity de longueurs differentes sont refusees.

Pourquoi une grille ne partage PAS son echantillon naturellement
-----------------------------------------------------------------
Decouvert le 2026-09-12, en lancant la premiere grille reelle. Une strategie de
croisement a 200 barres de fenetre lente commence 200 barres plus tard qu'une a
50 : sur ES quotidien, la grille 4x4 des fenetres usuelles donnait quatre
longueurs differentes - 2701, 2651, 2601 et 2551 rendements.

Les comparer telles quelles compare des EPOQUES : les configurations a fenetre
courte incluent le debut de 2016 que les autres n'ont pas. La CSCV recombinerait
alors des blocs qui ne recouvrent pas les memes dates, et le rang hors
echantillon melangerait « meilleure strategie » et « meilleure periode ».

D'ou l'alignement : le warmup de TOUTE la grille est porte au maximum de ses
membres, via `min_warmup_bars`. Chaque configuration voit alors exactement les
memes barres. Le cout est reel et il est rapporte - ici 150 barres perdues au
debut - et il est le prix de la comparabilite, pas un reglage a optimiser.

L'alternative - refuser les grilles a fenetres inegales - reviendrait a
interdire la seule grille que l'on veuille vraiment mesurer.

Le retrait des inactives n'est PAS neutre a grande echelle
-----------------------------------------------------------
Mesure le 2026-09-12 sur une grille de 462 configurations, ES quotidien, S=8 :
**357 retirees**, soit 77 %, toutes sur la sous-periode 0.

Le motif n'a rien d'aleatoire. Une strategie de croisement entre en position
sur un CROISEMENT ; si aucun ne se produit pendant un bloc, elle reste plate.
Plus la fenetre lente est longue, plus les croisements sont rares - et la
premiere sous-periode d'ES tombe sur 2017, une annee de tendance calme ou les
longues moyennes ne se croisent pas.

Le retrait elimine donc **systematiquement les fenetres longues**, et la PBO qui
suit porte sur un sous-ensemble biaise vers les fenetres courtes. Ce n'est pas
un defaut du retrait - donner zero a ces configurations serait pire - mais une
raison de lire `n_configurations` du resultat plutot que la taille de la grille
qu'on croit avoir soumise.

L'arbitrage qui en decoule : moins de sous-periodes laissent survivre plus de
configurations (les blocs sont plus longs, donc plus susceptibles de contenir un
croisement) mais donnent moins de combinaisons. Les deux termes tirent en sens
inverse, et aucune valeur de S ne les satisfait tous les deux.

Le decoupage
------------
`S` blocs CONTIGUS et de meme taille, dans l'ordre du temps. Les barres en trop
- quand la longueur n'est pas divisible par `S` - sont retirees a la FIN et le
rapport le dit. Les retirer au debut ferait disparaitre le warmup ; les repartir
donnerait des blocs de tailles differentes, donc des Sharpe non comparables
entre eux.

Contigus, et non entrelaces : la CSCV recombine ensuite les blocs de toutes les
facons possibles, ce qui est deja le brassage. Entrelacer en amont melangerait
les epoques a l'interieur d'un bloc et effacerait justement ce que la methode
cherche - la dependance du resultat a la periode.

Ce que la performance d'un bloc est ici
----------------------------------------
Le Sharpe PAR PERIODE des rendements du bloc, par le meme chemin que partout
ailleurs (`to_daily`, `simple_returns`, `sharpe_per_period`).

Un bloc sans dispersion n'a pas de Sharpe. Cela arrive vraiment, et pas comme
un cas limite : une strategie de croisement peu active peut ne prendre AUCUNE
position pendant un huitieme de l'echantillon - le walk-forward de
`sma_es_daily` a un pli entier a zero trade.

Lui donner zero serait une opinion et non une mesure : un zero la classerait
au-dessus de toutes les configurations perdantes, ce qui flatte l'inactivite.
Le defaut est donc de REFUSER, en nommant la configuration et la sous-periode.
`ignorer_inactives=True` la retire de la grille au lieu de refuser - le retrait
est rapporte, configuration par configuration, et il fait retrecir la grille de
facon visible. Ce qu'il ne faut pas perdre de vue : les retirees ne sont pas
neutres, ce sont des configurations qui n'ont rien fait, et la PBO qui suit
porte sur celles qui restent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rsl.config import BacktestSpec
from rsl.errors import ConfigurationError
from rsl.manifest import canonical_hash
from rsl.metrics.performance import sharpe_per_period, simple_returns, to_daily
from rsl.metrics.surapprentissage import ResultatPBO, probability_of_backtest_overfitting
from rsl.report import run_backtest_detailed
from rsl.strategies.base import build_strategy

SpecDict = dict[str, object]
FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Grille:
    """La matrice, et de quoi la relire.

    Les noms et les `config_hash` sont portes avec la matrice parce qu'une
    matrice anonyme ne se relit pas : « la configuration 7 gagne » n'est
    utilisable que si l'on sait laquelle c'est.
    """

    matrice: FloatArray
    labels: tuple[str, ...]
    config_hashes: tuple[str, ...]
    n_sous_periodes: int
    barres_par_bloc: int
    barres_ecartees: int
    warnings: tuple[str, ...] = ()
    rapports: tuple[SpecDict, ...] = ()
    """Le rapport complet de chaque configuration RETENUE.

    Hors de `describe` : quelques centaines de rapports feraient un fichier de
    grille de plusieurs dizaines de Mo. Ils servent a l'archivage, qui en tire
    une ligne de registre par configuration - le compteur du Deflated Sharpe en
    a besoin."""


    def evaluer(self) -> ResultatPBO:
        return probability_of_backtest_overfitting(self.matrice, self.n_sous_periodes)

    def describe(self) -> SpecDict:
        return {
            "labels": list(self.labels),
            "config_hashes": list(self.config_hashes),
            "n_sous_periodes": self.n_sous_periodes,
            "barres_par_bloc": self.barres_par_bloc,
            "barres_ecartees": self.barres_ecartees,
            "matrice": [[float(v) for v in ligne] for ligne in self.matrice],
            "warnings": list(self.warnings),
        }

    def render(self) -> str:
        entete = "  ".join(f"S{i}" for i in range(self.n_sous_periodes))
        lignes = [
            f"Grille       {len(self.labels)} configurations x "
            f"{self.n_sous_periodes} sous-periodes de {self.barres_par_bloc} barres",
        ]
        if self.barres_ecartees:
            lignes.append(
                f"Ecartees     {self.barres_ecartees} barre(s) en fin d'echantillon "
                f"(longueur non divisible par S)"
            )
        lignes.append(f"{'':<34}{entete}")
        for nom, ligne in zip(self.labels, self.matrice, strict=True):
            valeurs = "  ".join(f"{v:+.3f}" for v in ligne)
            lignes.append(f"{nom[:32]:<34}{valeurs}")
        return "\n".join(lignes)


def rendements_du_run(spec: BacktestSpec) -> tuple[FloatArray, SpecDict]:
    """Les rendements quotidiens d'une specification, et son rapport complet.

    Derives par LE MEME chemin que `compute_performance` : une seconde
    definition de « un rendement » finirait par diverger de la premiere.
    """
    artefacts = run_backtest_detailed(spec)
    _, equity = to_daily(
        np.asarray(artefacts.result.equity.ts_ns, dtype=np.int64),
        np.asarray(artefacts.result.equity.equity, dtype=np.float64),
    )
    return simple_returns(equity), artefacts.report.to_dict()


def warmup_naturel(spec: BacktestSpec) -> int:
    """Le nombre de barres qu'une specification consomme avant de decider.

    Calcule SANS lire les donnees : c'est exactement ce que fait le runner -
    le maximum entre la profondeur de la strategie, celle de la regle de
    dimensionnement, et le plancher declare. Le recalculer ici plutot que de
    l'observer apres coup evite un second run par configuration.
    """
    strategie = build_strategy(spec.strategy.as_dict())
    return max(
        strategie.warmup_bars,
        spec.build_risk().warmup_bars,
        spec.min_warmup_bars,
    )


def aligner_sur_un_echantillon_commun(
    specs: Sequence[BacktestSpec],
) -> tuple[list[BacktestSpec], int]:
    """Porte le warmup de toute la grille au maximum de ses membres.

    Rend les specifications alignees et le warmup retenu. Voir l'en-tete du
    module : sans cela, une grille de fenetres inegales compare des epoques.

    Les specifications d'origine ne sont pas modifiees - `model_copy` en rend
    de nouvelles. Une grille qui muterait ce qu'on lui passe rendrait le second
    appel different du premier.
    """
    plancher = max(warmup_naturel(spec) for spec in specs)
    return (
        [spec.model_copy(update={"min_warmup_bars": plancher}) for spec in specs],
        plancher,
    )


def construire_grille(
    specs: Sequence[BacktestSpec],
    n_sous_periodes: int,
    *,
    aligner: bool = True,
    ignorer_inactives: bool = False,
) -> Grille:
    """Execute chaque configuration et decoupe ses rendements en `S` blocs.

    `aligner` porte le warmup de toute la grille au maximum de ses membres,
    pour que chaque configuration voie les MEMES barres. C'est le defaut, parce
    que c'est la condition de validite de la CSCV ; `aligner=False` le refuse
    explicitement et fait lever la verification de longueur, ce qui sert a
    constater le probleme plutot qu'a le contourner.

    `ignorer_inactives` retire les configurations sans dispersion sur au moins
    une sous-periode, au lieu de refuser. Faux par defaut : le retrait change
    la grille sur laquelle la PBO porte, et cela doit etre demande.

    Refuse plutot que de rapiecer, dans trois cas qui rendraient tous la PBO
    plausible et fausse : moins de deux configurations, des echantillons de
    longueurs differentes, et un bloc dont le Sharpe n'est pas defini.
    """
    if len(specs) < 2:
        raise ConfigurationError(
            f"{len(specs)} configuration(s) : la PBO mesure le surapprentissage "
            f"d'une SELECTION. Sans choix a faire, il n'y a rien a mesurer."
        )
    if n_sous_periodes < 2 or n_sous_periodes % 2 != 0:
        raise ConfigurationError(
            f"S doit etre PAIR et >= 2, recu {n_sous_periodes}"
        )

    aligne: list[str] = []
    if aligner:
        specs, plancher = aligner_sur_un_echantillon_commun(specs)
        aligne.append(
            f"warmup porte a {plancher} barres pour toute la grille : sans cela, "
            f"les configurations a fenetre courte verraient un debut d'echantillon "
            f"que les autres n'ont pas, et la CSCV comparerait des epoques."
        )

    executes = [rendements_du_run(spec) for spec in specs]
    series = [serie for serie, _ in executes]
    rapports = [rapport for _, rapport in executes]
    longueurs = {int(s.size) for s in series}
    if len(longueurs) > 1:
        detail = ", ".join(
            f"{spec.name}={s.size}" for spec, s in zip(specs, series, strict=True)
        )
        raise ConfigurationError(
            f"les configurations ne couvrent pas le meme echantillon ({detail}). "
            f"Comparer des epoques differentes ne compare pas des strategies."
        )

    total = longueurs.pop()
    par_bloc = total // n_sous_periodes
    if par_bloc < 2:
        raise ConfigurationError(
            f"{total} rendements pour {n_sous_periodes} sous-periodes : "
            f"{par_bloc} par bloc. Un Sharpe demande au moins deux observations ; "
            f"baisser S ou allonger l'echantillon."
        )
    ecartees = total - par_bloc * n_sous_periodes

    avertissements: list[str] = list(aligne)
    if par_bloc < 30:
        avertissements.append(
            f"{par_bloc} rendements par sous-periode : un Sharpe calcule sur si peu "
            f"de points est domine par le bruit, et la PBO en herite."
        )

    lignes: list[list[float]] = []
    retenues: list[BacktestSpec] = []
    retenus: list[SpecDict] = []
    inactives: list[str] = []
    for spec, serie, rapport in zip(specs, series, rapports, strict=True):
        ligne: list[float] = []
        muette: int | None = None
        for bloc in range(n_sous_periodes):
            morceau = serie[bloc * par_bloc : (bloc + 1) * par_bloc]
            valeur = sharpe_per_period(morceau)
            if valeur is None:
                muette = bloc
                break
            ligne.append(valeur)
        if muette is not None:
            if not ignorer_inactives:
                raise ConfigurationError(
                    f"'{spec.name}' n'a pas de Sharpe defini sur la sous-periode "
                    f"{muette} (dispersion nulle - la configuration n'y a rien "
                    f"fait). Lui donner zero la classerait au-dessus de toutes "
                    f"les perdantes, ce qui flatte l'inactivite. La retirer de la "
                    f"grille, ou demander `ignorer_inactives` / `--drop-idle`."
                )
            inactives.append(f"{spec.name} (sous-periode {muette})")
            continue
        lignes.append(ligne)
        retenues.append(spec)
        retenus.append(rapport)

    if len(retenues) < 2:
        raise ConfigurationError(
            f"il ne reste que {len(retenues)} configuration(s) apres retrait des "
            f"inactives ({', '.join(inactives)}). Une grille dont la plupart des "
            f"membres ne negocient pas sur une sous-periode ne mesure pas une "
            f"selection : baisser S, ou construire une grille plus active."
        )
    if inactives:
        avertissements.append(
            f"{len(inactives)} configuration(s) RETIREE(S) faute d'activite sur une "
            f"sous-periode : {', '.join(inactives)}. Elles ne sont pas neutres - "
            f"la PBO ci-dessous porte sur les {len(retenues)} restantes."
        )

    return Grille(
        matrice=np.asarray(lignes, dtype=np.float64),
        labels=tuple(spec.name for spec in retenues),
        config_hashes=tuple(canonical_hash(spec.canonical()) for spec in retenues),
        rapports=tuple(retenus),
        n_sous_periodes=n_sous_periodes,
        barres_par_bloc=par_bloc,
        barres_ecartees=ecartees,
        warnings=tuple(avertissements),
    )
