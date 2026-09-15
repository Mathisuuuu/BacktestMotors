---
type: reference
updated: 2026-09-15
autorite: tests/couverture/recensement_intraday.py
---

# Couverture intraday — que sait-on ecrire ?

> Page de RESULTAT. L'autorite est
> [tests/couverture/recensement_intraday.py](../../tests/couverture/recensement_intraday.py),
> qui se relance en une commande et refait la mesure :
>
>     python tests/couverture/recensement_intraday.py

## Le denominateur, avant le chiffre

Un pourcentage de couverture n'a de sens que contre une liste explicite. Celle
du recensement est **ecrite a la main**, donc discutable — c'est pourquoi elle
vit dans un fichier lisible et modifiable plutot que resumee par un nombre.

Chaque element y est **ecrit en JSON et evalue** sur 4 680 barres de 5 minutes.
Aucun verdict n'est donne de memoire.

## Deux comptages, et pourquoi il en faut deux

| | 2026-09-14, premier jet | apres les ajouts du 14 | **2026-09-15** |
|---|---|---|---|
| **Elements** (71) | 63 OK — 88,7 % | 67 OK, 2 partiels, 2 impossibles — 94,4 % | **70 OK**, 0 partiel, 1 impossible — **98,6 %** |
| **Familles** (25) | 21 realisables — 84,0 % | 24 realisables, 1 bloquee — 96,0 % | **24 realisables**, 1 bloquee — **96,0 %** |

Le saut du 15 vient pour **deux tiers d'une correction, pas d'un ajout** : deux des quatre manques etaient des verdicts ECRITS A LA MAIN devenus faux ([[lessons]] L36). Le troisieme, lui, est un vrai ajout — la serie exogene.

Le second est le chiffre honnete. Un pourcentage d'elements **surestime** la
couverture : une strategie est une COMBINAISON, et un seul element manquant
bloque toute une famille. Les deux comptages ne divergent pas beaucoup ici, ce
qui dit quelque chose d'utile — **les manques sont concentres**, pas disperses.

## Ce qui bloque, et c'est tout

Quatre familles, quatre causes distinctes, aucune redondante. Trois sont
comblees depuis.

| Famille | Cause | Etat |
|---|---|---|
| Reprise de niveau evitee | retenir un PRIX d'une barre a l'autre | **comble** — `value_when` |
| Reduction apres serie de mauvais JOURS | `cumulative` remettait a zero chaque seance | **comble** — `cumulative.sessions` |
| Trading d'annonce macro | aucun canal de donnees exogene | **comble** — section `events` + noeud `event` |
| Scalping sur carnet | le moteur est a la BARRE | **bloque**, et hors du perimetre declare |

Le dernier element non couvert est le meme que la derniere famille bloquee :
**le carnet d'ordres**. Il exige des TICKS, donc un autre moteur d'execution
— c'est l'item ouvert cote Nautilus. Tant qu'il tient, **98,6 % est le
plafond**, et c'est une information plus utile qu'un objectif de 99 %.

Les trois combles touchaient chacun une idee que le ledger avait ecartee.
Aucune n'a ete rouverte : chacune remplissait la condition de reprise que le
ledger avait ECRITE ([[lessons]] L34).

### Les deux reserves etaient fausses (corrige le 2026-09-15)

Toutes deux vivaient dans le dictionnaire `HORS_SIGNAL` du recensement, commente
« ce que le CODE ne peut pas trancher ». Un verdict que le code ne verifie pas
ne vieillit pas avec le code.

- **taille fonction de la force du signal** — la note disait « pas par les regles
  de dimensionnement de `rules@1` ». Or `risk.sizing.kind = signal` prend une
  expression arbitraire avec `max_contracts` obligatoire, et
  [nq_zarattini_60_30_15](../../examples/reglages/nq_zarattini_60_30_15.json)
  est un `rules@1` **mono-instrument** qui s'en sert — 923 trades a taille
  variable. J'avais ajoute le mecanisme moi-meme la veille sans rouvrir le
  recensement.
- **deux ancrages de seance differents** — mesure : ES 09:30-16:00 New York en
  15min et NQ 08:30-15:00 Chicago en 1m **coexistent**, chacun avec son index de
  seance. Le seul cas refuse est DEUX series reechantillonnees en
  intra-journalier a ancrages differents, et ce refus porte son propre motif
  mesure : le panneau produirait **100 % de lignes a un seul instrument**. Ce
  n'est pas un manque, c'est une garde.

### Ce qui a ete AJOUTE le 2026-09-15

- **donnees fondamentales ou de sentiment** — section `exogenous` + noeud
  `exogenous` (`value`, `age_minutes`). `evenements.py` nommait lui-meme le
  manque : « ce module ne sait rien dire d'un libelle ou d'une surprise
  chiffree ». Le piege n'est PAS celui des evenements — lire la derniere valeur
  connue est aussi causal qu'un `lag` — mais une donnee fondamentale porte DEUX
  dates, ce qu'elle mesure et quand elle a paru. Le rapport COT du mardi parait
  le vendredi. D'ou la signature exigee : `horodatee_a_la_publication` OU un
  `publication_lag_minutes` strictement positif.

## Ce que le chiffre ne dit pas

- **« Exprimable » n'est pas « fidele ».** Une strategie peut s'ecrire et etre
  mal simulee : conventions de fill, marges, slippage constant. La couverture
  mesure le VOCABULAIRE, pas le realisme du moteur.
- **Le catalogue est celui de la litterature classique**, pas celui de ce qui
  se trade. Une famille absente du catalogue n'apparait dans aucun des deux
  pourcentages.
- **Il n'y a pas de population de reference.** Personne ne sait combien de
  strategies intraday « existent ». 84 % veut dire « 21 des 25 familles que
  cette page nomme », et rien de plus.

## Sous le perimetre declare

Le perimetre en vigueur — intraday, futures, **une position a la fois**,
principalement mono-actif — retire une des quatre familles bloquees : le
scalping sur carnet n'en releve pas. Il rend aussi sans objet deux limites du
vocabulaire qui comptaient ailleurs : une seule position nette par symbole, et
le dimensionnement qui ne voit pas le signal.

Les trois manques que ce perimetre rendait genants sont combles. **Il ne reste
que le scalping sur carnet**, qu'une strategie a une position et a decisions a
la barre ne demande pas.

Restent deux reserves, aucune bloquante ici : la taille proportionnelle au
signal (possible en transversal, pas en mono-actif — sans objet a une position)
et deux ancrages de seance en intra-journalier reechantillonne (refus
delibere).

## Liens wiki

- [[reference/vocabulaire-signaux]] — les 26 types de noeuds et 136 primitives
- [[reference/seances]] — ce que le calendrier declare rend possible
- [[Failed Ideas/ledger]] — `reset: never` y figure, avec son motif
