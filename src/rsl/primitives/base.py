"""Contrat d'une primitive.

Une primitive est une fonction pure `(Context, params) -> float | None`. Elle
ne recoit QUE le `Context` : la garantie anti-look-ahead du contexte se propage
donc a toute la bibliotheque sans regle supplementaire
(`docs/no-lookahead.md` §5.1).

`None` signifie "pas de valeur calculable ici", jamais `NaN`. Un `NaN` se
propage en silence ; un `None` force l'appelant a decider.

Extension par ajout : une primitive est identifiee par un couple
`(nom, version)`. Corriger le comportement d'une primitive publiee ne se fait
pas en editant sa fonction, mais en enregistrant une version suivante. Un
rapport de run archive doit rester rejouable a l'identique des annees plus
tard ; il ne le serait pas si `sma@1` changeait de sens.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol, cast

from pydantic import BaseModel, ConfigDict

from rsl.data.feed import Context
from rsl.errors import ConfigurationError


class PrimitiveParams(BaseModel):
    """Parametres d'une primitive : immuables et fermes.

    `extra="forbid"` est deliberatif : un parametre mal orthographie doit etre
    une erreur, pas un defaut silencieux. C'est la premiere ligne de defense
    quand les specifications seront produites par une machine.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class NoParams(PrimitiveParams):
    """Pour les primitives qui n'ont rien a parametrer."""


PrimitiveFn = Callable[[Context, PrimitiveParams], "float | None"]
WarmupFn = Callable[[PrimitiveParams], int]

VERSION_SEPARATOR: Final[str] = "@"


@dataclass(frozen=True, slots=True)
class PrimitiveRef:
    """Reference nommee et versionnee, ex. `sma@1`.

    `version=None` signifie "la derniere connue". Utilisable en exploration,
    mais toute specification archivee est resolue et epinglee avant d'etre
    ecrite dans le manifeste : un run rejoue ne doit pas dependre de ce qui a
    ete enregistre depuis.
    """

    name: str
    version: int | None = None

    @staticmethod
    def parse(text: str) -> PrimitiveRef:
        if VERSION_SEPARATOR not in text:
            return PrimitiveRef(text)
        name, _, raw = text.partition(VERSION_SEPARATOR)
        if not raw.isdigit():
            raise ConfigurationError(
                f"version invalide dans '{text}' : attendu un entier apres "
                f"'{VERSION_SEPARATOR}', recu '{raw}'"
            )
        return PrimitiveRef(name, int(raw))

    @property
    def is_pinned(self) -> bool:
        return self.version is not None

    def __str__(self) -> str:
        if self.version is None:
            return self.name
        return f"{self.name}{VERSION_SEPARATOR}{self.version}"


@dataclass(frozen=True, slots=True)
class Primitive:
    """Une primitive enregistree : sa fonction, son modele de parametres, son warmup.

    `warmup(params)` retourne le nombre de barres closes necessaires AVANT que
    la primitive puisse produire une valeur. Le runner s'en sert pour ne pas
    appeler une strategie qui leverait `InsufficientHistoryError` a la premiere
    barre.
    """

    name: str
    version: int
    fn: PrimitiveFn
    params_model: type[PrimitiveParams]
    warmup_fn: WarmupFn
    summary: str

    @property
    def ref(self) -> PrimitiveRef:
        return PrimitiveRef(self.name, self.version)

    def parse_params(self, values: dict[str, object] | None = None) -> PrimitiveParams:
        """Valide un dictionnaire de parametres. Point d'entree des specs declaratives."""
        return self.params_model.model_validate(values or {})

    def warmup_bars(self, params: PrimitiveParams) -> int:
        return self.warmup_fn(params)

    def __call__(self, ctx: Context, params: PrimitiveParams) -> float | None:
        return self.fn(ctx, params)

    def bind(self, **values: object) -> BoundPrimitive:
        """Fige des parametres et retourne un objet appelable sur un `Context` seul."""
        return BoundPrimitive(self, self.parse_params(values))

    def json_schema(self) -> dict[str, object]:
        """Description machine, destinee au futur compilateur de specifications.

        Aucune brique LLM n'est construite ici : c'est le point de branchement,
        et il n'expose que ce qui existe deja dans le registre statique.
        """
        return {
            "name": self.name,
            "version": self.version,
            "ref": str(self.ref),
            "summary": self.summary,
            "params": self.params_model.model_json_schema(),
        }


@dataclass(frozen=True, slots=True)
class BoundPrimitive:
    """Primitive + parametres valides. Immuable, reutilisable entre barres."""

    primitive: Primitive
    params: PrimitiveParams

    @property
    def warmup_bars(self) -> int:
        return self.primitive.warmup_bars(self.params)

    def __call__(self, ctx: Context) -> float | None:
        return self.primitive(ctx, self.params)

    def describe(self) -> dict[str, object]:
        return {
            "ref": str(self.primitive.ref),
            "params": self.params.model_dump(mode="json"),
        }


class WindowParams(PrimitiveParams):
    """Parametre commun a toutes les statistiques roulantes.

    La fenetre est en NOMBRE DE BARRES, jamais en duree : le moteur ne
    reconstruit aucune barre manquante, donc une fenetre de 20 barres traverse
    un week-end sans le savoir (`docs/execution-model.md` §5.1).
    """

    window: int

    def model_post_init(self, _context: object, /) -> None:
        if self.window < 1:
            raise ValueError(f"window doit etre >= 1, recu {self.window}")


class _HasWindow(Protocol):
    """Ce que `window_warmup` a besoin de savoir des parametres."""

    window: int


def window_warmup(offset: int = 0) -> WarmupFn:
    """Fabrique un `warmup_fn` pour les primitives a fenetre.

    Le `cast` remplace une contrainte que le registre ne peut pas exprimer : il
    est heterogene, donc type sur `PrimitiveParams`, alors que chaque primitive
    a fenetre travaille sur un modele qui porte `window`. La contrainte reelle
    est verifiee par pydantic a la construction des parametres.
    """

    def compute(params: PrimitiveParams) -> int:
        return cast("_HasWindow", params).window + offset

    return compute


class SupportsSignal(Protocol):
    """Tout ce qui produit une valeur a partir d'un `Context` seul.

    `BoundPrimitive` le satisfait, les noeuds de `strategies.signals` aussi :
    c'est ce qui permet de composer les deux sans les distinguer.
    """

    @property
    def warmup_bars(self) -> int: ...

    def __call__(self, ctx: Context) -> float | None: ...
