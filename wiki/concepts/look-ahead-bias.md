---
type: concept
updated: 2026-09-10
statut: stable
alias: [look-ahead, biais de anticipation, fuite du futur]
---

# Look-ahead bias

## Definition

Toute situation ou un backtest utilise, a l'instant `t`, une information qui
n'etait pas disponible a `t`. Le resultat n'est alors pas une estimation
optimiste de la performance : c'est une mesure d'autre chose.

Le parti pris de ce depot n'est pas d'*interdire* la fuite, mais de la rendre
**impossible a exprimer**. Une strategie ne recoit jamais un tableau complet :
elle recoit un `Context`, c'est-a-dire une reference vers un magasin de barres
immuable plus un entier. Rien dans sa surface publique ne permet de lire au-dela
de cet entier, ni meme de savoir combien de barres restent.

## Dans ce depot

L'autorite est [docs/no-lookahead.md](../../docs/no-lookahead.md), qui est
**normatif** : un comportement du code qui le contredit est un bug du code.
Il decrit un modele de menace en sept voies, dont six sont fermees par
construction et la septieme rendue visible.

Point d'entree cote wiki : [[reference/contrat-anti-lookahead]].

## Pourquoi ca compte

C'est la raison d'etre du depot entier. Ce socle est la verite terrain d'un
systeme plus large — lire des papers, en extraire une specification, la compiler
en backtest. Si le socle fuit, tout ce qui est bati dessus est faux, et faux
silencieusement : un backtest qui triche ne leve pas d'exception, il affiche un
beau Sharpe.

Deux consequences pratiques qui reviennent souvent :

- Les primitives sont a **fenetre glissante uniquement**. Une normalisation sur
  l'echantillon complet (z-score global, min-max global) est une fuite.
- L'execution est decalee d'au moins une barre : executer au `close` de la barre
  qui a produit le signal est la troisieme voie du modele de menace.

## Liens

[[concepts/determinisme]] · [[concepts/context-curseur]] ·
[[reference/contrat-anti-lookahead]] · [[reference/modele-execution]] ·
[[Failed Ideas/ledger]]
