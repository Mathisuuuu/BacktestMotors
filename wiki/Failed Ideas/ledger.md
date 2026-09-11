---
type: ledger
updated: 2026-09-11
---

# Ledger des idees abandonnees

> **A lire AVANT de commencer un travail.** Ce fichier existe pour une seule
> raison : empecher de refaire un chemin qui est deja mort. Une idee est ici
> parce qu'elle a ete tentee ou serieusement envisagee, puis ecartee **pour un
> motif nommable**. Si une idee qu'on s'apprete a proposer figure dans ce
> tableau, il faut d'abord lire la colonne « Pourquoi » et expliquer ce qui a
> change depuis.

Regles :

- Une ligne par idee. On n'efface jamais une ligne.
- La colonne **Pourquoi** doit contenir un mecanisme, un chiffre ou une
  contradiction avec une garantie du socle. « Ne marchait pas » est refuse.
- Une idee reprise plus tard devient une **nouvelle ligne** qui reference
  l'ancienne, pour que la trace du revirement reste visible.
- Le rejet d'une approche technique compte autant que le rejet d'une strategie :
  les deux coutent du temps a redecouvrir.

## Idees ecartees

| Date | Idee | Ce qui a ete tente | Pourquoi ca a echoue | A retenter si | Lien |
|---|---|---|---|---|---|
| 2026-09-10 | pandas pour la couche donnees | Envisage, ecarte au profit de polars | Index implicite : alignement et forward-fill silencieux sur les jointures multi-instruments. Ce sont exactement les deux voies par lesquelles le look-ahead entre dans une couche de donnees — il serait impossible de garantir le contrat en s'appuyant dessus | Jamais, tant que le contrat anti-look-ahead tient | [[concepts/look-ahead-bias]] |
| 2026-09-10 | Generer du code Python de strategie a partir d'une specification | Ecarte par construction : `rules@1`, `panel_rules@1` et `ranking@1` interpretent le JSON au lieu de le compiler | Du code genere peut etre faux, et un backtest faux est indetectable sans relecture ligne a ligne. Un moule parametre ne peut etre faux qu'une fois, la ou du code genere peut etre faux a chaque generation | Le vocabulaire JSON bute sur un cas qu'aucun moule ne couvre, ET une methode de verification du code genere existe | [[reference/vocabulaire-signaux]] |
| 2026-09-10 | Noeuds de signaux a memoire interne (pour l'etat de position) | Ecarte : l'etat de position est calcule par le runner et expose par le `Context` | Un noeud a etat survit d'un run a l'autre, ce qui casse le determinisme et donc la reproductibilite bit-a-bit. La garantie « deux runs identiques donnent la meme empreinte » deviendrait invalidable | Jamais sans une remise a zero prouvee entre runs, ce qui reviendrait a deplacer le probleme | [[concepts/determinisme]], [docs/no-lookahead.md](../../docs/no-lookahead.md) §2.5 |
| 2026-09-10 | Fenetres exprimees en duree (« 20 jours », « 1 heure ») | Ecarte : toute fenetre est en **nombre de barres** | Les trous sont la norme sur ces series : coupure de maintenance quotidienne d'une heure, week-ends de 49 h, feries. Une fenetre en duree obligerait le moteur a reconstruire des barres absentes, donc a inventer des donnees | Un jeu de donnees sans trous ET un besoin reel exprime en duree calendaire | [[reference/donnees]] |
| 2026-09-10 | Annualiser avec un facteur suppose (`sqrt(252 * 1440)` a la minute) | Ecarte : le pas d'annualisation est **mesure sur l'echantillon** | Le facteur suppose revient a postuler un marche ouvert 24/7/365 : il gonfle le Sharpe d'un facteur ~2 sur des donnees minute. Un chiffre faux d'un facteur deux n'est pas une approximation, c'est une conclusion differente | Jamais | [[concepts/deflated-sharpe-ratio]] |
| 2026-09-10 | Corriger une primitive publiee en place | Ecarte : les registres sont versionnes, la cle est `(nom, version)` et reenregistrer une cle existante leve | Un rapport de run archive epingle `sma@1`. Si `sma@1` changeait de sens, le run cesserait d'etre rejouable et la verite terrain serait perdue retroactivement | Jamais. Corriger = publier `@2`, `@1` reste | [[concepts/registre-versionne]] |
| 2026-09-10 | Presenter le decoupage ancre et le decoupage glissant comme deux mesures independantes | Ecarte : un test verifie au contraire leur **egalite** | Tant qu'aucun parametre n'est optimise, la fenetre d'apprentissage ne sert que d'historique : les deux decoupages produisent exactement les memes plis. Les presenter comme deux mesures suggererait une confirmation croisee qui n'existe pas | Une selection de parametres s'insere entre les deux fenetres — alors le choix comptera vraiment | [[concepts/walk-forward]] |
| 2026-09-10 | Traiter les 28 `I001` de `ruff` en lancant `ruff --fix` | Diagnostic : 28 erreurs, une par fichier de test, toutes dans des fichiers important `rsl.data` ; `src/` seul passe `All checks passed` | Ce sont des **symptomes de P1**, pas un defaut de style. Ruff resout le chemin complet du sous-module : `src/rsl/engine/` existe donc `rsl.engine` est premiere partie, `src/rsl/data/` est absent donc `rsl.data` est classe **tiers** et doit etre groupe avec `pytest`. Preuve : avec des stubs `feed.py` + `schema.py`, `test_risk.py` passe et le total tombe de 28 a 12. `--fix` reecrirait 28 fichiers de test pour graver la casse dans l'arbre, et les signalerait tous en sens inverse au retour de `rsl.data` | Jamais. Les 28 erreurs doivent disparaitre d'elles-memes quand `rsl.data` revient ; si elles persistent alors, ce sera un vrai defaut | [[lessons]] L6 |
| 2026-09-11 | Publier la variante Wilder de `atr` et `rsi` en `atr@2` / `rsi@2` | Ecarte : publiees sous des NOMS distincts, `atr_wilder@1` et `rsi_wilder@1` | `get_primitive` resout une reference sans version vers la **plus recente** (`registry.py:124`). Publier Wilder en `@2` ferait basculer toute specification ecrite `"ref": "atr"` d'une moyenne simple a une moyenne exponentielle, sans aucun changement de code et sans le dire. Les docstrings de `atr@1` et `rsi@1` proposent pourtant ce chemin : elles decrivent un piege | Jamais tant que la resolution sans version existe. `@2` reste reserve a la CORRECTION d'un comportement, pas a une variante | [[concepts/registre-versionne]] |
| 2026-09-11 | Publier `rolling@2` pour ajouter six statistiques | Ecarte : les statistiques sont ajoutees a `rolling@1`, qui est une extension ADDITIVE | Une specification archivee avec `stat: "mean"` se reconstruit a l'identique - verifie, les 5 empreintes d'exemples sont inchangees apres l'ajout. Un `rolling@2` aurait fragmente le vocabulaire en deux noeuds au comportement identique sur leur partie commune, pour aucune garantie supplementaire | Le jour ou une statistique existante devrait changer de sens : ce serait une correction, donc `@2` | [[reference/vocabulaire-signaux]] |
| 2026-09-11 | `mplfinance` pour les bougies du tableau de bord | Ecarte : bougies dessinees a la main (`LineCollection` + `bar`) | Exige pandas, dont le rejet figure ci-dessus. Le motif de ce rejet vise la couche donnees et non l'affichage, donc l'utiliser ne contredirait pas la lettre du ledger - mais vingt lignes suffisent, et une dependance lourde pour un graphique ne se justifie pas | Un besoin de rendu financier avance (profils de volume, renko, point & figure) que le trace manuel ne couvre pas | [[reference/tableau-de-bord]] |

## Idees mises en attente (ni retenues, ni mortes)

Distinctes des precedentes : rien ne les invalide, elles ne sont simplement pas
faites. A ne pas confondre avec un echec.

| Date | Idee | Etat | Ce qui manque |
|---|---|---|---|
| 2026-09-10 | PBO / CSCV (probabilite de sur-ajustement) | Protocole ecrit, pas d'implementation | Une implementation et une grille d'essais assez large pour que le chiffre veuille dire quelque chose |
| 2026-09-10 | Primitive dediee remplacant `rolling` sur les cas couteux | Cout assume, non traite | Un cas precis mesure comme trop lent. `rolling` reevalue son sous-arbre `window` fois par barre (360 evaluations pour une fenetre de 120 et un sous-arbre de 3 noeuds) |
| 2026-09-10 | Optimisation de parametres dans le runner walk-forward | Hors perimetre de la phase | Une decision explicite : le runner n'optimise rien aujourd'hui, et la fenetre `train` sert d'historique, pas d'echantillon d'apprentissage |
