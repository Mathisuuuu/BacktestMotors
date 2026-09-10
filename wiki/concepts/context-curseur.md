---
type: concept
updated: 2026-09-10
statut: stable
alias: [Context, curseur, BarFeed]
---

# `Context` a curseur

## Definition

L'objet que recoit une strategie a chaque barre. Il tient en deux elements : une
reference vers un magasin de barres immuable, et un entier — la position du
curseur. Il ne contient pas les donnees, et il n'expose aucun moyen de connaitre
la taille du magasin.

Trois proprietes de sa surface publique, chacune volontaire :

- `ctx.value(field, lag=k)` avec `k >= 0` lit une barre close ; `k < 0` leve
  `LookAheadError`.
- `ctx.history(n)` leve `InsufficientHistoryError` plutot que de rendre des NaN.
  Une fenetre incomplete est une erreur, jamais une valeur.
- `len(ctx)` n'existe pas. Savoir combien de barres restent est deja une
  information sur le futur.

## Dans ce depot

Implementation attendue : `src/rsl/data/feed.py` et la couche `src/rsl/data/`
-- **paquet actuellement absent du depot**, voir l'avertissement de
[[reference/donnees]]. Contrat : [docs/no-lookahead.md](../../docs/no-lookahead.md) §2.
Exemple d'usage minimal : le bloc « L'idee en une phrase » de
[README.md](../../README.md).

Le `Context` expose aussi l'**etat de position** — quantite, barres depuis
l'entree, prix d'entree, extremes atteints — calcule par le runner. Ce choix
est explique dans [[Failed Ideas/ledger]] : un noeud a memoire aurait fait la
meme chose en cassant le determinisme.

## Pourquoi ca compte

C'est le mecanisme unique qui ferme la premiere voie du modele de menace. Toutes
les autres garanties supposent celle-ci : si une strategie pouvait remonter au
tableau complet, aucune regle sur les primitives ou l'execution ne servirait a
rien.

Corollaire pour tout nouveau code : **ne jamais ajouter a `Context` une methode
qui revele la longueur du magasin ou une valeur non close.** C'est la seule
facon de casser le socle depuis l'interieur.

## Liens

[[concepts/look-ahead-bias]] · [[concepts/determinisme]] ·
[[reference/contrat-anti-lookahead]] · [[reference/donnees]]
