"""Interface en ligne de commande.

    rsl validate FICHIER...     valide des fichiers de donnees
    rsl instruments             table des contrats
    rsl catalogue               primitives, noeuds et strategies enregistres
    rsl schema                  JSON Schema du vocabulaire, a rediriger
    rsl example                 specification d'exemple, a rediriger
    rsl run CONFIG              execute un backtest et ecrit son rapport
    rsl walkforward CONFIG      evalue par fenetres successives
    rsl verify CONFIG           execute deux fois et compare les empreintes

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
from rsl.config import BacktestSpec
from rsl.data.instruments import INSTRUMENTS, get_instrument
from rsl.data.loader import validate_file
from rsl.errors import ConfigurationError, RslError
from rsl.metrics.statistics import AnchoredWalkForward, RollingWalkForward
from rsl.primitives.registry import describe_registry
from rsl.report import BacktestReport, run_backtest
from rsl.skeleton import build_skeleton
from rsl.strategies.base import describe_strategies
from rsl.strategies.signals import describe_node_types, signal_json_schema
from rsl.walkforward import run_walk_forward

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


def main(argv: Sequence[str] | None = None) -> int:
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
    run.set_defaults(handler=_cmd_run)

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


def _cmd_run(args: argparse.Namespace) -> int:
    spec = _load_spec(args.config, args.settings, args.symbol)
    report = run_backtest(spec)
    _emit(report, as_json=args.json, out=args.out)
    if args.gui:
        # Import tardif : tkinter peut manquer sur une machine sans interface,
        # et `rsl run` sans `--gui` doit continuer d'y fonctionner.
        from rsl.gui.app import launch

        launch(config=args.config)
    return EXIT_OK


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
    return EXIT_OK


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
