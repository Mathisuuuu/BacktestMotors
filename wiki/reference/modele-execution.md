---
type: reference
updated: 2026-09-11
autorite: docs/execution-model.md
---

# Modele d'execution — routeur

> Page routeur. [docs/execution-model.md](../../docs/execution-model.md) est
> **normatif**. Certains points y sont marques `[A ARBITRER]` : ils attendent
> une decision explicite et bloquent l'implementation de la brique concernee —
> les traiter comme ouverts, pas comme tranches.

| Question | Reponse faisant autorite |
|---|---|
| Quand une barre est-elle reputee connue ? | [docs/execution-model.md](../../docs/execution-model.md) §1.1 — `ts_event` = debut d'intervalle, `ts_close` distinct |
| Quel est le lag d'execution ? | §2.1 — `execution_lag >= 1`, non contournable |
| Quels types d'ordres, et quelles bornes de fill ? | §2 et suivantes |
| Quel modele de couts ? | section couts |
| Comment sont comptabilises les futures ? | section comptabilite futures |
| Que se passe-t-il sur un trou de session ? | section trous de session |

## Cote code

| Brique | Fichier |
|---|---|
| Ordres | [src/rsl/orders.py](../../src/rsl/orders.py) — **hors de `engine/`**, voir ci-dessous |
| Execution et fills | [src/rsl/engine/execution.py](../../src/rsl/engine/execution.py) |
| Portefeuille | [src/rsl/engine/portfolio.py](../../src/rsl/engine/portfolio.py) |
| Risque | [src/rsl/engine/risk.py](../../src/rsl/engine/risk.py) |
| Runner mono-instrument | [src/rsl/engine/runner.py](../../src/rsl/engine/runner.py) |
| Runner transversal | [src/rsl/engine/cross_sectional.py](../../src/rsl/engine/cross_sectional.py) |

## Pourquoi `orders.py` n'est pas dans `engine/`

Il y a vecu jusqu'au 2026-09-11, et cela faisait partir la dependance dans les
deux sens : le runner a besoin du protocole `Strategy`, et les strategies ont
besoin d'`Order` pour declarer ce qu'elles rendent. `import rsl.strategies`
chargeait donc sept modules de moteur.

`Order` et `Fill` n'appartiennent a aucune des deux couches : ils sont le
vocabulaire par lequel elles se parlent. Ils se placent sous les deux, avec
`errors.py`, dont ils dependent seuls.

`rsl.engine` continue de les reexporter — le moteur travaille sur des ordres.
Ce qui garde le sens unique n'est pas cette facade mais
[tests/unit/test_couches.py](../../tests/unit/test_couches.py), qui verifie
dans un interpreteur neuf qu'importer `rsl.strategies` ne charge aucun
`rsl.engine.*`. Detail qui compte : aucun outil du depot ne voit un cycle de
paquets, `ruff` et `mypy --strict` inclus ([[lessons]] L14).

## Liens wiki

[[reference/contrat-anti-lookahead]] · [[concepts/look-ahead-bias]] ·
[[reference/donnees]]
