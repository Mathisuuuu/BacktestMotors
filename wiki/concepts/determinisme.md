---
type: concept
updated: 2026-09-10
statut: stable
alias: [reproductibilite, empreinte de resultat, rejouable]
---

# Determinisme et empreinte de resultat

## Definition

Deux executions de la meme configuration doivent produire des resultats
**bit-a-bit identiques**. L'exigence porte sur l'**empreinte de resultat**,
calculee sur la courbe d'equity, les fills, les compteurs et la comptabilite —
jamais sur l'horodatage. Deux runs identiques lances a dix minutes d'intervalle
doivent donner la meme empreinte, sinon l'exigence serait inverifiable.

Distinct mais lie : le champ **Rejouable** du manifeste. Il vaut `NON` des
qu'une piece manque — arbre de travail modifie, fichier source sans empreinte,
absence de depot — plutot que d'afficher un numero de commit qui laisserait
croire a une tracabilite inexistante.

## Dans ce depot

- Manifeste et empreintes : [src/rsl/manifest.py](../../src/rsl/manifest.py)
- Commande dediee : `rsl verify CONFIG` execute **deux fois** et compare les
  empreintes. Code de sortie `2` en cas de divergence.
- Le test de corruption du futur : bruiter toutes les barres apres l'index `k`
  ne doit rien changer a un backtest arrete a `k`, empreinte exhaustive
  comparee.

## Pourquoi ca compte

`verify` existe comme commande a part entiere parce que l'exigence « deux runs
identiques produisent le meme resultat » est facile a ecrire dans un document et
facile a perdre dans le code. Les codes de sortie sont concus pour qu'un script
distingue « je n'ai pas pu » (`1`) de « j'ai pu, et c'est faux » (`2`).

C'est aussi ce qui interdit deux tentations recurrentes, toutes deux au
[[Failed Ideas/ledger]] : les noeuds de signaux a memoire, et la correction en
place d'une primitive publiee.

## Liens

[[concepts/registre-versionne]] · [[concepts/context-curseur]] ·
[[reference/cli]] · [[Failed Ideas/ledger]]
