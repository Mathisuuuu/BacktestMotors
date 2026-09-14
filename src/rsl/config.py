"""Specification declarative d'un backtest, et sa traduction en objets moteur.

Un fichier de configuration decrit un run entierement : donnees, couts,
execution, risque, strategie. Il est valide par pydantic avec
`extra="forbid"` - un parametre mal orthographie est une erreur, jamais un
defaut silencieux. C'est la meme regle que pour les parametres de primitives,
et pour la meme raison : ces fichiers seront bientot ecrits par une machine.

La specification est aussi ce qui est hache dans le manifeste. Deux runs de
meme `config_hash` ont recu les memes instructions - a condition que le hash
porte sur la specification CANONIQUE, pas sur le texte du fichier. Un fichier
reindente donnerait sinon un run "different".
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rsl.data.evenements import EventCalendar, charger_calendrier
from rsl.data.instruments import get_instrument
from rsl.data.loader import build_panel, load_bar_store
from rsl.data.resample import CloseStamp, Period, resample
from rsl.data.schema import (
    AlignPolicy,
    BarStore,
    Granularity,
    InstrumentSpec,
    Panel,
    ns_to_datetime,
)
from rsl.data.session import SessionCalendar, build_session_index
from rsl.data.validation import ValidationConfig
from rsl.engine.cross_sectional import EveryNRows, EveryRow, RebalanceSchedule
from rsl.engine.execution import (
    BpsSlippage,
    ExecutionConfig,
    FeeModel,
    FlatFee,
    IntrabarPriority,
    MarginPolicy,
    PerContractFee,
    SlippageModel,
    TickSlippage,
    ZeroFee,
    ZeroSlippage,
)
from rsl.engine.limites import PortfolioLimits
from rsl.engine.risk import (
    EquityFraction,
    FixedContracts,
    RiskFraction,
    RiskManager,
    SignalSizing,
    SizingRule,
    VolatilityTarget,
)
from rsl.engine.runner import RunConfig
from rsl.env import resolve_data_path
from rsl.errors import ConfigurationError
from rsl.manifest import DataSource
from rsl.strategies.signals import build_signal

SpecDict = dict[str, object]


def _sans_notes(valeur: object) -> Any:
    """Copie de `valeur` sans aucune cle `note`, a toute profondeur.

    `note` est donc un mot RESERVE dans une specification : une cle de ce nom
    y est un commentaire, jamais une donnee. Aucun champ du vocabulaire ne
    porte ce nom, et le squelette le dit dans ses contraintes.

    Recursif plutot que cible sur `strategy.params` : une region libre qui
    apparaitrait demain ailleurs serait couverte sans qu'on y pense - et sur
    les blocs types, ou pydantic a deja retire la note, le passage ne fait
    rien.
    """
    if isinstance(valeur, dict):
        return {c: _sans_notes(v) for c, v in valeur.items() if c != "note"}
    if isinstance(valeur, list):
        return [_sans_notes(v) for v in valeur]
    return valeur


def _sans_plafonds_muets(payload: SpecDict) -> None:
    """Retire `risk.limits` de la charge quand aucun plafond n'y est declare.

    Meme regle que pour `note`, et pour la meme raison : ce qui ne porte aucune
    INSTRUCTION ne doit pas entrer dans le `config_hash`. Un bloc `limits`
    entierement nul dit « aucun plafond », ce que disait deja l'absence du bloc
    avant qu'il existe ; les deux runs ont recu les memes instructions, et deux
    hachages differents pretendraient le contraire.

    Sans ce retrait, ajouter le champ changeait le `config_hash` des SEPT
    exemples - mesure le 2026-09-12 - et rendait incomparable tout run archive,
    sans qu'aucune decision de strategie n'ait bouge.

    La regle est deliberement ETROITE : elle ne retire pas les blocs nuls en
    general, seulement celui-ci, et seulement s'il est entierement nul. Un
    plafond declare, meme large, reste hache - c'est une instruction.

    Modifie sur place : `canonical()` vient de construire la charge et en est
    seul proprietaire.
    """
    risque = payload.get("risk")
    if not isinstance(risque, dict):
        return
    plafonds = risque.get("limits")
    if isinstance(plafonds, dict) and all(v is None for v in plafonds.values()):
        del risque["limits"]


def _sans_calendriers_muets(payload: SpecDict) -> None:
    """Retire `events` quand aucun calendrier n'est declare.

    Meme regle que `_sans_plafonds_muets`, et meme raison : une liste vide
    dit « aucun calendrier », ce que disait deja l'absence du champ avant
    qu'il existe. Sans ce retrait, l'ajouter changerait les sept
    `config_hash` archives sans qu'aucune decision n'ait bouge.
    """
    if not payload.get("events"):
        payload.pop("events", None)


def _sans_allegement_muet(payload: SpecDict) -> None:
    """Retire `execution.intraday_margin_ratio` quand il n'est pas declare.

    Meme regle que `_sans_plafonds_muets`, et meme raison : `null` dit « la
    marge de place s'applique », ce que disait deja l'absence du champ avant
    qu'il existe. Deux runs ont recu les memes instructions ; deux hachages
    differents pretendraient le contraire.

    Verifie le 2026-09-14 : sans ce retrait, ajouter le champ changeait le
    `config_hash` des SEPT exemples, sans qu'aucune decision n'ait bouge.

    Un ratio DECLARE, meme a 1.0, reste hache - c'est une instruction, et
    elle dit quelque chose de different de son absence : celui qui l'ecrit
    affirme avoir considere la question.
    """
    execution = payload.get("execution")
    if not isinstance(execution, dict):
        return
    if execution.get("intraday_margin_ratio") is None:
        execution.pop("intraday_margin_ratio", None)


class StrictModel(BaseModel):
    """Base commune : immuable, fermee aux champs inconnus, annotable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    note: str | list[str] | None = Field(
        default=None,
        exclude=True,
        description=(
            "Commentaire libre. Ignore par le moteur, EXCLU du config_hash. "
            "Une liste de chaines vaut plusieurs lignes."
        ),
    )
    """Le « pourquoi », que JSON ne permet pas d'ecrire autrement.

    Une specification declare `-1.5` et `120` sans pouvoir dire d'ou ils
    viennent. C'est le seul manque reel de JSON face a YAML - mesure le
    2026-09-12 : le reste du proces fait a JSON ne tenait pas ici, les modeles
    stricts attrapant les coercions de YAML, et cinq des dix operateurs du
    vocabulaire (`>`, `>=`, `!=`, `-`, `*`) entrant en collision avec sa
    syntaxe.

    `exclude=True` est le point qui compte : le champ ne figure pas dans
    `model_dump`, donc pas dans `canonical()`, donc pas dans le `config_hash`.
    Corriger une faute de frappe dans un commentaire n'invalide pas la
    comparaison avec un run archive. Il reste PUBLIE dans le schema engendre -
    une machine qui ecrit une specification doit savoir qu'elle peut
    s'expliquer.

    Une LISTE pour les notes de plusieurs lignes : JSON n'a pas de chaine
    multiligne, et `
` au milieu d'un texte est illisible.
    """


# ---------------------------------------------------------------------------
# Donnees
# ---------------------------------------------------------------------------


class SessionSpec(StrictModel):
    """Calendrier de seance DECLARE pour un instrument.

    Vit dans la specification, donc entre dans le `config_hash` : deux runs qui
    declarent des seances differentes ne peuvent pas se confondre. Le socle ne
    deduit jamais de frontiere des donnees - voir `rsl.data.session`.
    """

    start: str = Field(description="Heure d'ouverture locale, 'HH:MM'")
    end: str = Field(description="Heure de fermeture locale, 'HH:MM'")
    timezone: str = Field(description="Fuseau IANA, ex. 'America/Chicago'")

    def build(self) -> SessionCalendar:
        return SessionCalendar(start=self.start, end=self.end, timezone=self.timezone)


class DataSpec(StrictModel):
    """Un instrument, son fichier, et son eventuelle agregation."""

    root: str = Field(min_length=1, description="Racine connue de la table d'instruments")
    path: Path
    timestamp_column: str | None = None
    granularity_minutes: int = Field(default=1, ge=1)
    resample: Period | None = Field(
        default=None,
        description="Agregation calendaire appliquee apres chargement.",
    )
    resample_min_bars: int | None = Field(default=None, ge=1)
    close_stamp: CloseStamp = CloseStamp.PERIOD_END
    max_gap_seconds: float | None = Field(default=None, gt=0.0)
    allow_non_positive_prices: bool = True
    session: SessionSpec | None = Field(
        default=None,
        description="Calendrier de seance. Sans lui, le noeud `session` leve.",
    )
    alias: str | None = Field(
        default=None,
        min_length=1,
        description="Nom sous lequel cette serie est publiee. Permet de declarer "
        "le MEME instrument a deux granularites, chacune sous son nom.",
    )

    @model_validator(mode="after")
    def _une_periode_intraday_exige_une_seance(self) -> DataSpec:
        """Une barre de 4 h ne dit pas ou elle commence.

        Les periodes calendaires se lisent dans l'horodatage seul. Les
        intra-journalieres n'ont aucun ancrage naturel, et le socle refuse d'en
        deviner un - c'est la meme decision que celle qui a fait ecarter le
        noeud `session` jusqu'a ce qu'un calendrier soit DECLARE (voir le
        ledger, 2026-09-11).

        Refuse ici plutot qu'au chargement : l'erreur porte sur le fichier, et
        `resample` la leverait apres avoir lu des centaines de Mo de parquet.
        """
        if self.resample is None or not self.resample.intra_journaliere:
            return self
        if self.session is None:
            raise ValueError(
                f"resample '{self.resample.value}' sur '{self.root}' exige une "
                f"`session` : une barre de {self.resample.minutes} min ne dit pas "
                f"ou elle commence, et le socle ne devine aucune frontiere. "
                f"Ajouter session: {{start, end, timezone}} a cette entree."
            )
        return self

    @property
    def key(self) -> str:
        """Nom sous lequel la serie est publiee au panneau.

        Sans alias, c'est le symbole du contrat. L'unicite reste verifiee sur
        CE nom : declarer deux fois la meme serie reste une erreur, mais
        declarer deux granularites devient possible a condition de les nommer.
        Nommer est le point : une duplication accidentelle et une duplication
        voulue ne doivent pas se ressembler.
        """
        return self.alias if self.alias is not None else self.instrument.symbol

    @property
    def instrument(self) -> InstrumentSpec:
        return get_instrument(self.root)

    @property
    def resolved_path(self) -> Path:
        """Chemin absolu reel du fichier, sur CETTE machine.

        Un chemin relatif est resolu contre la racine declaree par
        l'environnement (`RSL_DATA_DIR`, ou un `.env`). C'est la seule forme
        portable : voir `rsl.env`.
        """
        return resolve_data_path(self.path)

    def canonical_path(self) -> str:
        """Forme du chemin qui entre dans le `config_hash`.

        Un chemin relatif est conserve relatif, et normalise en separateurs
        POSIX : c'est ce qui permet a deux machines de produire le MEME
        `config_hash` pour le meme run. Un chemin absolu reste absolu - le
        comportement d'origine, conserve pour les specifications anciennes,
        au prix de sa non-portabilite.
        """
        if self.path.is_absolute():
            return str(self.path.resolve())
        return self.path.as_posix()

    @property
    def validation(self) -> ValidationConfig:
        return ValidationConfig(
            max_gap=(
                None if self.max_gap_seconds is None else timedelta(seconds=self.max_gap_seconds)
            ),
            allow_non_positive_prices=self.allow_non_positive_prices,
        )


# ---------------------------------------------------------------------------
# Couts et execution
# ---------------------------------------------------------------------------


class FeeSpec(StrictModel):
    """Modele de frais. Aucun defaut : le choix doit etre ecrit."""

    kind: Literal["per_contract", "flat", "zero"]
    per_contract: float | None = Field(default=None, ge=0.0)

    def build(self) -> FeeModel:
        match self.kind:
            case "per_contract":
                return PerContractFee()
            case "flat":
                if self.per_contract is None:
                    raise ConfigurationError("frais 'flat' : `per_contract` est requis")
                return FlatFee(self.per_contract)
            case "zero":
                return ZeroFee()


class SlippageSpec(StrictModel):
    """Modele de slippage. Aucun defaut, meme raison."""

    kind: Literal["tick", "bps", "zero"]
    ticks: float | None = Field(default=None, ge=0.0)
    bps: float | None = Field(default=None, ge=0.0)

    def build(self) -> SlippageModel:
        match self.kind:
            case "tick":
                if self.ticks is None:
                    raise ConfigurationError("slippage 'tick' : `ticks` est requis")
                return TickSlippage(self.ticks)
            case "bps":
                if self.bps is None:
                    raise ConfigurationError("slippage 'bps' : `bps` est requis")
                return BpsSlippage(self.bps)
            case "zero":
                return ZeroSlippage()


class ExecutionSpec(StrictModel):
    """Parametres d'execution. `fees` et `slippage` sont obligatoires."""

    fees: FeeSpec
    slippage: SlippageSpec
    lag_bars: int = Field(default=1, ge=1)
    intrabar_priority: IntrabarPriority = IntrabarPriority.PESSIMISTIC
    max_fill_gap_seconds: float | None = Field(default=None, gt=0.0)
    margin_policy: MarginPolicy = MarginPolicy.REJECT
    intraday_margin_ratio: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description=(
            "Fraction de la marge initiale immobilisee, pour une strategie "
            "qui ne franchit pas la nuit. La table des instruments porte des "
            "marges OVERNIGHT ; un intraday paie une marge de JOUR, fixee par "
            "son courtier. Sans ce champ, la marge de place s'applique."
        ),
    )

    @property
    def margin_ratio(self) -> float:
        """1.0 tant qu'aucun allegement intraday n'est declare."""
        return 1.0 if self.intraday_margin_ratio is None else self.intraday_margin_ratio

    def build(self) -> ExecutionConfig:
        return ExecutionConfig(
            fees=self.fees.build(),
            slippage=self.slippage.build(),
            execution_lag=self.lag_bars,
            intrabar_priority=self.intrabar_priority,
            max_fill_gap=(
                None
                if self.max_fill_gap_seconds is None
                else timedelta(seconds=self.max_fill_gap_seconds)
            ),
            margin_policy=self.margin_policy,
            margin_ratio=self.margin_ratio,
        )


# ---------------------------------------------------------------------------
# Risque
# ---------------------------------------------------------------------------


class SizingSpec(StrictModel):
    kind: Literal[
        "none", "fixed", "equity_fraction", "risk_fraction", "vol_target", "signal"
    ] = "none"
    contracts: int | None = Field(default=None, ge=1)
    fraction: float | None = Field(default=None, gt=0.0)
    atr_window: int = Field(default=14, ge=1)
    atr_multiple: float = Field(default=2.0, gt=0.0)
    vol_target: float | None = Field(
        default=None,
        gt=0.0,
        description="Ecart-type cible des rendements PAR BARRE, jamais annualise.",
    )
    vol_window: int = Field(default=20, ge=2)
    vol_max_multiple: float = Field(default=4.0, gt=0.0)
    signal: SpecDict | None = Field(
        default=None,
        description="Noeud de signal donnant la taille. Requis pour kind='signal'.",
    )
    max_contracts: int | None = Field(
        default=None,
        ge=1,
        description="Plafond obligatoire pour kind='signal' : une expression "
        "arbitraire n'est pas bornee.",
    )

    def build(self) -> SizingRule | None:
        match self.kind:
            case "none":
                return None
            case "fixed":
                if self.contracts is None:
                    raise ConfigurationError("sizing 'fixed' : `contracts` est requis")
                return FixedContracts(self.contracts)
            case "equity_fraction":
                if self.fraction is None:
                    raise ConfigurationError("sizing 'equity_fraction' : `fraction` est requis")
                return EquityFraction(self.fraction)
            case "risk_fraction":
                if self.fraction is None:
                    raise ConfigurationError("sizing 'risk_fraction' : `fraction` est requis")
                return RiskFraction(
                    self.fraction, atr_window=self.atr_window, atr_multiple=self.atr_multiple
                )
            case "signal":
                if self.signal is None:
                    raise ConfigurationError("sizing 'signal' : `signal` est requis")
                if self.max_contracts is None:
                    raise ConfigurationError(
                        "sizing 'signal' : `max_contracts` est requis. Une expression "
                        "arbitraire peut produire n'importe quelle valeur, et une taille "
                        "non bornee n'est pas une strategie"
                    )
                return SignalSizing(build_signal(self.signal), self.max_contracts)
            case "vol_target":
                if self.vol_target is None:
                    raise ConfigurationError("sizing 'vol_target' : `vol_target` est requis")
                return VolatilityTarget(
                    self.vol_target,
                    vol_window=self.vol_window,
                    vol_max_multiple=self.vol_max_multiple,
                    contracts_base=self.contracts if self.contracts is not None else 1,
                )


class PortfolioLimitsSpec(StrictModel):
    """Plafonds portant sur le PORTEFEUILLE entier.

    A ne pas confondre avec `max_gross_contracts`, juste au-dessus, qui borne
    un INSTRUMENT en contrats. Les deux coexistent et repondent a deux
    questions differentes ; `engine/limites.py` explique pourquoi un plafond en
    contrats ne peut pas repondre a celle-ci.

    Tout est facultatif et `None` par defaut : une specification ecrite avant
    ce jour rend exactement les memes chiffres qu'avant.
    """

    max_gross_exposure: float | None = Field(
        default=None,
        gt=0.0,
        description="Somme des |notionnels| / equity. Borne le risque de base "
        "total, y compris celui d'un portefeuille neutre en directionnel.",
    )
    max_net_exposure: float | None = Field(
        default=None,
        gt=0.0,
        description="|Somme des notionnels signes| / equity. Borne la seule "
        "exposition directionnelle ; un long/short couvert y compte pour peu.",
    )
    max_positions: int | None = Field(
        default=None, ge=1, description="Nombre d'instruments detenus a la fois."
    )
    max_per_category: int | None = Field(
        default=None,
        ge=1,
        description="Nombre d'instruments detenus par classe d'actif "
        "(indices, metaux, energie, forex). Un instrument sans classe declaree "
        "est compte avec les autres sans classe, jamais exempte.",
    )

    def build(self) -> PortfolioLimits:
        return PortfolioLimits(
            max_gross_exposure=self.max_gross_exposure,
            max_net_exposure=self.max_net_exposure,
            max_positions=self.max_positions,
            max_per_category=self.max_per_category,
        )


class RiskSpec(StrictModel):
    sizing: SizingSpec = SizingSpec()
    max_gross_contracts: int | None = Field(
        default=None,
        ge=1,
        description="Borne |position| POUR UN INSTRUMENT, en contrats. Son nom "
        "dit 'gross' mais il ne regarde pas le portefeuille : pour cela, voir "
        "`limits`.",
    )
    limits: PortfolioLimitsSpec = PortfolioLimitsSpec()

    def build(self, margin_policy: MarginPolicy) -> RiskManager:
        # Le ratio de marge ne passe PAS par ici : il vit sur le
        # portefeuille, que le gestionnaire de risque interroge. Le
        # dupliquer ouvrirait la porte a ce que les deux divergent.
        return RiskManager(
            sizing=self.sizing.build(),
            margin_policy=margin_policy,
            max_gross_contracts=self.max_gross_contracts,
            limits=self.limits.build(),
        )


# ---------------------------------------------------------------------------
# Strategie et calendrier
# ---------------------------------------------------------------------------


class StrategySpec(StrictModel):
    ref: str = Field(min_length=1, description="Reference versionnee, ex. 'sma_crossover@1'")
    params: dict[str, object] = Field(default_factory=dict)

    def as_dict(self) -> SpecDict:
        return {"ref": self.ref, "params": dict(self.params)}


class EventSourceSpec(StrictModel):
    """Un calendrier d'ANNONCES declare.

    Le fichier porte une colonne `ts_event` en nanosecondes UTC. Son
    contenu est hache et entre au manifeste, comme les cotations.
    """

    name: str = Field(min_length=1, description="Nom lu par le noeud `event`")
    path: Path = Field(description="Relatif a RSL_DATA_DIR, ou absolu")
    known_in_advance: bool = Field(
        default=False,
        description=(
            "AFFIRME que ces dates etaient publiees a l'avance. Sans cette "
            "affirmation, `minutes_until` leve - il lit un instant futur, et "
            "un calendrier reconstruit apres coup ferait entrer du futur sans "
            "qu'aucune inspection du code ne le voie."
        ),
    )

    def canonical_path(self) -> str:
        """Meme regle que pour les cotations : relatif reste relatif."""
        if self.path.is_absolute():
            return str(self.path.resolve())
        return self.path.as_posix()


class RebalanceSpec(StrictModel):
    kind: Literal["every_row", "every_n_rows"] = "every_row"
    n: int = Field(default=1, ge=1)
    offset: int = Field(default=0, ge=0)

    def build(self) -> RebalanceSchedule:
        if self.kind == "every_row":
            return EveryRow()
        return EveryNRows(self.n, self.offset)


class PanelSpec(StrictModel):
    align_policy: AlignPolicy = AlignPolicy.DROP
    max_ffill_bars: int | None = Field(default=None, ge=0)
    allow_mixed_granularity: bool = Field(
        default=False,
        description="Autorise des granularites differentes dans le panneau. "
        "Necessaire pour le multi-timeframe, dangereux pour un classement "
        "transversal - qui comparerait alors des rendements de natures "
        "differentes.",
    )


# ---------------------------------------------------------------------------
# Specification complete
# ---------------------------------------------------------------------------


class BacktestSpec(StrictModel):
    """Tout ce qu'il faut pour lancer un run, et rien d'autre."""

    name: str = Field(min_length=1)
    initial_cash: float = Field(gt=0.0)
    data: list[DataSpec] = Field(min_length=1)
    events: list[EventSourceSpec] = Field(
        default_factory=list,
        description="Calendriers d'annonces, lus par le noeud `event`",
    )
    execution: ExecutionSpec
    strategy: StrategySpec
    risk: RiskSpec = RiskSpec()
    panel: PanelSpec = PanelSpec()
    rebalance: RebalanceSpec = RebalanceSpec()
    seed: int = 0
    stop: int | None = Field(default=None, ge=1)
    min_warmup_bars: int = Field(
        default=0,
        ge=0,
        description=(
            'Plancher de prechauffage. Utilise par le walk-forward pour decrire '
            'une fenetre de test qui commence a une barre donnee.'
        ),
    )
    liquidate_at_end: bool = False
    check_invariant: bool = True
    risk_free_annual: float = Field(default=0.0, ge=-0.5)
    with_data_hash: bool = Field(
        default=True,
        description=(
            "Calculer le SHA-256 des fichiers sources. Le desactiver accelere une "
            "exploration mais rend le manifeste incomplet, et le rapport le signale."
        ),
    )

    @model_validator(mode="after")
    def _refuse_un_panneau_intraday_a_seances_differentes(self) -> BacktestSpec:
        """Deux seances differentes n'ont aucune frontiere de tranche commune.

        Une periode calendaire aligne les instruments parce que la frontiere de
        mois est la meme pour tous. Une tranche intra-journaliere est ancree sur
        l'OUVERTURE, donc deux instruments qui n'ouvrent pas a la meme heure
        n'ont plus une seule frontiere en commun.

        Le panneau prend l'UNION des horodatages de cloture : chaque tranche de
        chaque instrument y devient sa propre ligne, avec un univers d'un seul
        nom. Mesure le 2026-09-12 sur ES (CME) + FDAX (Eurex) en tranches de
        4 h : **18 653 lignes sur 18 654 ne portaient qu'un instrument**, soit
        100 %. Une strategie transversale n'y aurait jamais rien a comparer, et
        n'aurait leve aucune erreur - elle aurait simplement saute tous ses
        rebalancements.

        C'est le meme defaut que celui qui a fait choisir `CloseStamp.
        PERIOD_END` pour les periodes calendaires (`rsl.data.resample`), mais
        `allow_mixed_granularity` ne le voit pas : les deux series sont bien en
        `4h`, c'est leur ANCRAGE qui differe.

        Un seul instrument agrege en intra-journalier reste evidemment permis -
        c'est l'usage prevu.
        """
        # Un TUPLE trie plutot que le dictionnaire de `describe()` : il faut
        # pouvoir mettre ces declarations dans un ensemble pour les compter.
        seances = {
            (
                (entry.session.start, entry.session.end, entry.session.timezone)
                if entry.session is not None
                else None
            )
            for entry in self.data
            if entry.resample is not None and entry.resample.intra_journaliere
        }
        if len(seances) <= 1:
            return self
        lisibles = sorted(
            "aucune" if s is None else f"{s[0]}-{s[1]}@{s[2]}" for s in seances
        )
        raise ValueError(
            f"panneau intra-journalier a seances differentes ({', '.join(lisibles)}) : "
            f"deux seances distinctes n'ont aucune frontiere de tranche commune, et "
            f"le panneau produirait une ligne par instrument et par tranche - mesure "
            f"a 100 % de lignes a un seul instrument sur ES + FDAX en 4 h. Declarer "
            f"la MEME seance pour tous les instruments agreges en intra-journalier, "
            f"ou agreger en `day` ou au-dela, qui alignent."
        )

    @model_validator(mode="after")
    def _refuse_allocation_ecrasee(self) -> BacktestSpec:
        """Une allocation en argent et une regle de dimensionnement s'excluent.

        `RiskManager._size` REMPLACE la quantite de l'ordre par celle que rend
        la regle de dimensionnement. Une strategie de classement qui a reparti
        son budget entre six noms verrait donc ses six tailles ecrasees par la
        meme valeur, sans erreur et sans compteur : l'allocation serait
        declaree, calculee, et jetee.

        Les deux repondent d'ailleurs a la meme question - combien de contrats
        - depuis deux endroits. Une seule doit le faire.

        Refuse a la VALIDATION, pas au run : le fichier est faux, et un backtest
        de plusieurs minutes qui produit des chiffres ininterpretables est pire
        qu'un refus immediat. `kind: "fixed"` reste autorise avec un
        dimensionnement, puisqu'il ne repartit rien.

        Leve un `ValueError` nu et non un `ConfigurationError` : ce dernier se
        documente comme « detectee HORS du champ de pydantic ». Ici on est
        dedans, et pydantic l'enveloppe dans le `ValidationError` qui porte deja
        toutes les autres erreurs de specification - `extra="forbid"`, `ge=1`,
        type invalide. Une seule forme d'echec a lire pour un fichier faux.
        """
        if self.risk.sizing.kind == "none":
            return self
        allocation = self.strategy.params.get("allocation")
        if not isinstance(allocation, dict):
            return self
        genre = allocation.get("kind", "fixed")
        if genre == "fixed":
            return self
        raise ValueError(
            f"allocation '{genre}' et sizing '{self.risk.sizing.kind}' ne peuvent "
            f"pas coexister : les deux decident du nombre de contrats, et le "
            f"dimensionnement passe en dernier - il ecraserait la repartition. "
            f"Choisir l'un des deux : `risk.sizing.kind = \"none\"` pour laisser "
            f"l'allocation repartir, ou une allocation 'fixed' pour laisser le "
            f"dimensionnement decider."
        )

    def canonical(self) -> SpecDict:
        """Forme canonique hachee dans le manifeste.

        Les chemins sont normalises : deux invocations depuis des repertoires
        differents doivent donner la meme empreinte si elles designent les
        memes fichiers.

        Un bloc `risk.limits` entierement nul est retire : voir
        `_sans_plafonds_muets`. Il ne dit rien de plus que son absence, et
        l'avoir hache aurait rendu incomparable tout run anterieur a son
        existence. Meme traitement pour `execution.intraday_margin_ratio`
        laisse a `null` (`_sans_allegement_muet`).

        Les `note` sont retirees a TOUTE profondeur. Sur les blocs types,
        pydantic s'en charge deja (`exclude=True`) - mais les noeuds de
        signaux vivent dans une region LIBRE (`strategy.params.rules`, que
        `RuleStrategyParams` declare `dict[str, object]`), que `model_dump`
        recopie telle quelle. Sans ce retrait, annoter un seuil changeait le
        `config_hash` : mesure le 2026-09-12, `c686c31f` -> `bf0f2f3f` sur
        `examples/paire_es_nq.json`. C'est exactement la ou une note sert le
        plus, donc exactement la ou la garantie devait tenir.
        """
        payload = self.model_dump(mode="json")
        for entry, source in zip(payload["data"], self.data, strict=True):
            entry["path"] = source.canonical_path()
        _sans_plafonds_muets(payload)
        _sans_allegement_muet(payload)
        _sans_calendriers_muets(payload)
        propre = _sans_notes(payload)
        assert isinstance(propre, dict)
        return propre

    def build_run_config(self) -> RunConfig:
        return RunConfig(
            initial_cash=self.initial_cash,
            execution=self.execution.build(),
            liquidate_at_end=self.liquidate_at_end,
            check_invariant=self.check_invariant,
            stop=self.stop,
            min_warmup_bars=self.min_warmup_bars,
        )

    def build_risk(self) -> RiskManager:
        return self.risk.build(self.execution.margin_policy)


# ---------------------------------------------------------------------------
# Chargement des donnees
# ---------------------------------------------------------------------------


def load_events(spec: BacktestSpec) -> dict[str, EventCalendar]:
    """Charge les calendriers declares, et refuse deux fois le meme nom."""
    calendriers: dict[str, EventCalendar] = {}
    for source in spec.events:
        if source.name in calendriers:
            raise ConfigurationError(
                f"deux calendriers portent le nom '{source.name}' : le noeud "
                f"`event` ne saurait lequel lire."
            )
        calendriers[source.name] = charger_calendrier(
            resolve_data_path(source.path),
            name=source.name,
            known_in_advance=source.known_in_advance,
            with_hash=spec.with_data_hash,
        )
    return calendriers


def load_stores(
    spec: BacktestSpec,
) -> tuple[dict[str, BarStore], dict[str, InstrumentSpec], tuple[DataSource, ...]]:
    """Charge, valide, agrege si demande, et decrit chaque source.

    Leve `DataValidationError` si un fichier est rejete : mieux vaut pas de
    resultat qu'un resultat sur des donnees douteuses.
    """
    stores: dict[str, BarStore] = {}
    instruments: dict[str, InstrumentSpec] = {}
    sources: list[DataSource] = []

    for entry in spec.data:
        instrument = entry.instrument
        store, _report = load_bar_store(
            entry.resolved_path,
            symbol=instrument.symbol,
            granularity=Granularity.minutes(entry.granularity_minutes),
            timestamp_column=entry.timestamp_column,
            config=entry.validation,
            with_hash=spec.with_data_hash,
        )
        transformations: list[str] = []
        if entry.resample is not None:
            # Le calendrier n'est transmis que pour une periode
            # intra-journaliere : `resample` REFUSE d'en recevoir un sur une
            # periode calendaire, ou il ne changerait rien - le passer quand
            # meme laisserait croire le contraire.
            store, resample_report = resample(
                store,
                entry.resample,
                min_bars=entry.resample_min_bars,
                close_stamp=entry.close_stamp,
                calendar=(
                    entry.session.build()
                    if entry.session is not None and entry.resample.intra_journaliere
                    else None
                ),
            )
            transformations.append(
                f"resample:{entry.resample.value}"
                f"({resample_report.n_periods} periodes, "
                f"{resample_report.n_dropped_incomplete} ecartee(s))"
            )

        if entry.session is not None:
            calendrier = entry.session.build()
            store = store.with_sessions(
                build_session_index(
                    store.ts_close, store.open, store.high, store.low,
                    store.close, store.volume, calendrier,
                )
            )
            transformations.append(
                f"session:{calendrier.start}-{calendrier.end}@{calendrier.timezone}"
            )

        cle = entry.key
        if cle in stores:
            raise ConfigurationError(
                f"'{cle}' apparait deux fois dans la specification. Pour declarer "
                f"le meme instrument a deux granularites, donner un `alias` distinct "
                f"a l'une des deux entrees."
            )
        stores[cle] = store
        # Meme contrat, donc memes multiplicateur, tick et frais : un alias
        # change la SERIE publiee, jamais l'instrument sous-jacent.
        instruments[cle] = instrument
        sources.append(
            DataSource(
                symbol=cle,
                path=str(entry.resolved_path.resolve()),
                source_hash=store.source_hash,
                n_bars=store.n_bars,
                granularity=str(store.granularity),
                first_ts=ns_to_datetime(int(store.ts_close[0])).isoformat(),
                last_ts=ns_to_datetime(int(store.ts_close[-1])).isoformat(),
                transformations=tuple(transformations),
            )
        )

    return stores, instruments, tuple(sources)


def build_panel_from(spec: BacktestSpec, stores: dict[str, BarStore]) -> Panel:
    """Panneau multi-instruments, selon la politique d'alignement demandee."""
    return build_panel(
        stores,
        align_policy=spec.panel.align_policy,
        max_ffill_bars=spec.panel.max_ffill_bars,
        allow_mixed_granularity=spec.panel.allow_mixed_granularity,
    )
