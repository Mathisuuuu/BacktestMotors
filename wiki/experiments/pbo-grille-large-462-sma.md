---
type: experiment
updated: 2026-09-12
statut: termine
verdict: negatif
strategie: sma_crossover@1
instruments: [ES.v.0]
essais: 462
---

# PBO d'une grille SMA de 462 configurations — ES quotidien

> **Elargir la grille a empire le resultat, exactement comme la theorie le
> prevoit.** Seize configurations donnaient une PBO de 0,70-0,80 ; quatre cent
> soixante-deux en donnent **0,83 a 1,00**. Plus on essaie, plus le maximum
> qu'on retient doit a la chance.

## Hypothese

L'essai precedent ([[experiments/pbo-grille-sma-es-quotidien]]) et le ledger
disaient la meme chose : seize configurations, c'est trop peu pour que la PBO
veuille dire quelque chose - le rang hors echantillon ne prend que huit valeurs
apres retrait. L'article de Bailey, Borwein, Lopez de Prado et Zhu travaille sur
des centaines.

Question : la PBO d'une grille large est-elle differente, et dans quel sens ?

## Montage

- **462 configurations** de `sma_crossover@1` : `fast_window` de 2 a 40 par pas
  de 2 (20 valeurs), `slow_window` de 20 a 250 par pas de 10 (24 valeurs),
  `fast < slow`.
- Donnees : `ES.v.0` quotidien,
  [examples/reglages/sma_es_daily.json](../../examples/reglages/sma_es_daily.json)
- Warmup aligne a **251 barres** pour toute la grille, laissant 2501 rendements
  par configuration.
- 462 backtests en **1021 s**.
- Commande :
  `rsl pbo <repertoire> --settings examples/reglages/sma_es_daily.json --symbol ES.v.0 --blocks 4 --archive`
- Les 462 sont enregistrees au [registre des essais](../../essais/registre.jsonl).

## Resultat

| S | combinaisons | retenues | retirees | **PBO** | rang median |
|---|---|---|---|---|---|
| 2 | 2 | **462** | 0 | **1,000** | 0,056 |
| 4 | 6 | **462** | 0 | **0,833** | 0,221 |
| 6 | 20 | 294 | 168 | 0,800 | 0,449 |
| 8 | 70 | 105 | 357 | 0,643 | 0,368 |
| 10 | 252 | 74 | 388 | 0,694 | 0,373 |

Toutes les valeurs sont au-dessus de 0,5 - le seuil auquel choisir le meilleur
en echantillon ne vaut pas mieux qu'un tirage a pile ou face.

**A S=4, la grille entiere survit et la PBO vaut 0,833.** C'est la ligne a
retenir : les 462 configurations y sont toutes, sans selection prealable.

## Le piege de ce tableau, et il est important

Les lignes ne sont PAS comparables entre elles, et lire la baisse de 1,00 a 0,64
comme « la PBO diminue avec S » serait faux.

A partir de S=6, des configurations sont **retirees faute d'activite** : elles
n'ont pris aucune position pendant un bloc entier, donc leur Sharpe n'y est pas
defini. Le motif n'a rien d'aleatoire - une strategie de croisement entre sur un
CROISEMENT, et plus la fenetre lente est longue, plus les croisements sont
rares. La premiere sous-periode tombe sur 2017, une annee de tendance calme.

Le retrait elimine donc **systematiquement les fenetres longues** : 357 sur 462
a S=8. La PBO de 0,643 porte sur un sous-ensemble biaise vers les fenetres
courtes, pas sur la grille soumise.

L'arbitrage est structurel et aucune valeur de S ne le resout :

- **peu de sous-periodes** : blocs longs, donc toutes les configurations
  negocient, donc la grille est entiere - mais `C(S, S/2)` ne donne que 2 ou 6
  combinaisons, et la part de logits negatifs n'est pas stable ;
- **beaucoup de sous-periodes** : 70 ou 252 combinaisons - mais la grille est
  decimee et son echantillon survivant n'est plus celui qu'on voulait mesurer.

## Ce que l'elargissement a confirme

| grille | configurations | PBO (S ou rien n'est retire) |
|---|---|---|
| 4x4 | 16 | 0,80 (S=6, 12 retenues) |
| 20x24 | 462 | **0,833 (S=4, 462 retenues)** |

Le sens de la variation est celui que la theorie annonce : le maximum d'un
ensemble plus grand doit davantage a la chance. Elargir la grille n'a pas rendu
le chiffre plus rassurant, il l'a rendu plus **credible** - et plus mauvais.

## L'effet sur le compteur, et une surprise

Le registre passe a **493 configurations distinctes**. Le DSR de l'exemple
phare `sma_es_daily`, Sharpe observe 0,0376 par periode :

| essais | variance des Sharpe | maximum attendu sous H0 | DSR |
|---|---|---|---|
| 1 | 0 | 0,0000 | 0,9719 |
| 493 | 0,000473 | 0,0663 | **0,0724** |

La surprise n'est pas le chiffre final mais son CHEMIN. Avant ce balayage, le
meme calcul a 31 essais donnait un maximum attendu de 0,1600 ; apres, a 493
essais, il n'est plus que de 0,0663. **Le maximum attendu a BAISSE alors que le
nombre d'essais a ete multiplie par seize.**

La raison : le DSR depend du nombre d'essais et de leur DISPERSION. Les 462
configurations ajoutees sont des variantes du meme croisement, avec des Sharpe
tous serres entre 0,02 et 0,06 ; la variance des essais tombe de 0,01203 a
0,000473. Un ensemble plus grand mais plus homogene a un maximum attendu plus
FAIBLE qu'un petit ensemble heterogene.

Ce que cela dit sur la methode : ajouter des essais correles n'est pas
seulement inutile, cela **relache** la correction. Le denominateur du DSR
suppose des tirages independants, et 462 croisements de moyennes sur le meme
instrument n'en sont pas. Voir [[lessons]] L23.

## Ce qu'il ne faut PAS conclure

- **Que S=2 dit quelque chose.** Deux combinaisons : la PBO ne peut valoir que
  0, 0,5 ou 1. Le rang median de 0,056 est frappant, il n'est pas significatif.
- **Que les croisements de moyennes ne marchent pas.** La PBO qualifie le fait
  d'avoir pris le MAXIMUM d'une grille, pas une strategie. Une configuration
  choisie sur une hypothese exterieure aux donnees n'est pas concernee.
- **Que 462 est enfin « assez ».** L'echantillon, lui, n'a pas grandi : 2501
  rendements quotidiens, une dizaine d'annees, un seul instrument. Une grille
  plus dense sur le meme echantillon ajoute des essais correles, pas de
  l'information - et le tableau ci-dessus montre que cela va jusqu'a RELACHER
  la correction du DSR.
- **Que le DSR de 0,0724 se cite seul.** Il depend de l'etat du registre au
  moment du calcul. Le meme Sharpe rendait 0,0000 la veille et 0,0724
  aujourd'hui, sans que la strategie bouge.

## Verdict

`negatif`, et plus fermement que l'essai a seize configurations. Le processus
« essayer une grille de croisements sur ES quotidien et retenir le meilleur »
n'a montre aucun pouvoir predictif, quel que soit le decoupage.

Ce que l'elargissement apporte en plus : la demande du ledger - « une grille
assez large pour que le chiffre veuille dire quelque chose » - est satisfaite,
et la reponse ne change pas de signe.

## Liens

[[experiments/pbo-grille-sma-es-quotidien]] ·
[src/rsl/pbo.py](../../src/rsl/pbo.py) ·
[src/rsl/metrics/surapprentissage.py](../../src/rsl/metrics/surapprentissage.py) ·
[[concepts/deflated-sharpe-ratio]] · [[log]] (2026-09-12)
