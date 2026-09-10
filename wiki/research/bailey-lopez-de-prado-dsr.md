---
type: research
updated: 2026-09-10
statut: a-ingerer
source: Bailey & Lopez de Prado — Deflated Sharpe Ratio / PSR
url: a renseigner (papier non present dans le depot)
---

# Deflated Sharpe Ratio — la source

> **Statut : `a-ingerer`.** Cette page est un emplacement, pas un resume. Le
> papier n'est pas dans le depot et n'a pas ete lu dans le cadre de cette
> session. Elle existe parce que le depot **implemente** le DSR et le PSR : la
> provenance doit etre tracable, et un emplacement vide est plus honnete qu'un
> resume de memoire.

## Ce que la source affirme

A remplir apres lecture. A verifier en priorite, parce que l'implementation en
depend :

- la formule exacte du maximum attendu sous H0 en fonction du nombre d'essais
  et de leur variance ;
- la correction par les moments d'ordre 3 et 4 (asymetrie, kurtosis) dans le
  PSR ;
- les hypotheses d'independance entre essais, et ce qu'elles deviennent quand
  les essais sont une grille de parametres voisins — point le plus susceptible
  d'etre mal applique ici ;
- le lien avec PBO / CSCV, qui est dans ce depot au stade de protocole seulement.

## Ce qu'on en retient ici

A remplir. Question a trancher en lisant : **la dispersion d'une grille de
parametres voisins est-elle une estimation legitime de la variance des essais ?**
Une grille SMA 5/20, 5/50, 10/20... produit des essais fortement correles ; si
la formule suppose l'independance, le DSR affiche ici est probablement trop
optimiste, dans un sens qu'il faut savoir chiffrer.

## Contradictions

Aucune relevee, puisque rien n'a ete ingere. A reverifier contre
[[concepts/deflated-sharpe-ratio]] apres lecture.

## Statut d'ingestion

| Element | Etat |
|---|---|
| Source obtenue | non |
| Lue | non |
| [[concepts/deflated-sharpe-ratio]] confronte a la source | non |
| Implementation confrontee a la formule du papier | non |
| Hypothese d'independance des essais tranchee | non |

## Liens

[[concepts/deflated-sharpe-ratio]] · [[experiments/dsr-grille-sma-8-essais]] ·
[[Failed Ideas/ledger]]
