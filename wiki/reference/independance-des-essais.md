---
type: reference
updated: 2026-09-17
autorite: src/rsl/independance.py
---

# Independance des essais — pourquoi le seuil de deflation s'effondre

> Page **routeur**. L'autorite est
> [src/rsl/independance.py](../../src/rsl/independance.py),
> [statistics.py](../../src/rsl/metrics/statistics.py) pour la formule, et
> [tests/unit/test_independance.py](../../tests/unit/test_independance.py).

| Question | Reponse faisant autorite |
|---|---|
| La formule du seuil | `expected_max_sharpe` dans [statistics.py](../../src/rsl/metrics/statistics.py) |
| Les deux facteurs, separes | `Decomposition`, meme fichier |
| Qui porte le meme echantillon | `familles` dans [independance.py](../../src/rsl/independance.py) |
| Correlation de deux essais | `correlation`, meme fichier |
| Voir tout cela | `rsl essais --familles` |

## Le diagnostic d'avant designait le mauvais terme

Il etait ecrit depuis le 2026-09-12 qu'ajouter des essais correles degradait le
Deflated Sharpe, et que « ce qu'il faudrait est une notion de distance entre
essais ». La decomposition du 2026-09-17 montre autre chose. Le seuil est un
**produit** :

```
E[max SR] = sqrt(V) * f(N)
```

| Terme | 17 essais -> 498 |
|---|---|
| `f(N)` — le COMPTE | 1,8281 -> 3,0513, **+66,9 %** |
| `sqrt(V)` — la DISPERSION | 0,1011 -> 0,0219, **-78,3 %** |
| **seuil** | 0,1848 -> **0,0669** |

**Le compte se comporte correctement.** Ajouter des essais monte bien la barre.
C'est `V` qui s'effondre, et il s'effondre parce que 481 essais de la grille SMA
ont un ecart-type de Sharpe de **0,0093**, contre 0,1011 pour les dix-sept
autres - un facteur onze. Ce ne sont pas 481 mesures, c'est une mesure repetee
481 fois, et `variance_of_sharpes` l'estime comme si c'etaient 481 tirages.

## Ce que le rapport montre desormais

Il imprimait le produit, et a cote la variance brute. Une variance de 0,00048 ne
se lit pas comme « vos 481 essais n'en sont qu'un ». Les deux facteurs cote a
cote, si :

```
Maximum attendu sous H0       0.0669 = dispersion 0.0219 x compte 3.0513  (498 essai(s))
```

## Deux mesures, de portee differente

### Les familles d'echantillon — disponibles tout de suite

Deux essais qui portent les memes instruments sur le meme nombre
d'observations sont sur le MEME echantillon. Critere GROSSIER, et fiable pour
cette raison meme : il ne suppose rien. `rsl essais --familles` sur le registre
actuel :

```
462 essai(s)    2501 obs  ecart-type 0.0093  ES.v.0     sma-2-20
  7 essai(s)     114 obs  ecart-type 0.1072  6A,6B,...  momentum-12-1-dix-futures
  5 essai(s)    2651 obs  ecart-type 0.0051  ES.v.0     sma-crossover-es-quotidien
```

**92,8 % des essais dans une seule famille.**

### La correlation des rendements — a partir du 2026-09-17

Bien plus fine, et elle montre que la vue par famille **sur-regroupe**. Mesure
sur quatre essais reels :

| Paire | Correlation |
|---|---|
| SMA(20,100) vs SMA(22,100) | **+0,9920** |
| SMA(20,100) vs SMA(2,20) | +0,4907 |
| SMA(20,100) vs RSI hors lundi | +0,1617 |
| SMA(2,20) vs RSI hors lundi | +0,0578 |

Deux voisins de la grille ne sont pas deux essais. Mais 0,99 et 0,49 tombent
dans la meme famille : la famille est ce qu'on sait dire **sans** la serie, pas
ce qu'on voudrait dire.

## La serie quotidienne archivee

`essais/series/<cle>-<empreinte>.npz`, ecrite par `rsl run --archive`.

Trois choix a connaitre :

- **Quotidienne**, parce que `to_daily` l'a deja agregee ainsi quelle que soit
  la granularite des barres. Un run a la minute et un run quotidien produisent
  donc des series de meme nature, **sans qu'aucun reechantillonnage n'ait a
  etre invente**. C'est aussi celle dont sort le `sharpe_per_period`, donc
  celle qui explique la variance des essais.
- **Avec ses dates**, parce que deux essais couvrant des periodes differentes
  ne se comparent que sur leur intersection. La correlation est calculee sur
  les dates COMMUNES, jamais sur des series recadrees a la meme longueur.
- **En `.npz`**, contrairement au registre qui est en JSONL. Le registre est du
  texte pour qu'un `git diff` y reste lisible ; ici il n'y a rien a lire, et le
  binaire garde les flottants au bit pres. Cout mesure : **21 Ko par essai**,
  soit environ 5 Mo si les 498 en portaient une.

Deux cas rendent `None`, et ce n'est pas une erreur : les essais archives
**avant le 2026-09-17** - irrattrapable sans les rejouer - et les essais de
BALAYAGE, qui n'ecrivent deja aucun rapport.

## Ce qui n'est PAS fait, et pourquoi

**Le DSR publie n'a pas change d'un chiffre.** Aucune correction n'est
appliquee.

Decider ce qu'est un essai effectif appartient a Bailey & Lopez de Prado, dont
la source est encore `a-ingerer` ([[research/bailey-lopez-de-prado-dsr]]). Une
formule ecrite ici rendrait un DSR different, plausible, et faux d'une facon que
personne ne pourrait detecter - la famille [[lessons]] L30. Ce qui est livre
mesure la structure ; la corriger vient apres la source, pas avant.

## Voisins

- [[concepts/deflated-sharpe-ratio]] — pourquoi le maximum d'un ensemble de
  tirages n'est pas un tirage.
- [[experiments/pbo-grille-large-462-sma]] — les 462 essais en question.
- [[research/bailey-lopez-de-prado-dsr]] — la source qui manque encore.
