---
type: concept
updated: 2026-09-10
statut: stable
alias: [DSR, PSR, compteur d'essais, TrialLog]
---

# Deflated Sharpe Ratio

## Definition

Un Sharpe isole ne dit pas s'il vaut quelque chose. Essayer assez de
configurations sur un echantillon fixe finit toujours par en produire une qui
brille : **le maximum d'un ensemble de tirages n'est pas un tirage.** Le DSR
corrige le Sharpe observe par ce qu'on devrait attendre du meilleur essai sous
l'hypothese nulle, compte tenu du nombre d'essais et de leur dispersion.

Deux quantites a ne pas confondre :

- **PSR** — probabilite que le Sharpe vrai soit superieur a zero.
- **DSR** — probabilite qu'il soit superieur au **maximum attendu sous H0**.
  C'est le seul des deux qui tient compte du nombre d'essais.

## Dans ce depot

- Calcul : [src/rsl/metrics/statistics.py](../../src/rsl/metrics/statistics.py)
- `TrialLog` enregistre chaque essai **au moment ou il est fait**, et fournit au
  DSR les deux entrees qu'aucun backtest isole ne connait : le nombre d'essais
  et leur dispersion.
- Le pas d'annualisation est **mesure sur l'echantillon**, jamais suppose —
  voir la ligne correspondante du [[Failed Ideas/ledger]].

## Pourquoi ca compte

Le compteur d'essais n'a de valeur que s'il est tenu honnetement et en continu.
Un essai non enregistre gonfle mecaniquement le DSR de tous les autres. C'est
la raison pour laquelle l'unite de travail de ce wiki est **l'essai** et non le
« projet » : chaque page `experiments/` est une ligne du compteur.

Ordre de grandeur a garder en tete : huit essais est une grille minuscule. Une
vraie recherche en compte des centaines, et le meme Sharpe n'y survivrait pas —
c'est precisement ce que le DSR sert a montrer.

## Liens

[[concepts/walk-forward]] · [[experiments/dsr-grille-sma-8-essais]] ·
[[research/bailey-lopez-de-prado-dsr]] · [[lessons]]
