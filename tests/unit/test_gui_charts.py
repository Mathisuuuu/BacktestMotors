"""Bornes de l'axe des dates : ce que le lecteur croit voir.

Un axe qui annonce 2010-2040 pour des donnees 2017-2026 ne leve rien, ne casse
rien, et fait lire une courbe de dix ans comme une courbe de trente. C'est
exactement le genre de defaut qu'un coup d'oeil laisse passer, d'ou ces tests.

Sautes si tkinter ou matplotlib manquent : l'interface est une dependance
optionnelle (`pip install -e ".[gui]"`), le moteur doit rester testable sans.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

tk = pytest.importorskip("tkinter")
pytest.importorskip("matplotlib")

from matplotlib import dates as mdates  # noqa: E402

from rsl.gui.charts import ChartPanel  # noqa: E402

NS = 1_000_000_000


@pytest.fixture
def racine():
    try:
        fenetre = tk.Tk()
    except tk.TclError:  # pragma: no cover - machine sans serveur graphique
        pytest.skip("aucun affichage disponible")
    fenetre.withdraw()
    yield fenetre
    fenetre.destroy()


def serie(n: int = 120) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    debut = int(dt.datetime(2017, 3, 1, tzinfo=dt.UTC).timestamp())
    ts = np.asarray([(debut + i * 86400 * 30) * NS for i in range(n)], dtype=np.int64)
    capital = np.asarray([100_000.0 + 500.0 * i for i in range(n)], dtype=np.float64)
    drawdown = np.zeros(n, dtype=np.float64)
    return ts, capital, drawdown


class TestBornesDeLAxe:
    def test_l_axe_s_arrete_aux_donnees(self, racine):
        """Aucune marge : matplotlib en ajoute 5 % par defaut, ce qui invente
        des annees ou il n'existe aucune barre."""
        panneau = ChartPanel(racine)
        ts, capital, drawdown = serie()
        panneau.draw(ts, capital, drawdown)
        bas, haut = panneau.ax_equity.get_xlim()
        assert mdates.num2date(bas).year == 2017
        assert mdates.num2date(haut).year == mdates.num2date(
            mdates.date2num(dt.datetime.fromtimestamp(int(ts[-1]) / NS, tz=dt.UTC))
        ).year

    def test_les_bornes_survivent_a_un_redimensionnement(self, racine):
        """Le redessin declenche par un `<Configure>` ne doit pas reautoscaler."""
        panneau = ChartPanel(racine)
        ts, capital, drawdown = serie()
        panneau.draw(ts, capital, drawdown)
        avant = panneau.ax_equity.get_xlim()

        panneau.widget.configure(width=1600, height=900)
        panneau.widget.update_idletasks()
        panneau.canvas.draw()

        assert panneau.ax_equity.get_xlim() == pytest.approx(avant)

    def test_le_drawdown_partage_l_abscisse(self, racine):
        panneau = ChartPanel(racine)
        panneau.draw(*serie())
        assert panneau.ax_dd.get_xlim() == pytest.approx(panneau.ax_equity.get_xlim())

    def test_zoom_puis_reinitialisation_revient_aux_bornes_pleines(self, racine):
        panneau = ChartPanel(racine)
        panneau.draw(*serie())
        pleines = panneau.ax_equity.get_xlim()
        bas, haut = pleines
        panneau._apply((bas + (haut - bas) * 0.25, haut - (haut - bas) * 0.25))
        assert panneau.ax_equity.get_xlim() != pytest.approx(pleines)
        panneau.reset_zoom()
        assert panneau.ax_equity.get_xlim() == pytest.approx(pleines)

    def test_une_serie_vide_ne_leve_pas(self, racine):
        """Un filtre peut ne retenir aucune barre : la fenetre doit tenir."""
        panneau = ChartPanel(racine)
        vide_i = np.zeros(0, dtype=np.int64)
        vide_f = np.zeros(0, dtype=np.float64)
        panneau.draw(vide_i, vide_f, vide_f)
        assert panneau._base_xlim is None
