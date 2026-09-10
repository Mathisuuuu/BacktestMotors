---
type: reference
updated: 2026-09-10
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
| Ordres | [src/rsl/engine/orders.py](../../src/rsl/engine/orders.py) |
| Execution et fills | [src/rsl/engine/execution.py](../../src/rsl/engine/execution.py) |
| Portefeuille | [src/rsl/engine/portfolio.py](../../src/rsl/engine/portfolio.py) |
| Risque | [src/rsl/engine/risk.py](../../src/rsl/engine/risk.py) |
| Runner mono-instrument | [src/rsl/engine/runner.py](../../src/rsl/engine/runner.py) |
| Runner transversal | [src/rsl/engine/cross_sectional.py](../../src/rsl/engine/cross_sectional.py) |

## Liens wiki

[[reference/contrat-anti-lookahead]] · [[concepts/look-ahead-bias]] ·
[[reference/donnees]]
