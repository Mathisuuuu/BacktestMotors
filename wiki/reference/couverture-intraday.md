---
type: reference
updated: 2026-09-14
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

| | mesure |
|---|---|
| **Elements** de strategie (71) | **63 OK**, 3 partiels, 5 impossibles — **88,7 %** |
| **Familles** de strategie (25) | **21 realisables**, 4 bloquees — **84,0 %** |

Le second est le chiffre honnete. Un pourcentage d'elements **surestime** la
couverture : une strategie est une COMBINAISON, et un seul element manquant
bloque toute une famille. Les deux comptages ne divergent pas beaucoup ici, ce
qui dit quelque chose d'utile — **les manques sont concentres**, pas disperses.

## Ce qui bloque, et c'est tout

Quatre familles, quatre causes distinctes, aucune redondante.

| Famille bloquee | Cause | Nature |
|---|---|---|
| Reprise de niveau evitee | retenir un PRIX arbitraire d'une barre a l'autre | vocabulaire |
| Reduction apres serie de mauvais JOURS | `cumulative` remet a zero a chaque seance | vocabulaire |
| Trading d'annonce macro | aucun canal de donnees exogene | donnees |
| Scalping sur carnet | le moteur est a la BARRE | moteur |

Et trois reserves, qui s'ecrivent mais pas exactement :

- **arret sur perte NETTE du jour** — `close < entry_price` a la derniere barre
  en position approxime la perte ; les FRAIS et le prix du fill de sortie sont
  invisibles au vocabulaire ;
- **taille fonction de la force du signal** — possible par `ranking@1` (poids
  `signal`), pas par les regles de dimensionnement de `rules@1` ;
- **deux ancrages de seance differents** — accepte sur barres brutes, refuse en
  intra-journalier reechantillonne, et ce refus est deliberé.

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

Restent, par ordre d'utilite decroissante pour ce perimetre :

1. **le calendrier d'evenements** — sur futures intraday, FOMC et NFP font la
   seance, et rien ne permet de les voir ;
2. **la memoire au-dela de la seance** — `cumulative` ne franchit pas la nuit,
   donc aucune regle ne peut reagir a une serie de mauvais jours ;
3. **la memoire d'un niveau** — retenir un prix d'une barre a l'autre.

## Liens wiki

- [[reference/vocabulaire-signaux]] — les 24 types de noeuds et 136 primitives
- [[reference/seances]] — ce que le calendrier declare rend possible
- [[Failed Ideas/ledger]] — `reset: never` y figure, avec son motif
