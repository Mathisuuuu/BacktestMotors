---
type: experiment
updated: 2026-09-12
statut: termine
verdict: non-conclusif
strategie: ranking@1
instruments: [ES.v.0, NQ.v.0, YM.v.0, FDAX.v.0, GC.v.0, CL.v.0, 6E.v.0, 6B.v.0, 6J.v.0, 6A.v.0]
essais: 6
---

# Momentum 12-1, trois regles d'allocation — mensuel, dix futures

> **Six essais, pas trois.** Chaque regle a ete evaluee a DEUX niveaux de
> capital, et les six runs ont ete regardes. Les trois premiers sont
> inexploitables — ils mesuraient autre chose que ce qu'ils declaraient — mais
> ils comptent quand meme au compteur du Deflated Sharpe : un essai rate reste
> un essai. Voir [[concepts/deflated-sharpe-ratio]].

## Hypothese

La facon de repartir le budget entre les six noms retenus par un classement
momentum change materiellement le resultat. Trois regles :
`fixed` (un contrat chacun, le defaut historique), `equal_weight` (meme argent
chacun), `inverse_volatility` (poids en `1/vol`, normalises).

## Montage

- Strategie : `ranking@1`, score `momentum_score(lookback=12, skip=1)`,
  `n_long: 3`, `n_short: 3`
- Donnees : dix futures 1 min reechantillonnes en `month`, panneau de 115 lignes,
  9,5 ans
- `risk.sizing.kind: "none"` — obligatoire : une allocation en argent combinee
  a un dimensionnement est refusee a la validation
  ([docs/execution-model.md](../../docs/execution-model.md) §6.4)
- **Rapports ARCHIVES depuis le 2026-09-12** dans
  [essais/](../../essais/registre.jsonl) : les six essais y figurent, avec leur
  rapport complet. Ils ne l'etaient pas — ils vivaient dans un repertoire
  temporaire de session, et auraient ete perdus.

## Ce que les trois premiers essais mesuraient reellement

A **1 M$** de capital et `gross_target: 1.0`, six noms recoivent 166 666 $
chacun. Un contrat ES en vaut environ 250 000 : la troncature vers zero
l'elimine. Les compteurs le disent :

| Regle | Sharpe | noms tronques a zero |
|---|---|---|
| `fixed` | 0,92 | 0 |
| `equal_weight` | 0,02 | **190** |
| `inverse_volatility` | 0,15 | **294** |

Sur ~690 emplacements nom-rebalancement, 28 % et 43 % des noms disparaissaient
— et pas au hasard : **les gros contrats en premier**. Ces deux lignes ne
mesurent donc pas « l'equiponderation » ni « la ponderation inverse a la
volatilite », mais ces regles amputees de leurs plus gros instruments.

**Conclure de ce tableau que `fixed` est la meilleure allocation aurait ete
faux**, et rien dans les chiffres de performance ne l'aurait signale. C'est le
compteur `n_noms_tronques` qui l'a dit.

## Resultat, a capital suffisant

A **20 M$**, la troncature tombe a zero pour les trois regles, et les trois
selectionnent exactement les memes noms (107 trades chacune) : seules les
tailles different. La comparaison porte enfin sur ce qu'elle annonce.

| Regle | Sharpe | CAGR | vol ann. | DD max | tronques | empreinte |
|---|---|---|---|---|---|---|
| `fixed` | 0,84 | +0,38 % | 0,45 % | -0,59 % | 0 | `49bc362ae691` |
| `equal_weight` | 0,45 | +3,33 % | 8,10 % | -14,59 % | 0 | `1699e326b156` |
| `inverse_volatility` | 0,71 | +4,04 % | 5,86 % | -9,60 % | 0 | `1d15896fa9f6` |

L'hypothese est confirmee sur sa partie faible : **la repartition change
materiellement le resultat**. Trois portefeuilles construits sur les memes
decisions d'achat et de vente donnent des Sharpe de 0,45 a 0,84.

## Ce qu'il ne faut PAS conclure

- **Que `fixed` est superieur.** Un seul echantillon, aucun walk-forward, six
  essais enregistres. Le Sharpe le plus haut d'un petit ensemble n'est pas une
  estimation de performance, c'est un maximum — voir
  [[concepts/deflated-sharpe-ratio]].
- **Que les CAGR sont comparables.** `fixed` deploie environ 1,5 % de l'equity
  a 20 M$, les deux autres 100 %. Le Sharpe, invariant d'echelle, est le seul
  comparateur legitime de ce tableau ; le CAGR ne dit ici que le levier choisi.
- **Que `inverse_volatility` est de la parite de risque.** Elle n'egalise les
  contributions au risque que si les noms sont decorreles, ce qui est faux sur
  quatre indices actions et quatre devises.
- **Que le roulement est neutre.** Les series `.v.0` ne sont pas ajustees
  ([[reference/donnees]]) ; une part du momentum mensuel est mecanique.

## Verdict

`non-conclusif` sur le classement des trois regles. Ce qui est etabli :
l'allocation est un levier de premier ordre, et **le compteur de troncature
doit etre lu avant tout chiffre de performance issu d'une allocation** — sans
lui, trois des six essais auraient ete publies comme s'ils mesuraient ce qu'ils
declaraient.

## Liens

[docs/execution-model.md](../../docs/execution-model.md) §6.4 ·
[src/rsl/strategies/allocation.py](../../src/rsl/strategies/allocation.py) ·
[[lessons]] L21 · [[log]] (2026-09-12)
