"""Separer la STRATEGIE de ce sur quoi on la fait tourner.

Le probleme
-----------
Une `BacktestSpec` melange deux choses de nature differente :

- **la decision** : `strategy`, c'est-a-dire les regles. Elle ne depend ni de
  l'instrument, ni du capital, ni des frais ;
- **le montage** : `data`, `initial_cash`, `execution`, `risk`... Ce sont des
  choix d'execution, pas de strategie.

Les melanger a une consequence pratique : une meme strategie appliquee a ES et
a NQ demande deux fichiers presque identiques, et rien ne dit lequel des deux
mots a change. Une strategie n'est pas « SMA sur ES avec 1 M et 2 ticks de
slippage » ; c'est « SMA », que l'on fait tourner sur ES avec 1 M.

La separation
-------------
Un fichier de STRATEGIE ne porte que la decision. Le reste est choisi au
moment du run - par la fenetre de `rsl gui`, ou par les options de
`rsl run`. `compose()` recolle les deux.

Ce que la separation ne change PAS
-----------------------------------
**Le `config_hash` porte toujours sur le tout.** C'est le point non
negociable : deux runs de la meme strategie avec des capitaux differents sont
deux runs differents, et leurs empreintes de configuration doivent differer.
`compose()` construit une `BacktestSpec` complete, qui reste ce qui est hache
et archive. La separation est une commodite d'ECRITURE, jamais un relachement
de la reproductibilite.

`BacktestSpec` reste donc la source unique de ce qu'est un run : `compose()`
ne redeclare aucun champ, il valide le dictionnaire de reglages PAR elle. Une
option mal orthographiee est refusee par le meme `extra="forbid"` que partout
ailleurs.

Le symbole, et pourquoi il n'est pas dans le fichier de strategie
------------------------------------------------------------------
`rules@1`, `panel_rules@1`, `buy_and_hold@1` et `sma_crossover@1` exigent un
`symbol` dans leurs parametres. C'est justement ce qui empechait d'appliquer
une strategie a un autre actif sans reecrire le fichier.

`compose()` l'INJECTE : le fichier de strategie ne le porte pas, l'instrument
choisi le fournit. Les moules qui n'ont pas de champ `symbol` - `ranking@1`,
`multi_rules@1`, `cross_sectional_momentum@1` - travaillent sur un univers
entier et n'en recoivent aucun.

La detection se fait sur le MODELE DE PARAMETRES du moule, jamais sur une
liste de noms tenue a la main : un moule publie demain sera traite juste sans
que ce fichier soit touche.

Un couplage qui ne se reduit pas, et qu'il faut dire
-----------------------------------------------------
`multi_rules@1` associe un jeu de regles A CHAQUE symbole : ses `books` sont
indexes par symbole. Le choix des instruments fait donc partie de sa
decision, et aucune injection ne peut l'en sortir. Une strategie
`multi_rules@1` reste liee a ses instruments - c'est une propriete de ce
moule, pas une limite de la separation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal

from pydantic import Field

from rsl.config import BacktestSpec, SpecDict, StrategySpec, StrictModel
from rsl.errors import ConfigurationError
from rsl.strategies.base import get_strategy

FORMAT: Final[str] = "rsl-strategy@1"


class StrategyFile(StrictModel):
    """Une strategie SEULE : la decision, et rien d'autre.

    Deliberement pauvre. Tout ce qui n'est pas une regle - l'instrument, le
    capital, les frais, le dimensionnement - est un choix de run, pas de
    strategie, et se declare ailleurs.

    `format` est obligatoire et vaut une constante : c'est ce qui permet de
    distinguer sans ambiguite un fichier de strategie d'une `BacktestSpec`
    complete. Deviner d'apres les champs presents marcherait presque toujours,
    et c'est le « presque » qui coute.
    """

    format: Literal["rsl-strategy@1"]
    name: str = Field(min_length=1)
    strategy: StrategySpec

    @staticmethod
    def parse(texte: str) -> StrategyFile:
        return StrategyFile.model_validate_json(texte)


def est_fichier_de_strategie(charge: Mapping[str, object]) -> bool:
    """Vrai si ce document est une strategie seule et non un run complet."""
    return charge.get("format") == FORMAT


def attend_un_symbole(ref: str) -> bool:
    """Ce moule travaille-t-il sur UN instrument nomme ?

    Lu sur le modele de parametres du moule, jamais sur une liste de noms : un
    moule publie demain est traite juste sans que ce fichier soit modifie.
    """
    nom, _, version = ref.partition("@")
    entree = get_strategy(nom, int(version) if version else None)
    return "symbol" in entree.params_model.model_fields


def compose(
    strategie: StrategyFile,
    reglages: Mapping[str, object],
    *,
    symbol: str | None = None,
) -> BacktestSpec:
    """Recolle une strategie et son montage en une `BacktestSpec` complete.

    `reglages` est valide PAR `BacktestSpec` : aucun champ n'est redeclare
    ici, donc rien ne peut diverger d'elle. Une option inconnue est refusee
    par le meme `extra="forbid"` que partout ailleurs.

    `symbol` n'est utilise que si le moule en attend un. Le passer a un moule
    transversal est une erreur, pas un silence : se tromper d'instrument sur
    un classement d'univers ne doit pas s'ignorer.
    """
    for interdit in ("name", "strategy"):
        if interdit in reglages:
            raise ConfigurationError(
                f"'{interdit}' vient du fichier de strategie, pas des reglages "
                f"du run. Le laisser ici ferait exister deux sources pour la "
                f"meme chose."
            )

    params: SpecDict = dict(strategie.strategy.params)
    if attend_un_symbole(strategie.strategy.ref):
        if symbol is None:
            raise ConfigurationError(
                f"'{strategie.strategy.ref}' negocie UN instrument : il faut en "
                f"choisir un. C'est le role des reglages du run, pas du fichier "
                f"de strategie."
            )
        if "symbol" in params:
            raise ConfigurationError(
                "le fichier de strategie nomme deja un `symbol` : il n'est donc "
                "pas applicable a un autre actif, ce qui est tout l'interet de "
                "la separation. Retirez-le."
            )
        params["symbol"] = symbol
    elif symbol is not None:
        raise ConfigurationError(
            f"'{strategie.strategy.ref}' travaille sur un UNIVERS : elle ne "
            f"prend pas d'instrument unique. Declarez-les tous dans `data`."
        )

    charge: dict[str, Any] = {
        **reglages,
        "name": strategie.name,
        "strategy": {"ref": strategie.strategy.ref, "params": params},
    }
    return BacktestSpec.model_validate(charge)
