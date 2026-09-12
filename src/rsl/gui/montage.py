"""Le MONTAGE d'un run : l'actif, l'argent, les couts.

Ce que ce module est
--------------------
La moitie qu'un fichier de strategie ne porte pas. Une strategie dit QUOI
decider ; le montage dit sur quoi, avec combien, et a quels couts.

Sans tkinter, comme `gui/model.py` et pour la meme raison : l'interface est du
dessin, ce qu'elle produit est du calcul. Ce fichier est la partie qu'on peut
tester, et `gui/app.py` n'est que le formulaire qui le remplit.

Ce qu'il n'est pas
------------------
Il ne redeclare AUCUN champ de `BacktestSpec`. Il produit un dictionnaire que
`composition.compose()` fait valider par elle : une option mal orthographiee
est refusee par le meme `extra="forbid"` que partout ailleurs, et rien ne peut
diverger d'elle en silence.

Le choix de ne pas tout exposer
--------------------------------
Un run a une quinzaine de reglages. Le formulaire en expose SIX - ceux qu'on
change d'un essai a l'autre. Les autres (`lag_bars`, `intrabar_priority`,
`margin_policy`, `check_invariant`...) gardent les defauts du socle, qui sont
des choix de prudence et non des valeurs arbitraires : les rendre reglables
d'un clic inviterait a les desactiver sans y penser.

Qui veut y toucher ecrit un fichier de reglages et passe par
`rsl run --settings`. C'est plus long, et c'est voulu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rsl.data.instruments import get_instrument, known_roots
from rsl.errors import ConfigurationError

RESAMPLES: Final[tuple[str, ...]] = ("brut", "day", "week", "month", "quarter", "year")
"""`brut` signifie « pas de reechantillonnage » : les barres telles qu'elles
sont dans le fichier. Nomme plutot que represente par une chaine vide, pour
qu'un menu deroulant ne montre jamais une case vide dont personne ne sait si
elle veut dire « rien » ou « pas encore choisi »."""

FRAIS: Final[tuple[str, ...]] = ("per_contract", "flat", "zero")
GLISSEMENTS: Final[tuple[str, ...]] = ("tick", "bps", "zero")

RACINE_PAR_DEFAUT: Final[str] = "ES"
"""Instrument propose a l'ouverture.

Nomme plutot que « le premier par ordre alphabetique », qui donnait `6A` - un
contrat sur le dollar australien, que personne ne teste en premier. Un defaut
arbitraire n'est pas neutre : il est choisi par accident au lieu de l'etre
expres.
"""


def racine_initiale() -> str:
    """`ES` s'il est connu, sinon la premiere racine. Jamais une chaine vide."""
    racines = sorted(known_roots())
    if RACINE_PAR_DEFAUT in racines:
        return RACINE_PAR_DEFAUT
    return racines[0] if racines else ""


MIN_BARRES_AGREGEES: Final[int] = 200
"""Barres minimales exigees pour former une barre agregee.

Une seance tronquee - veille de ferie, incident technique - produit sinon une
barre quotidienne batie sur quelques minutes, qui ressemble a une vraie barre
et n'en est pas une."""


@dataclass(frozen=True, slots=True)
class Montage:
    """Les six reglages que l'on change d'un essai a l'autre."""

    root: str
    resample: str = "day"
    capital: float = 1_000_000.0
    frais: str = "per_contract"
    glissement: str = "tick"
    glissement_valeur: float = 1.0
    contrats: int = 1

    def __post_init__(self) -> None:
        if self.root not in known_roots():
            raise ConfigurationError(
                f"instrument inconnu : '{self.root}'. Connus : "
                f"{', '.join(sorted(known_roots()))}"
            )
        if self.resample not in RESAMPLES:
            raise ConfigurationError(
                f"agregation inconnue : '{self.resample}'. Connues : "
                f"{', '.join(RESAMPLES)}"
            )
        if self.frais not in FRAIS:
            raise ConfigurationError(f"frais inconnus : '{self.frais}'")
        if self.glissement not in GLISSEMENTS:
            raise ConfigurationError(f"glissement inconnu : '{self.glissement}'")
        if self.capital <= 0.0:
            raise ConfigurationError(
                f"capital initial a {self.capital} : un backtest sans capital "
                f"ne peut rien acheter."
            )
        if self.contrats < 1:
            raise ConfigurationError(
                f"nombre de contrats a {self.contrats} : une strategie qui ne "
                f"peut pas prendre position n'a rien a mesurer."
            )
        if self.glissement != "zero" and self.glissement_valeur < 0.0:
            raise ConfigurationError(
                f"glissement negatif ({self.glissement_valeur}) : il ferait "
                f"gagner de l'argent a chaque execution."
            )

    @property
    def symbole(self) -> str:
        """Le symbole complet de l'instrument choisi, ex. `ES.v.0`."""
        return get_instrument(self.root).symbol

    @property
    def chemin(self) -> str:
        """Chemin RELATIF a la racine des donnees.

        Relatif et non absolu : un chemin absolu ferait diverger le
        `config_hash` entre deux machines, et c'est precisement le defaut
        corrige le 2026-09-10.
        """
        return DOSSIERS[self.root] + f"/{self.root}_v0_1m.parquet"

    def reglages(self) -> dict[str, object]:
        """Le dictionnaire que `compose()` fera valider par `BacktestSpec`."""
        donnees: dict[str, object] = {
            "root": self.root,
            "path": self.chemin,
            "granularity_minutes": 1,
        }
        if self.resample != "brut":
            donnees["resample"] = self.resample
            donnees["resample_min_bars"] = MIN_BARRES_AGREGEES

        glissement: dict[str, object] = {"kind": self.glissement}
        if self.glissement == "tick":
            glissement["ticks"] = self.glissement_valeur
        elif self.glissement == "bps":
            glissement["bps"] = self.glissement_valeur

        return {
            "initial_cash": self.capital,
            "data": [donnees],
            "execution": {"fees": {"kind": self.frais}, "slippage": glissement},
            "risk": {"sizing": {"kind": "fixed", "contracts": self.contrats}},
        }

    def resume(self) -> str:
        """Une ligne pour le bandeau : ce qui a servi, pas ce qui est possible."""
        agregation = "1 min" if self.resample == "brut" else self.resample
        cout = (
            "sans cout"
            if self.glissement == "zero" and self.frais == "zero"
            else f"{self.frais}, {self.glissement} {self.glissement_valeur:g}"
        )
        return (
            f"{self.symbole}  -  {agregation}  -  "
            f"{self.capital:,.0f}".replace(",", " ")
            + f"  -  {self.contrats} contrat(s)  -  {cout}"
        )


DOSSIERS: Final[dict[str, str]] = {
    "ES": "indices", "NQ": "indices", "YM": "indices", "FDAX": "indices",
    "GC": "metaux", "CL": "energie",
    "6E": "forex", "6B": "forex", "6J": "forex", "6A": "forex",
}
"""Sous-dossier de chaque racine sous la racine des donnees.

Recopie de l'arborescence reelle, et c'est une DETTE assumee : le jour ou un
instrument est range ailleurs, ce dictionnaire ment sans prevenir. La table
d'instruments ne porte pas le chemin ; l'y ajouter serait le vrai correctif,
et il touche a la couche donnees.

`tests/unit/test_gui_montage.py` verifie au moins qu'il couvre exactement les
racines connues, donc qu'un instrument ajoute ne soit pas oublie ici.
"""
