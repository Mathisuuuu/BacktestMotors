---
type: hub
updated: 2026-09-11
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

## L7 -- Un chemin absolu dans une empreinte rend l'empreinte incomparable

`BacktestSpec.canonical()` resolvait les chemins de donnees en absolu avant de
les hacher, pour qu'une meme commande lancee depuis deux repertoires differents
donne le meme `config_hash`. L'intention etait juste, la portee trop courte :
deux **machines** dont les cotations ne sont pas au meme endroit produisaient
deux `config_hash` differents pour le meme run.

Mesure du 2026-09-11, meme strategie et meme fichier a deux emplacements :

| | machine A | machine B |
|---|---|---|
| `config_hash` | `80c7c6c6fe8ecb02` | `df38f197b3943c35` |
| empreinte de resultat | `96e230f1197c040b...` | `96e230f1197c040b...` |

L'empreinte de resultat, elle, etait deja portable : elle ne porte que des
fills, des trades et des compteurs. Le defaut ne touchait donc pas le
determinisme du moteur -- il touchait la capacite de **deux personnes a
constater qu'elles ont lance le meme run**.

**Consequence operationnelle :** ce qui entre dans une empreinte destinee a etre
comparee entre machines ne doit contenir aucune coordonnee de machine -- ni
chemin absolu, ni nom d'utilisateur, ni separateur dependant du systeme. La
forme canonique d'un chemin relatif est normalisee en `/` pour cette raison
precise : sans cela, Windows hacherait `indices\ES` et Linux `indices/ES`.

Fonde sur [[reference/donnees]] · [[concepts/determinisme]] · [[reference/cli]]

## L8 -- Filtrer un resultat produit un chiffre nouveau, pas le meme chiffre restreint

Un tableau de bord invite a cliquer « longs seulement » et a lire le Sharpe qui
s'affiche comme s'il repondait a « et sans les shorts, ca donnait quoi ? ». Il
n'y repond pas. Les shorts ont occupe du capital et de la marge pendant tout le
run ; une courbe « longs seulement » n'a jamais ete vecue, elle est fabriquee
apres coup en n'accumulant que le P&L des trades retenus.

Ce qu'un filtre mesure vraiment : **la contribution de ce sous-ensemble au
resultat observe**. Ce qu'il ne mesure pas : le resultat qu'aurait donne une
strategie qui ne prend que ces trades — pour l'obtenir il faut lancer un autre
backtest, donc consommer un essai de plus ([[lessons]] L2).

**Consequence operationnelle :** une interface qui filtre doit dire en
permanence dans quel regime elle est. `rsl gui` affiche `COURBE MESUREE` ou
`COURBE RECONSTRUITE` a cote des filtres, et l'export texte recopie
l'avertissement. C'est la meme regle que L3 : ce qui ne peut pas etre ferme par
du code doit etre rendu **visible**, pas passe sous silence.

Corollaire de mise en oeuvre : sans aucun filtre, le tableau de bord ne
recalcule rien - il recopie `metrics.sharpe` du moteur, et un test compare les
deux. Un affichage qui reimplemente un calcul finit par en diverger.

Fonde sur [[reference/tableau-de-bord]] · [[lessons]] L1 · [[lessons]] L3

## L9 -- Un callback dont la bibliotheque possede le cycle de vie n'est pas un point d'extension

`PricePanel` reajustait l'echelle des prix a la fenetre visible via le signal
`xlim_changed` de matplotlib, connecte a la construction. Le reglage ne s'est
jamais applique : `Axes.clear()`, appele a chaque redessin, **reinitialise le
registre de callbacks**. La connexion disparaissait au premier trace, sans
erreur, sans avertissement.

Le symptome ne designait pas la cause : on voyait une echelle Y figee entre
2 000 et 7 000 pour une fenetre qui ne couvrait que 2 000-2 900, et l'hypothese
naturelle etait une erreur de calcul des bornes - alors que le calcul n'etait
simplement jamais execute.

**Consequence operationnelle :** quand un comportement doit survivre a chaque
cycle de vie d'un objet d'une bibliotheque tierce, l'appeler explicitement
depuis notre propre code plutot que s'abonner a un signal dont on ne controle
pas la duree de vie. Ici, une methode `_apres_fenetre()` appelee par notre
`_apply()` - trois lignes, et le comportement ne peut plus disparaitre.

Meme famille que L3 : preferer ce qui ne peut pas etre silencieusement defait.

Fonde sur [[reference/tableau-de-bord]] · `tests/unit/test_gui_charts.py`

## L10 -- Un numero de version n'est pas un nom de variante

`get_primitive` resout une reference **sans version** vers la plus recente
(`registry.py:124`). La consequence est mecanique et facile a manquer :
enregistrer une variante d'un indicateur sous le numero suivant change le sens
de toute specification qui ne l'epingle pas - sans modifier une ligne de la
primitive d'origine, et sans que rien ne le signale.

Les docstrings de `atr@1` et `rsi@1` proposent justement d'enregistrer la
variante de Wilder en `@2`. Suivi a la lettre, ce conseil ferait qu'une
specification ecrite `"ref": "atr"` passerait d'une moyenne arithmetique a une
moyenne exponentielle au prochain `git pull`. Elles ont ete publiees sous
`atr_wilder@1` et `rsi_wilder@1`.

**Consequence operationnelle :** `@n+1` est reserve a la **correction** d'un
comportement juge faux. Un comportement different mais legitime prend un **nom
different**. La question a se poser : « une specification existante voudrait-elle
ce nouveau comportement sans rien changer ? » Si oui, c'est une correction. Si
non, c'est une variante, et elle a besoin de son propre nom.

Corollaire : une extension purement **additive** d'un noeud publie - six
statistiques de plus sur `rolling@1` - ne demande pas de nouvelle version. Une
specification archivee continue de se reconstruire a l'identique, ce qui se
verifie et s'est verifie : les cinq empreintes d'exemples sont inchangees apres
l'ajout. La regle protege la rejouabilite, pas le numero.

Fonde sur [[concepts/registre-versionne]] · [[Failed Ideas/ledger]] ·
[[reference/vocabulaire-signaux]]
