---
type: hub
updated: 2026-09-12
---

# Index

> **Premier fichier lu a chaque session.** C'est le catalogue : une ligne par
> page, avec de quoi decider s'il faut l'ouvrir. Il n'explique rien lui-meme —
> il oriente. Toute page creee dans `wiki/` doit apparaitre ici le jour meme,
> sinon elle est orpheline et personne ne la retrouvera.
>
> Ordre de lecture en debut de session : **cette page**, puis
> [[Failed Ideas/ledger]], puis [[hot]].

## De quoi parle ce wiki

`research-strategy-lab` — socle de backtest event-driven, deterministe, dans
lequel le look-ahead bias est structurellement impossible. Le depot est la
**verite terrain** d'un systeme plus large : lire des papers, en extraire une
specification de strategie, la compiler en backtest.

**Unite de travail : l'essai.** Une page de `experiments/` = une strategie
evaluee sur un echantillon avec une configuration = une ligne du compteur
d'essais du Deflated Sharpe.

Depuis le 2026-09-12, ce compteur a une source MACHINE et durable :
[essais/registre.jsonl](../essais/registre.jsonl), alimente par
`rsl run --archive`. Les pages d'`experiments/` portent le jugement - hypothese,
verdict, ce qu'il ne faut pas conclure ; le registre porte les faits. Quand les
deux se contredisent, le registre a raison sur les chiffres et la page sur le sens.

---

## Hubs

- [[index]] — cette page. Le catalogue.
- [[SCHEMA]] — le reglement : gabarits de page, recettes, procedure de lint.
- [[log]] — journal append-only, une ligne datee par evenement.
- [[hot]] — etat courant, **auto-genere**, plus un bloc `Next Actions` editable.
- [[lessons]] — ce qu'on sait maintenant, transversal aux experiences.
- [[Failed Ideas/ledger]] — **a lire avant tout travail** : les idees mortes et
  la raison de leur mort.

## Experiences — `experiments/`

- [[experiments/sma-es-daily-walkforward|SMA ES quotidien — walk-forward 9 plis]] — Sharpe 0,60 agrege contre 57 % du resultat dans un seul pli. Verdict : `fragile`.
- [[experiments/dsr-grille-sma-8-essais|Deflated Sharpe — grille SMA, 8 essais]] — DSR `SIGNIFICATIF`, sans portee a 8 essais. Verdict : `non-conclusif`.
- [[experiments/paire-es-nq-retour-a-la-moyenne|Paire ES/NQ, retour a la moyenne du ratio]] — Sharpe 0,61 sur un echantillon, sans walk-forward. Premiers chiffres ou le terme distant compte reellement. Verdict : `non-conclusif`.
- [[experiments/pbo-grille-large-462-sma|PBO d'une grille SMA de 462 configurations]] — **elargir la grille a empire le resultat, comme la theorie le prevoit** : PBO 0,833 sur les 462, contre 0,80 sur seize. Le tableau par S se lit avec precaution - a partir de S=6 le retrait des inactives biaise la grille vers les fenetres courtes. Verdict : `negatif`.
- [[experiments/pbo-grille-sma-es-quotidien|PBO d'une grille SMA 4x4 — ES quotidien]] — **le resultat le plus defavorable du depot, et le plus utile.** PBO 0,70-0,80 : le processus qui choisit la meilleure configuration n'a pas montre de pouvoir predictif. Le DSR de l'exemple phare tombe de 0,9719 a 0,0000 une fois les 31 essais comptes. Verdict : `negatif`.
- [[experiments/allocation-momentum-12-1-trois-regles|Momentum 12-1, trois regles d'allocation]] — la repartition change le Sharpe de 0,45 a 0,84 sur les MEMES decisions. **Trois des six essais mesuraient autre chose qu'eux-memes** : la troncature en contrats eliminait les gros contrats d'abord. Verdict : `non-conclusif`.
- [[experiments/rsi-survendu-hors-lundi|RSI survendu hors lundi — ES quotidien]] — Sharpe 0,46 ; 54 % du resultat dans un pli sur neuf. Sert de preuve qu'une strategie neuve s'ecrit en JSON seul. Verdict : `non-conclusif`.
- [[experiments/zarattini-nq-intraday-60-30|Zarattini NQ intraday 60/30/1.5]] — **-25,62 %, puis +111,53 %, puis +256,80 % sur la MEME strategie** : le capital d'abord (5 080 ordres sur 5 084 refuses pour marge), l'ancrage de `sigma` ensuite (`stride: 390` sur des seances de 1 362 barres). Aucun des trois ne passe le compteur d'essais, mais le DSR monte de 0,1107 a 0,6148. Verdict : `negatif`.

## Concepts — `concepts/`

- [[concepts/look-ahead-bias]] — la fuite du futur n'est pas interdite, elle est rendue inexprimable. La raison d'etre du depot.
- [[concepts/context-curseur]] — magasin immuable + un entier. Pas de `len(ctx)`, pas de lag negatif, pas de NaN.
- [[concepts/determinisme]] — empreinte de resultat, `rsl verify`, et le champ `Rejouable` qui vaut `NON` des qu'une piece manque.
- [[concepts/registre-versionne]] — cle `(nom, version)` ; corriger, c'est publier `@2`.
- [[concepts/deflated-sharpe-ratio]] — le maximum d'un ensemble de tirages n'est pas un tirage.
- [[concepts/walk-forward]] — distinguer une performance repartie d'une performance concentree.

## Routeurs — `reference/`

Ces pages ne font autorite sur rien : elles disent ou est l'autorite.

- [[reference/contrat-anti-lookahead]] — vers [docs/no-lookahead.md](../docs/no-lookahead.md), normatif. Y compris ce que le socle **ne** garantit **pas**.
- [[reference/modele-execution]] — vers [docs/execution-model.md](../docs/execution-model.md), normatif. Points `[A ARBITRER]` encore ouverts. **Inclut §6.3, les plafonds de portefeuille et ce qu'ils ne garantissent pas.**
- [[reference/vocabulaire-signaux]] — schemas engendres, `rsl catalogue`, moules `rules@1` / `panel_rules@1` / `ranking@1`.
- [[reference/donnees]] — 33,4 M barres a la MINUTE, agregeables de `5min` a `year`, series non ajustees au roulement, trous par defaut. **Contient un avertissement bloquant sur `rsl.data`.**
- [[reference/cli]] — commandes, codes de sortie `0/1/2`, boucle de developpement.
- [[reference/seances]] — calendrier de seance **declare** (`data[].session`), noeuds `session` et `cumulative`, et depuis le 2026-09-12 l'ANCRAGE des granularites intra-journalieres. Le socle ne devine toujours aucune frontiere.
- [[reference/tableau-de-bord]] — fenetre de resultats (`rsl gui`). **Contient la distinction MESUREE / RECONSTRUITE, a lire avant d'interpreter un chiffre filtre.**

## Sources — `research/`

- [[research/bailey-lopez-de-prado-dsr]] — source du DSR/PSR. Statut : `a-ingerer` (emplacement, pas resume).

---

## Conventions

| Regle | Detail |
|---|---|
| Les sources font foi | Le wiki **lie** vers `docs/`, `src/`, `examples/`, `schemas/` et les rapports de run. Il ne les recopie pas. Une page qui contredit le code a tort. |
| Une page = une chose | Un essai, un terme, une source, un routeur. Pas de page fourre-tout. |
| Dates absolues | `YYYY-MM-DD` partout, jamais « recemment ». |
| Le ledger ne s'efface pas | Une idee reprise devient une ligne nouvelle qui cite l'ancienne. |
| `hot.md` est genere | Seul le bloc `Next Actions` s'edite a la main. |

Gabarits et recettes completes : [[SCHEMA]].
