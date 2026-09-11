---
type: reference
updated: 2026-09-11
autorite: src/rsl/gui/
---

# Tableau de bord graphique — routeur

> Page routeur. L'autorite est [src/rsl/gui/](../../src/rsl/gui/) :
> [model.py](../../src/rsl/gui/model.py) pour tout ce qui se calcule,
> [charts.py](../../src/rsl/gui/charts.py) pour les courbes,
> [app.py](../../src/rsl/gui/app.py) pour la fenetre.

Fenetre de resultats d'un backtest : indicateurs, courbes de capital et de
drawdown, carnet d'ordres, export. Noir et blanc strict, chrome Windows 95.

## Lancer

```bash
.venv/Scripts/python.exe -m pip install -e ".[gui]"
```

```bash
.venv/Scripts/rsl.exe gui examples/sma_es_daily.json
```

`rsl gui` sans argument ouvre la fenetre vide ; le bouton **CHARGER UN JSON**
execute n'importe quelle specification. `rsl run CONFIG --gui` affiche le
tableau de bord a la fin d'un run ordinaire.

## Dependance optionnelle, et pourquoi

matplotlib est dans l'extra `gui`, **pas** dans les dependances du projet. Le
moteur ne l'importe jamais, et `rsl.manifest.TRACKED_DEPENDENCIES` ne
l'enregistre pas : un rapport produit sur une machine qui a l'interface reste
comparable a un rapport produit sur une machine qui ne l'a pas. `rsl gui` sur
une machine sans matplotlib rend `1` avec un message, il ne casse aucune autre
commande.

## Les deux regimes de mesure — a lire avant d'interpreter un chiffre filtre

Le bandeau affiche en permanence **COURBE MESUREE** ou **COURBE RECONSTRUITE**.
La distinction n'est pas cosmetique :

| | MESUREE | RECONSTRUITE |
|---|---|---|
| Quand | aucun filtre de sens | filtre `LONG` ou `SHORT` actif |
| Courbe | la vraie equity du run, tronquee a l'annee si demandee | fabriquee en n'accumulant que le P&L net des trades retenus |
| Sens | ce qui a ete vecu | **la contribution de ces trades au resultat observe** |

Une courbe « longs seulement » n'a jamais existe : la sortir d'un run
long-short n'est pas un backtest long-only, parce que les shorts ont occupe du
capital et de la marge pendant ce temps. La reconstruction se fait sur la
**meme grille de barres** que le run, pour que le Sharpe porte sur une serie de
meme periodicite et reste comparable — mais elle ne repond pas a la question
« qu'aurait donne cette strategie sans les shorts ». Pour cela, il faut lancer
un autre backtest, et l'enregistrer comme un essai de plus.

Sans aucun filtre, l'autorite reste le moteur : `compute_stats` recopie
`metrics.sharpe` au lieu de le recalculer, et un test compare les deux.

## Ce qui est affiche

| Bloc | Contenu |
|---|---|
| Indicateurs | Sharpe, Calmar, DD, DD max, gain net/brut, perte nette/brute, profit factor, taux de reussite, nombre de trades, gain/perte moyens |
| Filtres | annee (sur la date de **sortie**), sens (tous / long / short) |
| Courbes | capital et drawdown, abscisse partagee, molette = zoom, glisser = defiler |
| Carnet | date d'entree, date de sortie, sens, prix d'entree, prix de sortie, PnL, frais |
| Export | carnet en CSV (`;`), statistiques en TXT — tous deux en UTF-8 explicite |

## Limites connues

- **Calmar est calcule ici**, pas par le moteur : `metrics` ne le porte pas.
  Formule : CAGR de la courbe active divise par la valeur absolue du drawdown
  maximal.
- **L'annee est celle de la sortie.** Un trade ouvert en decembre et ferme en
  janvier compte pour l'annee suivante — sinon la somme des annees ne redonne
  pas le total.
- **Une entree etalee sur plusieurs barres** n'est pas representable en une
  ligne : seule la barre d'ouverture est lue pour le prix. `quantity` porte le
  maximum atteint par la position.
- Le zoom est reinitialise a chaque changement de filtre : garder l'ancien
  cadrage montrerait une fenetre temporelle qui ne correspond plus aux donnees.

## Liens wiki

[[reference/cli]] · [[concepts/determinisme]] · [[lessons]] ·
[[reference/donnees]]
