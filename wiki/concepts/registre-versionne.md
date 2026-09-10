---
type: concept
updated: 2026-09-10
statut: stable
alias: [extension par ajout, sma@1, cle nom-version]
---

# Registre versionne

## Definition

Chaque registre du socle — primitives, types de noeuds, strategies — est
statique et versionne. La cle est le couple `(nom, version)`, note `sma@1`, et
**reenregistrer une cle existante leve une erreur**. Le socle est donc ferme a
la modification et ouvert a l'extension.

| Besoin | Geste |
|---|---|
| Un indicateur nouveau | `@primitive("mon_indic", version=1, ...)` |
| Corriger un indicateur publie | `@primitive("mon_indic", version=2, ...)` — la v1 reste, et reste rejouable |
| Une regle nouvelle | composer des noeuds existants, aucun code |
| Un type de noeud nouveau | `@signal_node("mon_noeud", version=1)` |
| Une famille de strategies nouvelle | `@strategy("ma_famille", version=1, ...)` |

## Dans ce depot

- [src/rsl/primitives/registry.py](../../src/rsl/primitives/registry.py)
- Catalogue vivant : `rsl catalogue`
- Contrat publie : `rsl schema` — voir [[reference/vocabulaire-signaux]]

`signal.describe()` reproduit la specification d'un signal **versions
epinglees** : c'est ce qui rend l'aller-retour JSON ↔ objet verifiable.

## Pourquoi ca compte

Un rapport de run archive epingle `sma@1`. Si `sma@1` changeait de sens un jour,
le run cesserait d'etre rejouable et la verite terrain serait perdue —
retroactivement, sans que rien ne signale la perte. La regle « corriger =
publier `@2` » est au [[Failed Ideas/ledger]] parce que la tentation de corriger
en place revient a chaque bug d'indicateur.

## Liens

[[concepts/determinisme]] · [[reference/vocabulaire-signaux]] ·
[[reference/cli]] · [[Failed Ideas/ledger]]
