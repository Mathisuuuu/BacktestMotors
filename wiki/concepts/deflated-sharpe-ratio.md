---
type: concept
updated: 2026-09-12
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
- Registre DURABLE : [src/rsl/essais.py](../../src/rsl/essais.py) et
  [essais/registre.jsonl](../../essais/registre.jsonl), versionne. `rsl run
  --archive` y ajoute l'essai et calcule le DSR contre TOUS les precedents ;
  `rsl essais` montre ce que le compteur contient.

> **Jusqu'au 2026-09-12, ce compteur ne comptait rien.** `TrialLog` vivait dans
> un processus, et `rsl run` en creait un neuf : chaque run se declarait « 1
> essai », donc son DSR se confondait avec son PSR. Tous les DSR publies avant
> cette date sont des PSR deguises, quel que soit le nombre d'essais reellement
> faits. Le `SIGNIFICATIF` de la paire ES/NQ passe de 0,9722 a 0,9546 une fois
> compte au troisieme rang ([[experiments/paire-es-nq-retour-a-la-moyenne]]).
- Le pas d'annualisation est **mesure sur l'echantillon**, jamais suppose —
  voir la ligne correspondante du [[Failed Ideas/ledger]].

## Ce que le registre refuse de faire a votre place

Trois decisions lui sont deliberement interdites, parce que chacune est un
jugement et qu'un compteur qui juge cesse d'etre un compteur :

- **Rejouer n'est pas essayer.** Deux runs de la meme specification comptent
  pour un. Punir la reproductibilite serait contraire au but du socle. La cle
  est le `config_hash`.
- **Une empreinte qui change a `config_hash` constant** n'est pas un doublon :
  le moteur a change, et les chiffres d'avant et d'apres ne se comparent plus.
  Le registre garde les deux lignes et le SIGNALE, au lieu de choisir.
- **Un meme resultat sous deux specifications** gonfle le compteur d'un essai
  qui n'en est peut-etre pas un. Signale aussi, jamais corrige d'office —
  decider que deux ecritures sont « la meme idee » n'appartient pas a la
  machine. Et le signal est SUFFISANT, jamais necessaire : il ne voit que les
  resultats bit-identiques.

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
