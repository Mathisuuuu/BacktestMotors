---
type: experiment
updated: 2026-09-11
statut: termine
verdict: non-conclusif
strategie: rules@1
instruments: [ES.v.0]
essais: 1
---

# RSI survendu hors lundi — ES quotidien

> Cet essai n'a pas ete fait pour lui-meme : il sert de **preuve** qu'une
> strategie neuve se decrit entierement en JSON, sans une ligne de Python. Il
> compte quand meme au compteur d'essais -- voir [[lessons]] L2 : l'intention
> ne change rien a l'inflation du DSR.

## Hypothese

Un RSI(14) sous 30 sur ES quotidien annonce un rebond exploitable, et exclure
les entrees du lundi ameliore le resultat (le lundi porte le saut de week-end
de 49 h, cf. [[reference/donnees]]).

## Montage

- Config : [examples/rsi_survendu_hors_lundi.json](../../examples/rsi_survendu_hors_lundi.json)
- Donnees : `ES.v.0`, 1 min reechantillonne en `day`, 2732 barres, 10,57 ans
- Vocabulaire employe : `rules@1` + `all_of`, `any_of`, `compare`, `primitive`
  (`rsi@1`, `atr@1`), `time`, `position`, `arith`, `price`, `constant`
- Commande : `rsl run examples/rsi_survendu_hors_lundi.json`
- Empreinte : `80e646bf9477a627e0ac1344a2f3a4a0bfbb252350fff560087925395824fdd2`
- **Rapport non archive** : aucun `--out`. L'essai n'est donc pas rejouable en
  l'etat, et `rsl verify` rend d'ailleurs `2` (arbre de travail modifie).

## Resultat

```
Echantillon  2732 barres, 10.57 an(s), 258.5 periodes/an (mesure)
Rendement    total +21.40 %   CAGR +1.85 %
Risque       vol +4.14 %   Sharpe 0.46   Sortino 0.72
Drawdown     quotidien -7.65 % (1534 j sous l'eau)
Activite     49 trades   hit +61.22 %   profit factor 1.88   exposition +15.89 %
Moments      asymetrie +2.821, kurtosis 77.333, 2731 observations
```

Walk-forward glissant, `--train 500 --test 250`, 9 plis :

```
Sharpe       moyen 0.60   median 0.49   dispersion 1.20
Plis         9 au total, +66.67 % positifs
Extremes     pire pli 4 (-2.85 %)   meilleur pli 6 (+9.75 %)
Compose      +18.77 %
Concentration 54 % du resultat vient d'un seul pli
```

## Lecture

Le profil est le meme que celui de [[experiments/sma-es-daily-walkforward]] :
un Sharpe agrege honnete, et **54 % du resultat dans un pli sur neuf**. La
kurtosis de 77 et l'asymetrie de +2,8 disent la meme chose autrement -- le
resultat tient a quelques barres. C'est exactement la situation que
[[lessons]] L1 decrit.

Ce qui n'est **pas** teste : le filtre « hors lundi » n'a pas ete compare a son
absence. Sans ce temoin, l'hypothese n'est pas evaluee -- elle est seulement
illustree. Faire la comparaison couterait un second essai, et il faudrait
l'enregistrer.

## Verdict

`non-conclusif` : la strategie tourne et se comporte comme ses voisines, mais
l'hypothese du filtre calendaire n'a pas ete mise a l'epreuve faute de temoin.
Aucune ligne au ledger -- rien n'est ecarte, l'essai est simplement incomplet.

## Liens

[[experiments/sma-es-daily-walkforward]] · [[reference/vocabulaire-signaux]] ·
[[concepts/deflated-sharpe-ratio]] · [[lessons]]
