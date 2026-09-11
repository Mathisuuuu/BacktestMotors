"""Tableau de bord de resultats, en noir et blanc.

Deux couches, volontairement separees :

- `model` : extraction, filtrage et calcul. Aucune dependance a tkinter, donc
  testable comme n'importe quel autre module du socle.
- `app` : la fenetre. Ne calcule rien, n'affiche que ce que `model` produit.

La separation n'est pas decorative : un chiffre affiche par une interface est
un chiffre que personne ne relit. Tout ce qui se calcule ici est couvert par
`tests/unit/test_gui_model.py`, et le non-filtre est compare aux metriques du
moteur - si les deux divergent, c'est le tableau de bord qui a tort.
"""

from rsl.gui.model import Dashboard, Filters, SideFilter, TradeRow, build_dashboard, compute_stats

__all__ = [
    "Dashboard",
    "Filters",
    "SideFilter",
    "TradeRow",
    "build_dashboard",
    "compute_stats",
]
