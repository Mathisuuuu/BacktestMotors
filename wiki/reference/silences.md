---
type: reference
updated: 2026-09-15
autorite: src/rsl/metrics/silences.py
---

# Les silences — ce qui se passait sans que le rapport le dise

> Page **routeur**. L'autorite est
> [src/rsl/metrics/silences.py](../../src/rsl/metrics/silences.py) pour les deux
> mesures de seance, et
> [src/rsl/engine/risk.py](../../src/rsl/engine/risk.py) (`RiskStats.perte_par_troncature`)
> pour la troisieme. Les chiffres cites ici datent du jour ou ils ont ete
> mesures et ne se mettent pas a jour tout seuls.

## D'ou ils viennent

La replication de Zarattini 60/30/1,5 le 2026-09-15 a rendu un Sharpe de 0,99
contre 1,472 annonce. **Cinq ecarts** ont ete trouves en trois heures. Deux
etaient deja imprimes au rapport — `dropped_sizing` et `reduce_only_dropped` —
et ont pris quelques minutes chacun. Les trois autres etaient silencieux, et
ont pris le reste de la matinee.

C'est la quatrieme occurrence de la meme famille — [[lessons]] L18, L25, L28,
L30 : **un defaut qui produit un nombre parfaitement lisible**. Le remede a
chaque fois a ete le meme, et il est ici generalise.

## Les trois mesures

| Mesure | Ce qu'elle attrape | Se tait quand |
|---|---|---|
| **franchissements de nuit** | un fill execute dans une AUTRE seance que la barre qui l'a decide | aucun franchissement, ou aucune seance declaree |
| **seances sans cloture** | une seance dont aucune barre ne porte `is_last` | toutes les seances en ont une |
| **perte par troncature** | l'exposition supprimee par l'arrondi aux contrats entiers | aucune regle qui divise n'a repondu |

Le seuil est **zero** pour les deux premieres. Un seul franchissement de nuit
sur une strategie qui se declare intraday est deja une contradiction, et une
seule seance sans cloture forcee suffit a laisser une position ouverte.

## Ce que chacune a trouve sur Zarattini

- **17 sorties sur 1 846 fills remplies apres un gap de nuit (0,9 %).**
  `exit == is_last` decide a la derniere barre de seance ; avec `lag_bars: 1`
  et `session_only`, la barre suivante est la premiere du LENDEMAIN. Gap subi :
  **31,00 points de moyenne, 14,00 de mediane, 179,00 au maximum** — contre
  0,280 sur une barre ordinaire. Ordre de grandeur de l'exposition nocturne
  subie : ~14 500 $ sur 312 445 $ de profit, soit **4,6 %**.

  **Le compteur a corrige son auteur des sa premiere execution.** J'avais
  annonce 2 658 franchissements : j'avais mesure le gap sur les 2 658 dernieres
  barres de seance en SUPPOSANT qu'une position y etait ouverte. Elle ne l'est
  que 17 fois — la quasi-totalite des trades sort avant la fin de seance, sur
  la bande opposee ou le VWAP. C'est exactement ce pour quoi le compteur
  existe : un proxy plausible avait remplace la mesure.
- **90 seances sur 2 748 sans aucune cloture forcee.** Les demi-journees
  (13:00 x68, 13:15 x21, 13:01 x1) s'arretent avant la fermeture DECLAREE.
- **26,4 % d'exposition supprimee par la troncature**, dont **271 seances
  entierement muettes**, concentrees sur 2020, 2022 et 2025.

**Aucune de ces trois n'est un bug du moteur.** `lag_bars: 1` est normatif
(`docs/execution-model.md` §2.1), l'absence de `is_last` sur une seance
ecourtee est documentee et voulue dans
[session.py](../../src/rsl/data/session.py), et un contrat est entier. Ce sont
des consequences de la SPECIFICATION, qui etaient invisibles.

## Ou elles vivent, et pourquoi pas ailleurs

**Hors de `result_fingerprint`**, qui ne hache que `counters` et `portfolio`.
Ce sont des diagnostics : ils decrivent un run, ils ne le definissent pas. Les y
inclure aurait change les sept empreintes archivees sans qu'aucun comportement
ne change — ce qui s'etait deja produit trois fois avec `intraday_margin_ratio`,
`events` et `session_only`, rattrape chaque fois par un depouilleur de
canonicalisation.

Meme place, et meme raison, que `attribution_horaire`.

La troisieme fait exception : elle vit dans `RiskStats`, parce qu'elle a besoin
de la taille AVANT troncature, qui n'existe qu'a l'instant du dimensionnement.
`RiskStats` est lui aussi hors empreinte. Chaque regle qui DIVISE expose
desormais `taille_brute` ; `FixedContracts` ne l'expose pas, ce qui permet de
distinguer « aucune perte » de « regle qui ne sait pas repondre ».

## Ce qu'elles ne font pas

- Elles **ne corrigent rien**. Un franchissement de nuit signale reste un
  franchissement de nuit ; c'est a la specification de poser
  `max_fill_gap_seconds` ou de sortir une barre plus tot.
- Le gap des franchissements **n'est pas signe**. Une exposition nocturne subie
  est favorable une fois sur deux ; ce qu'elle coute a coup sur est de la
  VOLATILITE, donc du Sharpe.
- Sur plusieurs instruments, les seances sans cloture sont **agregees**. Chacun
  porte son propre calendrier, et un compte par symbole rendrait la ligne
  illisible sans rien apprendre.

Voir aussi : [[experiments/zarattini-nq-intraday-60-30]] · [[lessons]] L35 ·
[[reference/seances]]
