---
type: reference
updated: 2026-09-15
autorite: src/rsl/controles.py
---

# `rsl check` — ce que le vocabulaire ne dit pas de lui-meme

> Page **routeur**. L'autorite est
> [src/rsl/controles.py](../../src/rsl/controles.py) et ses tests,
> [tests/unit/test_controles.py](../../tests/unit/test_controles.py).
> La liste des controles ci-dessous vieillira ; le module non.

```
rsl check STRATEGIE --settings REGLAGES [--symbol NQ.v.0]
```

Code de sortie **2** des qu'un constat est de gravite `ERREUR`, comme
`rsl verify`. Un script d'integration peut donc refuser de lancer le run.

## Le probleme qu'elle resout

Le 2026-09-15, la replication de Zarattini a coute une matinee. Trois des cinq
ecarts venaient du meme defaut, qui n'est ni un bug du moteur ni une
negligence de lecture :

> **Plusieurs termes du vocabulaire ont un NOM qui promet plus que leur
> DEFINITION ne livre.**

| Terme | Ce que le nom dit | Ce que la definition fait |
|---|---|---|
| `session.is_last` | la derniere barre de la seance | la **premiere barre a atteindre l'heure de fermeture DECLAREE** |
| `rolling.rank` | un rang | un rang **temporel**, dans sa propre fenetre — jamais transversal |
| `session.minutes_from_open` | minutes depuis l'ouverture | parcourt **1..N**, ne vaut **jamais zero** |
| `vol_target.vol_window` | fenetre de volatilite | comptee en **BARRES** — sur du 1 min, une volatilite par minute |

Chacun est correct, documente et teste. Chacun est un piege pour qui ecrit une
specification en lisant les noms.

## Pourquoi on ne renomme pas

La tentation est de rebaptiser `is_last`. **C'est impossible**, et la raison
vaut d'etre retenue :

> « La derniere barre de la seance » est un fait **FUTUR**. Pour savoir que la
> barre `i` est la derniere, il faut regarder la barre `i+1`.

Le champ ne peut donc pas tenir la promesse de son nom. Ce n'est pas un
accident de nommage : c'est la garantie anti-look-ahead qui remonte a la
surface. Le socle donne ce qu'il peut donner causalement.

Corollaire : **le vocabulaire n'est pas trop complexe, il est trop
implicite**. Le simplifier cacherait ces definitions derriere des noms plus
avenants, donc plus trompeurs. Le remede est de le rendre BAVARD au bon
moment, pas plus simple.

## Les six controles

| Code | Gravite | Ce qu'il attrape |
|---|---|---|
| `is_last-absent` | **erreur** | une regle cite `is_last` et des seances de l'echantillon n'en portent aucune |
| `minutes-jamais-nulles` | **erreur** | `minutes_from_open` compare a zero : la regle ne declenchera jamais |
| `fill-de-nuit` | avertissement | une SORTIE a la derniere barre, sans `max_fill_gap_seconds` : le fill tombe la seance suivante |
| `vol-target-en-barres` | avertissement | `vol_target` sur des barres intra-journalieres |
| `seance-electronique` | avertissement | une `session` declaree sans `session_only` |
| `rank-temporel` | note | `rolling.rank` employe comme s'il classait des instruments |

Chaque constat porte un **remede**. Ce n'est pas decoratif : un constat sans
geste a faire se lit deux fois puis s'ignore. C'est la regle que le ledger
impose aux idees abandonnees, appliquee aux avertissements.

## Ce qu'elle donne sur Zarattini

**1,7 seconde**, code de sortie 2, et les deux defauts qui avaient coute la
matinee :

```
ERR  [is_last-absent] exit_long, exit_short cite `session.is_last`, mais
     90 seance(s) sur 2748 (3.3 %) n'en portent AUCUNE.
ATTN [fill-de-nuit]   exit_long, exit_short sort sur la derniere barre ;
     avec `lag_bars: 1`, l'ordre se remplira la seance d'apres.
```

## Ce qu'elle n'est pas, et ne sera pas

- **Pas un validateur.** Ce qui est invalide LEVE deja, par pydantic et par le
  JSON Schema. Ces controles portent sur des specifications **valides** dont
  les termes ne veulent pas dire ce que leur nom suggere.
- **Pas un refus.** Elle ne modifie aucun run et n'en casse aucun. La variante
  « faire refuser le moteur pendant le run » a ete ecartee — voir le ledger,
  2026-09-15.
- **Pas exhaustive.** Elle ne connait que les pieges DEJA payes. Chaque
  nouveau controle doit citer la trace datee qui l'a motive, sinon il decrit
  une peur et non un fait.

## Ce qu'elle ne peut pas attraper

Un backtest est une phrase conditionnelle : *« si le monde fonctionnait comme
votre specification, voici ce qui se serait passe. »* Le moteur garantit la
seconde moitie. Personne ne peut garantir la premiere, parce que l'intention
n'est pas dans les donnees.

`rsl check` reduit l'ecart entre ce qu'on a ecrit et ce qu'on voulait ecrire,
la ou cet ecart a deja coute quelque chose. Elle ne le supprime pas.

Voir aussi : [[reference/silences]] (les memes defauts, mesures APRES le run) ·
[[reference/cli]] · [[lessons]] L37 ·
[[experiments/zarattini-nq-intraday-60-30]]
