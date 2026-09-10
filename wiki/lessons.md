---
type: hub
updated: 2026-09-10
---

# Lecons

Synthese transversale. Une lecon arrive ici quand elle depasse l'experience qui
l'a produite — autrement dit quand elle changera une decision future. Chaque
lecon cite ce qui la fonde ; une lecon sans source est une opinion.

A distinguer de ses voisins :

- [[Failed Ideas/ledger]] = *ne refais pas ca*, une ligne par idee morte.
- **Ici** = *voici ce qu'on sait maintenant*, transversal, reformulable.
- [[log]] = *voici ce qui s'est passe quand*, jamais reecrit.

---

## L1 — Un chiffre agrege ne permet pas de decider

Sharpe 0,60 sur l'echantillon entier, et 57 % du resultat dans un pli sur neuf :
les deux decrivent le meme backtest. Tant qu'un resultat n'est pas decoupe, on ne
sait pas si on mesure une competence ou une fenetre chanceuse.

**Consequence operationnelle :** aucun resultat ne se rapporte sans sa
decomposition. Le drawdown est d'ailleurs deja rapporte deux fois — pleine
granularite et pas quotidien — parce que les deux valeurs different et que n'en
montrer qu'une serait un choix.

Fonde sur [[experiments/sma-es-daily-walkforward]] · [[concepts/walk-forward]]

## L2 — Le compteur d'essais n'a de valeur que tenu en continu

Le DSR prend en entree le nombre d'essais et leur dispersion. Ces deux nombres
ne peuvent pas etre reconstitues apres coup : un essai oublie gonfle
mecaniquement le DSR de tous les autres, et rien ne le signale.

**Consequence operationnelle :** l'essai est l'unite de travail du wiki.
Enregistrer l'essai **au moment ou il est fait**, y compris celui qui rate, y
compris celui dont on n'a pas envie de parler.

Fonde sur [[concepts/deflated-sharpe-ratio]] · [[experiments/dsr-grille-sma-8-essais]]

## L3 — Une garantie doit etre impossible a contourner, pas recommandee

Le parti pris du socle : la fuite du futur n'est pas interdite, elle est rendue
**inexprimable**. Pas de `len(ctx)`, pas de `lag` negatif, pas de NaN en cas de
fenetre insuffisante — une erreur a la place. On ne compte ni sur la discipline
du developpeur, ni sur la relecture, ni sur des conventions de nommage.

**Consequence operationnelle :** face a un choix de conception, preferer
systematiquement « le mauvais usage ne compile pas / leve » a « le mauvais usage
est documente ». Et quand une garantie ne peut pas etre fermee par du code, la
rendre **visible** plutot que la passer sous silence : c'est le role du champ
`Rejouable`, qui vaut `NON` des qu'une piece manque.

Fonde sur [[concepts/look-ahead-bias]] · [[concepts/context-curseur]] ·
[[concepts/determinisme]]

## L4 — Ce qui n'est pas genere ne peut pas etre faux

Les strategies descriptibles sont **interpretees** depuis du JSON par des moules
(`rules@1`, `panel_rules@1`, `ranking@1`), jamais compilees en Python. Un moule
parametre ne peut etre faux qu'une fois ; du code genere peut etre faux a chaque
generation, et un backtest faux ne leve pas d'exception.

Corollaire de meme famille : le contrat du vocabulaire est **engendre** depuis
les registres, pas saisi a la main, et les fichiers de `schemas/` sont compares
au registre a chaque execution des tests. Leur divergence est impossible par
construction, pas par vigilance.

Fonde sur [[reference/vocabulaire-signaux]] · [[Failed Ideas/ledger]]

## L5 — Un motif de `.gitignore` sans `/` initial frappe a toutes les
profondeurs

`data/` en premiere ligne de `.gitignore` etait destine au repertoire de donnees
a la racine. Il a aussi attrape `src/rsl/data/`, c'est-a-dire toute la couche
donnees : jamais commitee, absente de la copie de travail, alors que 20 fichiers
de `src/` et 27 de `tests/` l'importent et que le README la donne pour faite.

**Consequence operationnelle :** un motif d'ignore destine a un chemin precis
s'ecrit ancre — `/data/`, pas `data/`. Et apres tout ajout a `.gitignore`,
verifier ce qu'il attrape vraiment : `git status --ignored` ou
`git check-ignore -v <chemin>`.

Lecon plus large : le depot se decrit comme la verite terrain, mais un fichier
de configuration a silencieusement rendu le paquet central inexistant. Une
affirmation du README n'est pas une preuve d'existence.

Fonde sur [[reference/donnees]] · [[log]] (entree du 2026-09-10)

## L6 -- Un outil qui signale un probleme de style peut decrire un probleme de code absent

Avec `rsl.data` manquant, la chaine d'outils ne dit pas « il manque un paquet ».
Elle dit autre chose, et l'autre chose est plausible :

| Outil | Ce qu'il affiche | Ce que c'est vraiment |
|---|---|---|
| `ruff` | 28 × `I001 import block un-sorted`, « 28 fixable with `--fix` » | le chemin `src/rsl/data/` n'existe pas, donc `rsl.data` est classe en tiers. `src/` seul : `All checks passed` |
| `mypy` | 35 × `module is installed, but missing library stubs or py.typed` | le module n'est pas installe du tout -- le message est trompeur |
| `pytest` | `ImportError while loading conftest` | le seul des trois a nommer la vraie cause |

**Consequence operationnelle :** sur un arbre dont on sait qu'il est incomplet,
ne jamais lancer un correcteur automatique (`ruff --fix`, `--unsafe-fixes`, un
quick-fix d'IDE). Il graverait le symptome dans le code, et le vrai correctif
deviendrait ensuite une seconde vague de modifications en sens inverse. Corriger
la cause, relancer, et ne traiter comme defaut que ce qui reste.

Fonde sur [[reference/cli]] · [[Failed Ideas/ledger]] · [[log]] (2026-09-10)

