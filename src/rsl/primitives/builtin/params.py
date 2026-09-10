"""Modeles de parametres partages par les primitives integrees.

Ils vivent a part pour que l'ajout d'une primitive n'oblige jamais a toucher
au modele d'une autre.
"""

from __future__ import annotations

from rsl.data.schema import Field
from rsl.primitives.base import PrimitiveParams, WindowParams


class FieldWindowParams(WindowParams):
    """Fenetre glissante appliquee a un champ OHLCV."""

    field: Field = Field.CLOSE


class HighWindowParams(WindowParams):
    """Fenetre glissante, appliquee par defaut au `high`."""

    field: Field = Field.HIGH


class LowWindowParams(WindowParams):
    """Fenetre glissante, appliquee par defaut au `low`."""

    field: Field = Field.LOW


class ReturnsParams(PrimitiveParams):
    """Rendement sur `window` barres.

    `window=1` est le rendement barre a barre. La fenetre est en barres, pas en
    duree : sur des donnees 1 minute trouees, `window=60` n'est pas "une heure".
    """

    window: int = 1
    field: Field = Field.CLOSE
    log: bool = False

    def model_post_init(self, _context: object, /) -> None:
        if self.window < 1:
            raise ValueError(f"window doit etre >= 1, recu {self.window}")


class EmaParams(FieldWindowParams):
    """Moyenne exponentielle sur une fenetre tronquee.

    Une EMA exacte depend de toute l'histoire depuis l'origine. Une primitive
    ne voyant que les `n` dernieres barres, elle est calculee sur un historique
    tronque de `window * seed_multiplier` barres, amorce par la moyenne simple
    des `window` premieres valeurs de cet historique.

    Avec le defaut `seed_multiplier=5`, le poids residuel de l'amorce est de
    l'ordre de `(1 - 2/(w+1))^(4w)`, soit environ 3e-4 : negligeable devant le
    bruit de marche, et surtout DETERMINISTE, ce qui est l'exigence du socle.
    """

    seed_multiplier: int = 5

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.seed_multiplier < 2:
            raise ValueError(
                f"seed_multiplier doit etre >= 2, recu {self.seed_multiplier} : "
                f"en dessous, l'amorce domine le resultat"
            )

    @property
    def lookback(self) -> int:
        return self.window * self.seed_multiplier


class ZScoreParams(FieldWindowParams):
    """Z-score sur fenetre glissante PASSEE.

    Il n'existe pas de mode "echantillon complet" : normaliser sur tout
    l'echantillon injecte le futur dans chaque point (`docs/no-lookahead.md`
    §1, fuite n° 4).
    """

    ddof: int = 1

    def model_post_init(self, _context: object, /) -> None:
        super().model_post_init(_context)
        if self.ddof not in (0, 1):
            raise ValueError(f"ddof doit valoir 0 ou 1, recu {self.ddof}")
        if self.window <= self.ddof:
            raise ValueError(
                f"window ({self.window}) doit etre > ddof ({self.ddof}) : "
                f"sinon la variance n'est pas definie"
            )
