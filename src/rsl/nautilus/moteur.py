"""Monter un backtest Nautilus a partir d'une de nos specifications.

Ce module est la seconde moitie du pont : `pont.py` traduit les objets,
celui-ci traduit le MONTAGE - venue, capital, couts, donnees.

Ce qui se perd en chemin, et il faut le savoir avant de lire un chiffre
-----------------------------------------------------------------------
- **Les frais par contrat.** Nautilus facture par defaut en pourcentage du
  notionnel. Nos frais sont des dollars par contrat. On passe donc un
  `FixedFeeModel`, qui facture un montant FIXE PAR ORDRE - pas par contrat.
  Tant que `quantity` vaut 1, les deux coincident exactement ; au-dela, le
  nautilus sous-facture. Le lanceur le REFUSE plutot que de laisser passer un
  cout faux.
- **Le slippage.** Notre `TickSlippage` degrade chaque fill d'un nombre de
  ticks declare. Nautilus a un `FillModel` probabiliste, d'une autre nature.
  Ici le slippage est mis a ZERO des deux cotes pour la comparaison : comparer
  deux moteurs ET deux modeles de friction ne dirait rien sur aucun des deux.
- **Le decalage d'execution.** Le notre est structurel (`lag_bars >= 1`) ;
  celui de Nautilus vient du simulateur, qui remplit un ordre au marche a la
  barre suivante. Le resultat se ressemble, la garantie non.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import FillModel, FixedFeeModel
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money

from rsl.data.schema import BarStore
from rsl.errors import ConfigurationError
from rsl.nautilus.pont import (
    VENUE,
    barres_nautilus,
    frais_par_contrat,
    instrument_nautilus,
    precision_de,
    type_de_barre,
)

SpecDict = dict[str, object]


@dataclass(frozen=True, slots=True)
class Montage:
    """Ce qu'il faut pour monter un backtest Nautilus.

    Volontairement plat et explicite : ce module traduit, il ne lit pas nos
    `BacktestSpec` directement. Laisser la traduction visible ici evite qu'une
    valeur passe d'un modele a l'autre sans qu'on l'ait regardee.
    """

    root: str
    agregation: str
    capital: float
    quantite: int = 1
    frais_actifs: bool = True


def monter(store: BarStore, montage: Montage) -> BacktestEngine:
    """Un `BacktestEngine` charge, pret a recevoir une strategie.

    Refuse une quantite superieure a un tant que les frais sont actifs :
    `FixedFeeModel` facture par ORDRE et non par contrat, donc au-dela d'un
    contrat le cout serait sous-estime en silence. Mieux vaut un refus qu'un
    Sharpe flatte.
    """
    if montage.frais_actifs and montage.quantite != 1:
        raise ConfigurationError(
            f"quantite={montage.quantite} avec frais actifs : le `FixedFeeModel` "
            f"de Nautilus facture par ORDRE, nos frais sont par CONTRAT. Au-dela "
            f"d'un contrat le cout serait sous-estime. Mettre `frais_actifs=False` "
            f"pour une comparaison sans friction, ou rester a un contrat."
        )

    prix_reference = float(store.close[-1])
    instrument = instrument_nautilus(montage.root, prix_reference=prix_reference)

    moteur = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="RSL-001",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    moteur.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(montage.capital, USD)],
        # Modele de remplissage NEUTRE : ni slippage, ni remplissage partiel.
        # Comparer deux moteurs et deux modeles de friction a la fois ne dirait
        # rien sur aucun des deux.
        fill_model=FillModel(
            prob_fill_on_limit=1.0, prob_fill_on_stop=1.0, prob_slippage=0.0
        ),
        fee_model=FixedFeeModel(
            Money(frais_par_contrat(montage.root) if montage.frais_actifs else 0.0, USD)
        ),
    )
    moteur.add_instrument(instrument)

    bar_type = type_de_barre(montage.root, montage.agregation)
    moteur.add_data(
        barres_nautilus(
            store, bar_type, precision=precision_de(float(instrument.price_increment))
        )
    )
    return moteur


def resume(moteur: BacktestEngine) -> SpecDict:
    """Les chiffres comparables aux notres, extraits du moteur apres un run.

    Volontairement MAIGRE : le but est de confronter deux moteurs, pas de
    reproduire notre rapport. Les metriques de performance restent calculees de
    notre cote, sur la courbe d'equity - c'est la seule facon que les deux
    chiffres soient produits par le meme code.
    """
    compte = moteur.portfolio.account(VENUE)
    rapport = moteur.trader.generate_account_report(VENUE)
    return {
        "solde_final": float(compte.balance_total(USD).as_double()),
        "n_ordres": len(moteur.cache.orders()),
        "n_positions_fermees": len(moteur.cache.positions_closed()),
        "n_lignes_de_compte": len(rapport),
    }


def decimal_ou_zero(valeur: float) -> Decimal:
    """Conversion explicite, pour que les arrondis restent visibles."""
    return Decimal(str(valeur))
