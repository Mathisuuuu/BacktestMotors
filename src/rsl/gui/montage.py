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
from rsl.data.resample import Period
from rsl.data.session import SessionCalendar
from rsl.errors import ConfigurationError

RESAMPLES: Final[tuple[str, ...]] = (
    "brut",
    "5min", "10min", "15min", "30min", "1h", "2h", "4h",
    "day", "week", "month", "quarter", "year",
)
"""`brut` signifie « pas de reechantillonnage » : les barres telles qu'elles
sont dans le fichier. Nomme plutot que represente par une chaine vide, pour
qu'un menu deroulant ne montre jamais une case vide dont personne ne sait si
elle veut dire « rien » ou « pas encore choisi ».

Les sept premieres apres `brut` sont INTRA-JOURNALIERES et exigent une seance
declaree : une barre de 4 h ne dit pas ou elle commence. Le formulaire le
refuse plutot que de choisir un ancrage a la place de l'utilisateur."""

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
"""Barres minimales exigees pour former une barre agregee CALENDAIRE.

Une seance tronquee - veille de ferie, incident technique - produit sinon une
barre quotidienne batie sur quelques minutes, qui ressemble a une vraie barre
et n'en est pas une."""

SEANCES_CONNUES: Final[dict[str, str]] = {
    "CME": "17:00-16:00@America/Chicago",
    "CBOT": "17:00-16:00@America/Chicago",
    "COMEX": "17:00-16:00@America/Chicago",
    "NYMEX": "17:00-16:00@America/Chicago",
    "EUREX": "01:10-22:00@Europe/Berlin",
}
"""Seances PROPOSEES par le formulaire, par place, et rien de plus.

Elles ne font autorite sur rien. Le socle n'a aucune notion de seance qu'il
n'ait recue, et ces valeurs ne changent pas cela : elles pre-remplissent une
case que l'utilisateur relit et corrige. Ce qui compte est ce qu'il VALIDE -
c'est cela qui entre dans le `config_hash`, pas cette table.

Une place absente d'ici ne casse rien : la case reste vide, et choisir une
agregation intra-journaliere demande alors de la remplir."""


def part_intra_journaliere(resample: str) -> bool:
    """L'agregation demandee exige-t-elle une seance ?

    Interroge `Period`, plutot que de recopier la liste : une periode ajoutee
    au socle devient disponible ici sans qu'on y pense, et ne peut pas etre
    classee differemment des deux cotes ([[lessons]] L15).
    """
    if resample == "brut":
        return False
    return Period(resample).intra_journaliere


def min_barres_pour(resample: str) -> int:
    """Seuil de remplissage d'une periode, selon sa famille.

    200 barres sur une tranche de 5 min n'ecarterait pas les periodes creuses :
    il les ecarterait TOUTES. Le seuil calendaire ne peut donc pas servir tel
    quel, et un seuil fixe qui conviendrait aux deux n'existe pas.

    Pour une tranche intra-journaliere, la moitie de sa duree nominale : une
    tranche de 4 h batie sur moins de deux heures de cotation n'est pas une
    tranche de 4 h. La derniere tranche de chaque seance, plus courte par
    construction, reste donc acceptee tant qu'elle depasse cette moitie - et
    sur une seance ES de 23 h decoupee en 4 h, la tranche finale en fait 3.
    """
    if not part_intra_journaliere(resample):
        return MIN_BARRES_AGREGEES
    return max(1, Period(resample).minutes // 2)


def lire_seance(texte: str) -> dict[str, str]:
    """`"17:00-16:00@America/Chicago"` -> les trois champs de `session`.

    Une seule case plutot que trois : le formulaire en compte deja six, et
    trois de plus pour une option qui ne sert qu'a une famille d'agregations
    les noieraient. La validation des trois champs reste faite par
    `SessionCalendar`, qui seul fait autorite.
    """
    bornes, _, fuseau = texte.strip().partition("@")
    debut, _, fin = bornes.partition("-")
    if not (debut and fin and fuseau):
        raise ConfigurationError(
            f"seance : format attendu 'HH:MM-HH:MM@Fuseau', recu {texte!r}. "
            f"Exemple : 17:00-16:00@America/Chicago"
        )
    calendrier = SessionCalendar(start=debut, end=fin, timezone=fuseau)
    return calendrier.describe()


def seance_proposee(root: str) -> str:
    """Ce que le formulaire pre-remplit pour cet instrument. Peut etre vide."""
    return SEANCES_CONNUES.get(get_instrument(root).exchange, "")


@dataclass(frozen=True, slots=True)
class Montage:
    """Les six reglages que l'on change d'un essai a l'autre."""

    root: str
    resample: str = "day"
    seance: str = ""
    """`"HH:MM-HH:MM@Fuseau"`, ou vide. Obligatoire pour une agregation
    intra-journaliere, inutile autrement."""
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
        if part_intra_journaliere(self.resample) and not self.seance.strip():
            raise ConfigurationError(
                f"l'agregation '{self.resample}' exige une SEANCE : une barre de "
                f"{Period(self.resample).minutes} min ne dit pas ou elle commence, "
                f"et le socle ne devine aucune frontiere. Remplir le champ SEANCE "
                f"(format 'HH:MM-HH:MM@Fuseau')."
            )
        if self.seance.strip():
            lire_seance(self.seance)  # leve si le format ou le fuseau sont faux
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

        Lu sur la table des contrats depuis le 2026-09-12. Ce module en portait
        une COPIE - un dictionnaire `DOSSIERS` recopiant l'arborescence - qui
        aurait menti sans prevenir le jour ou un instrument serait range
        ailleurs, ou simplement oublie ici.
        """
        return get_instrument(self.root).data_path

    def reglages(self) -> dict[str, object]:
        """Le dictionnaire que `compose()` fera valider par `BacktestSpec`."""
        donnees: dict[str, object] = {
            "root": self.root,
            "path": self.chemin,
            "granularity_minutes": 1,
        }
        if self.resample != "brut":
            donnees["resample"] = self.resample
            donnees["resample_min_bars"] = min_barres_pour(self.resample)
        if self.seance.strip():
            donnees["session"] = lire_seance(self.seance)

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
        if part_intra_journaliere(self.resample):
            agregation += f" ({self.seance.strip()})"
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
