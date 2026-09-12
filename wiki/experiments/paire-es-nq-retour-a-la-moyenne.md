---
type: experiment
updated: 2026-09-11
statut: termine
verdict: non-conclusif
strategie: panel_rules@1
instruments: [ES.v.0, NQ.v.0]
essais: 1
---

# Paire ES/NQ, retour a la moyenne du ratio — quotidien

> Cet essai est enregistre pour une raison particuliere : **il tournait deja,
> et il ne faisait pas ce qu'il annoncait**. Jusqu'au 2026-09-11, le terme
> distant de son signal etait inerte, et l'exemple negociait ES seul. Les
> chiffres ci-dessous sont les PREMIERS qui correspondent a l'hypothese
> ecrite. Les precedents, publies dans plusieurs rapports, decrivaient une
> autre strategie que celle qu'on croyait lire.

## Hypothese

Le ratio `ES / NQ` revient a sa moyenne. Entrer long sur ES quand son z-score
sur 120 jours descend sous -1,5 ; sortir au retour a zero, ou apres 40 barres.

## Montage

- Config : [examples/strategies/paire_es_nq.json](../../examples/strategies/paire_es_nq.json) —
  **inchangee** ; c'est le moteur qui a ete corrige, pas la specification, et
  le `config_hash` le montre (identique avant et apres).
- Donnees : `ES.v.0` et `NQ.v.0`, 1 min reechantillonnes en `day`, panneau de
  2633 lignes, 10,19 ans
- Vocabulaire : `panel_rules@1` + `rolling(zscore)`, `arith`, `peer`,
  `position`, `compare`, `any_of`
- Commande : `rsl run examples/strategies/paire_es_nq.json --settings examples/reglages/paire_es_nq.json --symbol ES.v.0`
- Empreinte : `479348a0ff34b8e36d5ed79d26d9642573ea67d6890bf193fff2c1ca4bb86ac3`
- **Rapport non archive** : aucun `--out`, donc pas rejouable en l'etat.

## Resultat

```
Echantillon  2633 barres, 10.19 an(s), 258.5 periodes/an (mesure)
Rendement    total +13.59 %   CAGR +1.26 %
Risque       vol +2.08 %   Sharpe 0.61   Sortino 0.85
Drawdown     quotidien -5.64 % (570 j sous l'eau)
Activite     149 trades   hit +53.69 %   profit factor 1.77   exposition +44.36 %
Moments      asymetrie -0.919, kurtosis 24.096, 2632 observations
```

## Ce qu'il ne faut PAS conclure

Le Sharpe passe de 0,24 a 0,61 entre l'ancien comportement et le nouveau.
**Ce n'est pas une amelioration de la strategie.** C'est une strategie
DIFFERENTE : l'ancienne ne regardait pas NQ. Comparer les deux chiffres n'a
pas de sens, et les presenter comme un avant/apres serait trompeur.

Trois raisons de ne rien conclure de 0,61 :

- **Un seul echantillon, aucun walk-forward.** Le DSR affiche
  `SIGNIFICATIF` a 0,9722, mais il se confond avec le PSR a un seul essai
  enregistre — le programme le dit lui-meme dans son avertissement. Voir
  [[concepts/deflated-sharpe-ratio]].
- **Les seuils n'ont pas ete choisis pour ces donnees, mais ils n'ont pas non
  plus ete choisis au hasard** : -1,5 et 120 jours viennent de l'exemple
  d'origine, ecrit quand le signal etait inerte. Ils n'ont donc jamais ete
  evalues sur ce qu'ils gouvernent aujourd'hui.
- **Le roulement n'est pas ajuste** ([[reference/donnees]]). Un ratio entre
  deux series `.v.0` saute a chaque roulement, et les deux ne roulent pas le
  meme jour. Une part du signal est mecanique.

## Verdict

`non-conclusif`. Ce qui est etabli, c'est que la strategie **fait desormais ce
qu'elle decrit**. Sa valeur reste a mesurer, et un walk-forward est le
prealable minimum — voir [[concepts/walk-forward]].

## Liens

[[reference/vocabulaire-signaux]] · [[lessons]] L18 · [[log]] (2026-09-11)
