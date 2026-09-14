---
type: hub
updated: 2026-09-12
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

Effet de bord decouvert en chemin, et **corrige le meme jour** : le terme
distant ne glissait pas avec la fenetre. Voir [[lessons]] L18 - c'etait un
defaut, pas une convention, et il etait invisible pour une raison
mathematique.

Fonde sur [[Failed Ideas/ledger]] · [[concepts/determinisme]] · [[log]] (2026-09-11)


---

## L18 -- Une symetrie du calcul peut rendre un defaut STRICTEMENT invisible

`BarContext.shifted(lag)` recopiait le resolveur de pairs sans le reculer :
une expression evaluee « telle qu'elle etait il y a `lag` barres » voyait les
autres instruments a l'instant COURANT. Dans

    rolling(zscore, 120, close / peer(NQ, close))

les 120 clotures d'ES etaient donc divisees par la MEME cloture de NQ.

**Le z-score est invariant par changement d'echelle.** Diviser toute une
fenetre par une constante ne le change pas. Le terme distant ne modifiait donc
rien du tout - mesure : ecart maximum **2,08e-14** avec un z-score d'ES seul,
c'est-a-dire l'erreur d'arrondi. L'exemple phare du depot, presente comme une
strategie de paires, negociait ES tout court.

Ce qui rend ce defaut instructif est la liste de ce qui NE pouvait pas le
voir :

| Garde | Pourquoi elle ne voit rien |
|---|---|
| Tests unitaires | chaque noeud pris isolement est juste |
| `mypy --strict`, `ruff` | rien d'incorrect a signaler |
| Corruption du futur | aucune fuite : `NQ[t]` lu a l'instant `t` est du passe |
| Empreintes de resultat | stables - un comportement faux et CONSTANT le reste |
| Relecture du code | `sub._set_peers(self._peers)` est la ligne qu'on ecrit |

Les empreintes sont le point le plus contre-intuitif : elles garantissent
qu'un resultat ne CHANGE pas, jamais qu'il est juste. Un defaut deterministe
leur est transparent par construction.

Ce qui l'a trouve est un raisonnement sur le CONTENU du contexte, mene pour
une autre raison : la memoisation exigeait d'enumerer ce que porte un
`BarContext` et de montrer que la cle le couvre. Deux attributs n'etaient pas
couverts ; regarder pourquoi a montre que l'un des deux ne devrait pas l'etre.

**Consequence operationnelle :** pour un signal compose, verifier qu'un terme
COMPTE, et pas seulement qu'il est present. Le test s'ecrit en une ligne -
comparer l'expression a la meme expression privee de ce terme, et exiger
qu'elles different. Une invariance du calcul (echelle, translation, monotonie)
peut annuler un terme entier sans qu'aucun outil ne s'en apercoive.

Corollaire pour les mesures : deux rampes PROPORTIONNELLES sont un montage de
test degenere. Le premier test ecrit pour cette correction prenait
`A = 100 + k` et `B = 1000 + 10k`, dont le ratio vaut 0,1 pour tout `k` - il
echouait sur du code juste, pour la meme raison mathematique que le defaut
qu'il devait attraper.

Fonde sur [[experiments/paire-es-nq-retour-a-la-moyenne]] · [[log]] (2026-09-11)

---

## L19 -- Une garantie qui tient sur la partie TYPEE peut tomber sur la partie libre

Le champ `note` devait ne changer aucun chiffre : `Field(exclude=True)` le
retire de `model_dump`, donc de `canonical()`, donc du `config_hash`. Verifie
sur une specification : identique. Publie.

Et faux la ou il comptait le plus.

Les noeuds de signaux vivent dans `strategy.params.rules`, que
`RuleStrategyParams` declare `dict[str, object]` - une region **libre**, que
pydantic recopie telle quelle. `exclude=True` n'y a aucune prise, puisqu'il
n'y a pas de champ a exclure. Annoter un seuil changeait donc le
`config_hash` : mesure, `c686c31f` -> `bf0f2f3f` sur
`examples/paire_es_nq.json`.

La dissymetrie est le point a retenir. Ce depot protege sa partie typee par
trois mecanismes - `frozen`, `extra="forbid"`, `exclude` - et **aucun des
trois ne s'applique a un `dict[str, object]`**. Or c'est precisement la que
vit l'expressivite : le vocabulaire de signaux est libre par construction, et
c'est un choix defendu au ledger (dupliquer le registre dans un schema
pydantic le ferait diverger de lui).

Consequence : toute garantie formulee sur « la specification » doit etre
verifiee DEUX fois, une fois sur un bloc type, une fois sur un noeud enfoui.
Mon premier test ne faisait que la premiere - il passait.

Ce qui l'a trouve : un test qui prenait un exemple REEL et annote, plutot
qu'un objet construit dans le test. Les fixtures minimales n'ont pas de
region libre a exercer.

Le remede est dans `canonical()`, qui retire les notes a toute profondeur -
recursif plutot que cible, pour qu'une region libre apparue demain soit
couverte sans qu'on y pense. Effet de bord assume : `note` devient un mot
RESERVE dans une specification.

Fonde sur [[Failed Ideas/ledger]] (2026-09-12) · [[log]] (2026-09-12)

---

## L20 -- Une contrainte de portefeuille verifiee ordre par ordre ne contraint rien

Les quatre plafonds de `engine/limites.py` etaient justes, testes, et sans
effet la ou ils servaient.

Chaque ordre etait evalue contre le portefeuille **commite**. Or une strategie
de classement emet TOUS ses ordres d'un coup, avant qu'aucun ne soit rempli :
les dix ordres d'un rebalancement lisaient chacun « aucune position detenue »,
chacun passait le controle, et `max_positions=2` laissait detenir jusqu'a SIX
instruments sur `momentum_12_1_mensuel`.

Le mecanisme est general et vaut au-dela de ce cas : **une contrainte qui porte
sur un agregat ne peut pas se verifier sur les elements pris un par un**, si
les elements arrivent par lots. Ni le type, ni le test unitaire, ni la relecture
ne le montrent - chaque verification prise isolement est correcte.

Ce qui l'a trouve : un test qui REJOUE les fills dans l'ordre et mesure le pire
etat atteint, au lieu de lire l'etat final. L'etat final respectait le plafond ;
c'est le transitoire qui ne le respectait pas. Un test de l'etat final aurait
publie la contrainte comme fonctionnelle.

Corollaire sur le choix de la mesure : `max_positions` COMPTE, il ne valorise
pas, donc sa projection est exacte et l'assertion peut etre stricte. Les deux
plafonds en argent dependent de marques prises une barre avant le fill : ils
admettent un depassement, et un test strict sur eux aurait ete faux pour une
raison sans rapport. C'est en choisissant la limite EXACTE comme sonde que le
defaut est devenu visible sans tolerance a negocier.

Le remede est une reservation valable le temps d'une fournee
(`RiskManager.begin_submission`), les reductions reservees comme les entrees -
sans quoi le plafond interdirait la rotation qu'il est cense encadrer.

Fonde sur [docs/execution-model.md](../docs/execution-model.md) §6.3 · [[log]] (2026-09-12)

---

## L21 -- Une conversion en entiers peut changer la question sans changer la reponse

Trois regles d'allocation comparees sur `momentum_12_1` : `fixed` rendait un
Sharpe de 0,92, `equal_weight` 0,02, `inverse_volatility` 0,15. Le tableau
etait net, et il etait faux.

A 1 M$ reparti sur six noms, chaque nom recoit 166 666 $. Un contrat ES en vaut
250 000. `trunc` le met a zero. Ce ne sont donc pas « l'equiponderation » et
« la ponderation inverse a la volatilite » qui ont ete mesurees, mais ces
regles **amputees de leurs plus gros instruments** : 190 et 294 noms tronques
sur ~690 emplacements, 28 % et 43 %.

Le mecanisme merite d'etre retenu au-dela du cas. La troncature est une regle
connue, documentee, et deja consignee comme piege pour `VolatilityTarget`. Ce
qui est nouveau, c'est qu'elle ne frappe pas au hasard : elle **elimine
preferentiellement les gros contrats**. Une conversion en entiers qui perd
uniformement fait du bruit ; une qui perd selon la taille fait un BIAIS, et le
resultat reste plausible.

Rien dans les metriques ne pouvait le signaler. Le run tournait, les 107 trades
etaient la, les Sharpe etaient dans les ordres de grandeur habituels. Les trois
lignes se comparaient entre elles, ce qui donnait au tableau son air de
resultat.

Ce qui l'a trouve : avoir ecrit le compteur `n_noms_tronques` AVANT de lire le
moindre chiffre de performance, et l'avoir regarde en premier. Il n'y avait
aucune raison de le consulter - c'est l'habitude prise sur `n_dropped_sizing`
qui a joue.

Regle pratique : quand une grandeur continue devient un entier, verifier que
**la perte ne depend pas de l'unite**. Ici, doubler puis decupler le capital
(20 M$) ramene la troncature a zero et rend la comparaison licite - les trois
regles selectionnent alors exactement les memes noms, seules les tailles
different.

Corollaire sur la publication : un compteur qui n'apparait pas dans le rapport
n'est pas lu. `n_noms_tronques` est publie dans
`run.strategy.allocation.stats`, et [docs/execution-model.md](../docs/execution-model.md)
§6.4 dit qu'il se lit AVANT les performances.

Fonde sur [[experiments/allocation-momentum-12-1-trois-regles]] · [[log]] (2026-09-12)

---

## L22 -- Une frontiere DECLAREE reste une hypothese sur les donnees

Le decoupage intra-journalier est ancre sur la seance declaree, ce qui etait la
condition pour l'ecrire du tout : le socle n'invente aucune frontiere. La
declaration lui donne la sienne, le probleme semblait clos.

Il ne l'etait pas. Une seance ES declaree `17:00-16:00@America/Chicago` est
juste ; les DONNEES, elles, contiennent des barres d'une minute horodatees
16:00, qui cloturent donc a 16:01 - une minute apres la fermeture declaree.
Borner la disponibilite d'une tranche a la fermeture declaree aurait rendu 74
barres agregees sur 16 417 disponibles AVANT la cloture d'une de leurs propres
composantes. Une fuite, produite par une declaration correcte.

Le point a retenir : une declaration dit ce que le marche est CENSE faire. Elle
ne dit pas ce que le fichier contient. Les deux coincident presque toujours, et
« presque » suffit a fabriquer un biais - 74 occurrences reparties sur dix ans,
invisibles a l'oeil, chacune un signal lisible avant son heure.

Le remede est structurel plutot que defensif : la disponibilite d'une tranche
est un MAXIMUM entre la borne theorique et la derniere cloture reellement
observee. La propriete ne depend alors plus de la qualite de la declaration ni
de celle des donnees - elle tient par construction, y compris sur une seance
mal declaree.

Ce qui l'a trouve : avoir mesure sur les vraies series avant d'ecrire les
tests, en cherchant explicitement si le troisieme terme du maximum etait du
code mort. Il ne l'etait pas. Une suite synthetique ne l'aurait jamais montre -
les seances y finissent a l'heure.

A rapprocher de L18 : la ou un defaut de symetrie rendait une erreur invisible,
c'est ici une declaration exacte qui rendait une hypothese invisible.

Fonde sur [docs/execution-model.md](../docs/execution-model.md) §1.3 · [[log]] (2026-09-12)

---

## L23 -- Ajouter des essais CORRELES relache la correction censee les punir

Le Deflated Sharpe compare un Sharpe observe au maximum attendu du meilleur de
N tirages. L'intuition dit : plus d'essais, correction plus severe. Le balayage
du 2026-09-12 montre l'inverse.

Avant : 31 essais enregistres, variance des Sharpe 0,01203, maximum attendu
sous H0 **0,1600**.
Apres avoir ajoute 462 configurations : 493 essais, variance **0,000473**,
maximum attendu **0,0663**.

Le nombre d'essais a ete multiplie par seize et la correction a ete divisee par
deux et demi.

Le mecanisme est dans la formule, et il est evident une fois vu : le maximum
attendu croit avec le nombre d'essais MAIS il est proportionnel a l'ecart-type
des Sharpe essayes. Les 462 ajoutes sont des variantes du meme croisement de
moyennes sur le meme instrument ; leurs Sharpe tiennent entre 0,02 et 0,06. Un
ensemble grand et homogene a un maximum attendu plus faible qu'un petit
ensemble heterogene.

Ce que cela veut dire en pratique : **remplir le compteur d'essais quasi
identiques affaiblit le DSR au lieu de le durcir.** Ce n'est pas une faille de
l'implementation, c'est l'hypothese d'INDEPENDANCE des essais qui est violee -
celle que la source du DSR reste a ingerer, et qui vient de gagner une raison
concrete d'etre lue.

Consequence immediate sur la facon de citer un chiffre : un DSR calcule depuis
le registre depend de l'etat du registre. Le meme Sharpe de `sma_es_daily`
rendait 0,0000 le matin et 0,0724 le soir, sans que la strategie bouge d'un
bit. Un DSR ne se cite donc jamais seul - il se cite avec le nombre d'essais ET
leur variance.

Le garde existant ne suffit pas : `Registre.doublons` ne repere que les
resultats BIT-IDENTIQUES. Quatre cent soixante-deux croisements voisins ont
462 empreintes differentes et passent tous pour des essais independants.

Fonde sur [[experiments/pbo-grille-large-462-sma]] · [[log]] (2026-09-12)

---

## L24 -- Deux moteurs sans fuite ne donnent pas le meme chiffre pour autant

Le vocabulaire JSON a ete porte sur Nautilus en une seule idee : ne pas le
porter. Il ne parle pas a un moteur, il parle a un `Context` - un curseur sur
des barres closes. Il suffisait que Nautilus mene l'horloge et que notre
`BarContext` serve le vocabulaire. Les 136 primitives et les 23 noeuds
fonctionnent sans qu'une ligne de leur code change.

Puis la comparaison a donne 0,081 % d'ecart sur `sma_es_daily`, et j'ai failli
conclure que les deux moteurs concordaient.

Ils ne concordent pas. Deux mesures l'ont montre, dans cet ordre.

**D'abord une fuite, chez Nautilus.** Son moteur de correspondance remplit un
ordre au marche a la cloture de la barre qu'il traite. Soumettre pendant
`on_bar(t)` donne donc un fill a `close[t]` : le prix meme que la strategie
vient de lire pour decider. Mesure sur `_moule` : +19,43 % d'equity. Ce n'est
pas un defaut de Nautilus - c'est une convention de simulation sur barres, que
rien n'annonce et que personne ne remarque tant qu'il ne la cherche pas.

**Ensuite une divergence, apres correction.** Le differe supprime la fuite mais
place les fills sur `close[t+1]` la ou nous servons a `open[t+1]`. Une journee
entiere d'ecart sur du quotidien, et - c'est le point - **il se compose a
chaque trade** :

    4 trades   ->  -0,93 %
    10 trades  ->  -0,47 %
    18 trades  ->  +23,84 %
    49 trades  ->  +17,44 %

La lecon generale : **l'absence de fuite ne rend pas deux moteurs
comparables**. Ils peuvent etre tous deux corrects et mesurer deux choses
differentes. Ce qui les separe n'est pas la justesse mais la CONVENTION, et une
convention ne se devine pas - elle se mesure.

Corollaire sur les tests, et c'est celui qui a failli passer : mon premier test
de concordance tolerait 0,5 % d'ecart. Il PASSAIT, parce que l'exemple sur
lequel il portait negocie dix fois. Un test vert sur le cas tranquille pendant
que les cas actifs derivent de vingt pour cent est pire que pas de test. Il a
ete remplace par un test qui NOMME l'ecart et borne par le BAS - se rejouir
d'une convergence qu'on n'a pas provoquee serait la mauvaise reaction.

Deuxieme corollaire, sur les temoins : le premier temoin ne neutralisait rien.
Il remplacait une file par un espion, mais `on_bar` reassigne cette file des la
premiere barre. Le test comparait deux executions identiques et passait. Un
temoin doit etre VERIFIE comme le reste - c'est ce que fait desormais
`test_le_temoin_reproduit_bien_la_fuite`.

Fonde sur [[log]] (2026-09-13) · `tests/test_nautilus_coexistence.py`

---

## L25 -- Un backtest qui ne negocie pas ressemble a un backtest qui perd

Le portage du vocabulaire TRANSVERSAL sur Nautilus a rencontre deux defauts
distincts. Ni l'un ni l'autre n'a leve d'exception. Tous deux rendaient le meme
resultat : capital intact, zero position, aucun avertissement.

**Le premier.** Une coupe transversale se reconstitue a partir de barres
livrees une par une. Ma premiere version decidait a l'arrivee de la premiere
barre d'un nouvel instant - la ligne precedente etait bien finie. Mais le
simulateur, lui, n'avait traite qu'UNE barre du nouvel instant : les neuf
autres instruments n'avaient pas de prix, et Nautilus rejetait chaque ordre avec
`no market`. **684 ordres emis, 684 rejetes.**

**Le second.** Meme symptome, autre cause, trouve juste apres. Nautilus ne
remplit AUCUN ordre sur des barres etiquetees `MONTH`. Mesure en ne changeant
qu'une chaine de caracteres, tout le reste identique : `1-DAY-LAST` donne 14
fills, `1-MONTH-LAST` 14 rejets.

Ce que les deux ont en commun est plus important que leurs causes. Un backtest
qui n'aboutit a rien PRODUIT UN CHIFFRE - le capital initial - et ce chiffre se
lit comme une performance nulle. Rien ne distingue « la strategie n'a pas gagne »
de « la strategie n'a jamais joue ».

C'est le meme mecanisme que [[lessons]] L18, ou un terme de signal inerte
donnait un resultat parfaitement plausible. La famille entiere se resume ainsi :
**les defauts dangereux ne sont pas ceux qui font echouer, ce sont ceux qui font
aboutir a quelque chose de lisible.**

Consequence sur les tests : compter les ORDRES ne suffit pas, il faut compter
les FILLS. Le piege des 684 rejets avait 684 ordres. `test_nautilus_transversal`
assert donc `n_remplis > n_rejetes`, et separement que le capital a bouge.

Troisieme defaut, trouve par ces tests eux-memes : la garde censee refuser un
`risk.limits` declare interrogeait `risque.limits.actives` via une chaine de
`getattr`. `actives` appartient a l'objet CONSTRUIT, pas a la specification ; la
chaine rendait `False` en silence et la garde ne gardait rien. Un acces TYPE
l'aurait refuse a la compilation - c'est ce qu'il fait desormais.

Fonde sur [[log]] (2026-09-13) · `src/rsl/nautilus/transversal.py`

---

## L26 -- Une memoire consultee APRES avoir paye ce qu'elle evite n'evite rien

`cumulative` coutait 1249 us par barre sur un VWAP ancre a la seance, contre
0,05 us pour l'equivalent vectorise en numpy. Vingt-cinq mille fois. J'ai
d'abord attribue cet ecart a la somme recalculee depuis l'ouverture - un
O(n^2) par seance - et c'etait faux.

**Le vrai cout etait la creation de contextes.** Pour rassembler ses valeurs,
le noeud appelait `ctx.shifted(lag)` une fois par lag, soit 400 allocations de
`BarContext` par barre. La memoisation existait pourtant et rangeait bien les
valeurs - mais `_vue_et_valeur` construisait la vue AVANT de la consulter.
Elle payait exactement le cout qu'elle etait censee supprimer.

La cle de la memoire est `n_bars_seen`, qui se calcule depuis le contexte
courant : `ctx.n_bars_seen - lag`. Il n'y avait aucune raison de reculer pour
savoir si la reponse etait deja connue. Consulter d'abord : **1249 -> 429 us**,
et le gain profite a `rolling` et `bars_since` par la meme voie.

Restait une boucle Python par lag - lecture du jeton, recherche, test de type,
ajout a une liste - soit quatre operations fois quatre cents. Un tampon numpy
par seance, qui n'ajoute qu'UNE valeur par barre nouvelle : **429 -> 36,5 us**.
Au total **34 fois**, et les sept empreintes archivees sont inchangees.

Ce qui a failli mal tourner
----------------------------
La premiere idee etait un accumulateur courant : garder un total et y ajouter
la valeur nouvelle. Plus rapide encore, et **faux** - `np.sum` somme par paires,
l'addition sequentielle non, et les derniers bits different. Les sept empreintes
auraient bouge, et il aurait fallu decider si c'etait une correction ou une
regression alors que les deux calculs sont legitimes.

Le tampon garde donc les VALEURS et laisse numpy reduire. Il rend meme une vue
RENVERSEE, pour que la sequence presentee a `np.sum` soit identique a celle de
la liste d'avant - le groupement de la sommation par paires depend de l'ordre.

La regle generale : **quand on remplace un calcul par un plus rapide, verifier
d'abord ce qui coute**. J'ai failli optimiser la sommation, qui ne representait
rien, et j'aurais ecrit un accumulateur qui aurait change les resultats pour un
gain nul.

Fonde sur [[log]] (2026-09-13) · `tests/unit/test_cumulative_tampon.py`

---

## L27 -- Une estimation de duree extrapolee d'un microbenchmark s'est trompee trois fois de suite

Le run Zarattini sur 3 705 199 barres minute a ete MESURE de bout en bout le
2026-09-13 : **15 min 55 s**. Mes trois estimations successives disaient 6,7 h,
puis 3,05 h, puis 22 min. La derniere n'etait pas juste non plus, elle etait
seulement moins fausse.

La cause etait la meme les trois fois, et elle n'a rien a voir avec
l'optimisation : **je mesurais un noeud fraichement construit**, donc une
memoisation VIDE. Dans un run reel, chaque valeur intermediaire est calculee une
fois puis relue soixante fois par le `stride`. L'ecart est mesure :

| | a froid | a chaud (24 000 barres) |
|---|---|---|
| `rolling` strie | 655,6 us | **52,1 us** |

Douze fois. Un microbenchmark de N barres sur un etat neuf ne mesure pas le cout
marginal d'une barre, il mesure le cout d'amorcage divise par N.

**La regle : une duree de run se mesure en lancant le run.** Un microbenchmark
sert a comparer deux implementations du MEME noeud dans le MEME etat ; il ne sert
pas a predire un temps total. Quand la question posee est « combien de temps »,
la reponse s'obtient avec `time`, pas avec une multiplication.

Ce que cela a failli couter
----------------------------
Sur la foi des 3 h, la question posee etait de tout reecrire en C#. Cela aurait
voulu dire 24 343 lignes, 136 primitives, 23 noeuds, le moteur, le registre
d'essais et la PBO - et l'abandon de 4 168 tests et des 7 empreintes - pour un
programme qui prend seize minutes. Le travail lourd est deja en C : numpy fait
les reductions. Ce qui restait en Python etait le parcours d'arbre, c'est-a-dire
exactement ce que [[lessons]] L26 a divise par 34 en deux heures.

Fonde sur [[log]] (2026-09-13)

---

## L28 -- 5 080 rejets de marge se lisent comme une strategie perdante

Le meme run rend **-25,62 %** sur 10,59 ans, avec 2 trades et une exposition de
5,7 x 10^-6. Lu comme un resultat, c'est une strategie qui perd. Ce n'en est pas
un : les compteurs disent autre chose.

```
n_orders_submitted     5084
n_orders_dropped_risk  5080
n_rejected_margin      5080
n_fills                   4
```

**Quatre ordres sur 5 084 ont ete executes.** La regle d'entree, elle, fonctionne :
mesuree sur 120 000 barres contigues, `entry_long` est vraie 94 fois, soit environ
une par seance - l'ordre de grandeur du papier.

Le blocage est arithmetique. Le facteur `vol_target` sature a `vol_max_multiple`
= 4, la strategie demande donc 4 contrats NQ. La marge initiale de NQ est
27 000 : **4 x 27 000 = 108 000 sur un compte de 100 000**. Chaque entree est
refusee. Les deux seules qui sont passees l'ont ete a 3 contrats, et leur perte -
12 808 chacune - EST le -25,62 % affiche.

Le -25,62 % ne mesure donc pas la strategie. Il mesure deux trades.

C'est la troisieme occurrence de la meme famille apres [[lessons]] L18 et L25 :
**un backtest empeche produit un nombre lisible**. Ici le diagnostic etait
pourtant a portee de main - le rapport publie `n_rejected_margin` - mais rien
dans le resume imprime ne le signale. Un taux de rejet de 99,9 % devrait
s'afficher a cote du rendement, pas seulement dans le JSON.

<!-- NOTE: action ouverte, pas encore faite. -->

Fonde sur [[log]] (2026-09-13) · rapport `zarattini_rapport.json`

---

## L29 -- Une approximation annoncee a 3,4 % en valait 100 %

La specification Zarattini portait cette note, ecrite de bonne foi :

> « Le stride suppose 390 barres par seance. Sur les seances ECOURTEES
> l'alignement derive - 94 seances sur 2748 dans notre historique, soit 3,4 %.
> C'est la seule approximation qui subsiste. »

Trois affirmations, et **les trois etaient fausses**.

Les cotations NQ portent la seance ELECTRONIQUE, pas le RTH : **1 362 barres
par jour**, pas 390. Le pas de 390 ne tombait donc jamais sur le rang voulu -
pas « rarement », jamais. Et les seances courtes ne sont pas 94 accidents de
calendrier : ce sont **les vendredis**, la seance ouverte le vendredi a 9 h 30
se fermant avant le week-end, soit 435 barres. Une semaine sur une, sur dix
ans. Enfin, ce n'etait pas la seule approximation : c'etait la seule qui avait
ete ECRITE.

Le chiffre qui tranche : reecrit sur un ancrage de seance reel, `sigma[tau]`
differe de l'ancien a **100 % des points de controle** ou tous deux sont
definis, de **28,3 % en mediane** et jusqu'a 94,7 %. Le seuil de la strategie
etant `1,5 x sigma`, c'est la decision entiere qui portait sur autre chose que
ce que le papier decrit.

Pourquoi la note n'a rien protege
----------------------------------
Elle chiffrait l'erreur **dans l'hypothese ou l'hypothese etait vraie**. « 94
seances sur 2748 » compte les seances plus courtes que 390 barres ; il fallait
compter les seances differentes de 390 barres, c'est-a-dire toutes. Une
approximation documentee reste une approximation non mesuree tant que personne
n'a compte la grandeur reelle.

Le cout d'une minute de verification : `len(barres) / len(seances)` rend 1 362.

La regle : **une note qui chiffre une approximation doit nommer la mesure qui
la produit**, sinon elle donne a une supposition l'apparence d'un fait verifie.
Celle-ci a survecu a la redaction de la strategie, a un run de sept heures
estimees, a deux backtests complets et a trois seances de travail.

Ce que la correction a coute, et ce qu'elle refuse
---------------------------------------------------
`rolling.across: "sessions"` et le noeud `session_lag`, tous deux adosses au
calendrier DECLARE. Ils reprennent une idee du [[Failed Ideas/ledger]] ecartee
le 2026-09-11 - la condition de reprise etait « un calendrier existe ET le
desalignement devient genant » : il ne l'est pas devenu, il l'etait deja.

Ils refusent de substituer une barre voisine quand une seance ecourtee n'a pas
le rang demande. Consequence assumee et mesuree : 33 % des barres gardent une
fenetre complete sur NQ, **88 % aux douze points de controle**. Les 67 % perdus
sont des barres de nuit dont le rang n'existe pas un vendredi - refuser de les
comparer a un marche ferme n'est pas une perte d'information.

Fonde sur [[log]] (2026-09-13) · `tests/unit/test_fenetre_par_seance.py` ·
`docs/execution-model.md` §1.3

---

## L30 -- Une valeur NEUTRE est un mensonge quand il n'y a pas de valeur

Pour agreger sur une tranche de seance - le plus haut des trente premieres
minutes - le vocabulaire n'offrait qu'un detour :

    cumulative(max, if_then_else(mfo <= 30, high, constant(-1e18)))

L'idee est de neutraliser les barres hors tranche par une valeur qui ne gagnera
jamais un `max`. Elle marche. Elle marche meme tres bien - tant que la tranche
contient au moins une barre.

Quand elle est vide, il n'y a plus de valeur a rendre, et l'expression en rend
une quand meme : **-1e+18**. Mesure du 2026-09-14 : la regle `cours > cette
borne` vaut alors vrai a CHAQUE barre. Le backtest ouvre des positions partout,
termine sans erreur, et publie un rendement.

Une tranche vide n'est pas un cas d'ecole. Il suffit d'une seance ecourtee plus
courte que la tranche, d'un masque ecrit en heure UTC quand la seance est
declaree a New York, ou d'une faute de frappe dans un seuil.

Le correctif, `cumulative.mask`, ne rend pas la tranche vide plus intelligente :
il la rend **muette**. `None`, et une regle qui vaut `None` ne declenche pas. Le
pire cas devient une strategie qui ne negocie pas.

La regle generale
------------------
**Une valeur de remplacement n'est acceptable que si l'absence est impossible.**
Des qu'elle ne l'est pas, la valeur neutre transforme un cas indefini en un cas
defini et faux - et le socle entier est bati sur le refus inverse : pas de
`NaN`, pas de zero par defaut, `InsufficientHistoryError` plutot qu'une valeur
inventee.

Ce qui rend celle-ci difficile a voir : l'artifice etait ECRIT PAR L'UTILISATEUR
dans son JSON, pas par le socle. Les gardes du socle ne s'appliquent pas a une
expression que l'utilisateur compose lui-meme. Un vocabulaire assez expressif
pour tout dire est aussi assez expressif pour dire des choses fausses ; la
reponse n'est pas de le restreindre, mais d'offrir la forme JUSTE assez
commodement pour que le detour cesse d'etre tentant.

Quatrieme occurrence de la famille
-----------------------------------
Apres [[lessons]] L18 (terme de signal inerte), L25 (backtest qui ne negocie
pas) et L28 (5 080 rejets de marge). Le motif est toujours le meme : **le
resultat reste LISIBLE**. Ici il est meme pire que d'habitude - les trois
premiers faisaient trop peu negocier, celui-ci fait negocier trop, ce qui
ressemble d'autant plus a une strategie.

Comment le test s'en protege
-----------------------------
`tests/unit/test_tranche_de_seance.py` fixe DEUX proprietes, et la premiere
n'est pas decorative : la ou la sentinelle est juste, le masque rend exactement
la meme chose. Sans elle, on pourrait rendre `None` partout et passer le test
d'honnetete. Un test qui fige le defaut historique garde la trace de ce qu'on
evite - s'il devenait vert tout seul, c'est l'argument qui aurait change.

Fonde sur [[log]] (2026-09-14) · `docs/execution-model.md` §1.3
