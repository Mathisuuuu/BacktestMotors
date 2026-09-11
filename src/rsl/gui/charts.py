"""Les deux courbes, tracees par matplotlib, embarquees dans tkinter.

matplotlib plutot qu'un trace manuel sur `Canvas` : axes de dates corrects,
graduations lisibles a toutes les echelles, et surtout un zoom et un
deplacement qui ne sont pas a reecrire. Elle est declaree en dependance
**optionnelle** (`pip install -e ".[gui]"`) : le moteur de backtest n'en depend
pas, et le manifeste de run n'en enregistre donc pas la version.

Le style est impose ici, pas herite : matplotlib peint en bleu par defaut.
Fond blanc, trace noir, grille gris tres clair, police monospace.

Les deux axes partagent l'abscisse (`sharex`) : zoomer sur le capital zoome le
drawdown au meme endroit. Les regarder a des echelles differentes serait la
premiere facon de se tromper.
"""

from __future__ import annotations

import datetime as dt
from tkinter import Misc

import matplotlib.dates as mdates
import numpy as np
import numpy.typing as npt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

BLANC = "#FFFFFF"
NOIR = "#000000"
GRILLE = "#DCDCDC"

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

NS_PER_SECOND = 1_000_000_000


def _dates(ts_ns: IntArray) -> FloatArray:
    """Horodatages nanosecondes -> nombres de jours matplotlib.

    `date2num` plutot qu'une liste de `datetime` : matplotlib travaille en
    flottants en interne, et lui passer les flottants directement evite une
    conversion par point sur des series de plusieurs milliers de barres.
    """
    moments = [dt.datetime.fromtimestamp(int(t) / NS_PER_SECOND, tz=dt.UTC) for t in ts_ns]
    return np.asarray(mdates.date2num(moments), dtype=np.float64)


def _montant(valeur: float, _position: int) -> str:
    return f"{valeur:,.0f}".replace(",", " ")


def _pourcent(valeur: float, _position: int) -> str:
    return f"{valeur * 100:.1f}%"


class ChartPanel:
    """Capital au-dessus, drawdown en dessous, abscisse commune."""

    def __init__(self, master: Misc) -> None:
        self.figure = Figure(figsize=(9.5, 2.9), dpi=100)
        self.figure.patch.set_facecolor(BLANC)
        grille = self.figure.add_gridspec(2, 1, height_ratios=(2, 1), hspace=0.12)
        self.ax_equity = self.figure.add_subplot(grille[0])
        self.ax_dd = self.figure.add_subplot(grille[1], sharex=self.ax_equity)

        self.canvas = FigureCanvasTkAgg(self.figure, master=master)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(bg=BLANC, highlightthickness=1, highlightbackground=NOIR)

        self._base_xlim: tuple[float, float] | None = None
        self._current_xlim: tuple[float, float] | None = None
        self._drag_x: float | None = None
        # Le redimensionnement du widget declenche un redessin complet de la
        # figure : on y rejoue les bornes courantes plutot que de faire
        # confiance a ce que matplotlib aura garde.
        self.widget.bind("<Configure>", self._on_resize, add="+")
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)

    # -- trace --------------------------------------------------------------

    def draw(self, ts_ns: IntArray, capital: FloatArray, drawdown: FloatArray) -> None:
        """Redessine les deux courbes.

        Le cadrage est reinitialise a chaque appel, volontairement : changer de
        filtre change les donnees, et garder l'ancien zoom montrerait une
        fenetre temporelle qui ne veut plus rien dire.
        """
        for axe in (self.ax_equity, self.ax_dd):
            axe.clear()
            axe.set_facecolor(BLANC)
            for bord in axe.spines.values():
                bord.set_color(NOIR)
                bord.set_linewidth(0.8)
            axe.grid(visible=True, color=GRILLE, linewidth=0.6)
            axe.tick_params(colors=NOIR, labelsize=7)

        if ts_ns.size == 0:
            self.ax_equity.text(0.5, 0.5, "aucune donnee", ha="center", va="center",
                                color=NOIR, fontfamily="monospace", fontsize=9,
                                transform=self.ax_equity.transAxes)
            self._base_xlim = None
            self._current_xlim = None
            self.canvas.draw_idle()
            return

        dates = _dates(ts_ns)
        self.ax_equity.plot(dates, capital, color=NOIR, linewidth=0.9)
        self.ax_equity.set_ylabel("CAPITAL", color=NOIR, fontsize=7.5, labelpad=6)
        self.ax_equity.yaxis.set_major_formatter(FuncFormatter(_montant))
        self.ax_equity.tick_params(labelbottom=False)

        # Le drawdown est hachure et non rempli en aplat : un aplat noir
        # ecraserait la courbe, et un aplat clair demanderait une teinte.
        self.ax_dd.fill_between(dates, drawdown, 0.0, facecolor="none",
                                edgecolor=NOIR, hatch="////", linewidth=0.0)
        self.ax_dd.plot(dates, drawdown, color=NOIR, linewidth=0.9)
        self.ax_dd.set_ylabel("DRAWDOWN", color=NOIR, fontsize=7.5, labelpad=6)
        self.ax_dd.yaxis.set_major_formatter(FuncFormatter(_pourcent))
        self.ax_dd.axhline(0.0, color=NOIR, linewidth=0.6)

        reperes = mdates.AutoDateLocator()
        self.ax_dd.xaxis.set_major_locator(reperes)
        self.ax_dd.xaxis.set_major_formatter(mdates.ConciseDateFormatter(reperes))

        # Sans cela matplotlib ajoute 5 % de marge de chaque cote, et l'axe
        # annonce des annees pour lesquelles il n'existe aucune donnee.
        # `set_autoscalex_on(False)` verrouille : un redimensionnement de la
        # fenetre redessine la figure, et une bornes laissee "auto" peut alors
        # etre recalculee avec des marges - l'axe se remet a annoncer 2010-2040
        # pour des donnees 2017-2026, sans que rien ne le signale.
        for axe in (self.ax_equity, self.ax_dd):
            axe.set_autoscalex_on(False)
        self.ax_equity.set_xlim(float(dates[0]), float(dates[-1]))
        self.figure.subplots_adjust(left=0.11, right=0.985, top=0.97, bottom=0.13)
        self._base_xlim = (float(dates[0]), float(dates[-1]))
        self._current_xlim = self._base_xlim
        self.canvas.draw_idle()

    def reset_zoom(self) -> None:
        if self._base_xlim is not None:
            self._apply(self._base_xlim)

    def _apply(self, bornes: tuple[float, float]) -> None:
        self._current_xlim = bornes
        self.ax_equity.set_xlim(bornes)
        self.canvas.draw_idle()

    def _on_resize(self, _event: object) -> None:
        if self._current_xlim is not None:
            self.ax_equity.set_xlim(self._current_xlim)

    # -- interactions -------------------------------------------------------

    def _on_scroll(self, event: object) -> None:
        """Molette : zoom autour du curseur, sur l'axe des dates seulement."""
        x = getattr(event, "xdata", None)
        pas = float(getattr(event, "step", 0.0))
        if x is None or pas == 0.0:
            return
        centre = float(x)
        bas, haut = self.ax_equity.get_xlim()
        facteur = 0.8 if pas > 0 else 1.25
        self._apply((centre - (centre - bas) * facteur,
                     centre + (haut - centre) * facteur))

    def _on_press(self, event: object) -> None:
        x = getattr(event, "xdata", None)
        self._drag_x = None if x is None else float(x)

    def _on_release(self, _event: object) -> None:
        self._drag_x = None

    def _on_motion(self, event: object) -> None:
        x = getattr(event, "xdata", None)
        if self._drag_x is None or x is None:
            return
        decalage = self._drag_x - float(x)
        bas, haut = self.ax_equity.get_xlim()
        self._apply((bas + decalage, haut + decalage))
