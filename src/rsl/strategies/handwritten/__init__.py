"""Strategies de reference, ecrites a la main et versionnees.

Ce sont elles qui donnent au socle sa verite terrain : leur resultat est
verifiable independamment du moteur. Aucune n'est generee.

Importer ce paquet les enregistre.
"""

from __future__ import annotations

from rsl.strategies.handwritten.buy_and_hold import BuyAndHold

__all__ = ["BuyAndHold"]
