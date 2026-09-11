"""La fenetre. Noir et blanc, chrome Windows 95, aucune couleur.

Choix assumes :

- **tkinter**, bibliotheque standard. Le manifeste de run enregistre la version
  de chaque dependance ; en ajouter une pour afficher deux courbes se paierait
  sur tous les rapports archives.
- **Gris uniquement pour le chrome.** `#C0C0C0` est achromatique (R = V = B) :
  c'est du gris, pas une couleur. Les zones de donnees restent blanches, les
  courbes et le texte noirs, la grille gris tres clair. Aucune teinte nulle
  part, y compris pour la selection dans le tableau, forcee en noir sur blanc.
- Ce module **ne calcule rien**. Tout vient de `rsl.gui.model`, qui est teste.
"""

from __future__ import annotations

import contextlib
import csv
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Literal

from rsl.config import BacktestSpec
from rsl.gui.charts import ChartPanel
from rsl.gui.model import (
    Dashboard,
    Filters,
    SideFilter,
    Stats,
    build_dashboard,
    compute_stats,
    drawdown_series,
    format_ts,
    select_trades,
)
from rsl.report import run_backtest_detailed

BLANC = "#FFFFFF"
NOIR = "#000000"
GRIS_CHROME = "#C0C0C0"
GRIS_OMBRE = "#808080"
MONO = ("Courier New", 9)
MONO_GRAS = ("Courier New", 9, "bold")
MONO_TITRE = ("Courier New", 11, "bold")

Ancrage = Literal["w", "e", "center"]

COLONNES: tuple[tuple[str, str, int, Ancrage], ...] = (
    ("entree", "DATE ENTREE", 130, "w"),
    ("sortie", "DATE SORTIE", 130, "w"),
    ("sens", "SENS", 55, "center"),
    ("prix_in", "PRIX ENTREE", 95, "e"),
    ("prix_out", "PRIX SORTIE", 95, "e"),
    ("pnl", "PNL", 100, "e"),
    ("frais", "FRAIS", 75, "e"),
)


def _texte(valeur: float | None, gabarit: str, absent: str = "n/d") -> str:
    return absent if valeur is None else gabarit.format(valeur)


class DashboardApp(tk.Tk):
    """Fenetre de resultats d'un backtest."""

    def __init__(self, dashboard: Dashboard | None = None) -> None:
        super().__init__()
        self.title("rsl - tableau de bord")
        self.configure(bg=GRIS_CHROME)
        # Taille deduite de l'ecran : une geometrie codee en dur depasse des que
        # la machine a une definition plus petite, et le carnet d'ordres passe
        # alors sous la ligne de flottaison sans que rien ne le signale.
        largeur = min(1180, self.winfo_screenwidth() - 60)
        hauteur = min(840, self.winfo_screenheight() - 120)
        self.geometry(f"{largeur}x{hauteur}+20+10")
        self.minsize(900, 600)
        # `winfo_screenheight` rend la hauteur de l'ecran, barre des taches
        # comprise : une fenetre calculee depuis elle depasse encore. L'etat
        # "zoomed" epouse la zone de travail reelle, que tkinter n'expose pas.
        # `suppress` : tous les gestionnaires de fenetres ne connaissent pas
        # "zoomed", et la geometrie calculee ci-dessus sert alors de repli.
        with contextlib.suppress(tk.TclError):
            self.state("zoomed")

        self.dashboard = dashboard
        self.var_annee = tk.StringVar(value="TOUTES")
        self.var_sens = tk.StringVar(value=SideFilter.ALL.value)
        self.var_statut = tk.StringVar(value="pret")
        self._valeurs: dict[str, tk.StringVar] = {}

        self._style_bw()
        self._bandeau()
        self._barre_filtres()
        self._panneau_metriques()
        # La barre de boutons est construite AVANT les zones extensibles et
        # ancree en bas : empilee en dernier, elle se faisait pousser hors de
        # la fenetre par les graphes et le carnet, sans aucun avertissement.
        self._barre_boutons()
        self._graphes()
        self._carnet()

        if dashboard is not None:
            self.charger(dashboard)

    # -- apparence ----------------------------------------------------------

    def _style_bw(self) -> None:
        """Force un theme achromatique : ttk peint en bleu par defaut."""
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "BW.Treeview", background=BLANC, fieldbackground=BLANC, foreground=NOIR,
            font=MONO, rowheight=17, borderwidth=1, relief="sunken",
        )
        style.configure(
            "BW.Treeview.Heading", background=GRIS_CHROME, foreground=NOIR,
            font=MONO_GRAS, relief="raised", borderwidth=1,
        )
        style.map(
            "BW.Treeview",
            background=[("selected", NOIR)],
            foreground=[("selected", BLANC)],
        )
        style.map("BW.Treeview.Heading", background=[("active", GRIS_CHROME)])
        style.configure(
            "BW.Vertical.TScrollbar", background=GRIS_CHROME, troughcolor=BLANC,
            bordercolor=NOIR, arrowcolor=NOIR, relief="raised",
        )

    def _cadre(self, parent: tk.Misc, **kwargs: object) -> tk.Frame:
        """Cadre au relief Windows 95."""
        return tk.Frame(parent, bg=GRIS_CHROME, bd=2, relief="ridge", **kwargs)  # type: ignore[arg-type]

    def _bouton(self, parent: tk.Misc, texte: str, commande: object) -> tk.Button:
        return tk.Button(
            parent, text=texte, command=commande,  # type: ignore[arg-type]
            font=MONO, bg=GRIS_CHROME, fg=NOIR, activebackground=GRIS_CHROME,
            activeforeground=NOIR, bd=2, relief="raised", padx=10, pady=2,
            highlightthickness=0,
        )

    # -- construction -------------------------------------------------------

    def _bandeau(self) -> None:
        cadre = self._cadre(self)
        cadre.pack(fill="x", padx=4, pady=(4, 2))
        self.var_titre = tk.StringVar(value="aucun run charge")
        self.var_sous_titre = tk.StringVar(value="")
        tk.Label(cadre, textvariable=self.var_titre, font=MONO_TITRE, bg=GRIS_CHROME,
                 fg=NOIR, anchor="w").pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(cadre, textvariable=self.var_sous_titre, font=MONO, bg=GRIS_CHROME,
                 fg=NOIR, anchor="w").pack(fill="x", padx=6, pady=(0, 4))

    def _barre_filtres(self) -> None:
        cadre = self._cadre(self)
        cadre.pack(fill="x", padx=4, pady=2)

        tk.Label(cadre, text="ANNEE", font=MONO_GRAS, bg=GRIS_CHROME, fg=NOIR).pack(
            side="left", padx=(8, 4), pady=6)
        self.menu_annee = tk.OptionMenu(cadre, self.var_annee, "TOUTES")
        self.menu_annee.configure(
            font=MONO, bg=BLANC, fg=NOIR, activebackground=NOIR, activeforeground=BLANC,
            bd=2, relief="sunken", highlightthickness=0, width=9, anchor="w",
            indicatoron=True, direction="below",
        )
        menu = self.menu_annee["menu"]
        menu.configure(font=MONO, bg=BLANC, fg=NOIR, activebackground=NOIR,
                       activeforeground=BLANC, bd=1, relief="solid")
        self.menu_annee.pack(side="left", pady=6)

        tk.Label(cadre, text="   SENS", font=MONO_GRAS, bg=GRIS_CHROME, fg=NOIR).pack(
            side="left", padx=(12, 4), pady=6)
        for etiquette, valeur in (
            ("TOUS", SideFilter.ALL), ("LONG", SideFilter.LONG), ("SHORT", SideFilter.SHORT)
        ):
            tk.Radiobutton(
                cadre, text=etiquette, variable=self.var_sens, value=valeur.value,
                command=self.rafraichir, font=MONO, bg=GRIS_CHROME, fg=NOIR,
                selectcolor=BLANC, activebackground=GRIS_CHROME, activeforeground=NOIR,
                indicatoron=False, width=7, bd=2, relief="raised", highlightthickness=0,
            ).pack(side="left", padx=1, pady=6)

        self.var_regime = tk.StringVar(value="")
        tk.Label(cadre, textvariable=self.var_regime, font=MONO_GRAS, bg=GRIS_CHROME,
                 fg=NOIR).pack(side="right", padx=10)

        self.var_annee.trace_add("write", lambda *_a: self.rafraichir())

    def _panneau_metriques(self) -> None:
        cadre = self._cadre(self)
        cadre.pack(fill="x", padx=4, pady=2)
        grille = tk.Frame(cadre, bg=GRIS_CHROME)
        grille.pack(fill="x", padx=6, pady=6)

        champs = (
            ("sharpe", "RATIO DE SHARPE"), ("calmar", "RATIO DE CALMAR"),
            ("dd", "DRAWDOWN (DD)"), ("dd_max", "DRAWDOWN MAX"),
            ("gain_net", "GAIN NET"), ("gain_brut", "GAIN BRUT"),
            ("perte_nette", "PERTE NETTE"), ("perte_brute", "PERTE BRUTE"),
            ("pf", "PROFIT FACTOR"), ("win", "TAUX DE REUSSITE"),
            ("n", "NOMBRE DE TRADES"), ("moy", "GAIN / PERTE MOYENS"),
        )
        for index, (cle, etiquette) in enumerate(champs):
            ligne, colonne = divmod(index, 4)
            case = tk.Frame(grille, bg=GRIS_CHROME)
            case.grid(row=ligne, column=colonne, sticky="w", padx=(0, 10), pady=1)
            tk.Label(case, text=etiquette, font=MONO, bg=GRIS_CHROME, fg=NOIR,
                     width=19, anchor="w").pack(side="left")
            variable = tk.StringVar(value="n/d")
            self._valeurs[cle] = variable
            # "GAIN / PERTE MOYENS" porte deux nombres signes : 14 caracteres
            # tronquent le signe du premier, ce qui change le sens affiche.
            tk.Label(case, textvariable=variable, font=MONO_GRAS, bg=BLANC, fg=NOIR,
                     width=20 if cle == "moy" else 14, anchor="e", bd=2,
                     relief="sunken").pack(side="left")

    def _graphes(self) -> None:
        cadre = self._cadre(self)
        cadre.pack(fill="both", expand=True, padx=4, pady=2)
        entete = tk.Frame(cadre, bg=GRIS_CHROME)
        entete.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(entete, text="COURBES  -  molette = zoom, glisser = defiler",
                 font=MONO_GRAS, bg=GRIS_CHROME, fg=NOIR, anchor="w").pack(side="left")
        self._bouton(entete, "REINITIALISER LE ZOOM", self._reinitialiser_zoom).pack(
            side="right")
        self.charts = ChartPanel(cadre)
        self.charts.widget.pack(fill="both", expand=True, padx=6, pady=(4, 6))

    def _reinitialiser_zoom(self) -> None:
        self.charts.reset_zoom()

    def _carnet(self) -> None:
        cadre = self._cadre(self)
        # `side="bottom"` + hauteur minimale : le carnet est une exigence de la
        # specification, il ne doit jamais etre le premier sacrifie.
        cadre.pack(side="bottom", fill="both", expand=True, padx=4, pady=2)
        cadre.configure(height=200)
        tk.Label(cadre, text="CARNET D'ORDRES", font=MONO_GRAS, bg=GRIS_CHROME,
                 fg=NOIR, anchor="w").pack(fill="x", padx=6, pady=(4, 2))

        interieur = tk.Frame(cadre, bg=GRIS_CHROME)
        interieur.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self.table = ttk.Treeview(
            interieur, columns=[c[0] for c in COLONNES], show="headings",
            style="BW.Treeview", height=7,
        )
        for cle, entete, largeur, ancrage in COLONNES:
            self.table.heading(cle, text=entete, anchor=ancrage)
            self.table.column(cle, width=largeur, anchor=ancrage, stretch=True)

        defilement = ttk.Scrollbar(interieur, orient="vertical", command=self.table.yview,
                                   style="BW.Vertical.TScrollbar")
        self.table.configure(yscrollcommand=defilement.set)
        self.table.pack(side="left", fill="both", expand=True)
        defilement.pack(side="right", fill="y")

    def _barre_boutons(self) -> None:
        cadre = self._cadre(self)
        cadre.pack(side="bottom", fill="x", padx=4, pady=(2, 4))
        self._bouton(cadre, "CHARGER UN JSON...", self.ouvrir_config).pack(
            side="left", padx=(8, 4), pady=6)
        self._bouton(cadre, "EXPORTER LE CARNET (CSV)", self.exporter_csv).pack(
            side="left", padx=4, pady=6)
        self._bouton(cadre, "EXPORTER LES STATS (TXT)", self.exporter_txt).pack(
            side="left", padx=4, pady=6)
        tk.Label(cadre, textvariable=self.var_statut, font=MONO, bg=GRIS_CHROME,
                 fg=NOIR, anchor="e").pack(side="right", padx=10)

    # -- etat ---------------------------------------------------------------

    def filtres(self) -> Filters:
        brut = self.var_annee.get()
        annee = int(brut) if brut.isdigit() else None
        return Filters(year=annee, side=SideFilter(self.var_sens.get()))

    def charger(self, dashboard: Dashboard) -> None:
        """Installe un nouveau run dans la fenetre."""
        self.dashboard = dashboard

        rejouable = "OUI" if dashboard.is_reproducible else "NON"
        self.var_titre.set(f"{dashboard.name}   [{', '.join(dashboard.symbols)}]")
        self.var_sous_titre.set(
            f"empreinte {dashboard.fingerprint[:32]}...   rejouable {rejouable}"
        )

        menu = self.menu_annee["menu"]
        menu.delete(0, "end")
        for etiquette in ("TOUTES", *(str(a) for a in dashboard.years)):
            menu.add_command(label=etiquette,
                             command=lambda v=etiquette: self.var_annee.set(v))
        self.var_annee.set("TOUTES")
        self.rafraichir()

    def rafraichir(self) -> None:
        if self.dashboard is None:
            return
        stats = compute_stats(self.dashboard, self.filtres())
        self._ecrire_metriques(stats)
        self._remplir_carnet()
        self._redessiner()

    def _ecrire_metriques(self, stats: Stats) -> None:
        self.var_regime.set(f"COURBE {stats.regime}")
        v = self._valeurs
        v["sharpe"].set(_texte(stats.sharpe, "{:.2f}"))
        v["calmar"].set(_texte(stats.calmar, "{:.2f}"))
        v["dd"].set(_texte(stats.drawdown_current, "{:+.2%}"))
        v["dd_max"].set(_texte(stats.drawdown_max, "{:+.2%}"))
        v["gain_net"].set(f"{stats.net_profit:+,.2f}".replace(",", " "))
        v["gain_brut"].set(f"{stats.gross_profit:+,.2f}".replace(",", " "))
        v["perte_nette"].set(f"{-stats.net_loss:+,.2f}".replace(",", " "))
        v["perte_brute"].set(f"{-stats.gross_loss:+,.2f}".replace(",", " "))
        v["pf"].set(_texte(stats.profit_factor, "{:.2f}", absent="n/d"))
        v["win"].set(_texte(stats.win_rate, "{:.2%}"))
        v["n"].set(str(stats.n_trades))
        gain = _texte(stats.average_win, "{:+,.0f}")
        perte = _texte(stats.average_loss, "{:+,.0f}")
        v["moy"].set(f"{gain} / {perte}".replace(",", " "))

    def _remplir_carnet(self) -> None:
        if self.dashboard is None:
            return
        self.table.delete(*self.table.get_children())
        for trade in select_trades(self.dashboard, self.filtres()):
            self.table.insert("", "end", values=(
                format_ts(trade.entry_ts_ns),
                format_ts(trade.exit_ts_ns),
                trade.side_label,
                f"{trade.entry_price:,.2f}".replace(",", " "),
                f"{trade.exit_price:,.2f}".replace(",", " "),
                f"{trade.net_pnl:+,.2f}".replace(",", " "),
                f"{trade.fees:,.2f}".replace(",", " "),
            ))

    def _redessiner(self) -> None:
        if self.dashboard is None:
            return
        stats = compute_stats(self.dashboard, self.filtres())
        self.charts.draw(stats.curve_ts_ns, stats.curve, drawdown_series(stats.curve))

    # -- actions ------------------------------------------------------------

    def ouvrir_config(self) -> None:
        chemin = filedialog.askopenfilename(
            title="Specification de backtest",
            filetypes=[("Specification JSON", "*.json"), ("Tous les fichiers", "*.*")],
        )
        if not chemin:
            return
        self.executer(Path(chemin))

    def executer(self, config: Path) -> None:
        """Lance le backtest decrit par `config` et affiche son resultat."""
        self.var_statut.set(f"execution de {config.name}...")
        self.update_idletasks()
        try:
            self.charger(dashboard_depuis_config(config))
            self.var_statut.set(f"{config.name} - {len(self.table.get_children())} trades")
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
            plume.writerow(["date_entree", "date_sortie", "sens", "prix_entree",
                            "prix_sortie", "pnl_net", "pnl_brut", "frais", "symbole"])
            for t in trades:
                plume.writerow([
                    format_ts(t.entry_ts_ns), format_ts(t.exit_ts_ns), t.side_label,
                    f"{t.entry_price:.4f}", f"{t.exit_price:.4f}", f"{t.net_pnl:.4f}",
                    f"{t.gross_pnl:.4f}", f"{t.fees:.4f}", t.symbol,
                ])
        self.var_statut.set(f"{len(trades)} trades exportes")

    def exporter_txt(self) -> None:
        if self.dashboard is None:
            return
        chemin = filedialog.asksaveasfilename(
            title="Exporter les statistiques", defaultextension=".txt",
            filetypes=[("Texte", "*.txt")], initialfile=f"{self.dashboard.name}-stats.txt",
        )
        if not chemin:
            return
        Path(chemin).write_text(self.rendu_texte(), encoding="utf-8")
        self.var_statut.set("statistiques exportees")

    def rendu_texte(self) -> str:
        """Les statistiques affichees, en texte brut alignable."""
        assert self.dashboard is not None
        filtres = self.filtres()
        stats = compute_stats(self.dashboard, filtres)
        regle = "-" * 62
        annee = filtres.year if filtres.year is not None else "toutes"
        lignes = [
            regle,
            f"{self.dashboard.name}   [{', '.join(self.dashboard.symbols)}]",
            f"empreinte   {self.dashboard.fingerprint}",
            f"rejouable   {'oui' if self.dashboard.is_reproducible else 'non'}",
            regle,
            f"filtre annee   {annee}",
            f"filtre sens    {filtres.side.value}",
            f"courbe         {stats.regime}",
        ]
        if filtres.needs_reconstruction:
            lignes.append(
                "  ATTENTION : courbe reconstruite a partir des seuls trades retenus."
            )
            lignes.append(
                "  Ce n'est PAS un backtest long-only : c'est la contribution de ces"
            )
            lignes.append("  trades au resultat observe.")
        lignes.extend([
            regle,
            f"Ratio de Sharpe      {_texte(stats.sharpe, '{:>12.4f}')}",
            f"Ratio de Calmar      {_texte(stats.calmar, '{:>12.4f}')}",
            f"Drawdown             {_texte(stats.drawdown_current, '{:>12.2%}')}",
            f"Drawdown maximum     {_texte(stats.drawdown_max, '{:>12.2%}')}",
            f"Gain net             {stats.net_profit:>12.2f}",
            f"Gain brut            {stats.gross_profit:>12.2f}",
            f"Perte nette          {-stats.net_loss:>12.2f}",
            f"Perte brute          {-stats.gross_loss:>12.2f}",
            f"Profit factor        {_texte(stats.profit_factor, '{:>12.4f}')}",
            f"Taux de reussite     {_texte(stats.win_rate, '{:>12.2%}')}",
            f"Nombre de trades     {stats.n_trades:>12}",
            f"Gain moyen           {_texte(stats.average_win, '{:>12.2f}')}",
            f"Perte moyenne        {_texte(stats.average_loss, '{:>12.2f}')}",
            f"Frais totaux         {stats.fees_total:>12.2f}",
            regle,
        ])
        return "\n".join(lignes) + "\n"


def dashboard_depuis_config(config: Path) -> Dashboard:
    """Execute une specification et en fait un jeu de donnees d'affichage."""
    spec = BacktestSpec.model_validate_json(config.read_text(encoding="utf-8"))
    report, result = run_backtest_detailed(spec)
    return build_dashboard(
        report, result.fills, result.portfolio.closed_trades,
        result.equity.ts_ns, result.equity.equity,
    )


def launch(dashboard: Dashboard | None = None, config: Path | None = None) -> None:
    """Ouvre la fenetre. `config` est execute au demarrage s'il est fourni."""
    application = DashboardApp(dashboard)
    if dashboard is None and config is not None:
        application.after(60, lambda: application.executer(config))
    application.mainloop()
