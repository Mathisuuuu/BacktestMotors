"""Interface en ligne de commande.

    rsl validate FICHIER...     valide des fichiers de donnees
    rsl instruments             table des contrats
    rsl catalogue               primitives, noeuds et strategies enregistres
    rsl schema                  JSON Schema du vocabulaire, a rediriger
    rsl example                 specification d'exemple, a rediriger
    rsl run CONFIG              execute un backtest et ecrit son rapport
    rsl walkforward CONFIG      evalue par fenetres successives
    rsl verify CONFIG           execute deux fois et compare les empreintes
    rsl essais                  registre des essais : ce que le DSR compte
    rsl pbo CONFIG...           probabilite de surapprentissage d'une grille

`verify` merite d'exister comme commande a part entiere. L'exigence "deux runs
identiques produisent des resultats bit-a-bit identiques" est facile a ecrire
dans un document et facile a perdre dans le code ; une commande qui la
constate la rend operationnelle.

Codes de sortie : 0 succes, 1 erreur d'usage ou d'execution, 2 verification
echouee (donnees rejetees, empreintes divergentes). Un script d'integration
peut donc distinguer "je n'ai pas pu" de "j'ai pu, et c'est faux".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from rsl.composition import StrategyFile, compose, est_fichier_de_strategie
from rsl.config import BacktestSpec, load_stores
from rsl.controles import Gravite, controler, render
from rsl.data.instruments import INSTRUMENTS, get_instrument
from rsl.data.loader import validate_file
from rsl.errors import ConfigurationError, RslError
from rsl.essais import EssaiDejaArchiveError, Registre, registre_par_defaut
from rsl.manifest import canonical_hash
from rsl.metrics.statistics import AnchoredWalkForward, RollingWalkForward
from rsl.metrics.surapprentissage import ResultatPBO
from rsl.pbo import Grille, construire_grille
from rsl.primitives.registry import describe_registry
from rsl.report import BacktestReport, run_backtest
from rsl.skeleton import build_skeleton
from rsl.strategies.base import describe_strategies
from rsl.strategies.signals import describe_node_types, signal_json_schema
from rsl.walkforward import WalkForwardReport, run_walk_forward

SpecDict = dict[str, object]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CHECK_FAILED = 2

EXAMPLE_STRATEGY: dict[str, object] = {
    "format": "rsl-strategy@1",
    "name": "sma-crossover-es-quotidien",
    "note": [
        "Croisement 20/100. Le fichier ne nomme NI l'actif, NI le capital, NI",
        "les couts : ce sont des choix de run, pas de strategie, et ils se",
        "donnent par `--settings` ou dans l'onglet MONTAGE de `rsl gui`.",
    ],
    "strategy": {
        "ref": "sma_crossover@1",
        "params": {"fast_window": 20, "slow_window": 100},
    },
}

EXAMPLE_SETTINGS: dict[str, object] = {
    "initial_cash": 500000.0,
    "seed": 0,
    "risk_free_annual": 0.0,
    "data": [
        {
            "root": "ES",
            "path": "indices/ES_v0_1m.parquet",
            "granularity_minutes": 1,
            "resample": "day",
            "resample_min_bars": 200,
        }
    ],
    "execution": {
        "fees": {"kind": "per_contract"},
        "slippage": {"kind": "tick", "ticks": 1.0},
        "lag_bars": 1,
        "intrabar_priority": "pessimistic",
        "margin_policy": "reject",
    },
    "risk": {"sizing": {"kind": "fixed", "contracts": 1}},
}


def sortie_en_utf8() -> None:
    """Force `stdout` et `stderr` en UTF-8, quelle que soit la machine.

    Le probleme
    -----------
    Sous Windows, `sys.stdout` prend l'encodage de la locale des qu'il est
    REDIRIGE : `cp1252` ici. `rsl schema --what all > contrat.json` produisait
    donc un fichier en cp1252 qu'aucun lecteur JSON n'ouvre en UTF-8 - mesure
    le 2026-09-12 : octet `0xa7` en position 126, la ou le texte porte un `§`.
    `--out` n'etait pas touche, parce qu'il ouvre le fichier en UTF-8
    explicitement.

    Le meme jour, TROIS des neuf commandes qui ecrivent etaient deja cassees
    (`schema --what all`, `--what spec`, `--what strategies` : `§`, `«`, `»`).
    Les six autres passaient uniquement parce que leur sortie etait purement
    ASCII - c'est-a-dire par chance, et jusqu'au premier caractere accentue
    ajoute a une docstring. C'est la raison pour laquelle la correction est
    ici : compter les commandes atteintes aujourd'hui ne dit rien de celles
    qui le seront demain.

    Pire que le fichier illisible : un caractere ABSENT de cp1252 ne se
    degrade pas, il leve. Verifie, toujours le 2026-09-12 : une fleche `->` ou
    un `>=` typographique dans une description donne `UnicodeEncodeError`,
    code de sortie 1, et une sortie tronquee au milieu.

    Pourquoi ici plutot que dans `_cmd_schema`
    -------------------------------------------
    Parce que le defaut n'appartient pas a `schema`. Il appartient a toute
    commande qui ecrit, et corriger la seule qui saignait aujourd'hui aurait
    laisse les six autres attendre leur tour. La propriete voulue est que la
    sortie du programme **ne depende pas de la machine qui l'execute** - la
    meme exigence que pour un `config_hash`.

    Le garde `hasattr` n'est pas de la prudence decorative : sous pytest,
    `sys.stdout` est un objet de capture qui n'est pas un `TextIOWrapper` et
    n'a pas de `reconfigure`.

    Ce que cela ne resout pas : une console Windows reglee sur une page de
    code ancienne affichera mal ces caracteres. C'est du RENDU, pas de la
    donnee - le fichier redirige, lui, est juste.
    """
    for flux in (sys.stdout, sys.stderr):
        reconfigurer = getattr(flux, "reconfigure", None)
        if callable(reconfigurer):
            reconfigurer(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    sortie_en_utf8()
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_ERROR
    try:
        return int(handler(args))
    except RslError as error:
        print(f"erreur : {error}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as error:
        print(f"fichier introuvable : {error}", file=sys.stderr)
        return EXIT_ERROR


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rsl",
        description="Socle de backtest deterministe, sans look-ahead par construction.",
    )
    sub = parser.add_subparsers(dest="command")

    validate = sub.add_parser("validate", help="valide des fichiers de donnees")
    validate.add_argument("paths", nargs="+", type=Path)
    validate.add_argument(
        "--root",
        help="racine du contrat. Par defaut, deduite du nom de fichier (ES_v0_1m -> ES).",
    )
    validate.add_argument("--json", action="store_true", help="sortie JSON")
    validate.set_defaults(handler=_cmd_validate)

    instruments = sub.add_parser("instruments", help="table des contrats")
    instruments.add_argument("--json", action="store_true")
    instruments.set_defaults(handler=_cmd_instruments)

    catalogue = sub.add_parser(
        "catalogue", help="primitives, noeuds et strategies enregistres"
    )
    catalogue.add_argument("--json", action="store_true")
    catalogue.set_defaults(handler=_cmd_catalogue)

    schema = sub.add_parser(
        "schema", help="JSON Schema du vocabulaire (signaux, strategies, specification)"
    )
    schema.add_argument(
        "--what",
        choices=("signals", "strategies", "spec", "all"),
        default="signals",
        help="quelle partie publier (defaut : signals)",
    )
    schema.add_argument("--out", type=Path, help="ecrit dans ce fichier")
    schema.set_defaults(handler=_cmd_schema)

    example = sub.add_parser(
        "example", help="strategie d'exemple, ou reglages de run"
    )
    example.add_argument(
        "--what",
        choices=("strategy", "settings"),
        default="strategy",
        help=(
            "`strategy` (defaut) : ce qu'on ECRIT. `settings` : l'actif, le "
            "capital et les couts, que la fenetre choisit aussi."
        ),
    )
    example.set_defaults(handler=_cmd_example)

    check = sub.add_parser(
        "check",
        help="confronte une specification a ses donnees, sans la lancer",
    )
    check.add_argument("config", type=Path)
    check.add_argument(
        "--settings",
        type=Path,
        help="reglages du run quand CONFIG est une strategie seule",
    )
    check.add_argument(
        "--symbol",
        help="instrument sur lequel appliquer une strategie mono-instrument",
    )

    check.set_defaults(handler=_cmd_check)

    run = sub.add_parser("run", help="execute un backtest")
    run.add_argument("config", type=Path)
    run.add_argument(
        "--settings",
        type=Path,
        help=(
            "reglages du run (actif, capital, couts) quand CONFIG est une "
            "strategie seule"
        ),
    )
    run.add_argument(
        "--symbol",
        help="instrument sur lequel appliquer une strategie mono-instrument",
    )
    run.add_argument("--out", type=Path, help="ecrit le rapport JSON dans ce fichier")
    run.add_argument("--json", action="store_true", help="affiche le rapport JSON")
    run.add_argument(
        "--gui",
        action="store_true",
        help="ouvre le tableau de bord a la fin du run",
    )
    run.add_argument(
        "--archive",
        action="store_true",
        help=(
            "enregistre ce run comme un ESSAI dans essais/ et compte le "
            "Deflated Sharpe contre tous les essais deja enregistres. Sans lui, "
            "le run se declare seul et son DSR se confond avec son PSR."
        ),
    )
    run.add_argument(
        "--note",
        default="",
        help="pourquoi cet essai a ete fait. Archive avec lui ; ignore sans --archive.",
    )
    run.set_defaults(handler=_cmd_run)

    essais = sub.add_parser(
        "essais", help="registre des essais : ce que le Deflated Sharpe compte"
    )
    essais.add_argument(
        "--json", action="store_true", help="sortie JSON plutot que tableau"
    )
    essais.set_defaults(handler=_cmd_essais)

    pbo = sub.add_parser(
        "pbo",
        help="probabilite de surapprentissage (CSCV) d'une grille de configurations",
    )
    pbo.add_argument(
        "configs",
        type=Path,
        nargs="+",
        help=(
            "au moins DEUX specifications, evaluees sur le meme echantillon. "
            "Un REPERTOIRE est developpe en ses fichiers .json, tries - c'est "
            "la forme a utiliser pour une grille de plusieurs centaines, que la "
            "ligne de commande ne peut pas porter. La PBO mesure le "
            "surapprentissage d'une SELECTION : sans choix a faire, il n'y a "
            "rien a mesurer."
        ),
    )
    pbo.add_argument(
        "--settings",
        type=Path,
        help="reglages communs, quand les CONFIGS sont des strategies seules",
    )
    pbo.add_argument("--symbol", help="instrument, pour une strategie mono-instrument")
    pbo.add_argument(
        "--blocks",
        type=int,
        default=8,
        help=(
            "nombre de sous-periodes S, PAIR. Le nombre de combinaisons croit "
            "comme C(S, S/2) : 70 a S=8, 252 a S=10, 184 756 a S=20. Defaut : 8."
        ),
    )
    pbo.add_argument(
        "--drop-idle",
        action="store_true",
        help=(
            "retire les configurations qui n'ont pris AUCUNE position sur une "
            "sous-periode, au lieu de refuser. Le retrait est nomme : ces "
            "configurations ne sont pas neutres, et la PBO porte alors sur les "
            "restantes."
        ),
    )
    pbo.add_argument(
        "--archive",
        action="store_true",
        help=(
            "enregistre CHAQUE configuration de la grille comme un essai. Un "
            "balayage de N configurations est N essais : sous-compter gonfle le "
            "Deflated Sharpe de tous les autres. Un seul artefact est ecrit, "
            "partage par les N lignes."
        ),
    )
    pbo.add_argument(
        "--note", default="", help="pourquoi cette grille a ete evaluee"
    )
    pbo.add_argument("--out", type=Path, help="ecrit le resultat JSON dans ce fichier")
    pbo.add_argument("--json", action="store_true", help="affiche le JSON")
    pbo.set_defaults(handler=_cmd_pbo)

    squelette = sub.add_parser(
        "squelette",
        help="squelette a trous : tout ce qu'on peut ecrire dans une specification",
    )
    squelette.add_argument("--out", type=Path, help="ecrit le squelette dans ce fichier")
    squelette.set_defaults(handler=_cmd_squelette)

    gui = sub.add_parser("gui", help="tableau de bord graphique des resultats")
    gui.add_argument(
        "config",
        type=Path,
        nargs="?",
        help="specification a executer au demarrage. Sans elle, la fenetre "
        "s'ouvre vide et propose de charger un JSON.",
    )
    gui.set_defaults(handler=_cmd_gui)

    walk = sub.add_parser(
        "walkforward", help="evalue la strategie par fenetres successives"
    )
    walk.add_argument("config", type=Path)
    walk.add_argument(
        "--settings",
        type=Path,
        help=(
            "reglages du run (actif, capital, couts) quand CONFIG est une "
            "strategie seule"
        ),
    )
    walk.add_argument(
        "--symbol",
        help="instrument sur lequel appliquer une strategie mono-instrument",
    )
    walk.add_argument("--train", type=int, required=True, help="barres d'apprentissage")
    walk.add_argument("--test", type=int, required=True, help="barres de test par pli")
    walk.add_argument("--step", type=int, help="pas entre plis (defaut : la taille du test)")
    walk.add_argument(
        "--anchored",
        action="store_true",
        help=(
            "fenetre d'apprentissage ancree au debut. Sans selection de parametres, "
            "donne les memes plis que le mode glissant."
        ),
    )
    walk.add_argument(
        "--keep-open",
        action="store_true",
        help="ne pas liquider les positions a la fin de chaque pli",
    )
    walk.add_argument("--out", type=Path, help="ecrit le rapport JSON dans ce fichier")
    walk.add_argument("--json", action="store_true")
    walk.add_argument(
        "--archive",
        action="store_true",
        help=(
            "enregistre ce walk-forward comme UN essai dans essais/. Un pli "
            "n'est pas un essai : c'est la meme configuration sur d'autres "
            "donnees, pas une configuration de plus."
        ),
    )
    walk.add_argument(
        "--note",
        default="",
        help="pourquoi cet essai a ete fait. Archive avec lui ; ignore sans --archive.",
    )
    walk.set_defaults(handler=_cmd_walkforward)

    verify = sub.add_parser("verify", help="execute deux fois et compare les empreintes")
    verify.add_argument("config", type=Path)
    verify.add_argument(
        "--settings",
        type=Path,
        help=(
            "reglages du run (actif, capital, couts) quand CONFIG est une "
            "strategie seule"
        ),
    )
    verify.add_argument(
        "--symbol",
        help="instrument sur lequel appliquer une strategie mono-instrument",
    )
    verify.set_defaults(handler=_cmd_verify)

    return parser


# ---------------------------------------------------------------------------
# Commandes
# ---------------------------------------------------------------------------


def _cmd_validate(args: argparse.Namespace) -> int:
    reports = []
    failed = False
    for path in args.paths:
        root = args.root or _infer_root(path)
        report = validate_file(path, symbol=get_instrument(root).symbol)
        reports.append(report)
        failed = failed or not report.is_valid
        if not args.json:
            print(report.render())
            print()
    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2, ensure_ascii=False))
    return EXIT_CHECK_FAILED if failed else EXIT_OK


def _infer_root(path: Path) -> str:
    """`ES_v0_1m.parquet` -> `ES`. Echoue clairement plutot que de deviner mal."""
    candidate = path.stem.split("_")[0]
    get_instrument(candidate)  # leve RegistryError si inconnu
    return candidate


def _cmd_instruments(args: argparse.Namespace) -> int:
    specs = [INSTRUMENTS[key] for key in sorted(INSTRUMENTS)]
    if args.json:
        print(json.dumps([s.model_dump(mode="json") for s in specs], indent=2))
        return EXIT_OK
    print(
        f"{'symbole':10} {'nom':14} {'place':7} {'mult':>10} {'tick':>10} "
        f"{'tick $':>8} {'frais/cote':>11} {'marge':>10}"
    )
    for spec in specs:
        print(
            f"{spec.symbol:10} {spec.name[:14]:14} {spec.exchange:7} "
            f"{spec.multiplier:>10,.0f} {spec.tick_size:>10.7f} "
            f"{spec.multiplier * spec.tick_size:>8.2f} "
            f"{spec.fee_per_contract_per_side:>11.2f} {spec.initial_margin:>10,.0f}"
        )
    print(
        "\nMarges statiques 2025-2026 appliquees a tout l'echantillon : anachroniques\n"
        "avant 2025, et notablement sous-estimees pendant mars 2020."
    )
    return EXIT_OK


def _cmd_catalogue(args: argparse.Namespace) -> int:
    catalogue = {
        "primitives": describe_registry(),
        "signal_nodes": describe_node_types(),
        "strategies": describe_strategies(),
    }
    if args.json:
        print(json.dumps(catalogue, indent=2, ensure_ascii=False))
        return EXIT_OK

    print("PRIMITIVES")
    for item in catalogue["primitives"]:
        print(f"  {item['ref']!s:18} {item['summary']}")
    print("\nNOEUDS DE SIGNAUX")
    for item in catalogue["signal_nodes"]:
        ref = f"{item['type']}@{item['version']}"
        print(f"  {ref:18} {item['summary']}")
    print("\nSTRATEGIES")
    for item in catalogue["strategies"]:
        kind = "transversale" if item["cross_sectional"] else "mono-instrument"
        print(f"  {item['ref']!s:26} [{kind}] {item['summary']}")
    print(
        "\nCe catalogue est le point de branchement de la phase suivante : un\n"
        "compilateur de specifications y lira ce qui existe deja."
    )
    return EXIT_OK


def _cmd_schema(args: argparse.Namespace) -> int:
    """Publie le contrat que doit respecter une specification.

    C'est ce qui permet de valider un fichier AVANT de l'executer - dans un
    editeur, dans une chaine d'integration, ou dans la brique qui produira ces
    fichiers a la place d'un humain. Les schemas sont engendres depuis les
    registres : un type de noeud ou une strategie ajoutee y apparait sans que
    rien d'autre soit touche.
    """
    parts: dict[str, object] = {}
    if args.what in ("signals", "all"):
        parts["signals"] = signal_json_schema()
    if args.what in ("strategies", "all"):
        parts["strategies"] = {
            str(entry["ref"]): entry["params"] for entry in describe_strategies()
        }
    if args.what in ("spec", "all"):
        parts["backtest_spec"] = BacktestSpec.model_json_schema()

    payload = parts if args.what == "all" else next(iter(parts.values()))
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"Schema ecrit dans {args.out}")
    else:
        print(rendered)
    return EXIT_OK


def _cmd_example(args: argparse.Namespace) -> int:
    """Un exemple a rediriger dans un fichier.

    Emet une STRATEGIE par defaut, et non une specification complete : depuis
    le 2026-09-12, ce qu'on ecrit est une strategie. Le montage se choisit dans
    la fenetre, ou se donne par `--settings`.
    """
    charge = (
        EXAMPLE_SETTINGS if args.what == "settings" else EXAMPLE_STRATEGY
    )
    print(json.dumps(charge, indent=2, ensure_ascii=False))
    return EXIT_OK


def _cmd_check(args: argparse.Namespace) -> int:
    """Confronte une specification a ses donnees, SANS la faire tourner.

    Ce que cette commande attrape est la zone ou le socle ne peut ni refuser
    ni deviner : une specification parfaitement valide dont les termes ne
    veulent pas dire ce que leur nom suggere. `is_last` marque la premiere
    barre atteignant l'heure DECLAREE, pas la derniere barre de la seance ;
    `vol_target` compte sa fenetre en BARRES ; `minutes_from_open` ne vaut
    jamais zero.

    Le 2026-09-15, trois des cinq ecarts d'une replication venaient de la, et
    chacun a coute une enquete apres un quart d'heure de calcul. Ils tiennent
    ici en une seconde.

    Code de sortie 2 des qu'un constat est de gravite ERREUR : un script
    d'integration peut donc refuser de lancer le run.
    """
    spec = _load_spec(args.config, args.settings, args.symbol)
    stores, _instruments, _sources = load_stores(spec)
    constats = controler(spec, stores)
    print(render(constats))
    grave = any(c.gravite is Gravite.ERREUR for c in constats)
    return EXIT_CHECK_FAILED if grave else EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    """Execute un backtest, et - avec `--archive` - le compte comme un essai.

    Sans `--archive`, le comportement est celui d'avant : un `TrialLog` vide,
    donc « 1 essai », donc un DSR qui se confond avec le PSR. Ce n'est pas un
    defaut a corriger silencieusement - un run exploratoire n'est pas toujours
    un essai qu'on revendique, et le rapport porte deja l'avertissement.

    Avec `--archive`, le compteur devient celui du DEPOT : le registre est
    charge avant le run, le Deflated Sharpe est calcule contre lui, et l'essai
    y est ajoute ensuite. L'ordre compte - s'ajouter soi-meme avant de se
    comparer ferait qu'un premier essai se trouverait deja un predecesseur.
    """
    spec = _load_spec(args.config, args.settings, args.symbol)
    registre = registre_par_defaut() if args.archive else None
    report = run_backtest(
        spec, trial_log=None if registre is None else registre.journal()
    )
    _emit(report, as_json=args.json, out=args.out)
    if registre is not None:
        _archiver(registre, report.to_dict(), note=args.note)
    if args.gui:
        # Import tardif : tkinter peut manquer sur une machine sans interface,
        # et `rsl run` sans `--gui` doit continuer d'y fonctionner.
        from rsl.gui.app import launch

        launch(config=args.config)
    return EXIT_OK


def _archiver(registre: Registre, rapport: SpecDict, *, note: str) -> None:
    """Ajoute l'essai au registre, ou dit pourquoi il ne l'a pas ete.

    Un doublon n'est PAS une erreur de l'utilisateur : relancer un backtest
    pour verifier qu'il se reproduit est exactement ce que le socle encourage.
    La commande le dit et rend `EXIT_OK`.
    """
    try:
        essai = registre.archiver(rapport, note=note)
    except EssaiDejaArchiveError as deja:
        print(f"\nessai deja enregistre : {deja}")
        return
    print(f"\nessai archive     {essai.render()}")
    print(f"rapport           {essai.rapport}")
    print(f"registre          {registre.fichier} ({registre.journal().n_trials} essai(s))")


def _cmd_essais(args: argparse.Namespace) -> int:
    """Ce que le compteur du Deflated Sharpe contient reellement.

    Une commande a part entiere, pour la meme raison que `verify` : un chiffre
    qui gouverne l'interpretation de tous les resultats doit pouvoir etre
    consulte sans relire un fichier a la main.
    """
    registre = registre_par_defaut()
    essais = registre.essais()
    if args.json:
        print(json.dumps(
            {"registre": registre.describe(), "essais": [e.describe() for e in essais]},
            indent=2, ensure_ascii=False, sort_keys=True,
        ))
        return EXIT_OK

    if not essais:
        print(
            f"Aucun essai enregistre dans {registre.fichier}.\n"
            f"Archiver un run : rsl run CONFIG --archive"
        )
        return EXIT_OK

    for essai in essais:
        print(essai.render())
    journal = registre.journal()
    print(
        f"\n{len(essais)} ligne(s), {journal.n_trials} configuration(s) distincte(s), "
        f"variance des Sharpe {journal.variance_of_sharpes:.6f}"
    )
    doublons = registre.doublons()
    if doublons:
        print(
            f"\nAVERTISSEMENT : {len(doublons)} resultat(s) obtenus par PLUSIEURS "
            f"specifications. Le compteur les voit comme autant d'essais alors "
            f"qu'une seule idee a peut-etre ete essayee - a trancher a la main, "
            f"le registre ne juge pas."
        )
        for empreinte, lignes in sorted(doublons.items()):
            noms = ", ".join(sorted({e.label for e in lignes}))
            print(f"  {empreinte[:12]} <- {noms}")

    divergences = registre.divergences()
    if divergences:
        print(
            f"\nAVERTISSEMENT : {len(divergences)} specification(s) ont rendu "
            f"PLUSIEURS resultats. Le moteur a change entre-temps ; les chiffres "
            f"d'avant et d'apres ne se comparent pas."
        )
        for cle, lignes in sorted(divergences.items()):
            empreintes = ", ".join(sorted({e.result_fingerprint[:12] for e in lignes}))
            print(f"  {cle[:12]} -> {empreintes}")
    return EXIT_OK


def _cmd_pbo(args: argparse.Namespace) -> int:
    """Probabilite de surapprentissage d'une grille, par CSCV.

    Repond a une question que le Deflated Sharpe ne pose pas : si je choisis la
    meilleure configuration sur une moitie de l'echantillon, quelle chance
    a-t-elle de finir sous la mediane sur l'autre ? Le DSR qualifie un CHIFFRE ;
    la PBO qualifie le PROCESSUS qui l'a produit.

    Code de sortie 2 quand la PBO depasse le seuil : une grille surapprise est
    une verification qui echoue, pas une erreur d'usage - c'est la meme
    distinction que pour `verify`.
    """
    specs = [
        _load_spec(chemin, args.settings, args.symbol)
        for chemin in _etendre(args.configs)
    ]
    grille = construire_grille(
        specs, args.blocks, ignorer_inactives=args.drop_idle
    )
    resultat = grille.evaluer()

    if args.json:
        print(json.dumps(
            {"grille": grille.describe(), "pbo": resultat.describe()},
            indent=2, ensure_ascii=False, sort_keys=True,
        ))
    else:
        rule = "-" * 78
        print(rule)
        print(grille.render())
        print(rule)
        print(resultat.render())
        print(rule)
        for avertissement in grille.warnings:
            print(f"Avertissement  {avertissement}")

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {"grille": grille.describe(), "pbo": resultat.describe()},
                indent=2, sort_keys=True, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if not args.json:
            print(f"\nResultat JSON ecrit dans {args.out}")

    if args.archive:
        _archiver_balayage(grille, resultat, note=args.note)

    return EXIT_CHECK_FAILED if resultat.est_surapprise else EXIT_OK


def _etendre(chemins: Sequence[Path]) -> list[Path]:
    """Developpe les REPERTOIRES en leurs fichiers `.json`, tries.

    Necessaire, et decouvert en lancant la premiere grille large : 462 chemins
    depassent la longueur de ligne de commande admise, et l'interpreteur rend
    « Argument list too long » sans que rien n'indique le remede. Une grille de
    quelques centaines de configurations est precisement ce que la CSCV demande
    - la lui rendre impossible a passer serait un defaut de dessin.

    Tries : l'ordre des lignes de la matrice determine quelle configuration
    `argmax` designe en cas d'egalite. Un ordre dependant du systeme de
    fichiers rendrait la PBO non reproductible.
    """
    etendus: list[Path] = []
    for chemin in chemins:
        if chemin.is_dir():
            trouves = sorted(chemin.glob("*.json"))
            if not trouves:
                raise ConfigurationError(
                    f"aucun fichier .json dans {chemin}"
                )
            etendus.extend(trouves)
        else:
            etendus.append(chemin)
    return etendus


def _archiver_balayage(
    grille: Grille, resultat: ResultatPBO, *, note: str
) -> None:
    """Enregistre chaque configuration de la grille comme un essai.

    Un seul fichier est ecrit - la grille entiere, avec sa matrice et sa PBO -
    et les N lignes du registre pointent dessus. Ecrire un rapport complet par
    configuration ajouterait des centaines de fichiers pour une information que
    ce fichier contient deja.

    Les doublons ne font pas echouer l'archivage : relancer une grille est une
    VERIFICATION, et une configuration deja enregistree ne doit pas monter le
    compteur une seconde fois. Le decompte final dit ce qui a ete ajoute.
    """
    registre = registre_par_defaut()
    dossier = registre.racine / "grilles"
    dossier.mkdir(parents=True, exist_ok=True)
    cle = canonical_hash(
        {"labels": list(grille.labels), "hashes": list(grille.config_hashes)}
    )[:12]
    chemin = dossier / f"{cle}.json"
    chemin.write_text(
        json.dumps(
            {"grille": grille.describe(), "pbo": resultat.describe()},
            indent=2, sort_keys=True, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    artefact = chemin.relative_to(registre.racine).as_posix()

    ajoutes = 0
    deja = 0
    for rapport in grille.rapports:
        try:
            registre.archiver(rapport, note=note, artefact=artefact)
            ajoutes += 1
        except EssaiDejaArchiveError:
            deja += 1

    print(f"\nBalayage archive  {ajoutes} essai(s) ajoute(s), {deja} deja connu(s)")
    print(f"artefact          {artefact}")
    print(f"registre          {registre.fichier} "
          f"({registre.journal().n_trials} configuration(s) distinctes)")


def _cmd_squelette(args: argparse.Namespace) -> int:
    """Publie le squelette a trous, engendre depuis les registres.

    Complement de `rsl schema` : le schema sert a VALIDER, le squelette a
    ECRIRE. Les deux sortent du meme registre, donc ne peuvent pas diverger.
    """
    rendu = json.dumps(build_skeleton(), indent=2, ensure_ascii=False, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendu, encoding="utf-8")
        print(f"Squelette ecrit dans {args.out}")
    else:
        print(rendu)
    return EXIT_OK


def _cmd_gui(args: argparse.Namespace) -> int:
    """Ouvre le tableau de bord. Le run, s'il y en a un, est lance par la fenetre."""
    try:
        from rsl.gui.app import launch
    except ImportError as erreur:  # pragma: no cover - depend de l'installation
        print(f"interface graphique indisponible : {erreur}", file=sys.stderr)
        return EXIT_ERROR

    launch(config=args.config)
    return EXIT_OK


def _cmd_walkforward(args: argparse.Namespace) -> int:
    """Evalue par fenetres, et - avec `--archive` - compte UN essai.

    Un pli n'est pas un essai, et c'est la seule decision que cette commande
    encode. Un essai est une CONFIGURATION differente sur les memes donnees ;
    un pli est la MEME configuration sur d'autres donnees. Verser neuf plis au
    compteur du Deflated Sharpe le rendrait pessimiste pour une raison qui n'a
    rien a voir avec la selection - c'est la regle que `walkforward.py` posait
    deja en commentaire, et qui devient ici executable.

    Le Sharpe enregistre est donc celui de la serie GROUPEE - les rendements
    hors echantillon de tous les plis, bout a bout - et non une moyenne des
    Sharpe par pli, ou un pli court pese autant qu'un pli long.
    """
    spec = _load_spec(args.config, args.settings, args.symbol)
    splitter = (
        AnchoredWalkForward(initial_train_bars=args.train, test_bars=args.test)
        if args.anchored
        else RollingWalkForward(
            train_bars=args.train, test_bars=args.test, step_bars=args.step
        )
    )
    report = run_walk_forward(spec, splitter, liquidate_folds=not args.keep_open)

    if args.json:
        print(json.dumps(report.describe(), indent=2, ensure_ascii=False))
    else:
        print(report.render())
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report.describe(), indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        if not args.json:
            print(f"\nRapport JSON ecrit dans {args.out}")
    if args.archive:
        _archiver(registre_par_defaut(), _essai_de_walkforward(report), note=args.note)
    return EXIT_OK


def _essai_de_walkforward(report: WalkForwardReport) -> SpecDict:
    """Traduit un walk-forward dans la forme qu'attend le registre.

    Le registre lit des rapports de BACKTEST : un `metrics.risk`, un
    `metrics.sample`, un `manifest`. Un walk-forward n'a pas cette forme - il a
    des plis. Plutot que d'apprendre deux formes au registre, on traduit ici :
    le registre reste simple, et le point de traduction est visible.

    Les quatre grandeurs statistiques viennent du bloc `pooled` du rapport,
    calcule sur les rendements hors echantillon de TOUS les plis concatenes.
    C'est la que se joue la decision « un pli n'est pas un essai ».

    L'empreinte de resultat est celle des plis mis bout a bout : deux
    walk-forwards qui produisent les memes plis sont le meme resultat, et
    l'ordre des plis compte puisqu'il est chronologique.
    """
    groupe = report.pooled()
    return {
        "name": f"{report.name} [walk-forward, {report.n_folds} plis]",
        "symbols": list(report.symbols),
        "result_fingerprint": canonical_hash([f.fingerprint for f in report.folds]),
        "manifest": report.manifest.describe(),
        "metrics": {
            "risk": {
                "sharpe_per_period": groupe["sharpe_per_period"],
                "n_returns": groupe["n_returns"],
                "returns_skewness": groupe["skewness"],
                "returns_kurtosis": groupe["kurtosis"],
            },
            "sample": {
                "n_bars": sum(f.metrics.n_bars for f in report.folds),
                "span_years": sum(f.metrics.span_years for f in report.folds),
            },
        },
        "walkforward": report.describe(),
    }


def _cmd_verify(args: argparse.Namespace) -> int:
    """Deux runs, deux empreintes. Elles doivent etre egales."""
    spec = _load_spec(args.config, args.settings, args.symbol)
    first = run_backtest(spec)
    second = run_backtest(spec)

    print(f"empreinte 1  {first.result_fingerprint}")
    print(f"empreinte 2  {second.result_fingerprint}")
    if first.result_fingerprint != second.result_fingerprint:
        print("\nDIVERGENCE : deux runs identiques ont produit des resultats differents.")
        print("Le determinisme du socle est rompu ; aucun resultat n'est exploitable.")
        return EXIT_CHECK_FAILED

    print("\nidentiques : le run est reproductible sur cette machine.")
    if not first.manifest.is_reproducible:
        print("\nMais il ne l'est pas AILLEURS :")
        for warning in first.manifest.warnings:
            print(f"  - {warning}")
        return EXIT_CHECK_FAILED
    return EXIT_OK


def _load_spec(
    path: Path, settings: Path | None = None, symbol: str | None = None
) -> BacktestSpec:
    """Charge un run, que le fichier soit complet ou une strategie seule.

    Le type est lu au marqueur `format`, jamais devine d'apres les champs
    presents : deviner marcherait presque toujours, et c'est le « presque » qui
    coute. Un fichier de strategie sans reglages est refuse avec la commande a
    taper - il lui manque l'actif, le capital et les couts, qui ne sont pas des
    details qu'on peut supposer.
    """
    charge = json.loads(path.read_text(encoding="utf-8"))
    if not est_fichier_de_strategie(charge):
        if settings is not None or symbol is not None:
            raise ConfigurationError(
                f"{path.name} est une specification COMPLETE : elle porte deja "
                f"ses donnees, son capital et ses couts. `--settings` et "
                f"`--symbol` ne s'appliquent qu'a un fichier de strategie "
                f"(`\"format\": \"rsl-strategy@1\"`)."
            )
        return BacktestSpec.model_validate(charge)

    if settings is None:
        raise ConfigurationError(
            f"{path.name} est une strategie SEULE : elle ne dit ni sur quoi la "
            f"faire tourner, ni avec combien, ni a quels couts. Fournissez ces "
            f"reglages : rsl run {path.name} --settings reglages.json "
            f"[--symbol ES.v.0]"
        )
    return compose(
        StrategyFile.model_validate(charge),
        json.loads(settings.read_text(encoding="utf-8")),
        symbol=symbol,
    )


def _emit(report: BacktestReport, *, as_json: bool, out: Path | None) -> None:
    if as_json:
        print(report.to_json())
    else:
        print(report.render())
    if out is not None:
        written = report.write(out)
        if not as_json:
            print(f"\nRapport JSON ecrit dans {written}")


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
