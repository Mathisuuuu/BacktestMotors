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

from rsl.gui.charts import ChartPanel, PricePanel  # noqa: E402

NS = 1_000_000_000


@pytest.fixture(scope="module")
def racine():
    """UNE racine Tk pour tout le module.

    Une racine par test faisait echouer `tk.Tk()` de facon intermittente sur
    les derniers tests - deux d'entre eux se sautaient en silence avec
    "aucun affichage disponible" alors que Tk fonctionnait. Un test qui se
    saute ne protege rien, et il ne le dit pas.
    """
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
        panneau.draw(ts, capital, drawdown, 100_000.0)
        bas, haut = panneau.ax_equity.get_xlim()
        assert mdates.num2date(bas).year == 2017
        assert mdates.num2date(haut).year == mdates.num2date(
            mdates.date2num(dt.datetime.fromtimestamp(int(ts[-1]) / NS, tz=dt.UTC))
        ).year

    def test_les_bornes_survivent_a_un_redimensionnement(self, racine):
        """Le redessin declenche par un `<Configure>` ne doit pas reautoscaler."""
        panneau = ChartPanel(racine)
        ts, capital, drawdown = serie()
        panneau.draw(ts, capital, drawdown, 100_000.0)
        avant = panneau.ax_equity.get_xlim()

        panneau.widget.configure(width=1600, height=900)
        panneau.widget.update_idletasks()
        panneau.canvas.draw()

        assert panneau.ax_equity.get_xlim() == pytest.approx(avant)

    def test_le_drawdown_partage_l_abscisse(self, racine):
        panneau = ChartPanel(racine)
        panneau.draw(*serie(), 100_000.0)
        assert panneau.ax_dd.get_xlim() == pytest.approx(panneau.ax_equity.get_xlim())

    def test_zoom_puis_reinitialisation_revient_aux_bornes_pleines(self, racine):
        panneau = ChartPanel(racine)
        panneau.draw(*serie(), 100_000.0)
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
        panneau.draw(vide_i, vide_f, vide_f, 0.0)
        assert panneau._base_xlim is None


class _Ordre:
    """Minimal : `PricePanel` ne lit que des attributs, pas un type."""

    def __init__(self, entree: int, sortie: int, pe: float, ps: float,
                 sens: int = 1, pnl: float = 10.0) -> None:
        self.entry_ts_ns = entree
        self.exit_ts_ns = sortie
        self.entry_price = pe
        self.exit_price = ps
        self.direction = sens
        self.quantity = 4
        self.net_pnl = pnl


def bougies(n: int = 60):
    debut = int(dt.datetime(2026, 8, 4, tzinfo=dt.UTC).timestamp())
    ts = np.asarray([(debut + i * 300) * NS for i in range(n)], dtype=np.int64)
    base = np.asarray([4100.0 + i * 2.0 for i in range(n)], dtype=np.float64)
    ouvert = base
    ferme = base + np.where(np.arange(n) % 3 == 0, -3.0, 4.0)
    haut = np.maximum(ouvert, ferme) + 2.0
    bas = np.minimum(ouvert, ferme) - 2.0
    return ts, ouvert, haut, bas, ferme


class TestPricePanel:
    def test_trace_les_bougies_sans_lever(self, racine):
        panneau = PricePanel(racine)
        panneau.draw(*bougies(), (), "TEST")
        assert panneau._base_xlim is not None

    def test_l_axe_s_arrete_aux_barres(self, racine):
        panneau = PricePanel(racine)
        ts, o, h, b, c = bougies()
        panneau.draw(ts, o, h, b, c, (), "TEST")
        gauche, droite = panneau.ax.get_xlim()
        assert mdates.num2date(gauche).day == 4
        assert (droite - gauche) == pytest.approx(
            (int(ts[-1]) - int(ts[0])) / NS / 86400, abs=1e-6
        )

    def test_les_ordres_sont_retenus(self, racine):
        panneau = PricePanel(racine)
        ts, o, h, b, c = bougies()
        ordre = _Ordre(int(ts[5]), int(ts[40]), 4110.0, 4180.0)
        panneau.draw(ts, o, h, b, c, (ordre,), "TEST")
        assert len(panneau._ordres) == 1

    def test_un_ordre_sans_horodatage_est_ignore(self, racine):
        """Un fill introuvable ne doit pas poser un marqueur en 1970."""
        panneau = PricePanel(racine)
        ts, o, h, b, c = bougies()
        panneau.draw(ts, o, h, b, c, (_Ordre(0, 0, 0.0, 0.0),), "TEST")
        assert panneau._ordres == []

    def test_etiquettes_posees_quand_les_ordres_sont_peu_nombreux(self, racine):
        panneau = PricePanel(racine)
        ts, o, h, b, c = bougies()
        ordre = _Ordre(int(ts[5]), int(ts[40]), 4110.0, 4180.0)
        panneau.draw(ts, o, h, b, c, (ordre,), "TEST")
        assert len(panneau._etiquettes) == 2

    def test_pas_d_etiquettes_quand_ils_sont_trop_nombreux(self, racine):
        """Des centaines d'etiquettes se recouvrent et masquent le prix."""
        panneau = PricePanel(racine)
        ts, o, h, b, c = bougies()
        ordres = [_Ordre(int(ts[i]), int(ts[i + 1]), 4100.0, 4105.0)
                  for i in range(0, 50, 2)]
        panneau.draw(ts, o, h, b, c, ordres, "TEST")
        assert panneau._etiquettes == []

    def test_serie_vide_ne_leve_pas(self, racine):
        panneau = PricePanel(racine)
        vide_i = np.zeros(0, dtype=np.int64)
        vide_f = np.zeros(0, dtype=np.float64)
        panneau.draw(vide_i, vide_f, vide_f, vide_f, vide_f, (), "TEST")
        assert panneau._base_xlim is None


class TestEchelleDesPrix:
    """L'echelle Y doit suivre la fenetre, sinon les bougies s'ecrasent."""

    def test_zoomer_resserre_l_echelle_des_prix(self, racine):
        panneau = PricePanel(racine)
        ts, o, h, b, c = bougies(200)
        panneau.draw(ts, o, h, b, c, (), "TEST")
        pleine = panneau.ax.get_ylim()

        gauche, droite = panneau.ax.get_xlim()
        milieu = (gauche + droite) / 2
        largeur = (droite - gauche) * 0.1
        panneau._apply((milieu - largeur, milieu + largeur))

        zoomee = panneau.ax.get_ylim()
        assert (zoomee[1] - zoomee[0]) < (pleine[1] - pleine[0]) / 3

    def test_l_echelle_revient_en_arriere_au_dezoom(self, racine):
        panneau = PricePanel(racine)
        ts, o, h, b, c = bougies(200)
        panneau.draw(ts, o, h, b, c, (), "TEST")
        pleine = panneau.ax.get_ylim()
        gauche, droite = panneau.ax.get_xlim()
        milieu = (gauche + droite) / 2
        panneau._apply((milieu - 1.0, milieu + 1.0))
        panneau.reset_zoom()
        assert panneau.ax.get_ylim() == pytest.approx(pleine)

    def test_les_etiquettes_sont_recalculees_apres_un_zoom(self, racine):
        """Regression : `Axes.clear()` reinitialise le registre de callbacks de
        matplotlib. Un `xlim_changed` connecte a la construction ne survit pas
        au premier redessin, et l'echelle Y restait alors figee."""
        panneau = PricePanel(racine)
        ts, o, h, b, c = bougies(200)
        ordres = [_Ordre(int(ts[i]), int(ts[i + 3]), 4100.0, 4110.0)
                  for i in range(0, 120, 6)]
        panneau.draw(ts, o, h, b, c, ordres, "TEST")
        assert panneau._etiquettes == []          # trop nombreux en vue pleine

        gauche, droite = panneau.ax.get_xlim()
        panneau._apply((gauche, gauche + (droite - gauche) * 0.06))
        assert panneau._etiquettes != []          # peu nombreux une fois zoome
