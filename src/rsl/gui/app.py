"""La fenetre : quatre onglets, fond blanc, vert et rouge pour le sens.

Parti pris visuel :

- **Blanc et plat.** Pas de biseau, pas d'ombre, pas de relief. Les separations
  sont des filets gris clair, la hierarchie vient des tailles et des espaces.
- **Vert et rouge portent une information, jamais une decoration.** Un gain est
  vert, une perte rouge, une hausse verte, une baisse rouge. Un chiffre neutre
  - un nombre de trades, une duree - reste encre.
- **Chiffres en monospace.** Les colonnes de nombres doivent s'aligner a la
  virgule ; le reste de l'interface est en police systeme.

Ce module **ne calcule rien**. Tout vient de `rsl.gui.model`, qui est teste.
"""

from __future__ import annotations

import contextlib
import csv
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Literal

from rsl.config import BacktestSpec
from rsl.gui.charts import ChartPanel, PricePanel
from rsl.gui.model import (
    Bars,
    Dashboard,
    Filters,
    SideFilter,
    Stats,
    build_dashboard,
    compute_stats,
    drawdown_series,
    format_duration,
    format_ts,
    select_trades,
)
from rsl.report import run_backtest_detailed

BLANC = "#FFFFFF"
ARDOISE = "#F7F8FA"
ENCRE = "#111827"
GRIS = "#6B7280"
GRIS_CLAIR = "#9CA3AF"
FILET = "#E5E7EB"
VERT = "#16A34A"
ROUGE = "#DC2626"
VERT_PALE = "#F0FAF3"
ROUGE_PALE = "#FDF1F1"

UI = ("Segoe UI", 9)
UI_PETIT = ("Segoe UI", 8)
UI_GRAS = ("Segoe UI", 9, "bold")
TITRE = ("Segoe UI", 13, "bold")
CHIFFRE = ("Consolas", 13, "bold")
MONO = ("Consolas", 9)
MONO_GRAS = ("Consolas", 9, "bold")

Teinte = Literal["neutre", "gain", "perte", "signe"]
Ancrage = Literal["w", "e", "center"]

COLONNES: tuple[tuple[str, str, int, Ancrage], ...] = (
    ("entree", "DATE ENTREE", 135, "w"),
    ("sortie", "DATE SORTIE", 135, "w"),
    ("sens", "SENS", 60, "center"),
    ("duree", "DUREE", 85, "e"),
    ("prix_in", "PRIX ENTREE", 100, "e"),
    ("prix_out", "PRIX SORTIE", 100, "e"),
    ("pnl", "PNL", 105, "e"),
    ("frais", "FRAIS", 80, "e"),
)

# (cle, libelle, teinte) groupes par onglet de synthese.
GROUPES: tuple[tuple[str, tuple[tuple[str, str, Teinte], ...]], ...] = (
    ("PERFORMANCE", (
        ("sharpe", "Ratio de Sharpe", "signe"),
        ("calmar", "Ratio de Calmar", "signe"),
        ("gain_net", "Gain net", "gain"),
        ("gain_brut", "Gain brut", "gain"),
    )),
    ("RISQUE", (
        ("dd", "Drawdown", "perte"),
        ("dd_max", "Drawdown maximum", "perte"),
        ("perte_nette", "Perte nette", "perte"),
        ("perte_brute", "Perte brute", "perte"),
    )),
    ("ACTIVITE", (
        ("pf", "Profit factor", "signe"),
        ("win", "Taux de reussite", "neutre"),
        ("n", "Nombre de trades", "neutre"),
        ("duree", "Duree moyenne en position", "neutre"),
        ("gain_moyen", "Gain moyen par trade", "gain"),
        ("perte_moyenne", "Perte moyenne par trade", "perte"),
    )),
)


def _texte(valeur: float | None, gabarit: str, absent: str = "n/d") -> str:
    return absent if valeur is None else gabarit.format(valeur)


def _espace(texte: str) -> str:
    return texte.replace(",", " ")


class DashboardApp(tk.Tk):
    """Fenetre de resultats d'un backtest."""

    def __init__(self, dashboard: Dashboard | None = None) -> None:
        super().__init__()
        self.title("rsl - tableau de bord")
        self.configure(bg=BLANC)
        largeur = min(1280, self.winfo_screenwidth() - 60)
        hauteur = min(860, self.winfo_screenheight() - 120)
        self.geometry(f"{largeur}x{hauteur}+20+10")
        self.minsize(980, 640)
        # `winfo_screenheight` compte la barre des taches : une fenetre calculee
        # depuis elle depasse encore. "zoomed" epouse la zone de travail reelle,
        # que tkinter n'expose pas. Tous les gestionnaires ne la connaissent pas.
        with contextlib.suppress(tk.TclError):
            self.state("zoomed")

        self.dashboard = dashboard
        self.var_annee = tk.StringVar(value="TOUTES")
        self.var_sens = tk.StringVar(value=SideFilter.ALL.value)
        self.var_symbole = tk.StringVar(value="")
        self.var_statut = tk.StringVar(value="pret")
        self.var_titre = tk.StringVar(value="aucun run charge")
        self.var_sous_titre = tk.StringVar(value="")
        self.var_rejouable = tk.StringVar(value="")
        self.var_regime = tk.StringVar(value="")
        self._valeurs: dict[str, tk.StringVar] = {}
        self._teintes: dict[str, tk.Label] = {}

        self._styler()
        self._bandeau()
        self._barre_filtres()
        self._pied()
        self._onglets()

        if dashboard is not None:
            self.charger(dashboard)

    # -- apparence ----------------------------------------------------------

    def _styler(self) -> None:
        """ttk peint en bleu ardoise par defaut : tout est repris ici."""
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background=BLANC, borderwidth=0,
                        tabmargins=(0, 6, 0, 0))
        # clam dessine un cadre autour de la zone de contenu : on le retire pour
        # que les onglets flottent sur le fond blanc.
        style.layout("TNotebook", [("TNotebook.client", {"sticky": "nswe"})])
        style.configure("TNotebook.Tab", background=BLANC, foreground=GRIS,
                        font=UI, padding=(18, 8), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", BLANC)],
                  foreground=[("selected", ENCRE)],
                  font=[("selected", UI_GRAS)])
        style.configure("Bord.TFrame", background=BLANC)
        style.configure("Tableau.Treeview", background=BLANC, fieldbackground=BLANC,
                        foreground=ENCRE, font=MONO, rowheight=22, borderwidth=0)
        style.configure("Tableau.Treeview.Heading", background=ARDOISE, foreground=GRIS,
                        font=UI_PETIT, relief="flat", borderwidth=0, padding=(4, 6))
        style.map("Tableau.Treeview.Heading", background=[("active", ARDOISE)])
        style.map("Tableau.Treeview",
                  background=[("selected", "#E8EDF5")],
                  foreground=[("selected", ENCRE)])
        style.configure("TCombobox", fieldbackground=BLANC, background=BLANC,
                        foreground=ENCRE, arrowcolor=GRIS, bordercolor=FILET,
                        lightcolor=BLANC, darkcolor=BLANC, borderwidth=1)
        style.configure("Vertical.TScrollbar", background=ARDOISE, troughcolor=BLANC,
                        bordercolor=BLANC, arrowcolor=GRIS, borderwidth=0)

    def _filet(self, parent: tk.Misc) -> None:
        tk.Frame(parent, bg=FILET, height=1).pack(fill="x")

    def _bouton(self, parent: tk.Misc, texte: str, commande: Callable[[], None],
                principal: bool = False) -> tk.Button:
        fond = ENCRE if principal else BLANC
        avant = BLANC if principal else ENCRE
        bouton = tk.Button(
            parent, text=texte, command=commande, font=UI, bg=fond, fg=avant,
            activebackground=fond, activeforeground=avant, bd=0, relief="flat",
            padx=14, pady=7, cursor="hand2", highlightthickness=1,
            highlightbackground=ENCRE if principal else FILET,
            highlightcolor=ENCRE if principal else FILET,
        )
        return bouton

    # -- construction -------------------------------------------------------

    def _bandeau(self) -> None:
        cadre = tk.Frame(self, bg=BLANC)
        cadre.pack(fill="x", padx=22, pady=(16, 0))
        haut = tk.Frame(cadre, bg=BLANC)
        haut.pack(fill="x")
        tk.Label(haut, textvariable=self.var_titre, font=TITRE, bg=BLANC, fg=ENCRE,
                 anchor="w").pack(side="left")
        self.badge = tk.Label(haut, textvariable=self.var_rejouable, font=UI_PETIT,
                              bg=BLANC, fg=GRIS, padx=8, pady=2)
        self.badge.pack(side="left", padx=(12, 0))
        tk.Label(cadre, textvariable=self.var_sous_titre, font=UI_PETIT, bg=BLANC,
                 fg=GRIS_CLAIR, anchor="w").pack(fill="x", pady=(2, 12))
        self._filet(cadre)

    def _barre_filtres(self) -> None:
        cadre = tk.Frame(self, bg=BLANC)
        cadre.pack(fill="x", padx=22, pady=(12, 0))

        tk.Label(cadre, text="ANNEE", font=UI_PETIT, bg=BLANC, fg=GRIS).pack(
            side="left", padx=(0, 8))
        self.combo_annee = ttk.Combobox(cadre, textvariable=self.var_annee, font=UI,
                                        state="readonly", width=10, values=("TOUTES",))
        self.combo_annee.pack(side="left")
        self.combo_annee.bind("<<ComboboxSelected>>", lambda _e: self.rafraichir())

        tk.Label(cadre, text="SENS", font=UI_PETIT, bg=BLANC, fg=GRIS).pack(
            side="left", padx=(24, 8))
        segments = tk.Frame(cadre, bg=FILET, bd=0)
        segments.pack(side="left")
        self._segments: dict[str, tk.Radiobutton] = {}
        for etiquette, valeur in (("TOUS", SideFilter.ALL), ("LONG", SideFilter.LONG),
                                  ("SHORT", SideFilter.SHORT)):
            bouton = tk.Radiobutton(
                segments, text=etiquette, variable=self.var_sens, value=valeur.value,
                command=self.rafraichir, font=UI, bg=BLANC, fg=GRIS,
                selectcolor=BLANC, activebackground=BLANC, activeforeground=ENCRE,
                indicatoron=False, width=7, bd=0, relief="flat", padx=6, pady=5,
                highlightthickness=0, cursor="hand2",
            )
            bouton.pack(side="left", padx=1, pady=1)
            self._segments[valeur.value] = bouton

        tk.Label(cadre, textvariable=self.var_regime, font=UI_PETIT, bg=BLANC,
                 fg=GRIS).pack(side="right")

    def _onglets(self) -> None:
        self.onglets = ttk.Notebook(self)
        self.onglets.pack(fill="both", expand=True, padx=18, pady=(14, 0))
        self._onglet_synthese()
        self._onglet_courbes()
        self._onglet_prix()
        self._onglet_carnet()

    def _onglet_synthese(self) -> None:
        page = tk.Frame(self.onglets, bg=BLANC)
        self.onglets.add(page, text="SYNTHESE")
        for titre, champs in GROUPES:
            bloc = tk.Frame(page, bg=BLANC)
            bloc.pack(fill="x", padx=16, pady=(14, 0))
            tk.Label(bloc, text=titre, font=UI_PETIT, bg=BLANC, fg=GRIS_CLAIR,
                     anchor="w").pack(fill="x", pady=(0, 8))
            rangee = tk.Frame(bloc, bg=BLANC)
            rangee.pack(fill="x")
            for cle, libelle, teinte in champs:
                self._carte(rangee, cle, libelle, teinte)

    def _carte(self, parent: tk.Misc, cle: str, libelle: str, teinte: Teinte) -> None:
        """Une carte : un libelle gris, un chiffre, un filet autour."""
        carte = tk.Frame(parent, bg=BLANC, highlightthickness=1,
                         highlightbackground=FILET, highlightcolor=FILET)
        carte.pack(side="left", fill="both", expand=True, padx=(0, 10))
        tk.Label(carte, text=libelle.upper(), font=UI_PETIT, bg=BLANC, fg=GRIS_CLAIR,
                 anchor="w").pack(fill="x", padx=14, pady=(12, 2))
        variable = tk.StringVar(value="n/d")
        self._valeurs[cle] = variable
        valeur = tk.Label(carte, textvariable=variable, font=CHIFFRE, bg=BLANC,
                          fg=ENCRE, anchor="w")
        valeur.pack(fill="x", padx=14, pady=(0, 14))
        valeur.teinte = teinte  # type: ignore[attr-defined]
        self._teintes[cle] = valeur

    def _onglet_courbes(self) -> None:
        page = tk.Frame(self.onglets, bg=BLANC)
        self.onglets.add(page, text="COURBES")
        barre = tk.Frame(page, bg=BLANC)
        barre.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(barre, text="Molette : zoom    Glisser : defiler", font=UI_PETIT,
                 bg=BLANC, fg=GRIS_CLAIR).pack(side="left")
        self._bouton(barre, "Reinitialiser le zoom",
                     lambda: self.charts.reset_zoom()).pack(side="right")
        self.charts = ChartPanel(page)
        self.charts.widget.pack(fill="both", expand=True, padx=16, pady=(0, 14))

    def _onglet_prix(self) -> None:
        page = tk.Frame(self.onglets, bg=BLANC)
        self.onglets.add(page, text="PRIX & ORDRES")
        barre = tk.Frame(page, bg=BLANC)
        barre.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(barre, text="INSTRUMENT", font=UI_PETIT, bg=BLANC, fg=GRIS).pack(
            side="left", padx=(0, 8))
        self.combo_symbole = ttk.Combobox(barre, textvariable=self.var_symbole, font=UI,
                                          state="readonly", width=14)
        self.combo_symbole.pack(side="left")
        self.combo_symbole.bind("<<ComboboxSelected>>", lambda _e: self._dessiner_prix())
        tk.Label(barre, text="Zoomez pour faire apparaitre les etiquettes des ordres",
                 font=UI_PETIT, bg=BLANC, fg=GRIS_CLAIR).pack(side="left", padx=16)
        self._bouton(barre, "Reinitialiser le zoom",
                     lambda: self.prix.reset_zoom()).pack(side="right")
        self.prix = PricePanel(page)
        self.prix.widget.pack(fill="both", expand=True, padx=16, pady=(0, 14))

    def _onglet_carnet(self) -> None:
        page = tk.Frame(self.onglets, bg=BLANC)
        self.onglets.add(page, text="CARNET D'ORDRES")
        interieur = tk.Frame(page, bg=BLANC)
        interieur.pack(fill="both", expand=True, padx=16, pady=14)

        self.table = ttk.Treeview(interieur, columns=[c[0] for c in COLONNES],
                                  show="headings", style="Tableau.Treeview")
        for cle, entete, largeur, ancrage in COLONNES:
            self.table.heading(cle, text=entete, anchor=ancrage)
            self.table.column(cle, width=largeur, anchor=ancrage, stretch=True)
        self.table.tag_configure("gain", background=VERT_PALE, foreground=ENCRE)
        self.table.tag_configure("perte", background=ROUGE_PALE, foreground=ENCRE)

        defilement = ttk.Scrollbar(interieur, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=defilement.set)
        self.table.pack(side="left", fill="both", expand=True)
        defilement.pack(side="right", fill="y")

    def _pied(self) -> None:
        cadre = tk.Frame(self, bg=BLANC)
        cadre.pack(side="bottom", fill="x", padx=22, pady=(10, 14))
        self._filet(cadre)
        rangee = tk.Frame(cadre, bg=BLANC)
        rangee.pack(fill="x", pady=(12, 0))
        self._bouton(rangee, "Charger un JSON", self.ouvrir_config, principal=True).pack(
            side="left")
        self._bouton(rangee, "Exporter le carnet (CSV)", self.exporter_csv).pack(
            side="left", padx=8)
        self._bouton(rangee, "Exporter les stats (TXT)", self.exporter_txt).pack(
            side="left")
        tk.Label(rangee, textvariable=self.var_statut, font=UI_PETIT, bg=BLANC,
                 fg=GRIS_CLAIR).pack(side="right")

    # -- etat ---------------------------------------------------------------

    def filtres(self) -> Filters:
        brut = self.var_annee.get()
        return Filters(year=int(brut) if brut.isdigit() else None,
                       side=SideFilter(self.var_sens.get()))

    def charger(self, dashboard: Dashboard) -> None:
        """Installe un nouveau run dans la fenetre."""
        self.dashboard = dashboard
        rejouable = dashboard.is_reproducible
        self.var_titre.set(dashboard.name)
        self.var_rejouable.set("REJOUABLE" if rejouable else "NON REJOUABLE")
        self.badge.configure(fg=VERT if rejouable else ROUGE,
                             bg=VERT_PALE if rejouable else ROUGE_PALE)
        self.var_sous_titre.set(
            f"{', '.join(dashboard.symbols)}    empreinte {dashboard.fingerprint[:24]}..."
        )
        self.combo_annee.configure(
            values=("TOUTES", *(str(a) for a in dashboard.years)))
        self.var_annee.set("TOUTES")
        symboles = tuple(dashboard.bars) or dashboard.symbols
        self.combo_symbole.configure(values=symboles)
        self.var_symbole.set(symboles[0] if symboles else "")
        self.rafraichir()

    def rafraichir(self) -> None:
        if self.dashboard is None:
            return
        for valeur, bouton in self._segments.items():
            actif = valeur == self.var_sens.get()
            fond = ENCRE if actif else BLANC
            # `selectcolor` ET `bg` : avec `indicatoron=False`, Tk peint l'etat
            # selectionne avec `selectcolor` et ignore `bg`. N'en regler qu'un
            # donnait un libelle blanc sur fond blanc - un bouton vide.
            bouton.configure(bg=fond, selectcolor=fond, activebackground=fond,
                             fg=BLANC if actif else GRIS,
                             activeforeground=BLANC if actif else ENCRE)
        stats = compute_stats(self.dashboard, self.filtres())
        self._ecrire(stats)
        self._remplir_carnet()
        self.charts.draw(stats.curve_ts_ns, stats.curve, drawdown_series(stats.curve),
                         self.dashboard.initial_equity)
        self._dessiner_prix()

    def _ecrire(self, stats: Stats) -> None:
        self.var_regime.set(f"COURBE {stats.regime}")
        v = self._valeurs
        v["sharpe"].set(_texte(stats.sharpe, "{:.2f}"))
        v["calmar"].set(_texte(stats.calmar, "{:.2f}"))
        v["dd"].set(_texte(stats.drawdown_current, "{:.2%}"))
        v["dd_max"].set(_texte(stats.drawdown_max, "{:.2%}"))
        v["gain_net"].set(_espace(f"{stats.net_profit:+,.0f}"))
        v["gain_brut"].set(_espace(f"{stats.gross_profit:+,.0f}"))
        v["perte_nette"].set(_espace(f"{-stats.net_loss:+,.0f}"))
        v["perte_brute"].set(_espace(f"{-stats.gross_loss:+,.0f}"))
        v["pf"].set(_texte(stats.profit_factor, "{:.2f}"))
        v["win"].set(_texte(stats.win_rate, "{:.1%}"))
        v["n"].set(str(stats.n_trades))
        v["duree"].set(format_duration(stats.average_holding_seconds))
        v["gain_moyen"].set(_texte(stats.average_win, "{:+,.0f}").replace(",", " "))
        v["perte_moyenne"].set(_texte(stats.average_loss, "{:+,.0f}").replace(",", " "))
        self._teinter(stats)

    def _teinter(self, stats: Stats) -> None:
        """Applique la couleur selon le SENS de chaque chiffre, pas son nom.

        Un profit factor sous 1 est rouge meme s'il est positif : c'est le sens
        du chiffre qui compte, pas son signe arithmetique.
        """
        signes: dict[str, float | None] = {
            "sharpe": stats.sharpe, "calmar": stats.calmar,
            "pf": None if stats.profit_factor is None else stats.profit_factor - 1.0,
        }
        for cle, etiquette in self._teintes.items():
            teinte: Teinte = getattr(etiquette, "teinte", "neutre")
            if teinte == "gain":
                couleur = VERT
            elif teinte == "perte":
                couleur = ROUGE
            elif teinte == "signe":
                valeur = signes.get(cle)
                couleur = ENCRE if valeur is None else (VERT if valeur >= 0 else ROUGE)
            else:
                couleur = ENCRE
            if self._valeurs[cle].get() in ("n/d", "+0", "0"):
                couleur = GRIS_CLAIR
            etiquette.configure(fg=couleur)

    def _remplir_carnet(self) -> None:
        if self.dashboard is None:
            return
        self.table.delete(*self.table.get_children())
        for trade in select_trades(self.dashboard, self.filtres()):
            self.table.insert("", "end", tags=("gain" if trade.is_win else "perte",), values=(
                format_ts(trade.entry_ts_ns),
                format_ts(trade.exit_ts_ns),
                trade.side_label,
                format_duration(trade.holding_seconds),
                _espace(f"{trade.entry_price:,.2f}"),
                _espace(f"{trade.exit_price:,.2f}"),
                _espace(f"{trade.net_pnl:+,.2f}"),
                _espace(f"{trade.fees:,.2f}"),
            ))

    def _dessiner_prix(self) -> None:
        if self.dashboard is None:
            return
        symbole = self.var_symbole.get()
        barres: Bars | None = self.dashboard.bars.get(symbole)
        retenus = [t for t in select_trades(self.dashboard, self.filtres())
                   if t.symbol == symbole]
        if barres is None:
            vide = drawdown_series(self.dashboard.equity[:0])
            self.prix.draw(self.dashboard.equity_ts_ns[:0], vide, vide, vide, vide,
                           (), symbole or "aucun instrument")
            return
        self.prix.draw(barres.ts_ns, barres.open, barres.high, barres.low, barres.close,
                       retenus, f"{symbole}  -  {len(retenus)} trade(s) affiche(s)")

    # -- actions ------------------------------------------------------------

    def ouvrir_config(self) -> None:
        chemin = filedialog.askopenfilename(
            title="Specification de backtest",
            filetypes=[("Specification JSON", "*.json"), ("Tous les fichiers", "*.*")],
        )
        if chemin:
            self.executer(Path(chemin))

    def executer(self, config: Path) -> None:
        """Lance le backtest decrit par `config` et affiche son resultat."""
        self.var_statut.set(f"execution de {config.name}...")
        self.update_idletasks()
        try:
            self.charger(dashboard_depuis_config(config))
            n = len(self.table.get_children())
            self.var_statut.set(f"{config.name}  -  {n} trade(s)")
        except Exception as erreur:  # la fenetre ne doit pas mourir sur un run rate
            self.var_statut.set("echec")
            messagebox.showerror("Echec du backtest", f"{type(erreur).__name__}\n\n{erreur}")

    def exporter_csv(self) -> None:
        if self.dashboard is None:
            return
        chemin = filedialog.asksaveasfilename(
            title="Exporter le carnet d'ordres", defaultextension=".csv",
            filetypes=[("CSV", "*.csv")], initialfile=f"{self.dashboard.name}-carnet.csv",
        )
        if not chemin:
            return
        trades = select_trades(self.dashboard, self.filtres())
        # `encoding` explicite : sans lui, Windows ecrirait en CP1252.
        with Path(chemin).open("w", newline="", encoding="utf-8") as flux:
            plume = csv.writer(flux, delimiter=";")
            plume.writerow(["date_entree", "date_sortie", "sens", "duree_secondes",
                            "prix_entree", "prix_sortie", "pnl_net", "pnl_brut",
                            "frais", "symbole"])
            for t in trades:
                duree = t.holding_seconds
                plume.writerow([
                    format_ts(t.entry_ts_ns), format_ts(t.exit_ts_ns), t.side_label,
                    "" if duree is None else f"{duree:.0f}",
                    f"{t.entry_price:.4f}", f"{t.exit_price:.4f}", f"{t.net_pnl:.4f}",
                    f"{t.gross_pnl:.4f}", f"{t.fees:.4f}", t.symbol,
                ])
        self.var_statut.set(f"{len(trades)} trade(s) exporte(s)")

    def exporter_txt(self) -> None:
        if self.dashboard is None:
            return
        chemin = filedialog.asksaveasfilename(
            title="Exporter les statistiques", defaultextension=".txt",
            filetypes=[("Texte", "*.txt")], initialfile=f"{self.dashboard.name}-stats.txt",
        )
        if chemin:
            Path(chemin).write_text(self.rendu_texte(), encoding="utf-8")
            self.var_statut.set("statistiques exportees")

    def rendu_texte(self) -> str:
        """Les statistiques affichees, en texte brut alignable."""
        assert self.dashboard is not None
        filtres = self.filtres()
        stats = compute_stats(self.dashboard, filtres)
        regle = "-" * 62
        lignes = [
            regle,
            f"{self.dashboard.name}   [{', '.join(self.dashboard.symbols)}]",
            f"empreinte   {self.dashboard.fingerprint}",
            f"rejouable   {'oui' if self.dashboard.is_reproducible else 'non'}",
            regle,
            f"filtre annee   {filtres.year if filtres.year is not None else 'toutes'}",
            f"filtre sens    {filtres.side.value}",
            f"courbe         {stats.regime}",
        ]
        if filtres.needs_reconstruction:
            lignes += [
                "  ATTENTION : courbe reconstruite a partir des seuls trades retenus.",
                "  Ce n'est PAS un backtest long-only : c'est la contribution de ces",
                "  trades au resultat observe.",
            ]
        lignes += [
            regle,
            f"Ratio de Sharpe        {_texte(stats.sharpe, '{:>12.4f}')}",
            f"Ratio de Calmar        {_texte(stats.calmar, '{:>12.4f}')}",
            f"Drawdown               {_texte(stats.drawdown_current, '{:>12.2%}')}",
            f"Drawdown maximum       {_texte(stats.drawdown_max, '{:>12.2%}')}",
            f"Gain net               {stats.net_profit:>12.2f}",
            f"Gain brut              {stats.gross_profit:>12.2f}",
            f"Perte nette            {-stats.net_loss:>12.2f}",
            f"Perte brute            {-stats.gross_loss:>12.2f}",
            f"Profit factor          {_texte(stats.profit_factor, '{:>12.4f}')}",
            f"Taux de reussite       {_texte(stats.win_rate, '{:>12.2%}')}",
            f"Nombre de trades       {stats.n_trades:>12}",
            f"Duree moyenne          {format_duration(stats.average_holding_seconds):>12}",
            f"Gain moyen             {_texte(stats.average_win, '{:>12.2f}')}",
            f"Perte moyenne          {_texte(stats.average_loss, '{:>12.2f}')}",
            f"Frais totaux           {stats.fees_total:>12.2f}",
            regle,
        ]
        return "\n".join(lignes) + "\n"


def bars_depuis_stores(stores: dict[str, Any]) -> dict[str, Bars]:
    """Extrait les barres OHLC servies au moteur, symbole par symbole."""
    return {
        symbole: Bars(
            symbol=symbole, ts_ns=store.ts_close, open=store.open, high=store.high,
            low=store.low, close=store.close,
        )
        for symbole, store in stores.items()
    }


def dashboard_depuis_config(config: Path) -> Dashboard:
    """Execute une specification et en fait un jeu de donnees d'affichage."""
    spec = BacktestSpec.model_validate_json(config.read_text(encoding="utf-8"))
    artefacts = run_backtest_detailed(spec)
    return build_dashboard(
        artefacts.report, artefacts.result.fills,
        artefacts.result.portfolio.closed_trades,
        artefacts.result.equity.ts_ns, artefacts.result.equity.equity,
        bars_depuis_stores(artefacts.stores),
    )


def launch(dashboard: Dashboard | None = None, config: Path | None = None) -> None:
    """Ouvre la fenetre. `config` est execute au demarrage s'il est fourni."""
    application = DashboardApp(dashboard)
    if dashboard is None and config is not None:
        application.after(60, lambda: application.executer(config))
    application.mainloop()


