---
type: experiment
updated: 2026-09-10
statut: termine
verdict: non-conclusif
strategie: sma_crossover@1
instruments: [ES.v.0]
essais: 8
---

# Deflated Sharpe du meilleur essai — grille SMA, 8 essais

> Page seminale : chiffres repris de [README.md](../../README.md) au moment de
> la mise en place du wiki (2026-09-10). Non reproduits ici.

## Hypothese

Le meilleur essai d'une grille SMA sur ES quotidien survit-il a la correction
pour le nombre d'essais, c'est-a-dire : est-il distinguable du maximum qu'on
attendrait d'une grille de cette taille sous l'hypothese nulle ?

## Montage

- Strategie : `sma_crossover@1`, meilleur essai SMA 5/20 sur ES quotidien
- Echantillon : 2731 observations
- Grille : **8 essais**, enregistres par `TrialLog` au moment ou ils sont faits
- Calcul : [src/rsl/metrics/statistics.py](../../src/rsl/metrics/statistics.py)

## Resultat

```
=== DEFLATED SHARPE du meilleur essai (SMA 5/20 sur ES quotidien) ===
Sharpe observe (par periode)  0.0560
Maximum attendu sous H0       0.0158 (8 essai(s), variance 0.00012)
PSR (contre zero)             0.9981
DSR (contre le maximum)       0.9810  SIGNIFICATIF
Moments                       asymetrie -0.258, kurtosis 11.712, 2731 observations
```

## Lecture

- Le DSR ressort `SIGNIFICATIF`, et **ca ne veut presque rien dire ici** : huit
  essais est une grille minuscule. Le maximum attendu sous H0 croit avec le
  nombre d'essais ; a quelques centaines d'essais, le meme Sharpe de 0,0560
  n'y survivrait pas. C'est exactement la demonstration que le DSR sert a faire,
  pas un feu vert.
- **Le chiffre n'est valide que si le compteur est honnete.** Tout essai fait et
  non enregistre gonfle mecaniquement le DSR. C'est la raison pour laquelle
  l'unite de travail de ce wiki est l'essai : une page `experiments/` = une ligne
  du compteur.
- **Kurtosis 11,7** sur 2731 observations : queues tres epaisses. Le PSR et le
  DSR tiennent compte des moments d'ordre 3 et 4, ce qui est precisement
  pourquoi il ne faut pas lire le Sharpe brut a cote.
- Le meme essai, decoupe en fenetres, concentre 57 % de son resultat sur un pli
  unique : voir [[experiments/sma-es-daily-walkforward]]. Les deux pages
  decrivent la meme strategie et disent la meme chose par deux chemins.

## Verdict

`non-conclusif` — le mecanisme fonctionne, la conclusion statistique n'a pas de
portee a 8 essais. Ce qui manque pour trancher : une grille d'au moins quelques
centaines d'essais, et PBO / CSCV, aujourd'hui au stade de protocole seulement
(idees en attente du [[Failed Ideas/ledger]]).

## Liens

[[concepts/deflated-sharpe-ratio]] · [[concepts/walk-forward]] ·
[[experiments/sma-es-daily-walkforward]] ·
[[research/bailey-lopez-de-prado-dsr]] · [[lessons]]
