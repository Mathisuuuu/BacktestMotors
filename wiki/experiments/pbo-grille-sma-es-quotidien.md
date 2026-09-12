---
type: experiment
updated: 2026-09-12
statut: termine
verdict: negatif
strategie: sma_crossover@1
instruments: [ES.v.0]
essais: 16
---

# PBO d'une grille SMA 4x4 — ES quotidien

> **Le resultat le plus defavorable du depot a ce jour, et le plus utile.** La
> famille de strategies dont sort l'exemple phare `sma_es_daily` a une
> probabilite de surapprentissage de **0,70 a 0,80** : choisir la meilleure
> configuration sur une moitie de l'echantillon la laisse sous la mediane sur
> l'autre moitie trois a quatre fois sur cinq.

## Hypothese

La CSCV de Bailey, Borwein, Lopez de Prado et Zhu ne demande pas si une
strategie est bonne. Elle demande si **le processus qui l'a choisie** a un
pouvoir predictif. Question posee ici a la grille la plus banale qui soit :
`fast_window` dans {5, 10, 20, 40} x `slow_window` dans {50, 100, 150, 200},
seize configurations, celles qu'on essaie sans y penser.

## Montage

- Grille : 16 configurations de `sma_crossover@1`, generees par produit
  cartesien. Les 16 sont enregistrees au
  [registre des essais](../../essais/registre.jsonl) du 2026-09-12.
- Donnees : `ES.v.0` quotidien, reglages de
  [examples/reglages/sma_es_daily.json](../../examples/reglages/sma_es_daily.json)
- Commande :
  `rsl pbo <16 fichiers> --settings examples/reglages/sma_es_daily.json --symbol ES.v.0 --blocks 8 --drop-idle`
- Code de sortie **2** : une grille surapprise est une verification qui echoue,
  pas une erreur d'usage.

## Resultat

| S | configurations retenues | combinaisons | PBO | rang median hors echantillon |
|---|---|---|---|---|
| 6 | 12 | 20 | **0,80** | 0,385 |
| 8 | 8 | 70 | **0,70** | 0,222 |

Les deux reglages concordent, et tous deux sont largement au-dessus du seuil de
0,5 - la valeur a laquelle choisir le meilleur en echantillon ne vaut pas mieux
qu'un tirage a pile ou face.

Le **rang median** est plus parlant que la PBO : a S=8, la configuration
championne en echantillon finit au 22e centile hors echantillon. Elle ne se
contente pas de perdre son avance, elle finit dans le dernier quart.

## L'effet sur le Deflated Sharpe

C'est la seconde moitie du resultat, et elle etait invisible avant que le
registre des essais existe (le meme jour).

| | essais | variance des Sharpe | maximum attendu sous H0 | DSR de `sma_es_daily` |
|---|---|---|---|---|
| Sans registre | 1 | 0 | 0,0000 | **0,9719 SIGNIFICATIF** |
| Registre du 2026-09-12 | 31 | 0,01203 | 0,1600 | **0,0000** |

Le Sharpe observe de l'exemple phare est de 0,0376 par periode. Le meilleur de
31 tirages sous l'hypothese nulle en valait 0,1600 : **quatre fois plus**.

Ce chiffre n'a pas change parce que la strategie s'est degradee. Il a change
parce qu'on a enfin compte les essais.

> **La variance est indiquee pour une raison.** Un DSR calcule depuis le
> registre n'est pas stable : il depend du nombre d'essais ET de leur
> dispersion, et les deux bougent quand le registre grandit - parfois en sens
> contraire. Le meme calcul refait apres le balayage de 462 configurations
> ([[experiments/pbo-grille-large-462-sma]]) rend 0,3461 a 31 essais, parce que
> la variance est tombee a 0,000473. Un DSR se cite donc avec l'etat du
> registre qui l'a produit, jamais seul. Voir [[lessons]] L23.

## Ce que le calcul a revele en chemin

Deux problemes de methode, trouves en lancant la premiere grille reelle et
consignes dans [src/rsl/pbo.py](../../src/rsl/pbo.py) :

- **Une grille ne partage pas son echantillon naturellement.** Une fenetre
  lente de 200 barres commence 200 barres plus tard qu'une de 50 : les seize
  configurations donnaient QUATRE longueurs (2701, 2651, 2601, 2551). Les
  comparer telles quelles aurait melange « meilleure strategie » et « meilleure
  epoque ». Le warmup est desormais porte au maximum de la grille, et le cout -
  ici 201 barres - est rapporte.
- **Quatre configurations ne negocient PAS du tout sur la premiere
  sous-periode.** Leur Sharpe n'y est pas defini. Leur donner zero les aurait
  classees au-dessus de toutes les perdantes, ce qui flatte l'inactivite ; elles
  sont retirees, sur demande explicite (`--drop-idle`) et nommement.

Le registre a par ailleurs signale de lui-meme que `sma-20-100` et
`sma-crossover-es-quotidien` rendent la MEME empreinte : l'exemple phare est un
membre de sa propre grille.

## Ce qu'il ne faut PAS conclure

- **Que les croisements de moyennes ne marchent pas.** La PBO qualifie une
  GRILLE et le fait d'en avoir pris le maximum, pas une strategie. Une
  configuration choisie pour une raison exterieure aux donnees - une hypothese
  economique - n'est pas concernee par ce chiffre.
- **Que 0,70 est precis.** Huit configurations retenues a S=8 : le rang hors
  echantillon ne prend que huit valeurs. L'article travaille sur des centaines
  de configurations. Les deux avertissements du programme le disent.
- **Que 31 essais est le bon denominateur.** C'est le nombre ENREGISTRE. Tout
  essai fait avant le 2026-09-12 et non archive manque, et chacun rendrait le
  DSR encore plus severe.

## Verdict

`negatif`. Non pas « la strategie perd » - elle gagne sur l'echantillon - mais
**le processus qui l'a selectionnee n'a pas montre de pouvoir predictif**. Le
Sharpe de 0,60 qui circule dans ce depot depuis le premier jour ne survit ni a
la CSCV ni au compteur d'essais.

La suite utile n'est pas d'elargir la grille : c'est de choisir une
configuration pour une raison qui ne vienne pas de l'echantillon.

## Liens

[src/rsl/metrics/surapprentissage.py](../../src/rsl/metrics/surapprentissage.py) ·
[src/rsl/pbo.py](../../src/rsl/pbo.py) ·
[[concepts/deflated-sharpe-ratio]] ·
[[experiments/sma-es-daily-walkforward]] ·
[[experiments/dsr-grille-sma-8-essais]] ·
[[log]] (2026-09-12)
