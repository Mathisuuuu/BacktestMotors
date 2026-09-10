---
type: reference
updated: 2026-09-10
autorite: docs/no-lookahead.md
---

# Contrat anti-look-ahead — routeur

> Page routeur. Elle ne fait autorite sur rien : elle dit ou est l'autorite.
> Le document [docs/no-lookahead.md](../../docs/no-lookahead.md) est
> **normatif** — un comportement du code qui le contredit est un bug du code.

| Question | Reponse faisant autorite |
|---|---|
| Quelles sont les sept voies de fuite du futur ? | [docs/no-lookahead.md](../../docs/no-lookahead.md) §1 — modele de menace |
| Comment le `Context` empeche de lire le futur ? | [docs/no-lookahead.md](../../docs/no-lookahead.md) §2 |
| Que fait le moteur quand un instrument est absent ? | [docs/no-lookahead.md](../../docs/no-lookahead.md) §4 — absence ≠ dernier prix |
| Comment l'univers evite le biais de survie ? | [docs/no-lookahead.md](../../docs/no-lookahead.md) §4.2 |
| Pourquoi seulement des fenetres glissantes ? | [docs/no-lookahead.md](../../docs/no-lookahead.md) §5 |
| Ou est expose l'etat de position ? | [docs/no-lookahead.md](../../docs/no-lookahead.md) §2.5 |
| **Ce que le socle ne garantit PAS** | [docs/no-lookahead.md](../../docs/no-lookahead.md), section dediee — a lire avant d'affirmer qu'un resultat est propre |
| Ou l'execution decalee est-elle imposee ? | [docs/execution-model.md](../../docs/execution-model.md) §2.1 — `execution_lag >= 1` |
| Quels tests attaquent ces garanties ? | [tests/adversarial/](../../tests/adversarial) — marqueur pytest `adversarial` |

## Liens wiki

[[concepts/look-ahead-bias]] · [[concepts/context-curseur]] ·
[[reference/modele-execution]] · [[reference/donnees]]
