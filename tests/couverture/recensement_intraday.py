"""Recensement d'expressivite INTRADAY : que sait-on ecrire, et que manque-t-il ?

    python tests/couverture/recensement_intraday.py

N'est PAS une suite de tests : rien n'echoue ici. C'est une MESURE, rejouable,
dont le resultat est consigne dans [[reference/couverture-intraday]]. Le jour ou
le vocabulaire gagne ou perd une capacite, relancer ce fichier le dit.

Un pourcentage n'a de sens que contre un DENOMINATEUR explicite. Celui-ci est un
catalogue d'elements de strategie intraday, ecrit a la main, par axe. Il est
discutable - c'est pourquoi il est ici, lisible et modifiable, plutot que
resume par un chiffre.

Chaque element est ECRIT en JSON et EVALUE. Trois verdicts :

  OK          construit et rend des valeurs
  PARTIEL     s'ecrit, mais avec une reserve qui change le sens
  IMPOSSIBLE  ne se construit pas, ou exige un artifice qu'on refuse
"""

import datetime as dt
import pathlib
import sys

# Rejouable depuis la racine du depot sans installation.
_RACINE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RACINE / "src"))
sys.path.insert(0, str(_RACINE / "tests"))


import numpy as np  # noqa: E402

from fixtures import synthetic  # noqa: E402
from rsl.data.feed import BarContext  # noqa: E402
from rsl.data.schema import (  # noqa: E402
    AccountState,
    BarStore,
    Granularity,
    PositionState,
)
from rsl.data.session import SessionCalendar, build_session_index  # noqa: E402
from rsl.strategies.signals import build_signal  # noqa: E402

NS = 1_000_000_000
PAR_SEANCE = 78  # une seance de 6h30 en barres de 5 minutes
SEANCE = SessionCalendar(start="09:00", end="15:30", timezone="UTC")


def magasin(n_seances: int = 60) -> BarStore:
    ts: list[int] = []
    base = dt.datetime(2024, 1, 2, 9, 0, tzinfo=dt.UTC)
    for j in range(n_seances):
        debut = int((base + dt.timedelta(days=j)).timestamp())
        ts.extend((debut + m * 300) * NS for m in range(PAR_SEANCE))
    tab = np.asarray(ts, dtype=np.int64)
    closes = synthetic.random_walk(tab.size, 100.0, sigma=0.25, seed=41)
    o, h, low, c = synthetic.ohlc_from_closes(closes, wick=0.003)
    store = BarStore.build(
        symbol="CEN.v.0", granularity=Granularity.minutes(5), ts_event=tab,
        open_=o, high=h, low=low, close=c,
        volume=np.abs(synthetic.random_walk(tab.size, 1000.0, sigma=40.0, seed=7)) + 1.0,
        source_hash="synthetic",
    )
    return store.with_sessions(
        build_session_index(store.ts_close, store.open, store.high, store.low,
                            store.close, store.volume, SEANCE)
    )


# --- briques ----------------------------------------------------------------
# Noms en MAJUSCULES a dessein : ce fichier est un catalogue, et sa valeur
# tient a ce qu'une ligne de strategie se lise d'un coup d'oeil.
# ruff: noqa: N802, E501
def P(c, lag=0):
    return {"type": "price", "field": c, "lag": lag}


def S(c, lag=0):
    return {"type": "session", "field": c, "lag": lag}


def K(v):
    return {"type": "constant", "value": float(v)}


def A(op, g, d):
    return {"type": "arith", "op": op, "left": g, "right": d}


def C(op, g, d):
    return {"type": "compare", "op": op, "left": g, "right": d}


def TOUS(*o):
    return {"type": "all_of", "operands": list(o)}


def UN(*o):
    return {"type": "any_of", "operands": list(o)}


def PRIM(ref, **params):
    return {"type": "primitive", "ref": ref, "params": params}


def ROLL(stat, window, inner, **extra):
    return {"type": "rolling", "stat": stat, "window": window, "inner": inner, **extra}


def CUM(stat, inner, **extra):
    return {"type": "cumulative", "stat": stat, "inner": inner, **extra}


def LAG(n, inner):
    return {"type": "lag", "bars": n, "inner": inner}


def SLAG(n, inner):
    return {"type": "session_lag", "sessions": n, "inner": inner}


def POS(champ):
    return {"type": "position", "field": champ}


def CPT(champ):
    return {"type": "account", "field": champ}


MFO = S("minutes_from_open")
TYPIQUE = A("/", A("+", A("+", P("high"), P("low")), P("close")), K(3.0))
VWAP = A("/", CUM("sum", A("*", TYPIQUE, P("volume"))), CUM("sum", P("volume")))
AVANT_30 = C("<=", MFO, K(30))

# ----------------------------------------------------------------------------
# LE CATALOGUE
# ----------------------------------------------------------------------------
CATALOGUE: dict[str, dict[str, object]] = {}


def axe(nom: str, elements: dict[str, object]) -> None:
    CATALOGUE[nom] = elements


axe("A. Declencheurs d'entree", {
    "cassure d'un plus haut glissant": C(">", P("close"), LAG(1, PRIM("rolling_high", window=20))),
    "cassure de l'opening range": C(">", P("close"), CUM("max", P("high"), mask=AVANT_30)),
    "cassure du plus haut de la veille": C(">", P("close"), S("high", lag=1)),
    "cassure d'un canal de Donchian": C(">", P("close"), LAG(1, PRIM("donchian", window=20))),
    "cassure de bande de volatilite": C(">", P("close"),
        A("*", S("open"), A("+", K(1.0), A("*", K(1.5),
          ROLL("mean", 20, across="sessions", inner=SLAG(1,
            {"type": "math", "op": "abs",
             "inner": A("-", A("/", P("close"), S("open")), K(1.0))})))))),
    "retour a la moyenne sur VWAP": C("<", A("/", P("close"), VWAP), K(0.998)),
    "sur-vente RSI": C("<", PRIM("rsi", window=14), K(30.0)),
    "z-score extreme": C("<", ROLL("zscore", 100, P("close")), K(-2.0)),
    "croisement de moyennes": {"type": "crosses_above", "fast": PRIM("ema", window=9),
                               "slow": PRIM("ema", window=21)},
    "MACD au-dessus de sa ligne": C(">", PRIM("macd", fast=12, slow=26, signal=9), K(0.0)),
    "bande de Bollinger percee": C(">", P("close"), PRIM("bollinger", window=20, multiplier=2.0)),
    "Keltner perce": C(">", P("close"), PRIM("keltner", window=20, multiplier=2.0)),
    "squeeze qui se detend": C(">", PRIM("squeeze", window=20), K(0.0)),
    "SuperTrend haussier": C(">", P("close"), PRIM("supertrend", window=10, multiplier=3.0)),
    "PSAR retourne": C(">", P("close"), PRIM("psar")),
    "momentum depuis l'ouverture": C(">", A("/", P("close"), S("open")), K(1.002)),
    "gap d'ouverture": C(">", A("/", S("open"), S("close", lag=1)), K(1.004)),
    "pic de volume relatif au meme moment": C(">",
        A("/", CUM("sum", P("volume")),
          ROLL("mean", 20, across="sessions", inner=SLAG(1, CUM("sum", P("volume"))))), K(1.5)),
    "poussee de volume brute": C(">", P("volume"), A("*", K(3.0), PRIM("sma", window=50, field="volume"))),
    "bougie de retournement (corps/meche)": C(">", PRIM("body_ratio"), K(0.7)),
    "prix au-dessus du pivot": C(">", P("close"), PRIM("pivot")),
    "efficience de tendance": C(">", PRIM("efficiency_ratio", window=20), K(0.5)),
    "divergence RSI (approx. par pente)": C("<", ROLL("slope", 20, PRIM("rsi", window=14)), K(0.0)),
})

axe("B. Sorties", {
    "objectif en pourcentage": C(">", A("/", P("close"), POS("entry_price")), K(1.01)),
    "stop en pourcentage": C("<", A("/", P("close"), POS("entry_price")), K(0.995)),
    "stop en multiples d'ATR": C("<", P("close"),
        A("-", POS("entry_price"), A("*", K(2.0), PRIM("atr", window=14)))),
    "stop suiveur sur plus haut depuis l'entree": C("<", P("close"),
        A("*", POS("high_since_entry"), K(0.99))),
    "stop temporel (N barres)": C(">=", POS("bars_held"), K(12.0)),
    "sortie sur retour au VWAP": C("<", P("close"), VWAP),
    "cloture forcee de seance": C("==", S("is_last"), K(1.0)),
    "sortie sur signal inverse": C("<", PRIM("rsi", window=14), K(50.0)),
    "sortie a une heure fixe": C(">=", MFO, K(360.0)),
    "sortie PARTIELLE (echelle de sortie)": C(">", A("/", P("close"), POS("entry_price")), K(1.005)),
    "coupe-circuit sur drawdown du compte": C("<", CPT("drawdown"), K(-0.1)),
})

axe("C. Filtres", {
    "fenetre horaire": TOUS(C(">=", MFO, K(30.0)), C("<=", MFO, K(330.0))),
    "grille horaire periodique": C("==", A("%", MFO, K(30.0)), K(0.0)),
    "jour de la semaine": C("!=", {"type": "time", "field": "weekday"}, K(0.0)),
    "regime de volatilite": C(">", PRIM("atr", window=14), PRIM("sma", window=100, field="close")),
    "volatilite relative a sa propre histoire": C(">",
        ROLL("rank", 60, PRIM("natr", window=14)), K(0.7)),
    "tendance de fond (meme serie, autre horizon)": C(">", P("close"), PRIM("sma", window=200)),
    "tendance de fond (autre serie via peer)": None,
    "marche directionnel (ADX)": C(">", PRIM("adx", window=14), K(25.0)),
    "choppiness": C("<", PRIM("chop", window=14), K(38.2)),
    "volume minimum": C(">", PRIM("dollar_volume", window=20), K(0.0)),
    "eviter les N premieres minutes": C(">", MFO, K(15.0)),
    "seance ecourtee exclue": C(">", CUM("count_true", K(1.0)), K(10.0)),
})

axe("D. Gestion de position", {
    "taille fixe": None,                      # `risk.sizing.kind = fixed`
    "fraction du capital": None,              # `equity_fraction`
    "risque par trade en ATR": None,          # `risk_fraction`
    "cible de volatilite": None,              # `vol_target`
    "plafond de contrats": None,              # `risk.max_gross_contracts`
    "marge de JOUR": None,                    # `execution.intraday_margin_ratio`
    "entree a cours limite": None,            # regle `entry_limit`
    "entree sur stop": None,                  # regle `entry_stop`
    "sortie partielle": None,                 # regle `exit_quantity`
    "pyramidage": None,                       # `allow_pyramiding`
})

axe("E. Etat et meta-regles", {
    "un seul trade par seance": C("==",
        CUM("count_true", TOUS(C("!=", POS("quantity"), K(0.0)),
                               C("==", LAG(1, POS("quantity")), K(0.0)))), K(0.0)),
    "N trades maximum par seance": C("<",
        CUM("count_true", C("<", POS("bars_held"), LAG(1, POS("bars_held")))), K(3.0)),
    "arret apres N fins de trade perdantes": C("<",
        CUM("count_true", TOUS(
            C("<", POS("bars_held"), LAG(1, POS("bars_held"))),
            LAG(1, C("<", P("close"), POS("entry_price"))))), K(2.0)),
    # `value_when` donne l'equity du compte a la derniere fin de trade : la
    # perte NETTE devient lisible, frais compris.
    "arret sur perte du jour (P&L NET realise)": C(">",
        CPT("equity"),
        {"type": "value_when", "lookback": 200,
         "when": C("<", POS("bars_held"), LAG(1, POS("bars_held"))),
         "inner": CPT("equity")}),
    "ne pas rejouer le meme niveau": C(">", P("close"),
        A("*", {"type": "value_when", "lookback": 200,
                "when": C(">", P("close"), CUM("max", P("high"), mask=AVANT_30)),
                "inner": P("close")}, K(1.002))),
    "serie de pertes sur PLUSIEURS seances": C("<",
        CUM("count_true", C("<", POS("bars_held"), LAG(1, POS("bars_held"))),
            sessions=5), K(6.0)),
    "taille fonction de la force du signal": None,
    "barres depuis la derniere entree": {"type": "bars_since", "lookback": 50,
                                         "inner": C("!=", POS("quantity"), K(0.0))},
})

axe("F. Donnees", {
    "granularites 1min a 4h ancrees sur la seance": None,
    "deux granularites de la meme serie": None,
    "deux ancrages de seance differents": None,
    "un autre instrument en filtre": None,
    "carnet d'ordres / ticks": None,
    "calendrier d'evenements (FOMC, NFP)": None,
    "donnees fondamentales ou de sentiment": None,
})

# Ce que le CODE ne peut pas trancher : verdicts etablis par mesure ailleurs,
# consignes ici avec leur justification.
HORS_SIGNAL: dict[str, tuple[str, str]] = {
    "taille fixe": ("OK", "risk.sizing.kind = fixed"),
    "fraction du capital": ("OK", "risk.sizing.kind = equity_fraction"),
    "risque par trade en ATR": ("OK", "risk.sizing.kind = risk_fraction"),
    "cible de volatilite": ("OK", "risk.sizing.kind = vol_target"),
    "plafond de contrats": ("OK", "risk.max_gross_contracts"),
    "marge de JOUR": ("OK", "execution.intraday_margin_ratio, 2026-09-14"),
    "entree a cours limite": ("OK", "cle de regle `entry_limit`"),
    "entree sur stop": ("OK", "cle de regle `entry_stop`"),
    "sortie partielle": ("OK", "cle de regle `exit_quantity`"),
    "pyramidage": ("OK", "params `allow_pyramiding`"),
    "tendance de fond (autre serie via peer)": (
        "OK",
        "verifie ailleurs : `paire_es_nq` est un exemple ARCHIVE qui lit un "
        "`peer`, et le multi-horizon mesure 100 % de lignes completes",
    ),
    "arret sur perte du jour (P&L NET realise)": (
        "PARTIEL",
        "approximable par `close < entry_price` a la derniere barre en position ; "
        "les FRAIS et le prix du fill de sortie sont invisibles au vocabulaire",
    ),
    "ne pas rejouer le meme niveau": (
        "IMPOSSIBLE", "demande de retenir un PRIX arbitraire d'une barre a l'autre"),
    "serie de pertes sur PLUSIEURS seances": (
        "IMPOSSIBLE", "`cumulative` remet a zero a chaque seance ; `reset: never` est au ledger"),
    "taille fonction de la force du signal": (
        "OK", "risk.sizing.kind = signal - une expression arbitraire avec "
        "`max_contracts` obligatoire. Verdict corrige le 2026-09-15 : il "
        "disait PARTIEL sur la foi d'une note, alors que "
        "`nq_zarattini_60_30_15` est un `rules@1` MONO-INSTRUMENT dont la "
        "taille vient d'un noeud - 923 trades a taille variable le prouvent"),
    "granularites 1min a 4h ancrees sur la seance": ("OK", "2026-09-12"),
    "deux granularites de la meme serie": ("OK", "alias + panel.allow_mixed_granularity, mesure 100 %"),
    "deux ancrages de seance differents": (
        "OK", "mesure le 2026-09-15 : ES 09:30-16:00 New York en 15min et NQ "
        "08:30-15:00 Chicago en 1m coexistent, chacun avec son index de "
        "seance. SEUL cas refuse - deux series REECHANTILLONNEES en "
        "intra-journalier a ancrages differents - et ce refus est motive par "
        "une mesure : le panneau produirait 100 % de lignes a un seul "
        "instrument. Ce n'est donc pas un manque mais une garde"),
    "un autre instrument en filtre": ("OK", "noeud `peer` + panel_rules@1"),
    "carnet d'ordres / ticks": ("IMPOSSIBLE", "le moteur est a la BARRE ; item ouvert cote Nautilus"),
    "calendrier d'evenements (FOMC, NFP)": (
        "OK",
        "section `events` + noeud `event`, 2026-09-14 ; `minutes_until` exige "
        "que la source declare `known_in_advance`",
    ),
    "donnees fondamentales ou de sentiment": (
        "OK",
        "section `exogenous` + noeud `exogenous`, 2026-09-15. La source doit "
        "affirmer `horodatee_a_la_publication` OU declarer un "
        "`publication_lag_minutes` strictement positif : une donnee "
        "fondamentale est connue APRES ce qu'elle mesure, et un fichier "
        "horodate a la mesure ferait entrer du futur invisible"),
}


# ----------------------------------------------------------------------------
def verdict(spec, store, positions) -> tuple[str, str]:
    try:
        signal = build_signal(spec)
    except Exception as exc:
        return "IMPOSSIBLE", f"{type(exc).__name__}: {exc}"[:90]
    ctx = BarContext(store)
    ctx._set_position_depth(200)
    # Un compte, sans quoi `account` leve - ce qui ne dirait rien du
    # vocabulaire, seulement de ce banc d'essai.
    ctx._account.set_initial(100_000.0)
    definies = 0
    total = 0
    for i in range(21 * PAR_SEANCE, store.n_bars):
        ctx._seek(i)
        ctx._set_position(positions(i))
        ctx._set_account(AccountState(equity=100_000.0 + i, cash=50_000.0,
                                      peak_equity=100_000.0 + i,
                                      initial_equity=100_000.0))
        total += 1
        try:
            if signal(ctx) is not None:
                definies += 1
        except Exception as exc:
            return "LEVE", f"{type(exc).__name__}: {exc}"[:90]
    if definies == 0:
        return "MUET", "ne rend que None"
    return "OK", f"{100 * definies / total:.0f} % de barres definies"


EN_POSITION = PositionState(quantity=1, bars_held=0, entry_price=100.0,
                            high_since_entry=101.0, low_since_entry=99.0)


def positions(i: int):
    """Une position ouverte cinq barres sur dix, pour que `position` reponde."""
    rang = i % PAR_SEANCE
    if rang % 10 < 5:
        return PositionState(quantity=1, bars_held=rang % 10, entry_price=100.0,
                             high_since_entry=101.0, low_since_entry=99.0)
    return PositionState()


def main() -> None:
    store = magasin()
    print(f"{store.n_bars:,} barres de 5 min, {store.sessions.n_sessions} seances\n")
    totaux = {"OK": 0, "PARTIEL": 0, "IMPOSSIBLE": 0}
    manquants: list[tuple[str, str, str]] = []

    for nom_axe, elements in CATALOGUE.items():
        print(f"--- {nom_axe} " + "-" * (66 - len(nom_axe)))
        largeur = max(len(n) for n in elements)
        for nom, spec in elements.items():
            if spec is None:
                etat, detail = HORS_SIGNAL[nom]
            else:
                etat, detail = verdict(spec, store, positions)
                if etat in ("MUET", "LEVE"):
                    etat = "IMPOSSIBLE"
            totaux[etat] = totaux.get(etat, 0) + 1
            if etat != "OK":
                manquants.append((nom_axe, nom, detail))
            print(f"  {etat:11} {nom:<{largeur}}  {detail[:58]}")
        print()

    n = sum(totaux.values())
    print("=" * 72)
    for etat in ("OK", "PARTIEL", "IMPOSSIBLE"):
        print(f"{etat:11} {totaux[etat]:>3} / {n}   {100 * totaux[etat] / n:5.1f} %")
    print()
    print("Ce qui manque :")
    for nom_axe, nom, detail in manquants:
        print(f"  [{nom_axe[0]}] {nom} -- {detail[:80]}")


main()


# ----------------------------------------------------------------------------
# Deuxieme comptage : par FAMILLE de strategie.
#
# Un pourcentage d'ELEMENTS surestime la couverture : une strategie est une
# COMBINAISON, et un seul element manquant bloque toute une famille. Ce second
# comptage associe a chaque famille les elements qu'elle exige, et la declare
# realisable seulement si tous le sont.
# ----------------------------------------------------------------------------
FAMILLES: dict[str, list[str]] = {
    "Opening range breakout": [
        "cassure de l'opening range", "stop en multiples d'ATR",
        "cloture forcee de seance", "fenetre horaire"],
    "ORB avec filtre de volume": [
        "cassure de l'opening range", "pic de volume relatif au meme moment",
        "cloture forcee de seance"],
    "VWAP reversion": [
        "retour a la moyenne sur VWAP", "sortie sur retour au VWAP",
        "cloture forcee de seance", "grille horaire periodique"],
    "VWAP trend-following": [
        "momentum depuis l'ouverture", "sortie sur retour au VWAP",
        "cloture forcee de seance"],
    "Momentum intraday (Zarattini)": [
        "cassure de bande de volatilite", "grille horaire periodique",
        "sortie sur retour au VWAP", "cloture forcee de seance"],
    "Cassure de la veille (PDH/PDL)": [
        "cassure du plus haut de la veille", "stop en pourcentage",
        "cloture forcee de seance"],
    "Gap fade": [
        "gap d'ouverture", "objectif en pourcentage", "stop en pourcentage",
        "cloture forcee de seance"],
    "Donchian intraday": [
        "cassure d'un canal de Donchian", "stop suiveur sur plus haut depuis l'entree",
        "cloture forcee de seance"],
    "Mean reversion RSI": [
        "sur-vente RSI", "sortie sur signal inverse", "stop en pourcentage",
        "cloture forcee de seance"],
    "Bollinger squeeze breakout": [
        "squeeze qui se detend", "bande de Bollinger percee",
        "stop en multiples d'ATR", "cloture forcee de seance"],
    "SuperTrend intraday": [
        "SuperTrend haussier", "cloture forcee de seance", "regime de volatilite"],
    "Croisement de moyennes filtre ADX": [
        "croisement de moyennes", "marche directionnel (ADX)",
        "stop temporel (N barres)", "cloture forcee de seance"],
    "Pivots classiques": [
        "prix au-dessus du pivot", "objectif en pourcentage", "cloture forcee de seance"],
    "Multi-horizon (5 min filtre par le quotidien)": [
        "momentum depuis l'ouverture", "deux granularites de la meme serie",
        "un autre instrument en filtre", "cloture forcee de seance"],
    "Z-score de paire intraday": [
        "z-score extreme", "un autre instrument en filtre", "cloture forcee de seance"],
    "Un seul trade par jour": [
        "cassure de l'opening range", "un seul trade par seance",
        "cloture forcee de seance"],
    "Arret apres N pertes du jour": [
        "sur-vente RSI", "arret apres N fins de trade perdantes",
        "cloture forcee de seance"],
    "Echelle de sortie (scale-out)": [
        "cassure d'un plus haut glissant", "sortie PARTIELLE (echelle de sortie)",
        "sortie partielle", "cloture forcee de seance"],
    "Dimensionnement par volatilite cible": [
        "cassure d'un plus haut glissant", "cible de volatilite", "marge de JOUR",
        "cloture forcee de seance"],
    "Entree sur ordre stop (breakout passif)": [
        "cassure d'un plus haut glissant", "entree sur stop",
        "stop en multiples d'ATR", "cloture forcee de seance"],
    "Coupe-circuit sur drawdown": [
        "sur-vente RSI", "coupe-circuit sur drawdown du compte",
        "cloture forcee de seance"],
    "Reprise de niveau evite": [
        "cassure de l'opening range", "ne pas rejouer le meme niveau",
        "cloture forcee de seance"],
    "Reduction apres serie de mauvais JOURS": [
        "sur-vente RSI", "serie de pertes sur PLUSIEURS seances",
        "cloture forcee de seance"],
    "Trading d'annonce macro": [
        "poussee de volume brute", "calendrier d'evenements (FOMC, NFP)",
        "cloture forcee de seance"],
    "Scalping sur carnet": [
        "carnet d'ordres / ticks", "sortie a une heure fixe"],
}


def comptage_par_famille(etats: dict[str, str]) -> None:
    print()
    print("=" * 72)
    print("PAR FAMILLE DE STRATEGIE")
    print("=" * 72)
    entieres = partielles = bloquees = 0
    for nom, exigences in FAMILLES.items():
        verdicts = [etats[e] for e in exigences]
        if all(v == "OK" for v in verdicts):
            marque, entieres = "OUI      ", entieres + 1
        elif any(v == "IMPOSSIBLE" for v in verdicts):
            marque, bloquees = "NON      ", bloquees + 1
        else:
            marque, partielles = "AVEC RES.", partielles + 1
        bloquant = [
            f"{e} ({v})" for e, v in zip(exigences, verdicts, strict=True) if v != "OK"
        ]
        print(f"  {marque} {nom:<46} {'; '.join(bloquant)[:60]}")
    n = len(FAMILLES)
    print()
    print(f"  realisables entierement  {entieres:>3} / {n}   {100*entieres/n:5.1f} %")
    print(f"  avec reserve             {partielles:>3} / {n}   {100*partielles/n:5.1f} %")
    print(f"  bloquees                 {bloquees:>3} / {n}   {100*bloquees/n:5.1f} %")


ETATS: dict[str, str] = {}
for elements in CATALOGUE.values():
    for nom, spec in elements.items():
        if spec is None:
            ETATS[nom] = HORS_SIGNAL[nom][0]
        else:
            e, _ = verdict(spec, magasin(), positions)
            ETATS[nom] = "IMPOSSIBLE" if e in ("MUET", "LEVE") else e
comptage_par_famille(ETATS)
