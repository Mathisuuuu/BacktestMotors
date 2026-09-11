"""Les graphiques, traces par matplotlib et embarques dans tkinter.

Deux panneaux :

- `ChartPanel` : capital et drawdown, abscisse partagee.
- `PricePanel` : bougies de l'instrument, avec les ordres poses dessus -
  fleche d'entree, marqueur de sortie, et le trait pointille qui les relie.

Palette : fond blanc, texte encre, **vert et rouge reserves au sens** (hausse /
baisse, gain / perte). Ils ne decorent rien : partout ou l'un des deux apparait,
il porte une information que le lecteur ne pourrait pas deduire autrement.

Les bougies sont dessinees a la main. `mplfinance` ferait le meme trace, mais
exige pandas - ecarte au ledger du depot. Une `LineCollection` et un `bar`
evitent d'avoir a rouvrir ce debat pour un graphique.

matplotlib est une dependance **optionnelle** (`pip install -e ".[gui]"`) : le
moteur ne l'importe pas, et le manifeste de run n'en enregistre pas la version.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from tkinter import Misc
from typing import Any

import matplotlib.dates as mdates
import numpy as np
import numpy.typing as npt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

BLANC = "#FFFFFF"
ENCRE = "#111827"
GRIS = "#6B7280"
GRILLE = "#EDEFF2"
BORDURE = "#D1D5DB"
VERT = "#16A34A"
ROUGE = "#DC2626"
VERT_PALE = "#DCF3E4"
ROUGE_PALE = "#FBE0E0"

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

NS_PER_SECOND = 1_000_000_000
MAX_ETIQUETTES = 12


def to_num(ts_ns: IntArray) -> FloatArray:
    """Horodatages nanosecondes -> nombres de jours matplotlib."""
    moments = [dt.datetime.fromtimestamp(int(t) / NS_PER_SECOND, tz=dt.UTC) for t in ts_ns]
    return np.asarray(mdates.date2num(moments), dtype=np.float64)


def _montant(valeur: float, _position: int) -> str:
    return f"{valeur:,.0f}".replace(",", " ")


def _pourcent(valeur: float, _position: int) -> str:
    return f"{valeur * 100:.1f}%"


def _prix(valeur: float, _position: int) -> str:
    return f"{valeur:,.1f}".replace(",", " ")


def _habiller(axe: Any) -> None:
    """Style commun : fond blanc, cadre discret, grille tres claire."""
    axe.set_facecolor(BLANC)
    for cote, bord in axe.spines.items():
        bord.set_visible(cote in ("left", "bottom"))
        bord.set_color(BORDURE)
        bord.set_linewidth(0.8)
    axe.grid(visible=True, color=GRILLE, linewidth=0.8)
    axe.set_axisbelow(True)
    axe.tick_params(colors=GRIS, labelsize=7.5, length=3, width=0.6)


class _Zoomable:
    """Zoom molette et deplacement au glisser, sur l'axe des dates.

    Les bornes sont verrouillees (`set_autoscalex_on(False)`) et rejouees a
    chaque redimensionnement : un redessin declenche par un `<Configure>` peut
    sinon les recalculer avec des marges, et l'axe se met a annoncer des annees
    pour lesquelles il n'existe aucune barre - sans rien lever.
    """

    canvas: FigureCanvasTkAgg
    widget: Any
    ax_principal: Any
    _base_xlim: tuple[float, float] | None
    _current_xlim: tuple[float, float] | None
    _drag_x: float | None

    def _armer(self) -> None:
        self._base_xlim = None
        self._current_xlim = None
        self._drag_x = None
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.widget.bind("<Configure>", self._on_resize, add="+")

    def reset_zoom(self) -> None:
        if self._base_xlim is not None:
            self._apply(self._base_xlim)

    def _apply(self, bornes: tuple[float, float]) -> None:
        self._current_xlim = bornes
        self.ax_principal.set_xlim(bornes)
        self._apres_fenetre()
        self.canvas.draw_idle()

    def _apres_fenetre(self) -> None:
        """Appele apres tout changement de fenetre. Vide par defaut.

        Un point d'extension explicite plutot que le signal `xlim_changed` de
        matplotlib : `Axes.clear()` reinitialise le registre de callbacks, donc
        une connexion posee a la construction est perdue au premier redessin -
        silencieusement, et le symptome (une echelle Y figee) ne designe pas
        la cause.
        """

    def _on_resize(self, _event: object) -> None:
        if self._current_xlim is not None:
            self.ax_principal.set_xlim(self._current_xlim)

    def _on_scroll(self, event: object) -> None:
        x = getattr(event, "xdata", None)
        pas = float(getattr(event, "step", 0.0))
        if x is None or pas == 0.0:
            return
        centre = float(x)
        bas, haut = self.ax_principal.get_xlim()
        facteur = 0.8 if pas > 0 else 1.25
        self._apply((centre - (centre - bas) * facteur, centre + (haut - centre) * facteur))

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
        bas, haut = self.ax_principal.get_xlim()
        self._apply((bas + decalage, haut + decalage))


class ChartPanel(_Zoomable):
    """Capital au-dessus, drawdown en dessous, abscisse commune."""

    def __init__(self, master: Misc) -> None:
        self.figure = Figure(figsize=(9.5, 3.6), dpi=100, facecolor=BLANC)
        grille = self.figure.add_gridspec(2, 1, height_ratios=(2, 1), hspace=0.10)
        self.ax_equity = self.figure.add_subplot(grille[0])
        self.ax_dd = self.figure.add_subplot(grille[1], sharex=self.ax_equity)
        self.ax_principal = self.ax_equity

        self.canvas = FigureCanvasTkAgg(self.figure, master=master)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(bg=BLANC, highlightthickness=0, bd=0)
        self._armer()

    def draw(self, ts_ns: IntArray, capital: FloatArray, drawdown: FloatArray,
             depart: float) -> None:
        """Redessine les deux courbes.

        `depart` est le capital initial : il sert de reference au remplissage,
        vert au-dessus, rouge en dessous. Un remplissage par rapport au bas du
        cadre ne voudrait rien dire, le bas du cadre dependant du zoom.
        """
        for axe in (self.ax_equity, self.ax_dd):
            axe.clear()
            _habiller(axe)
            axe.set_autoscalex_on(False)

        if ts_ns.size == 0:
            self.ax_equity.text(0.5, 0.5, "aucune donnee sur ce filtre", ha="center",
                                va="center", color=GRIS, fontsize=9,
                                transform=self.ax_equity.transAxes)
            self._base_xlim = None
            self._current_xlim = None
            self.canvas.draw_idle()
            return

        x = to_num(ts_ns)
        self.ax_equity.fill_between(x, capital, depart, where=capital >= depart,
                                    facecolor=VERT_PALE, edgecolor="none", zorder=1)
        self.ax_equity.fill_between(x, capital, depart, where=capital < depart,
                                    facecolor=ROUGE_PALE, edgecolor="none", zorder=1)
        self.ax_equity.axhline(depart, color=GRIS, linewidth=0.7,
                               linestyle=(0, (4, 3)), zorder=2)
        self.ax_equity.plot(x, capital, color=ENCRE, linewidth=1.0, zorder=3)
        self.ax_equity.set_ylabel("CAPITAL", color=GRIS, fontsize=7.5, labelpad=8)
        self.ax_equity.yaxis.set_major_formatter(FuncFormatter(_montant))
        self.ax_equity.tick_params(labelbottom=False)

        self.ax_dd.fill_between(x, drawdown, 0.0, facecolor=ROUGE_PALE,
                                edgecolor="none", zorder=1)
        self.ax_dd.plot(x, drawdown, color=ROUGE, linewidth=0.9, zorder=3)
        self.ax_dd.set_ylabel("DRAWDOWN", color=GRIS, fontsize=7.5, labelpad=8)
        self.ax_dd.yaxis.set_major_formatter(FuncFormatter(_pourcent))

        reperes = mdates.AutoDateLocator()
        self.ax_dd.xaxis.set_major_locator(reperes)
        self.ax_dd.xaxis.set_major_formatter(mdates.ConciseDateFormatter(reperes))

        self.figure.subplots_adjust(left=0.085, right=0.99, top=0.97, bottom=0.11)
        self._base_xlim = (float(x[0]), float(x[-1]))
        self._current_xlim = self._base_xlim
        self.ax_equity.set_xlim(self._base_xlim)
        self.canvas.draw_idle()


class PricePanel(_Zoomable):
    """Bougies d'un instrument, avec les ordres poses dessus."""

    def __init__(self, master: Misc) -> None:
        self.figure = Figure(figsize=(9.5, 4.6), dpi=100, facecolor=BLANC)
        self.ax = self.figure.add_subplot(111)
        self.ax_principal = self.ax

        self.canvas = FigureCanvasTkAgg(self.figure, master=master)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(bg=BLANC, highlightthickness=0, bd=0)
        self._armer()
        self._ordres: list[tuple[float, float, float, float, int, int, float]] = []
        self._etiquettes: list[Any] = []
        self._x: FloatArray = np.zeros(0, dtype=np.float64)
        self._haut: FloatArray = np.zeros(0, dtype=np.float64)
        self._bas: FloatArray = np.zeros(0, dtype=np.float64)

    def draw(self, ts_ns: IntArray, ouvert: FloatArray, haut: FloatArray,
             bas: FloatArray, ferme: FloatArray, trades: Sequence[Any],
             titre: str) -> None:
        """Trace les bougies puis les ordres.

        `trades` n'est pas type par `TradeRow` volontairement : ce module ne lit
        que des attributs et reste ignorant du modele.
        """
        self.ax.clear()
        _habiller(self.ax)
        self.ax.set_autoscalex_on(False)
        self._etiquettes = []

        if ts_ns.size == 0:
            self.ax.text(0.5, 0.5, "aucune barre", ha="center", va="center",
                         color=GRIS, fontsize=9, transform=self.ax.transAxes)
            self._base_xlim = None
            self._current_xlim = None
            self.canvas.draw_idle()
            return

        x = to_num(ts_ns)
        self._x, self._haut, self._bas = x, haut, bas
        largeur = float(np.median(np.diff(x))) * 0.62 if x.size > 1 else 0.5
        monte = ferme >= ouvert

        # Meches en `LineCollection` : un seul artiste pour des milliers de
        # segments. En tracer un par barre rend le zoom perceptiblement lent.
        for masque, couleur in ((monte, VERT), (~monte, ROUGE)):
            if not bool(masque.any()):
                continue
            meches = [((float(xi), float(b)), (float(xi), float(h)))
                      for xi, b, h in zip(x[masque], bas[masque], haut[masque], strict=True)]
            self.ax.add_collection(
                LineCollection(meches, colors=couleur, linewidths=0.7, zorder=2)
            )
            corps = np.abs(ferme[masque] - ouvert[masque])
            self.ax.bar(x[masque], np.maximum(corps, 1e-9),
                        bottom=np.minimum(ouvert[masque], ferme[masque]),
                        width=largeur, color=couleur, edgecolor=couleur,
                        linewidth=0.4, zorder=3)

        self._ordres = []
        for trade in trades:
            if trade.entry_ts_ns <= 0 or trade.exit_ts_ns <= 0:
                continue
            paire = to_num(np.asarray([trade.entry_ts_ns, trade.exit_ts_ns], dtype=np.int64))
            self._ordres.append((
                float(paire[0]), float(trade.entry_price),
                float(paire[1]), float(trade.exit_price),
                int(trade.direction), int(trade.quantity), float(trade.net_pnl),
            ))

        for xe, pe, xs, ps, sens, _q, pnl in self._ordres:
            couleur = VERT if pnl > 0 else ROUGE
            self.ax.plot([xe, xs], [pe, ps], color=couleur, linewidth=0.9,
                         linestyle=(0, (3, 2)), alpha=0.9, zorder=4)
            self.ax.plot([xe], [pe], marker="^" if sens > 0 else "v", markersize=7,
                         color=VERT if sens > 0 else ROUGE, zorder=5)
            self.ax.plot([xs], [ps], marker="o", markersize=5, markerfacecolor=BLANC,
                         markeredgecolor=couleur, markeredgewidth=1.4, zorder=5)

        self.ax.set_title(titre, color=ENCRE, fontsize=9, loc="left", pad=8)
        self.ax.yaxis.set_major_formatter(FuncFormatter(_prix))
        reperes = mdates.AutoDateLocator()
        self.ax.xaxis.set_major_locator(reperes)
        self.ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(reperes))
        self.figure.subplots_adjust(left=0.075, right=0.99, top=0.92, bottom=0.09)
        self._base_xlim = (float(x[0]), float(x[-1]))
        self._current_xlim = self._base_xlim
        self.ax.set_xlim(self._base_xlim)
        self._apres_fenetre()
        self.canvas.draw_idle()

    def _recadrer_y(self) -> None:
        """Ajuste l'echelle des prix aux SEULES barres visibles.

        Garder l'echelle de toute la serie ecrase les bougies dans le bas du
        cadre des qu'on zoome : sur dix ans d'ES, une fenetre de 2017 se lit
        entre 2000 et 7000 alors qu'elle ne couvre que 2000-2900. C'est le
        comportement attendu de n'importe quel graphique de prix.
        """
        if self._x.size == 0:
            return
        gauche, droite = self.ax.get_xlim()
        vus = (self._x >= gauche) & (self._x <= droite)
        if not bool(vus.any()):
            return
        bas = float(np.min(self._bas[vus]))
        haut = float(np.max(self._haut[vus]))
        marge = max((haut - bas) * 0.16, 1e-6)
        self.ax.set_ylim(bas - marge, haut + marge)

    def _apres_fenetre(self) -> None:
        self._recadrer_y()
        self._reetiqueter()

    def _reetiqueter(self) -> None:
        """Pose les etiquettes des ordres visibles.

        Seulement quand ils sont peu nombreux : sur dix ans de trades, des
        centaines d'etiquettes se recouvrent et masquent le prix. Zoomer les
        fait apparaitre, ce qui correspond a l'usage - on lit une etiquette
        quand on regarde un trade en particulier.
        """
        for artiste in self._etiquettes:
            artiste.remove()
        self._etiquettes = []

        gauche, droite = self.ax.get_xlim()
        visibles = [o for o in self._ordres
                    if gauche <= o[0] <= droite or gauche <= o[2] <= droite]
        if not visibles or len(visibles) > MAX_ETIQUETTES:
            return

        bas, haut = self.ax.get_ylim()
        ecart = (haut - bas) * 0.05
        for xe, pe, xs, ps, sens, quantite, _pnl in visibles:
            entree = "T_Long" if sens > 0 else "T_Short"
            self._etiquettes.append(self.ax.annotate(
                f"{entree}\n{quantite} @ {pe:,.1f}".replace(",", " "),
                xy=(xe, pe), xytext=(xe, pe - ecart), ha="center", va="top",
                fontsize=7, color=ENCRE, zorder=6,
            ))
            self._etiquettes.append(self.ax.annotate(
                f"Close\n{quantite} @ {ps:,.1f}".replace(",", " "),
                xy=(xs, ps), xytext=(xs, ps + ecart), ha="center", va="bottom",
                fontsize=7, color=ENCRE, zorder=6,
            ))
