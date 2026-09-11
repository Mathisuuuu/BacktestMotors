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

## L11 -- Un test dont le verdict depend de l'etat du depot ne garde rien

P6 a survecu une journee entiere a une suite de plus de mille tests, alors
qu'un test le visait explicitement. La raison n'est pas qu'il manquait un test :
c'est que celui qui existait ne se declenchait que sur un **arbre de travail
propre**.

    is_reproducible = git.is_reproducible and all(s.source_hash for s in sources)

`all(())` vaut `True`, donc l'absence totale de source se declarait rejouable.
Mais des que l'arbre etait modifie - c'est-a-dire pendant tout developpement -
`git.is_reproducible` valait `False` et masquait le defaut. Le test passait au
vert exactement quand on travaillait, et virait au rouge apres chaque commit :
le moment ou l'on regarde le moins.

**Consequence operationnelle :** un test qui exerce une condition composee doit
**fixer** les autres termes plutot que les subir. Ici, construire un `GitState`
propre explicitement, au lieu d'heriter de celui du depot. La regle plus large :
si le resultat d'un test peut changer sans qu'aucune ligne de code n'ait bouge,
ce n'est pas un garde-fou, c'est un indicateur d'humeur.

Corollaire sur la forme du defaut lui-meme : `all()` sur un ensemble
potentiellement vide affirme le plus la ou l'on sait le moins. Quand une
condition porte sur une collection, la non-vacuite est une condition **a part
entiere**, pas une consequence.

Fonde sur [[concepts/determinisme]] · [[log]] (2026-09-11) · [[lessons]] L3

## L12 -- Un fichier ignore par git est aussi invisible pour les outils

`.gitignore:1` `data/` cachait `src/rsl/data/` a git. La lecon L5 en tirait la
regle du motif ancre. Ce qu'elle ne disait pas, et qui est apparu au moment de
versionner enfin le paquet : **ruff respecte `.gitignore`**. La couche donnees
n'avait donc jamais ete analysee - 7 defauts de style y dormaient depuis le
debut, dans du code central.

Le meme raisonnement vaut pour tout outil qui parcourt un arbre : formateurs,
analyseurs, compteurs de couverture, scanners de securite. Un fichier ignore ne
declenche aucune alerte, et l'absence d'alerte se lit comme une absence de
probleme.

**Consequence operationnelle :** apres tout ajout a `.gitignore`, se demander
non seulement « qu'est-ce que git va cesser de suivre ? » mais aussi « quel
outil va cesser de regarder ? ». Et au moment de desigorer un chemin, s'attendre
a une vague de signalements qui ne sont pas des regressions : ce sont des
defauts qui etaient deja la, simplement invisibles.

Precision qui evite un contresens : le ledger interdit `ruff --fix` sur un arbre
INCOMPLET, et les 28 `I001` qu'il cite etaient des symptomes de l'absence de
`rsl.data`. Ces 7 defauts-ci sont d'une autre nature - de vrais defauts, dans
les fichiers du paquet lui-meme, sur un arbre desormais complet et vert sous
mypy. Les empreintes des trois exemples sont identiques avant et apres
correction, ce qui le verifie plutot que de l'affirmer.

Fonde sur [[lessons]] L5 · [[Failed Ideas/ledger]] · [[reference/donnees]]

## L13 -- Une capacite implementee mais inatteignable ne se signale nulle part

`OrderType.LIMIT` et `OrderType.STOP` etaient entierement implementes dans
`execution.py` : declenchement, traitement du gap, regle de slippage propre a
chaque type, compteurs dedies. Et aucun moule de strategie ne les emettait.
`grep order_type src/rsl/strategies/` rendait le vide. La capacite existait,
personne ne pouvait l'atteindre depuis une specification, et rien - ni test, ni
avertissement, ni schema - ne le disait.

Un defaut de ce genre n'apparait pas dans les outils : le code est teste, typé,
lint-propre. Il n'est pas faux, il est **inaccessible**. C'est pourquoi les
trois questions « est-ce que ca marche ? », « est-ce que c'est juste ? » et
« est-ce qu'on peut s'en servir ? » ne se repondent pas avec les memes moyens.

**Consequence operationnelle :** quand on demande ou est la frontiere de ce
qu'on sait faire, comparer ce que le MOTEUR accepte a ce que le VOCABULAIRE
sait produire - pas lire la documentation, qui decrit l'intention. Concretement
ici : les valeurs d'un enum du moteur contre les occurrences de cet enum dans
`strategies/`. Trois autres ecarts du meme genre ont ete trouves de cette
facon le meme jour (sortie partielle, un seul symbole par moule a regles).

Fonde sur [[reference/vocabulaire-signaux]] · [[log]] (2026-09-11)

---

## L14 -- Un cycle d'import qui ne plante jamais coute quand meme

`rsl.engine.runner` importait `rsl.strategies.base` (il lui faut le protocole
`Strategy`), qui importait `rsl.engine.orders` (il lui faut `Order` pour
declarer ce qu'une strategie rend). `import rsl.strategies` chargeait donc
**sept modules de moteur**, mesure au 2026-09-11.

Ce cycle ne cassait pas, et c'est ce qui le rendait durable : trois tentatives
de le briser en reordonnant les imports ont echoue. La raison est mecanique --
`orders` est une **feuille**, donc `from rsl.engine.orders import X` se resout
meme quand `rsl.engine` n'est qu'a moitie initialise. Un cycle de paquets dont
le point de fermeture est une feuille est stable par construction.

Le cout n'etait donc pas un risque de plantage, et le presenter ainsi aurait
ete faux. Il etait ailleurs : **impossible de raisonner sur une couche sans
l'autre**. On ne peut ni charger la couche decision seule, ni affirmer qu'elle
ignore l'execution, ni le verifier.

Le remede n'est pas de supprimer une dependance mais de reconnaitre ce qu'elle
dit : `Order` et `Fill` n'appartiennent a aucune des deux couches, ils sont le
vocabulaire par lequel elles se parlent. Ils se placent donc **sous** les deux
(`rsl/orders.py`, aux cotes de `errors.py`), et la dependance redevient un
sens unique.

**Consequence operationnelle :** aucun outil du depot ne detecte un cycle de
paquets -- ni `ruff`, ni `mypy --strict`, qui sont tous deux passes dessus
pendant des semaines. Ce qui le tient fermé est un test qui lance un
interpreteur NEUF et regarde `sys.modules` ([`test_couches.py`](../tests/unit/test_couches.py)) :
dans le processus de pytest, tout est deja importe et la question n'a plus de
sens.

Fonde sur [[reference/modele-execution]] · [[log]] (2026-09-11)

---

## L15 -- Une liste enumeree a la main en N endroits est fausse a partir de N=2

Les neuf cles de `rules` (`entry_long`, `exit_long`, ...) etaient recopiees en
quatre endroits : la declaration des champs, `warmup_bars`, `describe()` et
`from_spec`. Plus une cinquieme, de contournement, dans `rsl/skeleton.py` --
qui construisait une strategie temoin uniquement pour lire les cles de son
descripteur, parce qu'aucune liste n'etait importable.

Les quatre copies etaient d'accord. Ce n'est pas le probleme : le probleme est
que chaque ajout de regle exigeait quatre modifications coordonnees, et qu'en
oublier une echoue **en silence** et differemment a chaque endroit --

- oubliee dans `warmup_bars` : la regle est lue avant que son indicateur soit
  defini ;
- oubliee dans `describe()` : elle disparait du rapport de run et du squelette ;
- oubliee dans `from_spec` : elle est ignoree, et la strategie tourne sans elle.

Aucun de ces trois echecs ne produit d'erreur. Le troisieme produit un backtest
faux.

La liste est desormais **derivee** des champs de la classe (`RULE_KEYS`), donc
il n'y a plus de copie a synchroniser. Un effet de bord l'a prouve utile
immediatement : avec une liste, on peut enfin **refuser une cle inconnue**.
`rules` est un `dict[str, object]` -- `extra="forbid"` ne s'y applique pas --
donc `exit_lng` au lieu de `exit_long` donnait une strategie qui entre et ne
sort jamais, sans un mot. Le schema publie annonçait meme
`additionalProperties: true`, plus permissif que le code.

**Consequence operationnelle :** quand une liste doit etre connue a plusieurs
endroits, la deriver d'une declaration existante plutot que la republier. Et
verifier au passage ce que son absence permettait : ici, une faute de frappe
silencieuse.

Fonde sur [[reference/vocabulaire-signaux]] · [[log]] (2026-09-11)

---

## L16 -- Une bibliotheque se verifie par PARCOURS, pas indicateur par indicateur

Passer de 22 a 136 primitives a pose une question que 22 ne posaient pas :
comment savoir que les 136 tiennent ? Ecrire des tests un par un ne repond
pas -- chaque ajout apporte alors sa propre couverture, et un oubli ne se voit
nulle part.

La reponse est de separer deux questions qui n'ont pas les memes moyens :

| Question | Moyen | Echelle |
|---|---|---|
| « respecte-t-elle le contrat ? » | parcours du registre, parametres DERIVES du schema | automatique, toute primitive future incluse |
| « la formule est-elle juste ? » | forme fermee, ou equivalence avec du code eprouve | une par une, irreductible |

Le parcours a trouve **trois defauts le jour de sa mise en place**, et aucun
n'aurait ete vu par relecture :

- `zlema@1` sous-declarait son warmup de `(window-1)/2` barres -- il aurait
  leve `InsufficientHistoryError` en plein run ;
- `inertia@1` rendait `NaN` sur une serie plate, parce que `np.std` d'un
  tableau VIDE vaut `NaN` et que `NaN <= 0` est faux : la garde existait et ne
  gardait rien ;
- `t3@1` empile SIX EMA et n'en recevait l'historique que pour cinq, donc
  rendait `None` a **chaque** barre des que la fenetre depassait 5. Il passait
  tous les autres tests -- il ne levait pas, ne lisait pas le futur, n'etait ni
  NaN ni infini. Il etait simplement mort. C'est [[lessons]] L13 sous une
  autre forme, et c'est le test « produit-elle une valeur au moins une fois »
  qui l'a attrape -- test ajoute APRES coup, parce que le defaut a d'abord ete
  trouve par une forme fermee.

Deux principes s'en degagent.

**Les parametres du parcours se DERIVENT du schema**, ils ne se listent pas.
Sans cela, la liste devient la copie a maintenir que le parcours devait
supprimer -- meme mecanisme qu'en [[lessons]] L15.

**Une contrainte entre parametres est une contrainte sur l'UTILISABILITE.**
`adosc@1` portait `window` rapide et une lente figee a 10 : toute fenetre >= 10
etait refusee, donc une machine lisant le squelette echouait au premier essai.
Le defaut n'etait pas dans la formule mais dans le choix de ce qui est
obligatoire. Rendre `window` la fenetre LENTE l'a supprime.

**Consequence operationnelle :** avant d'ajouter la dixieme chose d'une
famille, ecrire le parcours. Il coute une fois, et il paie a chaque ajout.

Fonde sur [[reference/vocabulaire-signaux]] · [[log]] (2026-09-11)

---

## L17 -- Une memoire qui ne change pas un resultat n'est pas l'etat qu'on interdit

Le ledger ecarte les « noeuds de signaux a memoire interne » parce qu'« un
noeud a etat survit d'un run a l'autre, ce qui casse le determinisme ». Ce
motif est juste, et il ne s'applique pas a tout ce qui se souvient.

**Deux choses differentes portent le meme mot.** Un etat SEMANTIQUE fait
dependre la sortie du noeud de l'ordre des appels : deux contextes identiques
donnent deux valeurs. Une MEMOISATION range le resultat d'une fonction pure ;
la rendre ou la recalculer donne les memes bits. La premiere invalide la
reproductibilite, la seconde ne peut pas la toucher.

Mais la distinction ne se decrete pas. Ce qui la rend utilisable est qu'elle
est **falsifiable**, par trois voies independantes :

1. les empreintes d'exemples restent identiques ;
2. `RSL_NO_MEMO=1` rejoue la suite entiere sans le mecanisme, et donne le
   meme resultat ;
3. les suites adversariales tiennent - une memoire qui traverserait deux
   series ferait echouer la corruption du futur.

**Et la distinction a failli etre fausse.** Memoiser suppose que la valeur du
sous-arbre ne depend que de `(serie, barre)`. C'est faux pour deux noeuds, et
l'empreinte de `examples/paire_es_nq.json` l'a dit tout de suite : 634
remplissages au lieu de 30. La cause est dans `BarContext.shifted`, qui
recopie le resolveur de pairs et l'etat de position de la vue d'origine. Dans
`rolling(zscore, 120, close / peer(NQ, close))`, le terme NQ vaut la barre
COURANTE pour les 120 decalages.

Le remede n'est pas une precaution mais une **demonstration** : un
`BarContext` porte exactement quatre choses - `_store`, `_i`, `_position`,
`_peers`. La cle en couvre deux ; les deux autres ne s'atteignent que par les
noeuds `peer` et `position`. Donc memoiser est correct si et seulement si le
sous-arbre ne contient ni l'un ni l'autre, et la liste est complete parce que
la liste des attributs l'est.

**Consequence operationnelle :** avant de memoiser quoi que ce soit, enumerer
ce que porte le contexte et montrer que la cle le couvre. Une cle « qui a
l'air suffisante » est une fuite qui attend. Et garder l'interrupteur : ce
n'est pas un reglage, c'est l'instrument qui rend l'equivalence verifiable a
tout moment.

Effet de bord a connaitre, decouvert en chemin : la semantique de `peer` sous
`rolling` - le terme distant ne glisse pas avec la fenetre - n'est ni
documentee ni evidemment voulue. Elle n'est pas modifiee ici : la corriger
changerait une empreinte archivee, et c'est une decision a prendre a part.

Fonde sur [[Failed Ideas/ledger]] · [[concepts/determinisme]] · [[log]] (2026-09-11)
