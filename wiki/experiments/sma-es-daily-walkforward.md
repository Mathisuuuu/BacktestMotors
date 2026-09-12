---
type: experiment
updated: 2026-09-12
statut: termine
verdict: fragile
strategie: sma_crossover@1
instruments: [ES.v.0]
essais: 1
---

# SMA croisement sur ES quotidien — walk-forward 9 plis

> Page seminale : les chiffres etaient repris du run documente dans
> [README.md](../../README.md) au moment de la mise en place du wiki
> (2026-09-10), pas d'une execution faite depuis ce wiki.
>
> **Reproduits et ARCHIVES le 2026-09-12** : les neuf plis sortent identiques,
> et l'essai figure desormais dans
> [essais/registre.jsonl](../../essais/registre.jsonl) sous la cle
> `95a3e8d456d0`, avec son rapport complet. Il compte pour **UN** essai au
> Deflated Sharpe, pas neuf — un pli est la meme configuration sur d'autres
> donnees, pas une configuration de plus.

## Le Sharpe agrege, et ce qu'il n'etait pas

Cette page parlait d'un « Sharpe 0,60 agrege » sans dire de quoi il etait
l'agregat. Depuis le 2026-09-12, le rapport publie la serie **groupee** - les
rendements hors echantillon des neuf plis mis bout a bout - et c'est elle qui
porte le chiffre : **0,0391 par periode**, soit environ 0,62 annualise sur
2241 observations.

L'ecart avec la moyenne des Sharpe par pli n'est pas anecdotique : **0,32**.
Une moyenne par pli donne le meme poids a un pli qui a negocie une fois et a un
pli qui a negocie tout du long ; la serie groupee, non. C'est la seconde qui
repond a « qu'aurait obtenu quelqu'un qui aurait applique la strategie a chaque
epoque ».

## Hypothese

Le Sharpe de 0,60 mesure sur l'echantillon entier decrit-il une performance
**repartie** dans le temps, ou une performance **concentree** sur quelques
fenetres ?

## Montage

- Config : [examples/strategies/sma_es_daily.json](../../examples/strategies/sma_es_daily.json)
- Donnees : `ES.v.0`, reechantillonne au quotidien, 2753 barres / 10,65 ans,
  258,6 periodes/an **mesurees**
- Commande : `rsl walkforward examples/strategies/sma_es_daily.json --settings examples/reglages/sma_es_daily.json --symbol ES.v.0 --train 500 --test 250`

## Resultat

```
  pli  0  barres    500-750    rendement   -0.54 %  Sharpe -0.26  DD -2.8 %  1 trades  expo 41.2 %
  pli  1  barres    750-1000   rendement   -0.05 %  Sharpe +0.00  DD -2.8 %  2 trades  expo 59.6 %
  pli  2  barres   1000-1250   rendement   -1.12 %  Sharpe -0.62  DD -2.1 %  1 trades  expo  2.0 %
  pli  3  barres   1250-1500   rendement   +0.00 %  Sharpe   n/d  DD +0.0 %  0 trades  expo  0.0 %
  pli  4  barres   1500-1750   rendement   -1.38 %  Sharpe -1.39  DD -1.5 %  1 trades  expo  1.6 %
  pli  5  barres   1750-2000   rendement   +0.86 %  Sharpe +0.27  DD -2.8 %  2 trades  expo 51.6 %
  pli  6  barres   2000-2250   rendement  +10.80 %  Sharpe +1.90  DD -4.6 %  1 trades  expo 82.8 %
  pli  7  barres   2250-2500   rendement   +5.51 %  Sharpe +1.68  DD -1.7 %  1 trades  expo 28.8 %
  pli  8  barres   2500-2750   rendement   +5.03 %  Sharpe +0.95  DD -3.6 %  1 trades  expo 34.4 %
------------------------------------------------------------------------------
Sharpe       moyen 0.32   median 0.13   dispersion 1.13
Plis         9 au total, +44.44 % positifs
Concentration 57 % du resultat vient d'un seul pli
```

Pour memoire, la meme strategie sur l'echantillon entier : **Sharpe 0,60**.

## Lecture

- **La concentration est le seul chiffre qui tranche.** 57 % du resultat vient
  d'un pli ; le Sharpe agrege de 0,60 ne le montre pas. Les deux mesures portent
  sur le meme backtest.
- **Le nombre de trades est minuscule** : 1 a 2 par pli, un pli a zero. Un
  Sharpe de +1,90 calcule sur un trade n'est pas une estimation de competence.
- **Ce decoupage ne valide rien hors echantillon.** Le runner n'optimise rien,
  donc la fenetre `train` n'est qu'un historique de chauffe : les plis ne sont
  pas des tests out-of-sample au sens usuel. Voir [[concepts/walk-forward]].
- **Non reproduit depuis ce wiki** : les chiffres viennent du README. Tant qu'un
  run n'a pas ete relance avec son manifeste et son empreinte archives, cette
  page est un releve, pas une mesure. Elle reste bloquee par l'absence du paquet
  `rsl.data` — voir [[reference/donnees]].
- Les donnees `.v.0` ne sont pas ajustees au roulement, ce qui pese surtout sur
  un buy & hold mais contamine aussi l'interpretation de l'exposition.

## Verdict

`fragile` — non pas rejete : la strategie n'est pas la cible, elle sert de
support de verification du socle. Comme resultat de recherche, elle ne tient
pas : trop peu de trades, resultat concentre sur une fenetre.

## Liens

[[concepts/walk-forward]] · [[concepts/deflated-sharpe-ratio]] ·
[[experiments/dsr-grille-sma-8-essais]] · [[reference/donnees]] · [[lessons]]
