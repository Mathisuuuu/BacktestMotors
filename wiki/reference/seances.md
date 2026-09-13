---
type: reference
updated: 2026-09-13
autorite: src/rsl/data/session.py
---

# Seances — routeur

> Page routeur. L'autorite est [src/rsl/data/session.py](../../src/rsl/data/session.py)
> pour le calcul, et [src/rsl/config.py](../../src/rsl/config.py) pour la
> declaration.

Le socle a longtemps refuse toute notion de seance, et il avait raison : les
series continues `.v.0` sont trouees, et inferer une frontiere d'un trou est une
supposition. Ce qui a change au 2026-09-11 n'est pas ce refus — c'est qu'une
seance peut desormais etre **declaree**. Une declaration ne devine rien.


## Depuis le 2026-09-13 : la seance ancre aussi les FENETRES

`rolling.across: "sessions"` compte `window` en seances, au meme rang ;
`session_lag` recule de N seances, au meme rang. Norme en
[docs/execution-model.md](../../docs/execution-model.md) §1.3, sous « Fenetres
comptees en seances ».

Ce qu'elles remplacent : `rolling.stride`, qui comptait des BARRES et supposait
donc des seances de longueur egale. **Les donnees ne le verifient pas** — sur
NQ, 1 362 barres les jours pleins et 435 le vendredi, la seance ouverte le
vendredi a 9 h 30 se fermant avant le week-end. Une semaine sur une, sur dix
ans.

Le chiffre qui a tranche : sur la strategie Zarattini, les deux ecritures de
`sigma[tau]` different a **100 %** des points de controle ou toutes deux sont
definies, de **28,3 % en mediane**. Ce n'etait donc pas une approximation.

Deux choses a savoir avant de s'en servir :

- une seance ECOURTEE n'a pas de barre au rang demande, et la fenetre rend
  `None` plutot qu'une barre voisine. Sur NQ avec `window: 60`, 33 % des barres
  ont une fenetre complete, **88 % aux douze points de controle** ;
- le `warmup_bars` de ces noeuds ne compte pas les seances : nul ne sait
  combien de barres elles font avant d'avoir lu les donnees. Declarer
  `min_warmup_bars` au niveau du run.

Reprend la ligne du [[Failed Ideas/ledger]] du 2026-09-11
(`rolling.across: sessions_same_offset`), dont les deux conditions de reprise
etaient remplies.


## Depuis le 2026-09-12 : la seance ancre aussi le DECOUPAGE

Le calendrier declare ne sert plus seulement aux noeuds `session` et
`cumulative`. C'est lui qui dit ou commence une barre de 4 h :
[docs/execution-model.md](../../docs/execution-model.md) §1.3. Une periode
intra-journaliere sans `session` est refusee a la validation.

Consequence a connaitre avant de s'en servir : deux instruments dont les
seances different n'ont plus aucune frontiere commune en intra-journalier. Le
decoupage ancre sur la seance est un outil **mono-instrument**.

Et une lecon : une declaration exacte ne decrit pas forcement le fichier. Voir
[[lessons]] L22, ou 74 tranches d'ES sur 16 417 auraient fuit malgre une seance
correctement declaree.

## Declarer

```json
"data": [{
  "root": "ES",
  "path": "indices/ES_v0_1m.parquet",
  "session": { "start": "17:00", "end": "16:00", "timezone": "America/Chicago" }
}]
```

Trois champs, aucun defaut. La declaration vit dans la **specification**, donc
elle entre dans le `config_hash` : deux personnes qui declarent des seances
differentes ne peuvent pas croire avoir fait le meme run. Sans elle, les noeuds
`session` et `cumulative` **levent** — le socle continue de refuser d'inventer.

## Comment une barre est rattachee

Une barre appartient a la seance ouverte a la **derniere occurrence de l'heure
d'ouverture qui precede son horodatage de cloture**. Deux proprietes de cette
regle comptent :

- les seances a cheval sur minuit ne sont pas un cas particulier. La seance ES
  court de 17 h a 16 h heure de Chicago ; une frontiere a minuit UTC la
  couperait en deux sans rien dire ;
- elle est **causale** : elle ne regarde jamais la barre suivante.

`is_last` decoule de l'heure de **fermeture declaree**, pas de l'existence d'une
barre suivante. Consequence assumee : si les dernieres barres d'une seance
manquent, aucune barre n'est marquee derniere ce jour-la.

## Ce qui est lisible, et quand

| Champ de `session` | `lag: 0` | `lag >= 1` |
|---|---|---|
| `open` | oui — connu des la premiere barre | oui |
| `high`, `low`, `close`, `volume` | **non**, la seance n'est pas finie | oui |
| `bar_index`, `minutes_from_open`, `is_first`, `is_last` | oui | **non**, ils decrivent la barre courante |

`lag` se compte en **seances**, pas en barres — toute la difference avec le
champ `lag` du noeud `price`.

## `cumulative` : la fenetre a longueur variable

Le VWAP ancre sur la seance s'ecrit par composition, sans primitive nouvelle :

```
arith(/, cumulative(sum, arith(*, price(close), price(volume))),
         cumulative(sum, price(volume)))
```

Statistiques : `sum`, `mean`, `min`, `max`, `first`, `last`, `count_true`.
Pas de `reset: never` — un cumul depuis l'origine aurait un cout dependant de
la position dans l'echantillon et un warmup indefinissable. Voir le
[[Failed Ideas/ledger|ledger]].

## Le futur n'entre pas par la

C'est le seul endroit du vocabulaire ou un agregat est calcule **a la
construction du magasin**, sur l'echantillon entier, plutot que barre par barre
a l'evaluation. C'est exactement le genre d'ajout par lequel le futur peut
entrer sans qu'on le voie.
[tests/adversarial/test_session_closure.py](../../tests/adversarial/test_session_closure.py)
le verifie : corrompre toutes les barres apres un point ne change **aucune**
valeur de seance lue avant ce point.

## Limites connues

- **Un calendrier par instrument, constant sur tout l'echantillon.** Les
  horaires d'echange ont change dans l'histoire ; declarer les horaires actuels
  sur dix ans est anachronique, exactement comme les marges statiques que
  [[reference/donnees]] signale deja.
- **Ni feries ni seances ecourtees.** Une demi-seance est traitee comme une
  seance pleine qui n'a simplement pas de barres apres son heure de fermeture,
  donc aucune barre n'y porte `is_last`.
- **Cout de `cumulative`** : le sous-arbre est reevalue une fois par barre
  ecoulee depuis l'ouverture. Sur une seance de 1 380 barres d'une minute, la
  derniere barre l'evalue 1 380 fois.

## Liens wiki

[[reference/donnees]] · [[reference/vocabulaire-signaux]] ·
[[concepts/look-ahead-bias]] · [[Failed Ideas/ledger]]
