"""Contraintes de PORTEFEUILLE : ce qu'on s'interdit, toutes positions confondues.

La difference avec le dimensionnement
--------------------------------------
Le dimensionnement repond a « combien de contrats sur CET ordre » en regardant
un instrument. Une contrainte de portefeuille repond a « ce portefeuille a-t-il
le droit d'exister » en regardant TOUTES les positions a la fois. Les deux
peuvent etre justes separement et donner ensemble un portefeuille inacceptable :
dix regles qui prennent chacune une position raisonnable font une exposition
qui ne l'est pas.

Ce qui existait, et ce que ce module ajoute
--------------------------------------------
`RiskManager.max_gross_contracts` existait deja, et son nom trompe : il borne
`abs(position)` POUR UN INSTRUMENT, pas le portefeuille. Il reste tel quel -
c'est une limite utile - mais il ne repond a aucune des questions ci-dessous.

Surtout, un plafond en CONTRATS ne veut rien dire d'un instrument a l'autre :
dix ES valent 10 x 50 x 5 000, dix CL valent 10 x 1 000 x 70. Une contrainte de
portefeuille se mesure donc en ARGENT, rapporte a l'equity.

    max_gross_exposure   somme des |notionnels| / equity
    max_net_exposure     |somme des notionnels signes| / equity
    max_positions        nombre d'instruments detenus
    max_per_category     nombre d'instruments detenus par classe d'actif

`max_per_category` n'etait pas ecrivable avant le 2026-09-12 : il a fallu que
`InstrumentSpec` porte une classe d'actif.

Brut et net ne disent pas la meme chose
----------------------------------------
Un portefeuille long 5 ES et court 5 ES a un net de zero et un brut de dix : il
n'a aucune exposition directionnelle et tout le risque de base. Un portefeuille
long 5 ES seulement a les deux a cinq. Borner l'un sans l'autre laisse passer
exactement l'un de ces deux risques.

Un plafond ne bloque jamais un retour vers lui
-----------------------------------------------
Les plafonds se comparent en ARGENT a une equity qui bouge toute seule. Un
portefeuille conforme a 1,9 le matin est a 2,1 le soir sans qu'aucun ordre soit
passe, simplement parce que l'equity a baisse. Refuser alors tout ordre qui
depasse encore le plafond enfermerait le portefeuille au-dessus : il ne pourrait
plus se reduire.

D'ou la regle, qui porte sur la VARIATION et non sur le niveau : un ordre est
refuse s'il depasse le plafond **et** aggrave la mesure qu'il depasse. Un ordre
qui la laisse egale ou la diminue passe toujours. `PortfolioLimits.refus` en decoule
directement, et c'est ce qui rend la contrainte sure - un plafond qui peut
pieger un portefeuille n'est pas une contrainte, c'est une panne.

L'honnetete sur ce que ces plafonds garantissent
-------------------------------------------------
Ils sont evalues a la SOUMISSION, sur les marques de la barre courante. Le fill
a lieu a la barre suivante, a un autre prix. L'exposition realisee peut donc
depasser legerement le plafond, et c'est structurel : un backtest sans lag
d'execution serait du look-ahead, et le plafond exact demanderait de connaitre
le prix de fill avant de le connaitre.

Le plafond borne donc ce qu'on DEMANDE, pas ce qu'on obtient. Deux autres
frontieres, du meme genre, a connaitre avant de s'y fier :

- un ordre `reduce_only` n'est pas soumis a ces plafonds. Il ne peut que
  reduire, et le passer au controle ne changerait rien qu'un risque de le
  refuser a tort ;
- une position qu'un STOP ou un objectif ferme n'est pas un ordre de la
  strategie : elle passe par le meme chemin `reduce_only` et echappe donc,
  elle aussi, au controle - ce qui est le comportement voulu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rsl.data.schema import InstrumentSpec
from rsl.errors import ConfigurationError

SpecDict = dict[str, object]

AUCUN: Final[str] = ""
"""Motif de refus vide : rien ne s'oppose a l'ordre."""

SANS_CLASSE: Final[str] = "?"
"""Classe des instruments synthetiques, qui n'en declarent pas.

Ils sont comptes ensemble plutot qu'exemptes : un plafond par classe qui
ignorerait les instruments non classes serait contournable en omettant un
champ facultatif.
"""

MOTIFS: Final[tuple[str, ...]] = (
    "gross_exposure",
    "net_exposure",
    "positions",
    "per_category",
)
"""Les refus possibles, nommes. Le rapport en publie un compteur par motif."""


@dataclass(frozen=True, slots=True)
class Expositions:
    """Photographie d'un jeu de positions, en argent et en nombre."""

    gross: float
    """Somme des |notionnels|, en devise."""

    net: float
    """Somme des notionnels SIGNES, en devise. Negatif si net vendeur."""

    n_positions: int
    par_categorie: dict[str, int]

    def rapportees(self, equity: float) -> tuple[float, float]:
        """`(brut, net)` en fraction de l'equity, le net en valeur absolue.

        Une equity nulle ou negative rend `(inf, inf)`. Diviser par zero
        l'aurait cache ; lever aurait fait tomber le run sur un etat qui est
        rare mais legitime.

        Consequence a connaitre, parce qu'elle n'est pas celle qu'on attend :
        combine a la regle de non-aggravation, `inf` rend les plafonds INERTES
        sous zero, puisque `inf > inf` est faux. Aucun ordre n'y est refuse,
        ni dans un sens ni dans l'autre. C'est voulu pour un sens - un compte
        ruine doit pouvoir se solder - et sans effet dans l'autre : sous la
        politique `reject`, la marge refuse deja tout ordre qui ajoute du
        risque quand l'equity ne couvre plus rien. Sous `warn`, elle ne le
        refuse pas, et ces plafonds non plus.
        """
        if equity <= 0.0:
            return (float("inf"), float("inf"))
        return (self.gross / equity, abs(self.net) / equity)

    def dans_la_classe(self, classe: str) -> int:
        return self.par_categorie.get(classe, 0)


def notionnel(spec: InstrumentSpec, quantite: int, marque: float) -> float:
    """Valeur signee d'une position, en devise.

    Le MULTIPLICATEUR est ce qui rend deux instruments comparables : sans lui,
    un plafond « dix contrats » autorise vingt fois plus de risque sur CL que
    sur 6E.
    """
    return quantite * spec.multiplier * marque


def classe_de(spec: InstrumentSpec) -> str:
    return SANS_CLASSE if spec.category is None else spec.category.value


def mesurer(
    quantites: dict[str, int],
    specs: dict[str, InstrumentSpec],
    marques: dict[str, float],
) -> Expositions:
    """Photographie d'un jeu de positions.

    `marques` est resolu par l'appelant, pas ici : le `RiskManager` le construit
    avec `Portfolio.mark_of`, la MEME resolution que celle de l'equity. Mesurer
    une exposition autrement que le denominateur auquel on la rapporte
    donnerait un ratio dont aucun des deux termes ne repond de l'autre.

    Un instrument sans marque du tout est compte dans les POSITIONS mais pas
    dans les notionnels : on sait qu'il est detenu, on ne sait pas ce qu'il
    vaut, et lui inventer une valeur serait la seule facon de se tromper en
    silence.
    """
    brut = 0.0
    net = 0.0
    detenus = 0
    par_categorie: dict[str, int] = {}
    for symbole in sorted(quantites):
        quantite = quantites[symbole]
        if quantite == 0:
            continue
        detenus += 1
        spec = specs[symbole]
        classe = classe_de(spec)
        par_categorie[classe] = par_categorie.get(classe, 0) + 1
        marque = marques.get(symbole)
        if marque is None:
            continue
        valeur = notionnel(spec, quantite, marque)
        brut += abs(valeur)
        net += valeur
    return Expositions(
        gross=brut, net=net, n_positions=detenus, par_categorie=par_categorie
    )


def projeter(quantites: dict[str, int], symbole: str, delta: int) -> dict[str, int]:
    """Les quantites telles qu'elles seraient si l'ordre passait.

    Fonction separee, et non deux lignes dans le `RiskManager`, parce que c'est
    ici que se joue la seule chose que la contrainte doit savoir : on plafonne
    le portefeuille d'APRES, pas celui d'avant. Le plafonner avant ne mordrait
    qu'une fois deja depasse.
    """
    projete = dict(quantites)
    projete[symbole] = projete.get(symbole, 0) + delta
    return projete


@dataclass(frozen=True, slots=True)
class PortfolioLimits:
    """Les plafonds declares. Tous facultatifs ; aucun n'est un defaut cache.

    `None` signifie « pas de plafond », et c'est le defaut partout : imposer
    une limite que personne n'a demandee changerait silencieusement le resultat
    de toutes les specifications ecrites avant aujourd'hui.
    """

    max_gross_exposure: float | None = None
    max_net_exposure: float | None = None
    max_positions: int | None = None
    max_per_category: int | None = None

    def __post_init__(self) -> None:
        for nom in ("max_gross_exposure", "max_net_exposure"):
            valeur = getattr(self, nom)
            if valeur is not None and valeur <= 0.0:
                raise ConfigurationError(
                    f"{nom} doit etre > 0, recu {valeur}. A zero, aucune position "
                    f"ne serait jamais ouverte - ce n'est pas un backtest."
                )
        for nom in ("max_positions", "max_per_category"):
            valeur = getattr(self, nom)
            if valeur is not None and valeur < 1:
                raise ConfigurationError(
                    f"{nom} doit etre >= 1, recu {valeur}. A zero, aucune position "
                    f"ne serait jamais ouverte - ce n'est pas un backtest."
                )

    @property
    def actives(self) -> bool:
        """Y a-t-il quoi que ce soit a verifier ?

        Sert a ne pas payer la mesure des expositions quand rien n'est declare -
        et rien ne l'est dans aucune specification anterieure a ce module.
        """
        return any(
            valeur is not None
            for valeur in (
                self.max_gross_exposure,
                self.max_net_exposure,
                self.max_positions,
                self.max_per_category,
            )
        )

    def refus(
        self,
        avant: Expositions,
        apres: Expositions,
        equity: float,
        classe: str,
    ) -> str:
        """Le NOM du plafond qui refuse l'ordre, ou `AUCUN`.

        Rend un nom et non un booleen : un ordre refuse sans motif laisse
        chercher lequel des quatre plafonds a mordu, et le rapport n'aurait
        qu'un seul compteur indistinct a publier.

        Chaque plafond refuse a deux conditions - depasse APRES, et pire
        qu'AVANT. La seconde est ce qui empeche d'enfermer un portefeuille
        au-dessus d'un plafond qu'une baisse d'equity a fait franchir seul.
        """
        brut_avant, net_avant = avant.rapportees(equity)
        brut_apres, net_apres = apres.rapportees(equity)

        tenus = apres.dans_la_classe(classe)
        depassements = (
            ("gross_exposure", self.max_gross_exposure, brut_apres, brut_avant),
            ("net_exposure", self.max_net_exposure, net_apres, net_avant),
            (
                "positions",
                self.max_positions,
                float(apres.n_positions),
                float(avant.n_positions),
            ),
            (
                "per_category",
                self.max_per_category,
                float(tenus),
                float(avant.dans_la_classe(classe)),
            ),
        )
        for motif, plafond, apres_, avant_ in depassements:
            if plafond is not None and apres_ > plafond and apres_ > avant_:
                return motif
        return AUCUN

    def describe(self) -> SpecDict:
        return {
            "max_gross_exposure": self.max_gross_exposure,
            "max_net_exposure": self.max_net_exposure,
            "max_positions": self.max_positions,
            "max_per_category": self.max_per_category,
        }


AUCUNE_LIMITE: Final[PortfolioLimits] = PortfolioLimits()
"""Le defaut partage. Immuable, donc partageable sans copie."""
