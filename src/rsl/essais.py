"""Registre des ESSAIS : la memoire du compteur, entre les sessions.

Le probleme que ce module resout
---------------------------------
`TrialLog` compte les essais d'un PROCESSUS. Chaque `rsl run` en cree un neuf,
donc chaque run se declare « 1 essai » et son Deflated Sharpe se confond avec
son PSR - le rapport le dit lui-meme dans son avertissement. Autrement dit : le
seul chiffre qui corrige la selection ne corrigeait jamais rien.

Or le nombre d'essais n'est pas une propriete d'un run, c'est une propriete de
la RECHERCHE. Vingt configurations evaluees sur le meme echantillon font vingt
essais, meme lancees vingt jours de suite depuis vingt terminaux differents. Un
essai fait et non enregistre gonfle mecaniquement le DSR de tous les autres,
sans que rien ne le signale (CLAUDE.md, « unite de travail : l'essai »).

Ce que le registre est, et ce qu'il n'est pas
----------------------------------------------
Un fichier JSONL VERSIONNE, `essais/registre.jsonl`, une ligne par essai,
append-only comme `wiki/log.md`. Une ligne par essai le rend fusionnable :
deux sessions qui archivent en parallele produisent deux lignes, pas un
conflit sur un tableau reindente.

Il ne remplace pas `wiki/experiments/`. Les pages d'experience portent
l'HYPOTHESE, le verdict, et ce qu'il ne faut pas conclure - du jugement, que
personne ne peut deriver d'un run. Le registre porte les FAITS, et il est ecrit
par la machine. Quand les deux se contredisent, c'est le registre qui a raison
sur les chiffres, et la page sur le sens.

`runs/` reste ce qu'il etait : la sortie de `--out`, un fichier qu'on regarde
et qu'on jette, hors du depot. `essais/` est ce qu'on garde.

Rejouer n'est pas essayer
--------------------------
Deux runs de la MEME specification ne comptent qu'une fois. C'est la regle de
`TrialLog`, et elle est ici aussi : penaliser la reproductibilite serait
exactement contraire au but. La cle est le `config_hash`.

Mais la meme specification qui rend un AUTRE resultat est un evenement, pas un
doublon : le moteur a change, et les chiffres archives avant ne sont plus
comparables a ceux d'apres. Le registre l'enregistre alors comme une ligne
distincte et le DIT, plutot que de laisser deux verites porter le meme nom.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from rsl.errors import ConfigurationError, RslError
from rsl.metrics.performance import DailySeries
from rsl.metrics.statistics import TrialLog

SpecDict = dict[str, object]

DOSSIER = Path("essais")
REGISTRE = DOSSIER / "registre.jsonl"
RAPPORTS = DOSSIER / "rapports"
SERIES = DOSSIER / "series"

CLE = 12
"""Longueur du prefixe de `config_hash` qui nomme un rapport archive.

Douze caracteres hexadecimaux : 2^48 valeurs. A quelques milliers d'essais, la
probabilite de collision reste sous 10^-7, et un nom de fichier lisible vaut
mieux qu'un nom de 64 caracteres que personne ne relit. La cle COMPLETE reste
dans la ligne du registre - c'est elle qui fait foi."""


class EssaiDejaArchiveError(RslError):
    """Rejouer un essai deja enregistre n'en fait pas un nouveau."""


@dataclass(frozen=True, slots=True)
class Essai:
    """Une ligne du registre : ce qu'il faut pour recalculer un DSR, et retrouver le run.

    Les quatre champs statistiques (`sharpe_per_period`, `n_returns`,
    `skewness`, `kurtosis`) sont recopies du rapport A DESSEIN : le Deflated
    Sharpe doit pouvoir se recalculer a partir du seul registre, sans relire
    des rapports ni des donnees. C'est la seule duplication assumee du module,
    et le rapport archive reste la source si les deux divergent.
    """

    date: str
    label: str
    config_hash: str
    result_fingerprint: str
    sharpe_per_period: float
    n_returns: int
    skewness: float
    kurtosis: float
    n_bars: int
    span_years: float
    symbols: tuple[str, ...]
    rapport: str | None = None
    serie: str | None = None
    """Chemin de la serie QUOTIDIENNE archivee, ou `None`.

    C'est la seule chose qui rende deux essais comparables autrement que par
    leur echantillon. Elle vaut `None` pour tous les essais anterieurs au
    2026-09-17 - irrattrapable sans les rejouer - et pour les essais de
    BALAYAGE, qui n'ecrivent deja aucun rapport.
    """
    note: str = ""

    @staticmethod
    def depuis_rapport(rapport: SpecDict, *, note: str = "") -> Essai:
        """Extrait une ligne de registre d'un rapport complet.

        Leve si le Sharpe par periode est absent : un essai sans Sharpe
        n'apporte rien au compteur du DSR, et l'enregistrer avec un zero
        inventerait une mesure - il ferait baisser la variance des essais, donc
        monter le DSR de tous les autres.
        """
        metriques = _bloc(rapport, "metrics")
        risque = _bloc(metriques, "risk")
        echantillon = _bloc(metriques, "sample")
        manifeste = _bloc(rapport, "manifest")

        sharpe = risque.get("sharpe_per_period")
        if not isinstance(sharpe, (int, float)):
            raise ConfigurationError(
                "ce rapport n'a pas de `sharpe_per_period` : un essai sans Sharpe "
                "ne dit rien au compteur du Deflated Sharpe, et lui en inventer un "
                "ferait monter le DSR de tous les autres."
            )
        symboles = rapport.get("symbols")
        return Essai(
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
            label=str(rapport.get("name", "")),
            config_hash=str(manifeste["config_hash"]),
            result_fingerprint=str(rapport["result_fingerprint"]),
            sharpe_per_period=float(sharpe),
            n_returns=int(_nombre(risque, "n_returns")),
            skewness=float(_nombre(risque, "returns_skewness")),
            kurtosis=float(_nombre(risque, "returns_kurtosis")),
            n_bars=int(_nombre(echantillon, "n_bars")),
            span_years=float(_nombre(echantillon, "span_years")),
            symbols=tuple(str(s) for s in symboles) if isinstance(symboles, list) else (),
            note=note,
        )

    def avec_rapport(self, chemin: str, serie: str | None = None) -> Essai:
        return Essai(
            **{**self.describe_brut(), "rapport": chemin, "serie": serie}  # type: ignore[arg-type]
        )

    def describe_brut(self) -> SpecDict:
        return {
            "date": self.date,
            "label": self.label,
            "config_hash": self.config_hash,
            "result_fingerprint": self.result_fingerprint,
            "sharpe_per_period": self.sharpe_per_period,
            "n_returns": self.n_returns,
            "skewness": self.skewness,
            "kurtosis": self.kurtosis,
            "n_bars": self.n_bars,
            "span_years": self.span_years,
            "symbols": tuple(self.symbols),
            "rapport": self.rapport,
            "serie": self.serie,
            "note": self.note,
        }

    def describe(self) -> SpecDict:
        charge = self.describe_brut()
        charge["symbols"] = list(self.symbols)
        return charge

    def ligne(self) -> str:
        """Une ligne JSON, cles triees : deux archivages du meme essai donnent
        le meme texte, et un `git diff` reste lisible."""
        return json.dumps(self.describe(), sort_keys=True, ensure_ascii=False)

    @staticmethod
    def depuis_ligne(ligne: str) -> Essai:
        charge = json.loads(ligne)
        if not isinstance(charge, dict):
            raise ConfigurationError(f"ligne de registre invalide : {ligne[:60]!r}")
        charge["symbols"] = tuple(charge.get("symbols", ()))
        return Essai(**charge)

    @property
    def cle(self) -> str:
        return self.config_hash[:CLE]

    def render(self) -> str:
        noms = ",".join(self.symbols) or "-"
        return (
            f"{self.date}  {self.cle}  sharpe/periode {self.sharpe_per_period:+.4f}  "
            f"{self.n_returns:>6} obs  {noms:<28} {self.label}"
        )


def _bloc(charge: SpecDict, cle: str) -> SpecDict:
    valeur = charge.get(cle)
    if not isinstance(valeur, dict):
        raise ConfigurationError(f"rapport sans bloc '{cle}' : ce n'est pas un rapport rsl")
    return valeur


def _nombre(charge: SpecDict, cle: str) -> float:
    valeur = charge.get(cle)
    if not isinstance(valeur, (int, float)):
        raise ConfigurationError(f"champ '{cle}' absent ou non numerique")
    return float(valeur)


@dataclass(frozen=True, slots=True)
class Registre:
    """Le registre, lu depuis un dossier. Immuable ; ecrire rend un nouvel etat."""

    racine: Path

    @property
    def fichier(self) -> Path:
        return self.racine / REGISTRE.name

    @property
    def rapports(self) -> Path:
        return self.racine / RAPPORTS.name

    @property
    def series(self) -> Path:
        return self.racine / SERIES.name

    def lire_serie(self, essai: Essai) -> tuple[np.ndarray, np.ndarray] | None:
        """Les dates et rendements quotidiens d'un essai, s'ils ont ete gardes.

        `None` n'est pas une erreur : aucun essai archive avant le 2026-09-17
        n'en porte, et un essai de balayage n'en portera jamais.
        """
        if essai.serie is None:
            return None
        chemin = self.racine / essai.serie
        if not chemin.exists():
            raise ConfigurationError(
                f"l'essai {essai.cle} declare une serie en {essai.serie}, qui "
                f"n'existe pas. Le registre et le disque se contredisent."
            )
        with np.load(chemin) as charge:
            return charge["ts"], charge["returns"]

    def essais(self) -> list[Essai]:
        """Les essais enregistres, dans l'ordre d'archivage.

        Un fichier absent rend une liste vide plutot que de lever : un depot
        neuf n'a pas encore d'essais, et ce n'est pas une erreur.
        """
        if not self.fichier.exists():
            return []
        return list(_lire(self.fichier))

    def par_configuration(self) -> dict[str, list[Essai]]:
        """Les essais groupes par `config_hash`.

        Plusieurs entrees sous une meme cle signalent un changement de MOTEUR :
        la meme specification a rendu des resultats differents.
        """
        groupes: dict[str, list[Essai]] = {}
        for essai in self.essais():
            groupes.setdefault(essai.config_hash, []).append(essai)
        return groupes

    def divergences(self) -> dict[str, list[Essai]]:
        """Les specifications qui ont rendu PLUSIEURS resultats.

        Ce n'est pas une anomalie du registre : c'est le registre qui fait son
        travail. Une empreinte qui change a `config_hash` constant veut dire que
        le moteur a change - les chiffres d'avant et d'apres ne se comparent
        plus, et il faut savoir lesquels on lit.
        """
        return {
            cle: essais
            for cle, essais in self.par_configuration().items()
            if len({e.result_fingerprint for e in essais}) > 1
        }

    def doublons(self) -> dict[str, list[Essai]]:
        """Les RESULTATS obtenus par plusieurs specifications differentes.

        Le miroir de `divergences`, et le plus insidieux des deux. Deux facons
        d'ecrire la meme strategie - `cross_sectional_momentum@1` et
        `ranking@1` avec le score correspondant, par exemple - ont deux
        `config_hash` et une seule empreinte de resultat. Le compteur les voit
        comme DEUX essais alors qu'une seule idee a ete essayee.

        L'effet sur le Deflated Sharpe n'est pas neutre : le nombre d'essais
        monte, mais la variance des Sharpe baisse, puisque les deux valeurs
        sont identiques. Les deux vont dans des sens opposes, et le resultat
        net n'est pas lisible a l'oeil. Mieux vaut le SIGNALER que le corriger
        d'office : decider que deux specifications sont « la meme idee » est un
        jugement, et le registre n'en porte aucun.

        Ce que ce test NE voit pas, et il faut le savoir avant de s'y fier : il
        compare des empreintes, donc il ne repere que les resultats
        bit-identiques. Deux ecritures economiquement equivalentes dont les
        fills portent des etiquettes differentes ont deux empreintes et
        passeront inapercues - constate le 2026-09-12 entre
        `cross_sectional_momentum@1` et `ranking@1`, qui rendent le meme Sharpe
        a la quinzieme decimale et deux empreintes distinctes, parce que leurs
        `tag` different. Le signal est donc SUFFISANT, jamais NECESSAIRE.
        """
        groupes: dict[str, list[Essai]] = {}
        for essai in self.essais():
            groupes.setdefault(essai.result_fingerprint, []).append(essai)
        return {
            empreinte: essais
            for empreinte, essais in groupes.items()
            if len({e.config_hash for e in essais}) > 1
        }

    def journal(self) -> TrialLog:
        """Le registre, sous la forme que le Deflated Sharpe attend.

        La deduplication est faite ici, par `config_hash` : c'est cette clef
        qui dit « meme instructions », et rejouer un backtest n'est pas un
        nouvel essai. Une divergence de moteur ne compte donc PAS pour deux
        essais - c'est une seule configuration, essayee une fois, dont on a
        deux mesures.
        """
        journal = TrialLog()
        for essai in self.essais():
            journal.record(
                {"config_hash": essai.config_hash},
                essai.sharpe_per_period,
                label=essai.label,
            )
        return journal

    def contient(self, config_hash: str, result_fingerprint: str) -> bool:
        return any(
            e.config_hash == config_hash and e.result_fingerprint == result_fingerprint
            for e in self.essais()
        )

    def archiver(
        self,
        rapport: SpecDict,
        *,
        note: str = "",
        artefact: str | None = None,
        serie: DailySeries | None = None,
    ) -> Essai:
        """Ajoute un essai et ecrit son rapport complet.

        Refuse un essai deja present a l'identique - meme configuration ET meme
        resultat. Rejouer un backtest est une VERIFICATION, pas une recherche ;
        la compter gonflerait le denominateur du DSR en punissant exactement ce
        qu'on veut encourager.

        Il n'y a deliberement AUCUN drapeau pour passer outre. Un doublon leve,
        et l'appelant decide quoi en faire : une echappatoire finirait par
        transformer « j'ai relance pour verifier » en un essai de plus, par
        inadvertance, et c'est precisement ce que ce module existe pour
        empecher.

        Le cas « meme configuration, AUTRE resultat » n'est pas un doublon et
        passe sans rien forcer : c'est un changement de moteur, et il doit
        laisser une trace.

        `artefact` sert aux BALAYAGES. Une grille de plusieurs centaines de
        configurations est plusieurs centaines d'essais - le compteur du DSR en
        a besoin, et sous-compter gonflerait le DSR de tous les autres. Mais
        ecrire un rapport complet par configuration ajouterait des milliers de
        fichiers au depot pour une information que le fichier de grille contient
        deja. Les lignes pointent alors toutes vers ce seul artefact.

        Ce qui est perdu en echange, et il faut le savoir : le detail par
        configuration - fills, trades, manifeste - n'est pas conserve. Un essai
        de balayage est donc RECOMPTE mais pas rejouable a l'identique sans
        relancer la grille. C'est le bon arbitrage pour une grille systematique,
        et le mauvais pour un essai qu'on publie.
        """
        essai = Essai.depuis_rapport(rapport, note=note)
        if self.contient(essai.config_hash, essai.result_fingerprint):
            raise EssaiDejaArchiveError(
                f"essai deja enregistre : {essai.cle} rend toujours "
                f"{essai.result_fingerprint[:12]}. Rejouer n'est pas essayer - "
                f"le compteur du Deflated Sharpe ne doit pas monter."
            )
        # La racine est creee ICI, et non en effet de bord de l'ecriture d'un
        # rapport : un balayage n'en ecrit aucun, et le premier appel sur un
        # depot neuf echouait a ouvrir le registre. Constate le 2026-09-12, en
        # ajoutant justement le chemin des balayages.
        self.racine.mkdir(parents=True, exist_ok=True)
        if artefact is None:
            self.rapports.mkdir(parents=True, exist_ok=True)
            chemin = self.rapports / f"{essai.cle}-{essai.result_fingerprint[:CLE]}.json"
            chemin.write_text(
                json.dumps(rapport, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
            artefact = chemin.relative_to(self.racine).as_posix()
        essai = essai.avec_rapport(artefact, self._ecrire_serie(essai, serie))
        with self.fichier.open("a", encoding="utf-8", newline="\n") as flux:
            flux.write(essai.ligne() + "\n")
        return essai

    def _ecrire_serie(self, essai: Essai, serie: DailySeries | None) -> str | None:
        """Ecrit la serie quotidienne a cote du rapport, et rend son chemin.

        Pourquoi un `.npz` et non du JSON, contrairement au registre : ce sont
        des milliers de flottants que personne ne relit ni ne fusionne a la
        main. Le registre est en JSONL parce qu'un `git diff` doit y rester
        lisible ; ici il n'y a rien a lire, et le binaire compresse garde les
        flottants au bit pres la ou un texte imposerait de choisir un format.

        Pourquoi la serie QUOTIDIENNE et pas celle des barres : elle est deja
        agregee au jour par `to_daily`, donc un run a la minute et un run
        quotidien produisent des series de meme nature. Aucun
        reechantillonnage n'a a etre invente pour les rapprocher - et c'est
        celle dont sort le `sharpe_per_period`, donc celle qui explique la
        variance des essais.
        """
        if serie is None:
            return None
        self.series.mkdir(parents=True, exist_ok=True)
        chemin = self.series / f"{essai.cle}-{essai.result_fingerprint[:CLE]}.npz"
        np.savez_compressed(
            chemin,
            ts=np.asarray(serie.ts, dtype=np.int64),
            returns=np.asarray(serie.returns, dtype=np.float64),
        )
        return chemin.relative_to(self.racine).as_posix()

    def describe(self) -> SpecDict:
        journal = self.journal()
        return {
            "n_lignes": len(self.essais()),
            "n_trials": journal.n_trials,
            "variance_of_sharpes": journal.variance_of_sharpes,
            "n_divergences": len(self.divergences()),
            "n_doublons": len(self.doublons()),
        }


def _lire(chemin: Path) -> Iterator[Essai]:
    """Lit le registre ligne a ligne. Une ligne fautive est NOMMEE.

    Un JSONL corrompu au milieu ne doit pas se solder par « quelque chose ne va
    pas dans le registre » : le numero de ligne est ce qui permet de le
    reparer a la main, et un registre append-only se repare a la main.
    """
    with chemin.open(encoding="utf-8") as flux:
        for numero, ligne in enumerate(flux, start=1):
            texte = ligne.strip()
            if not texte:
                continue
            try:
                yield Essai.depuis_ligne(texte)
            except (json.JSONDecodeError, TypeError, ValueError) as erreur:
                raise ConfigurationError(
                    f"{chemin}:{numero} : ligne illisible ({erreur})"
                ) from erreur


def registre_par_defaut(racine: Path | None = None) -> Registre:
    """Le registre du depot : `essais/` a la racine du projet.

    Un chemin RELATIF au repertoire courant, comme `runs/` et `schemas/` : le
    depot est l'unite, et un chemin absolu rendrait le registre propre a une
    machine.
    """
    return Registre(racine=DOSSIER if racine is None else racine)
