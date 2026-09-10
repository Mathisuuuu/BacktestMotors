"""Exceptions du socle.

Une regle : le moteur ne rattrape jamais `LookAheadError` ni
`InsufficientHistoryError`. Un backtest qui a tente de lire le futur, ou qui a
demande plus d'historique qu'il n'en existe, ne produit pas un resultat degrade
- il ne produit pas de resultat. Voir `docs/no-lookahead.md` §2.3 et §2.4.
"""

from __future__ import annotations


class RslError(Exception):
    """Racine de toutes les exceptions du socle."""


class LookAheadError(RslError, RuntimeError):
    """Tentative d'acces a une information non disponible a l'instant courant.

    Levee par le `Context` des qu'un acces vise un index strictement superieur
    au curseur, ou un lag negatif.
    """


class InsufficientHistoryError(RslError, RuntimeError):
    """Historique insuffisant pour satisfaire la demande.

    Volontairement une exception plutot qu'un tableau complete de `NaN` : un
    `NaN` se propage en silence dans une moyenne puis dans une comparaison, et
    une comparaison avec `NaN` vaut `False`, ce qui produit "pas de signal" au
    lieu de "erreur".
    """


class SymbolNotAvailableError(RslError, KeyError):
    """Instrument absent de la coupe transversale a l'instant courant.

    Absent ne signifie pas "dernier prix connu" : voir `docs/no-lookahead.md` §4.1.
    """


class DataValidationError(RslError, ValueError):
    """Les donnees ont ete rejetees par la validation.

    Porte le rapport complet en attribut `report`, pour que l'appelant puisse
    l'afficher ou le serialiser sans re-executer la validation.
    """

    def __init__(self, message: str, report: object | None = None) -> None:
        super().__init__(message)
        self.report = report


class RegistryError(RslError, KeyError):
    """Conflit ou absence dans un registre statique."""


class ConfigurationError(RslError, ValueError):
    """Configuration incoherente detectee hors du champ de pydantic."""
