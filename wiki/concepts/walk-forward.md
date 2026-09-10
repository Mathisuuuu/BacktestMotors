---
type: concept
updated: 2026-09-10
statut: stable
alias: [plis, folds, decoupage ancre, decoupage glissant]
---

# Walk-forward

## Definition

Evaluer une strategie sur des fenetres successives plutot que sur l'echantillon
entier, pour distinguer une performance **repartie** d'une performance
**concentree**. Un chiffre agrege ne fait pas cette difference ; c'est tout
l'interet du decoupage.

Chaque pli repart du capital initial et est liquide a sa derniere barre. Sans
cela, le rendement d'un pli contiendrait un profit latent que le pli suivant
n'herite pas.

## Dans ce depot

- Implementation : [src/rsl/walkforward.py](../../src/rsl/walkforward.py)
- Commande : `rsl walkforward CONFIG --train N --test N`

**Ce runner n'optimise rien.** La fenetre `train` sert d'HISTORIQUE — la
strategie la traverse pour remplir ses fenetres glissantes, sans negocier.
L'optimisation de parametres est hors du perimetre de la phase actuelle.

Consequence a ne pas masquer : tant que rien n'est optimise, decoupage ancre et
decoupage glissant produisent exactement les memes plis, et un test verifie
cette egalite. Voir la ligne correspondante du [[Failed Ideas/ledger]].

## Pourquoi ca compte

Sur l'exemple de reference — SMA sur ES quotidien — la strategie affiche un
Sharpe de 0,60 sur l'echantillon entier. Decoupee en neuf fenetres, elle est
positive dans quatre, et **57 % de son resultat vient d'un seul pli**. Les deux
mesures decrivent le meme backtest ; une seule des deux permet de decider.

## Liens

[[concepts/deflated-sharpe-ratio]] ·
[[experiments/sma-es-daily-walkforward]] · [[reference/cli]]
