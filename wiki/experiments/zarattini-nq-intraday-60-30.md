---
type: experiment
updated: 2026-09-13
statut: termine
verdict: negatif
strategie: rules@1
instruments: [NQ.v.0]
essais: 3
---

# Zarattini NQ intraday 60/30/1.5 — deux essais, dont un rate

> **Le premier run rendait -25,62 %, le second +111,53 %, sur la MEME
> strategie.** Seul le capital changeait. Et le second, une fois compte contre
> les 495 essais du registre, n'est pas significatif non plus.

## Hypothese

La strategie de rupture de bande semi-horaire de Zarattini/Delgado, portee au
vocabulaire declaratif : entrer a l'un des douze points de controle
semi-horaires quand le cours casse `max(ouverture, cloture de la veille)` de
`1.5 x sigma[tau]` ET se tient du bon cote du VWAP ancre a la seance ; sortir
sur la bande opposee, sur le VWAP, ou a la cloture. Aucune position ne franchit
la nuit.

`sigma[tau]` est la moyenne sur 60 seances de `|cloture[t-j, tau] / ouverture[t-j] - 1|`,
prise au meme rang de seance.

## Protocole

| | |
|---|---|
| echantillon | NQ.v.0, 3 705 199 barres d'une minute, 10,59 ans (2016-01 a 2026-08) |
| seance declaree | 09:30-16:00 America/New_York |
| dimensionnement | `vol_target` 0,02 par barre, `vol_max_multiple` 4,0 |
| plafond | `max_gross_contracts` 4 |
| couts | frais par contrat, slippage 0,5 tick, `execution_lag` 1 barre |
| duree du run | **15 min 55 s** (mesure, pas estimee — [[lessons]] L27) |

Deux runs, identiques sauf `initial_cash`.

## Resultat

| | 100 000 | 500 000 |
|---|---|---|
| rendement total | **-25,62 %** | **+111,53 %** |
| CAGR | -2,76 % | +7,33 % |
| Sharpe | -0,31 | 0,83 |
| trades | **2** | **1 241** |
| exposition | 0,0000057 | 4,51 % |
| ordres soumis | 5 084 | 2 482 |
| **rejetes pour marge** | **5 080** | **0** |
| fills | 4 | 2 482 |

## Ce que le premier run mesurait vraiment

Rien. La marge initiale de NQ est 27 000 ; le facteur `vol_target` sature a
`vol_max_multiple` = 4, donc la strategie demande 4 contrats, soit **108 000 de
marge sur un compte de 100 000**. Chaque entree est refusee. Les deux seules
passees l'ont ete a 3 contrats, et leurs pertes — 12 808 chacune — SONT le
-25,62 % affiche.

La regle, elle, fonctionnait deja : mesuree sur 120 000 barres contigues,
`entry_long` est vraie 94 fois, soit environ une par seance. Le blocage etait
en aval, purement arithmetique, et **le resume imprime ne le disait pas** —
seul `risk_stats.n_rejected_margin` dans le JSON le revelait. Troisieme
occurrence de la famille [[lessons]] L18 / L25 / L28.

## Ce que le second ne mesure pas non plus

Le rapport publie `DSR 0,9981 SIGNIFICATIF`, avec un avertissement : un seul
essai compte. Recalcule contre le registre entier :

| | rapport | registre |
|---|---|---|
| essais comptes | 1 | **495** |
| variance des Sharpe essayes | 0 | 0,000478 |
| Sharpe observe par periode | 0,0469 | 0,0469 |
| maximum attendu sous H0 | 0,0000 | **0,0667** |
| PSR (contre zero) | 0,9981 | 0,9981 |
| **DSR** | **0,9981 SIGNIFICATIF** | **0,1107 NON significatif** |

Le Sharpe observe est **inferieur** au maximum qu'on attendrait par pure chance
apres 495 essais. Un Sharpe de 0,83 annualise sur dix ans ne suffit pas a
distinguer cette strategie du meilleur tirage d'un jeu de 495.

Reserve honnete, deja consignee en [[lessons]] L23 : les 495 essais sont tres
largement des variantes correlees d'une grille SMA, et le DSR suppose des
essais independants. La correction appliquee ici n'est donc pas la bonne
correction — elle est seulement la seule qu'on sache calculer.

## Troisieme essai : `sigma` ancre sur la seance (2026-09-13)

Le defaut decrit plus bas a ete corrige. `sigma[tau]` est reecrit avec
`rolling.across: "sessions"` et `session_lag`, qui retrouvent le meme RANG par
le calendrier declare au lieu de supposer 390 barres par seance.

| | `stride: 390` | ancre sur la seance |
|---|---|---|
| rendement total | +111,53 % | **+256,80 %** |
| CAGR | +7,33 % | **+13,00 %** |
| Sharpe | 0,83 | **1,26** |
| Sortino | 1,51 | 2,31 |
| drawdown quotidien | -14,21 % | -16,98 % |
| trades | 1 241 | **2 067** |
| exposition | 4,51 % | **11,98 %** |
| taux de reussite | 44,64 % | 38,17 % |
| profit factor | 1,233 | 1,314 |
| ordres / fills | 2 482 / 2 482 | 4 134 / 4 134 |

### Pourquoi la strategie negocie deux fois plus

Le nouveau `sigma` est **plus petit dans 82,5 % des cas**, de 25,4 % en
mediane. Le mecanisme est direct : un pas de 390 barres dans une seance qui en
compte 1 362 echantillonne surtout des barres de NUIT, dont le rendement depuis
l'ouverture de seance a derive pendant des heures. L'ancien `sigma` mesurait
donc une dispersion de fin de seance et l'appliquait a la 30e minute. Bandes
trop larges, cassures trop rares.

### Ce que le chiffre ne dit toujours pas

| | `stride: 390` | ancre sur la seance |
|---|---|---|
| essais comptes | 495 | 496 |
| Sharpe observe / periode | 0,0469 | 0,0715 |
| maximum attendu sous H0 | 0,0667 | 0,0668 |
| **DSR** | **0,1107** | **0,6148** |
| significatif | non | **non** |

Le Sharpe observe passe SOUS le maximum attendu par chance a AU-DESSUS - c'est
un progres reel. Il reste que 0,6148 n'est pas 0,95 : apres 496 essais, ce
resultat demeure compatible avec le meilleur tirage d'un jeu.

### Reserve sur la comparaison

**Les deux runs ne portent pas sur le meme echantillon.** Le warmup d'une
fenetre comptee en seances ne se declare pas en barres (voir
`docs/execution-model.md` §1.3), et `min_warmup_bars` a donc ete porte de
23 790 a 85 000 : le run par seance couvre 3 643 989 barres contre 3 705 199,
soit **45 seances de moins** - deux mois sur 10,6 ans. L'ecart de performance
est trop large pour venir de la, mais il n'a pas ete mesure a echantillon egal.

## Le defaut, tel qu'il a ete trouve

**Corrige le jour meme** ; conserve ici parce que la maniere dont il a
survecu compte autant que le defaut.

Les cotations NQ portent la seance ELECTRONIQUE : **1 362 barres par jour, pas
390**. Le `stride: 390` de `sigma`, cense echantillonner « au meme rang de
seance », tombe donc a des heures arbitraires. Le `note` du JSON qui annonce
« 94 seances ecourtees sur 2748, soit 3,4 % — la seule approximation qui
subsiste » repose sur une premisse fausse.

Ce defaut n'invalide pas les deux runs ci-dessus : il les rend simplement
etrangers au papier. Ce qui a tourne est UNE strategie de rupture de bande, pas
CELLE de Zarattini.

## Ce qu'on ne peut PAS en conclure

- Que la strategie est bonne : DSR 0,6148, sous le seuil.
- Que corriger `sigma` a « ameliore » la strategie. Cela a corrige une
  ERREUR DE MESURE. Le gain de +111 % a +257 % dit ce que l'erreur coutait,
  pas ce que la strategie vaut.
- Que le capital est un parametre de la strategie : ce n'en est pas un. C'est
  une contrainte de financabilite qui a rendu le premier essai muet.
- Que les trois essais se comparent entre eux sans reserve : le troisieme
  porte sur 45 seances de moins.

## Suites

- [x] Reecrire `sigma` sur un ancrage de seance reel — **fait 2026-09-13**.
- [ ] Rejouer les deux configurations a echantillon EGAL, pour que l'ecart
      de +145 points soit attribuable au seul `sigma`.
- [ ] Walk-forward : un Sharpe de 1,26 sur un echantillon unique ne dit rien
      de sa stabilite, et c'est la question que le DSR de 0,6148 laisse
      ouverte.
- [ ] Afficher le taux de rejet a cote du rendement ([[hot]], action ouverte).

Fonde sur [[log]] (2026-09-13) · [[lessons]] L27, L28 · registre `essais/registre.jsonl`
