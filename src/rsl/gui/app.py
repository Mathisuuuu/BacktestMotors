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
from typing import Any, Final, Literal

from rsl.composition import StrategyFile, compose
from rsl.config import BacktestSpec
from rsl.data.instruments import known_roots
from rsl.errors import ConfigurationError
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
from rsl.gui.montage import (
    FRAIS,
    GLISSEMENTS,
    RESAMPLES,
    Montage,
    racine_initiale,
    seance_proposee,
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

TEINTES: Final[dict[str, Teinte]] = {
    cle: teinte for _, champs in GROUPES for cle, _, teinte in champs
}
"""La teinte de chaque carte, DERIVEE de `GROUPES`.

Elle y etait deja declaree ; elle etait en plus injectee comme attribut sur le
`tk.Label` (`valeur.teinte = teinte`) puis relue par
`getattr(etiquette, "teinte", "neutre")`. Deux defauts a cela :

- `tk.Label` n'a pas de champ `teinte`, donc c'etait une greffe sur un objet
  d'une bibliotheque tierce - `mypy` l'ignorait par un `type: ignore`, et rien
  ne garantit qu'une version future de tkinter la tolere ;
- le defaut `"neutre"` du `getattr` rendait l'echec MUET. Une cle mal
  orthographiee, un widget reconstruit sans la greffe, et tous les chiffres
  passaient en noir sans qu'aucun test ni aucun lint ne le voie.

Ici la table est la source, l'acces se fait par cle, et une cle absente leve.
"""


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

        # Le MONTAGE : ce que le fichier de strategie ne dit pas.
        self.var_strategie = tk.StringVar(value="")
        self.var_actif = tk.StringVar(value=racine_initiale())
        self.var_agregation = tk.StringVar(value="day")
        self.var_capital = tk.StringVar(value="1000000")
        self.var_frais = tk.StringVar(value="per_contract")
        self.var_glissement = tk.StringVar(value="tick")
        self.var_glissement_valeur = tk.StringVar(value="1")
        self.var_contrats = tk.StringVar(value="1")
        self.var_seance = tk.StringVar(value=seance_proposee(racine_initiale()))
        self._chemin_strategie: Path | None = None

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
        self._onglet_montage()
        self._onglet_synthese()
        self._onglet_courbes()
        self._onglet_prix()
        self._onglet_carnet()

    def _onglet_montage(self) -> None:
        """Le MONTAGE : l'actif, l'argent, les couts.

        Separe de la strategie depuis le 2026-09-12. Un fichier de strategie ne
        porte que la decision ; ce qu'elle ne dit pas se choisit ici, ce qui
        permet d'appliquer la meme strategie a un autre actif sans reecrire une
        ligne de JSON.

        Six reglages seulement - ceux qu'on change d'un essai a l'autre. Les
        autres gardent les defauts du socle, qui sont des choix de prudence :
        les rendre reglables d'un clic inviterait a les desactiver sans y
        penser. Qui veut y toucher passe par `rsl run --settings`.
        """
        page = tk.Frame(self.onglets, bg=BLANC)
        self.onglets.add(page, text="MONTAGE")

        corps = tk.Frame(page, bg=BLANC)
        corps.pack(fill="both", expand=True, padx=24, pady=20)

        tk.Label(corps, text="STRATEGIE", font=UI_PETIT, bg=BLANC, fg=GRIS,
                 anchor="w").pack(fill="x")
        ligne = tk.Frame(corps, bg=BLANC)
        ligne.pack(fill="x", pady=(4, 2))
        tk.Entry(ligne, textvariable=self.var_strategie, font=UI, bg=BLANC,
                 fg=ENCRE, relief="flat", highlightthickness=1,
                 highlightbackground=FILET, highlightcolor=ENCRE,
                 state="readonly", readonlybackground=BLANC).pack(
            side="left", fill="x", expand=True, ipady=4)
        self._bouton(ligne, "Choisir...", self.choisir_strategie).pack(
            side="left", padx=(10, 0))
        tk.Label(
            corps,
            text=("Un fichier `\"format\": \"rsl-strategy@1\"`. Une specification "
                  "complete s'ouvre par Charger, en bas."),
            font=UI_PETIT, bg=BLANC, fg=GRIS_CLAIR, anchor="w", justify="left",
        ).pack(fill="x", pady=(0, 18))

        grille = tk.Frame(corps, bg=BLANC)
        grille.pack(fill="x")
        for colonne in range(4):
            grille.columnconfigure(colonne, weight=1, uniform="montage")

        self._champ_liste(grille, 0, 0, "ACTIF", self.var_actif, sorted(known_roots()))
        self._champ_liste(grille, 0, 1, "AGREGATION", self.var_agregation, RESAMPLES)
        self._champ_saisie(grille, 0, 2, "CAPITAL INITIAL", self.var_capital)
        self._champ_saisie(grille, 0, 3, "CONTRATS PAR ENTREE", self.var_contrats)
        self._champ_liste(grille, 1, 0, "FRAIS", self.var_frais, FRAIS)
        self._champ_liste(grille, 1, 1, "GLISSEMENT", self.var_glissement, GLISSEMENTS)
        self._champ_saisie(grille, 1, 2, "TICKS / BPS", self.var_glissement_valeur)
        self._champ_saisie(grille, 1, 3, "SEANCE", self.var_seance)
        tk.Label(
            corps,
            text=("La SEANCE n'est lue que pour une agregation intra-journaliere "
                  "(5min a 4h) : c'est elle qui dit ou commence une barre de 4 h. "
                  "Le socle ne devine aucune frontiere. Format "
                  "'HH:MM-HH:MM@Fuseau' ; la valeur proposee est a relire, pas a "
                  "croire."),
            font=UI_PETIT, bg=BLANC, fg=GRIS_CLAIR, anchor="w", justify="left",
            wraplength=760,
        ).pack(fill="x", pady=(2, 0))

        bas = tk.Frame(corps, bg=BLANC)
        bas.pack(fill="x", pady=(26, 0))
        self._filet(bas)
        action = tk.Frame(corps, bg=BLANC)
        action.pack(fill="x", pady=(16, 0))
        self._bouton(action, "LANCER LE BACKTEST", self.lancer_montage,
                     principal=True).pack(side="left")
        tk.Label(
            action,
            text=("Le `config_hash` couvre la strategie ET ce montage : deux "
                  "capitaux differents sont deux runs differents."),
            font=UI_PETIT, bg=BLANC, fg=GRIS_CLAIR,
        ).pack(side="left", padx=(16, 0))

    def _champ_liste(self, parent: tk.Misc, rangee: int, colonne: int, titre: str,
                     variable: tk.StringVar, valeurs: tuple[str, ...] | list[str]) -> None:
        cellule = tk.Frame(parent, bg=BLANC)
        cellule.grid(row=rangee, column=colonne, sticky="ew", padx=(0, 14), pady=(0, 14))
        tk.Label(cellule, text=titre, font=UI_PETIT, bg=BLANC, fg=GRIS,
                 anchor="w").pack(fill="x", pady=(0, 4))
        ttk.Combobox(cellule, textvariable=variable, values=list(valeurs), font=UI,
                     state="readonly").pack(fill="x")

    def _champ_saisie(self, parent: tk.Misc, rangee: int, colonne: int, titre: str,
                      variable: tk.StringVar) -> None:
        cellule = tk.Frame(parent, bg=BLANC)
        cellule.grid(row=rangee, column=colonne, sticky="ew", padx=(0, 14), pady=(0, 14))
        tk.Label(cellule, text=titre, font=UI_PETIT, bg=BLANC, fg=GRIS,
                 anchor="w").pack(fill="x", pady=(0, 4))
        tk.Entry(cellule, textvariable=variable, font=UI, bg=BLANC, fg=ENCRE,
                 relief="flat", highlightthickness=1, highlightbackground=FILET,
                 highlightcolor=ENCRE).pack(fill="x", ipady=4)

    def choisir_strategie(self) -> None:
        chemin = filedialog.askopenfilename(
            title="Choisir une strategie", filetypes=[("Strategie JSON", "*.json")],
        )
        if not chemin:
            return
        self._chemin_strategie = Path(chemin)
        self.var_strategie.set(chemin)

    def montage(self) -> Montage:
        """Lit le formulaire. Les erreurs de saisie sont nommees, pas devinees."""
        def nombre(variable: tk.StringVar, titre: str) -> float:
            texte = variable.get().strip().replace(" ", "").replace(",", ".")
            try:
                return float(texte)
            except ValueError as erreur:
                raise ConfigurationError(
                    f"{titre} : '{variable.get()}' n'est pas un nombre."
                ) from erreur

        return Montage(
            root=self.var_actif.get(),
            resample=self.var_agregation.get(),
            seance=self.var_seance.get(),
            capital=nombre(self.var_capital, "Capital initial"),
            frais=self.var_frais.get(),
            glissement=self.var_glissement.get(),
            glissement_valeur=nombre(self.var_glissement_valeur, "Ticks / bps"),
            contrats=int(nombre(self.var_contrats, "Contrats par entree")),
        )

    def lancer_montage(self) -> None:
        """Compose la strategie choisie avec le montage, puis execute."""
        if self._chemin_strategie is None:
            messagebox.showwarning(
                "Aucune strategie",
                "Choisissez d'abord un fichier de strategie.",
            )
            return
        self.var_statut.set("composition...")
        self.update_idletasks()
        try:
            strategie = StrategyFile.model_validate_json(
                self._chemin_strategie.read_text(encoding="utf-8")
            )
            reglage = self.montage()
            spec = compose(strategie, reglage.reglages(), symbol=reglage.symbole)
        except Exception as erreur:
            self.var_statut.set("echec")
            messagebox.showerror(
                "Montage impossible",
                f"{type(erreur).__name__}\n\n{erreur}",
            )
            return
        self.executer_spec(spec, f"{strategie.name}  -  {reglage.resume()}")

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
            for cle, libelle, _ in champs:
                self._carte(rangee, cle, libelle)

    def _carte(self, parent: tk.Misc, cle: str, libelle: str) -> None:
        """Une carte : un libelle gris, un chiffre, un filet autour.

        La carte ne connait pas sa teinte : elle est dans `TEINTES`, lue au
        moment de colorer. Un widget ne porte que ce que tkinter lui donne.
        """
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
            # `TEINTES[cle]` et non un defaut : une cle inconnue doit lever
            # ici plutot que peindre tout en noir sans le dire.
            teinte = TEINTES[cle]
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
        """Lance le backtest decrit par un fichier COMPLET."""
        self.var_statut.set(f"execution de {config.name}...")
        self.update_idletasks()
        try:
            self.charger(dashboard_depuis_config(config))
        except Exception as erreur:  # la fenetre ne doit pas mourir sur un run rate
            self.var_statut.set("echec")
            messagebox.showerror("Echec du backtest", f"{type(erreur).__name__}\n\n{erreur}")
            return
        n = len(self.table.get_children())
        self.var_statut.set(f"{config.name}  -  {n} trade(s)")

    def executer_spec(self, spec: BacktestSpec, libelle: str) -> None:
        """Lance une specification deja composee.

        `libelle` dit d'ou elle vient : une composition n'a pas de nom de
        fichier, et « execution de ... » sans objet ne renseigne personne.
        """
        self.var_statut.set(f"execution : {libelle}")
        self.update_idletasks()
        try:
            self.charger(dashboard_depuis_spec(spec))
        except Exception as erreur:
            self.var_statut.set("echec")
            messagebox.showerror("Echec du backtest", f"{type(erreur).__name__}\n\n{erreur}")
            return
        n = len(self.table.get_children())
        self.var_statut.set(f"{libelle}  -  {n} trade(s)")
        # On bascule sur la SYNTHESE : l'utilisateur vient de lancer un run, ce
        # qu'il veut voir est son resultat, pas le formulaire qu'il a rempli.
        #
        # `ignore` cible sur UNE ligne : `ttk.Notebook.select` n'est pas annotee
        # en amont. Elargir l'exception `disallow_untyped_calls` a tout ce
        # module - comme elle l'est pour `gui/charts.py` - couvrirait sept cents
        # lignes d'appels tkinter pour un seul besoin reel.
        self.onglets.select(1)  # type: ignore[no-untyped-call]

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
    """Execute une specification COMPLETE lue sur disque."""
    return dashboard_depuis_spec(
        BacktestSpec.model_validate_json(config.read_text(encoding="utf-8"))
    )


def dashboard_depuis_spec(spec: BacktestSpec) -> Dashboard:
    """Execute une specification deja construite et en fait un affichage.

    Separe de `dashboard_depuis_config` depuis le 2026-09-12 : une
    specification peut desormais venir d'un fichier COMPLET ou de la
    composition « strategie + montage » faite dans la fenetre.
    """
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


