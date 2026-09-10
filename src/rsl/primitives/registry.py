"""Registre STATIQUE et versionne des primitives.

Statique : il se remplit a l'import, jamais a l'execution d'un run. Aucune
auto-extension, aucune generation de code - c'est explicitement hors perimetre
de cette phase.

Versionne : la cle est `(nom, version)`. Reenregistrer une cle existante leve
`RegistryError`. C'est la regle qui rend le socle extensible SANS reecriture :

  - une primitive nouvelle          -> `@primitive("atr", version=1)`
  - un comportement a corriger      -> `@primitive("atr", version=2)`, la v1
                                       reste en place et reste rejouable
  - une primitive obsolete          -> `deprecate("atr", 1, reason=...)`, elle
                                       reste resolvable et signale sa raison

Rien de ce qui est deja publie n'est jamais edite.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, TypeVar, cast

from rsl.data.feed import Context
from rsl.errors import RegistryError
from rsl.primitives.base import (
    BoundPrimitive,
    NoParams,
    Primitive,
    PrimitiveParams,
    PrimitiveRef,
    WarmupFn,
)

ParamsT = TypeVar("ParamsT", bound=PrimitiveParams)
TypedPrimitiveFn = Callable[[Context, ParamsT], "float | None"]

_REGISTRY: Final[dict[tuple[str, int], Primitive]] = {}
_DEPRECATIONS: Final[dict[tuple[str, int], str]] = {}


def _constant_warmup(n: int) -> WarmupFn:
    def compute(_params: PrimitiveParams) -> int:
        return n

    return compute


def primitive(
    name: str,
    *,
    version: int = 1,
    params: type[PrimitiveParams] = NoParams,
    warmup: int | WarmupFn = 1,
    summary: str = "",
) -> Callable[[TypedPrimitiveFn[ParamsT]], TypedPrimitiveFn[ParamsT]]:
    """Enregistre une primitive sous `(name, version)`.

    `warmup` est soit un entier constant, soit une fonction des parametres
    (typiquement `lambda p: p.window`).

    La fonction decoree est retournee inchangee : elle reste directement
    appelable et testable sans passer par le registre.
    """
    if version < 1:
        raise RegistryError(f"version doit etre >= 1, recu {version} pour '{name}'")
    if not name or not name.replace("_", "").isalnum():
        raise RegistryError(
            f"nom de primitive invalide : '{name}'. Attendu alphanumerique et underscores."
        )

    warmup_fn: WarmupFn = warmup if callable(warmup) else _constant_warmup(warmup)

    def decorate(fn: TypedPrimitiveFn[ParamsT]) -> TypedPrimitiveFn[ParamsT]:
        key = (name, version)
        if key in _REGISTRY:
            existing = _REGISTRY[key]
            raise RegistryError(
                f"'{name}@{version}' est deja enregistree ({existing.fn.__module__}."
                f"{existing.fn.__qualname__}). Une primitive publiee ne se modifie pas : "
                f"enregistrez '{name}@{version + 1}'."
            )
        _REGISTRY[key] = Primitive(
            name=name,
            version=version,
            # Le registre est heterogene : il stocke des primitives dont les
            # modeles de parametres different. Le `cast` remplace ici une
            # contravariance que le typage ne peut pas exprimer ; la validation
            # reelle des parametres se fait dans `Primitive.parse_params`.
            fn=cast("Callable[[Context, PrimitiveParams], float | None]", fn),
            params_model=params,
            warmup_fn=warmup_fn,
            summary=summary or (fn.__doc__ or "").strip().split("\n")[0],
        )
        return fn

    return decorate


def deprecate(name: str, version: int, *, reason: str) -> None:
    """Marque une version comme decouragee sans la retirer.

    Elle reste resolvable : un run archive qui l'epingle doit continuer a
    tourner. Seuls les nouveaux usages sont signales.
    """
    key = (name, version)
    if key not in _REGISTRY:
        raise RegistryError(f"'{name}@{version}' inconnue : rien a deprecier")
    _DEPRECATIONS[key] = reason


def deprecation_reason(name: str, version: int) -> str | None:
    return _DEPRECATIONS.get((name, version))


def get_primitive(ref: PrimitiveRef | str) -> Primitive:
    """Resout une reference. Sans version, retourne la plus recente."""
    reference = PrimitiveRef.parse(ref) if isinstance(ref, str) else ref
    versions = sorted(v for (n, v) in _REGISTRY if n == reference.name)
    if not versions:
        known = ", ".join(sorted({n for n, _ in _REGISTRY}))
        raise RegistryError(f"primitive inconnue : '{reference.name}'. Connues : {known}")
    if reference.version is None:
        return _REGISTRY[(reference.name, versions[-1])]
    if reference.version not in versions:
        raise RegistryError(
            f"'{reference.name}@{reference.version}' inconnue. "
            f"Versions disponibles : {', '.join(str(v) for v in versions)}"
        )
    return _REGISTRY[(reference.name, reference.version)]


def bind_primitive(ref: PrimitiveRef | str, **values: object) -> BoundPrimitive:
    """Resout et fige des parametres en une etape."""
    return get_primitive(ref).bind(**values)


def resolve_pinned(ref: PrimitiveRef | str) -> PrimitiveRef:
    """Retourne la reference epinglee correspondante.

    Utilise a l'ecriture du manifeste : une specification archivee ne doit pas
    dependre de ce qui a ete enregistre depuis.
    """
    return get_primitive(ref).ref


def list_primitives() -> tuple[Primitive, ...]:
    """Toutes les primitives, triees par (nom, version).

    Le tri est explicite : l'ordre d'iteration d'un dictionnaire ne doit
    influencer aucun resultat (exigence de reproductibilite).
    """
    return tuple(_REGISTRY[key] for key in sorted(_REGISTRY))


def latest_versions() -> dict[str, int]:
    out: dict[str, int] = {}
    for name, version in sorted(_REGISTRY):
        out[name] = max(version, out.get(name, 0))
    return out


def describe_registry() -> list[dict[str, object]]:
    """Catalogue machine du registre.

    C'est le point de branchement de la phase suivante : un compilateur de
    specifications lira ce catalogue pour savoir ce qui existe. Rien de tel
    n'est construit ici.
    """
    catalogue: list[dict[str, object]] = []
    for prim in list_primitives():
        entry = prim.json_schema()
        reason = deprecation_reason(prim.name, prim.version)
        if reason is not None:
            entry["deprecated"] = reason
        catalogue.append(entry)
    return catalogue


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """Empreinte du registre a un instant donne, pour le manifeste de run."""

    entries: tuple[str, ...]

    @staticmethod
    def capture() -> RegistrySnapshot:
        return RegistrySnapshot(tuple(str(p.ref) for p in list_primitives()))
