"""Contrat des strategies et registre versionne.

Deux familles, deux classes de base, un seul `Context` et un seul portefeuille
(`docs/execution-model.md` §7). Elles ne partagent pas de classe mere commune :
forcer une abstraction unique servirait mal les deux.

Ce que le socle garantit a une strategie :

  - `on_bar` n'est appele qu'apres `warmup_bars` barres closes, donc les
    fenetres qu'elle demande existent ;
  - le `Context` recu ne contient que du passe ;
  - les ordres retournes seront executes au plus tot a la barre suivante.

Ce qu'il exige d'elle :

  - `warmup_bars` honnete - le sous-declarer produit une
    `InsufficientHistoryError`, pas un resultat approximatif ;
  - aucun etat qui survive au run (voir `reset`), sinon le determinisme et le
    test de corruption du futur tombent ;
  - aucune lecture de fichier, aucun `random` non seede.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from rsl.data.feed import Context, MultiContext
from rsl.errors import ConfigurationError, RegistryError
from rsl.orders import Fill, Order

SpecDict = dict[str, object]


class StrategyParams(BaseModel):
    """Parametres d'une strategie : immuables, fermes, annotables."""

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

    Un bloc de parametres declare `quantity: 4` sans pouvoir dire pourquoi
    quatre. C'est le seul manque reel de JSON face a YAML - mesure le
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


class NoStrategyParams(StrategyParams):
    """Pour les strategies sans parametre."""


class Strategy(ABC):
    """Strategie mono-instrument, appelee a chaque barre close."""

    @property
    @abstractmethod
    def warmup_bars(self) -> int:
        """Barres closes a consommer avant le premier `on_bar`.

        Doit couvrir la plus longue fenetre utilisee. Le runner ne devine pas :
        une fenetre plus longue que le warmup declare leve.
        """

    @abstractmethod
    def on_bar(self, ctx: Context) -> Sequence[Order]:
        """Decision a la cloture de la barre courante.

        Retourne les ordres a soumettre. Une sequence vide signifie "rien a
        faire" - ce n'est pas une erreur, et c'est le cas le plus frequent.
        """

    def on_start(self, ctx: Context) -> None:  # noqa: B027 (crochet optionnel)
        """Appelee une fois, sur la premiere barre soumise apres le warmup."""

    def on_fill(self, fill: Fill) -> None:  # noqa: B027 (crochet optionnel)
        """Notification d'une execution.

        C'est le seul canal par lequel une strategie apprend sa position : elle
        ne lit pas le portefeuille. Cette contrainte a une raison - le
        portefeuille connait l'equity, donc indirectement la performance
        passee, et une strategie qui s'auto-observe devient difficile a
        raisonner. Ce qu'elle a le droit de savoir, c'est ce qu'elle a fait.
        """

    def on_finish(self) -> None:  # noqa: B027 (crochet optionnel)
        """Appelee une fois, apres la derniere barre. Aucun ordre n'est accepte ici.

        Une strategie ne peut pas liquider "a la fin" : elle ne sait pas que
        c'est la fin (`docs/no-lookahead.md` §2.2, regle 4). La liquidation
        terminale, si elle est voulue, est une decision du runner, pas de la
        strategie.
        """

    def reset(self) -> None:  # noqa: B027 (crochet optionnel)
        """Remet la strategie dans son etat initial.

        Appelee par le runner avant chaque run. Toute strategie qui garde un
        etat DOIT le reinitialiser ici : sans cela, deux runs identiques ne
        donnent pas le meme resultat (test n° 8) et un backtest arrete a `k`
        depend de ce qui a tourne avant.
        """

    def describe(self) -> SpecDict:
        """Specification declarative, destinee au manifeste de run."""
        return {"class": type(self).__qualname__}


class CrossSectionalStrategy(ABC):
    """Strategie transversale, appelee aux seules dates de rebalancement.

    Le calendrier de rebalancement appartient au runner, pas a la strategie :
    c'est ce qui permet de rejouer la meme strategie a une autre frequence sans
    la modifier.
    """

    @property
    @abstractmethod
    def warmup_bars(self) -> int:
        """Barres closes requises par instrument avant qu'il soit eligible."""

    def on_fill(self, fill: Fill) -> None:  # noqa: B027 (crochet optionnel)
        """Voir `Strategy.on_fill`."""

    @abstractmethod
    def on_rebalance(self, ctx: MultiContext) -> Sequence[Order]:
        """Decision a la cloture de la derniere barre de la periode.

        `ctx.symbols` ne liste que les instruments qui cotent a cet instant :
        un instrument absent n'a pas "le prix d'avant".
        """

    def on_finish(self) -> None:  # noqa: B027 (crochet optionnel)
        """Voir `Strategy.on_finish` : aucun ordre terminal."""

    def reset(self) -> None:  # noqa: B027 (crochet optionnel)
        """Voir `Strategy.reset`."""

    def describe(self) -> SpecDict:
        return {"class": type(self).__qualname__}


# ---------------------------------------------------------------------------
# Registre versionne
# ---------------------------------------------------------------------------

StrategyFactory = Callable[[StrategyParams], "Strategy | CrossSectionalStrategy"]


@dataclass(frozen=True, slots=True)
class StrategyEntry:
    name: str
    version: int
    factory: StrategyFactory
    params_model: type[StrategyParams]
    summary: str
    cross_sectional: bool

    def build(self, values: SpecDict | None = None) -> Strategy | CrossSectionalStrategy:
        return self.factory(self.params_model.model_validate(values or {}))

    def json_schema(self) -> SpecDict:
        return {
            "name": self.name,
            "version": self.version,
            "ref": f"{self.name}@{self.version}",
            "summary": self.summary,
            "cross_sectional": self.cross_sectional,
            "params": self.params_model.model_json_schema(),
        }


_STRATEGIES: Final[dict[tuple[str, int], StrategyEntry]] = {}


def strategy(
    name: str,
    *,
    version: int = 1,
    params: type[StrategyParams] = NoStrategyParams,
    summary: str = "",
    cross_sectional: bool = False,
) -> Callable[[StrategyFactory], StrategyFactory]:
    """Enregistre une fabrique de strategie sous `(name, version)`.

    Une fabrique plutot qu'une classe : la strategie peut alors etre une
    composition d'objets (patron Composite) et non forcement une sous-classe.
    C'est ce qui permettra a une specification declarative de produire une
    strategie sans qu'aucune classe nouvelle soit ecrite.
    """
    if version < 1:
        raise RegistryError(f"version doit etre >= 1, recu {version} pour '{name}'")

    def decorate(factory: StrategyFactory) -> StrategyFactory:
        key = (name, version)
        if key in _STRATEGIES:
            raise RegistryError(
                f"strategie '{name}@{version}' deja enregistree. Une strategie publiee "
                f"ne se modifie pas : enregistrez '{name}@{version + 1}'."
            )
        _STRATEGIES[key] = StrategyEntry(
            name=name,
            version=version,
            factory=factory,
            params_model=params,
            summary=summary or (factory.__doc__ or "").strip().split("\n")[0],
            cross_sectional=cross_sectional,
        )
        return factory

    return decorate


def get_strategy(name: str, version: int | None = None) -> StrategyEntry:
    versions = sorted(v for (n, v) in _STRATEGIES if n == name)
    if not versions:
        known = ", ".join(sorted({n for n, _ in _STRATEGIES})) or "(aucune)"
        raise RegistryError(f"strategie inconnue : '{name}'. Connues : {known}")
    chosen = versions[-1] if version is None else version
    if chosen not in versions:
        raise RegistryError(
            f"'{name}@{version}' inconnue. Versions : {', '.join(str(v) for v in versions)}"
        )
    return _STRATEGIES[(name, chosen)]


def list_strategies() -> tuple[StrategyEntry, ...]:
    """Triees par (nom, version)."""
    return tuple(_STRATEGIES[key] for key in sorted(_STRATEGIES))


def describe_strategies() -> list[SpecDict]:
    return [entry.json_schema() for entry in list_strategies()]


def build_strategy(spec: SpecDict) -> Strategy | CrossSectionalStrategy:
    """Construit une strategie a partir d'une specification declarative.

    Forme attendue : `{"ref": "sma_crossover@1", "params": {...}}`.

    Cette fonction ne connait aucune strategie en propre : elle delegue au
    registre. Ajouter une strategie ne la modifie pas.
    """
    ref = spec.get("ref")
    if not isinstance(ref, str):
        raise ConfigurationError(f"specification de strategie : champ 'ref' attendu, recu {spec!r}")
    name, _, raw_version = ref.partition("@")
    version = int(raw_version) if raw_version.isdigit() else None
    if raw_version and version is None:
        raise ConfigurationError(f"version invalide dans '{ref}'")
    params = spec.get("params") or {}
    if not isinstance(params, dict):
        raise ConfigurationError(f"'params' doit etre un objet, recu {params!r}")
    return get_strategy(name, version).build(params)
