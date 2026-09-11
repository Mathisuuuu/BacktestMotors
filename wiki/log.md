---
type: hub
updated: 2026-09-10
---

# Log

Journal chronologique **append-only**. On ajoute une ligne en bas, on n'en
modifie et on n'en retire jamais aucune. Une correction s'ecrit comme une
nouvelle entree, pas comme une reecriture de l'ancienne.

Format, strict parce qu'il doit rester analysable :

```
## [YYYY-MM-DD] <type> | <ce qui s'est passe> | <resultat>
```

Types : `setup` · `experiment` · `ingest` · `decision` · `lint` · `fix` ·
`query` · `note`

Les cinq dernieres entrees :

```bash
grep "^## \[" wiki/log.md | tail -5
```

---

## [2026-09-10] setup | mise en place du wiki LLM (hubs, contenu, schema, hooks, Obsidian) | 5 hubs + 13 pages, generateur hot.md, hooks PowerShell, groupes de couleurs Obsidian

## [2026-09-10] note | amorcage : 6 concepts, 4 routeurs, 2 experiences, 1 source a ingerer, 7 idees au ledger | tout tire du depot existant, aucune connaissance inventee

## [2026-09-10] fix | decouverte en verifiant les liens : `.gitignore:1` `data/` attrape aussi `src/rsl/data/` | paquet `rsl.data` jamais commite et absent du disque, `import rsl.data` leve ; signale, non corrige

## [2026-09-10] lint | premier passage : 20 pages, wikilinks et liens relatifs verifies | 0 orpheline, 1 lien mort reel (rsl.data) annote, placeholders de gabarits exclus

## [2026-09-10] note | correction de l'entree `note` ci-dessus (log append-only : on corrige par ajout) | le bon compte est 5 routeurs et 15 pages de contenu, pas 4 et 13

## [2026-09-10] note | audit « quels sont les problemes a regler » : etendue de la casse rsl.data mesuree, recuperation locale cherchee | 6 modules / 42 symboles perdus, aucune copie sur la machine, ~128 tests specificateurs intacts ; 3 problemes classes P1-P3

## [2026-09-10] fix | P2 : venv Python 3.14.6 + `pip install -e ".[dev]"` | 29 paquets installes ; polars/pyarrow/pydantic identiques au manifeste du README, numpy 2.5.3 au lieu de 2.4.6

## [2026-09-10] note | chaine d'outils passee sur l'arbre incomplet | `src/` propre sous ruff ; 28 I001 dans `tests/` et 35 des 36 erreurs mypy sont des symptomes de P1 ; 1 erreur reelle (stubs numpy vs python_version 3.11) -> P4 ; piege `ruff --fix` consigne au ledger

## [2026-09-10] fix | P5 : droits d'ecriture accordes, push reessaye | 3 commits pousses vers origin/main (26 fichiers, 1923 lignes) ; sync entre machines operationnelle

## [2026-09-11] note | audit « que fait l'application, est-ce que ca marche » : wiki relu, CLI exercee de bout en bout sur donnees reelles | 1179 tests passent / 1 echoue ; ruff et mypy propres ; les 2 experiences seminales se reproduisent au chiffre pres (Sharpe 0,60, 57 % dans un pli) ; P3 et P4 constates resolus ; 2 defauts vivants trouves -> voir entrees suivantes

## [2026-09-11] fix | P1 reexamine : `rsl.data` est revenu sur le disque mais reste NON VERSIONNE | `.gitignore:1` `data/` toujours non ancre ; 7 fichiers / 2063 lignes invisibles de git, `git status` affiche « propre » ; un clone frais ou un `git clean -xfd` reperd toute la couche donnees. Correctif : ancrer en `/data/`

## [2026-09-11] note | defaut trouve dans `RunManifest.is_reproducible` : `all(())` vaut `True` | un run sans aucune source de donnees enregistree se declare `Rejouable oui` ; `test_missing_data_sources_are_flagged` echoue et a raison. Le champ que [[concepts/determinisme]] designe comme le seul qui compte ment par vacuite

## [2026-09-11] note | defaut trouve sur `rsl schema` redirige : sortie en CP1252, pas en UTF-8 | `ensure_ascii=False` + stdout Windows ; le `§` sort en octet 0xA7, le fichier est illisible en UTF-8. `--out` ecrit correctement en UTF-8 : le defaut ne touche que la redirection `>`

## [2026-09-11] fix | chemins de donnees rendus portables : `RSL_DATA_DIR` + `.env`, et `config_hash` debarrasse du chemin absolu | nouveau `src/rsl/env.py` (103 l., zero dependance) ; 15 chemins absolus retires de `examples/` et `cli.py` ; 25 tests ajoutes ; les 4 empreintes de resultat sont INCHANGEES, seul le `config_hash` bouge -> voir [[lessons]] L7

## [2026-09-11] note | durcissement trouve par un test que j'ecrivais : la remontee vers le `.env` sortait du depot | elle atteignait `C:\Users\Mathis\.env` (118 o, UTF-16), etranger au projet. Bornee aux marqueurs `.git` / `pyproject.toml`, et lecture UTF-8/UTF-16/CP1252 (PowerShell 5.1 redirige en UTF-16)

## [2026-09-11] experiment | rsi-survendu-hors-lundi | `non-conclusif` : Sharpe 0,46 sur 2732 barres, 49 trades, 54 % du resultat dans un pli sur neuf ; le filtre calendaire n'a pas de temoin. Essai fait comme preuve qu'une strategie neuve s'ecrit en JSON seul -- compte quand meme au compteur (L2)

## [2026-09-11] note | question « peut-on creer une strategie sans une ligne de code » : verifie au shell | OUI dans le vocabulaire (13 primitives x 15 noeuds composables, 3 moules) ; NON au-dela : une primitive ou un type de noeud absent est refuse avec rc=1 et l'enumeration de ce qui existe. Ecrire l'un des deux demande du Python et un enregistrement `@1`

## [2026-09-11] note | P6 (`all(())` vaut `True`) est MASQUE, pas corrige | le test `test_missing_data_sources_are_flagged` passe desormais uniquement parce que l'arbre de travail est sale, ce qui met `git.is_reproducible` a `False`. Il redeviendra rouge au prochain commit propre

## [2026-09-11] note | correction de l'entree `fix` ci-dessus (log append-only : on corrige par ajout) | `src/rsl/env.py` fait 128 lignes et non 103 -- le chiffre notait l'etat avant le durcissement (borne de depot + encodages) ; le nombre de tests ajoutes est 25

## [2026-09-11] note | correction finale des chiffres de `src/rsl/env.py` (les deux entrees precedentes sont fausses toutes les deux) | chiffres verifies : **133 lignes**, **20 fonctions de test** dans `tests/unit/test_env.py` soit **23 tests collectes** (une est parametree sur 4 encodages). Total de la suite : 1180 -> 1203

## [2026-09-11] feat | tableau de bord graphique `rsl gui` : indicateurs, filtres annee/long/short, courbes capital et drawdown, carnet d'ordres, export CSV/TXT | tkinter + matplotlib en extra `gui` ; 3 modules (`model` 400 l., `charts`, `app`), 37 tests ajoutes, suite a 1240 ; noir et blanc strict, chrome Windows 95

## [2026-09-11] fix | couture `run_backtest_detailed` ajoutee a `report.py` | le rapport ne porte ni fills ni equity ni trades, seulement leurs agregats ; la rendre par une seconde fonction evite de rejouer le run pour l'afficher. Refactor pur : les 4 empreintes d'exemple sont inchangees

## [2026-09-11] decision | matplotlib declaree en dependance OPTIONNELLE, pas en dependance du projet | `TRACKED_DEPENDENCIES` ne l'enregistre pas : un rapport produit sur une machine avec interface reste comparable a un rapport produit sans. `rsl gui` sans matplotlib rend 1 avec un message, aucune autre commande n'est touchee

## [2026-09-11] note | defaut trouve puis verrouille : l'axe des dates annoncait 2010-2040 pour des donnees 2017-2026 | matplotlib ajoute 5 % de marge et peut reautoscaler au redimensionnement ; bornes fixees ET `set_autoscalex_on(False)` ET rejouees sur `<Configure>`. Couvert par `tests/unit/test_gui_charts.py`

## [2026-09-11] note | defaut de mise en page : la barre d'export etait poussee hors de la fenetre par les zones extensibles | empilee en dernier, elle sortait du cadre sans avertissement. Construite avant les zones extensibles et ancree `side="bottom"` ; geometrie verifiee au widget pres (tous les blocs dans les 793 px de la fenetre)

## [2026-09-11] feat | tableau de bord refondu : 4 onglets, style plat blanc, vert/rouge porteurs de sens, onglet PRIX & ORDRES avec bougies et ordres, duree moyenne en position | style Windows 95 abandonne sur demande ; `RunArtifacts` remplace le tuple rendu par `run_backtest_detailed` pour transporter aussi les barres servies au moteur ; suite a 1275 tests

## [2026-09-11] note | defaut trouve et verrouille : l'echelle des prix restait figee au zoom | `Axes.clear()` reinitialise le registre de callbacks de matplotlib, donc le `xlim_changed` connecte a la construction ne survivait pas au premier redessin. Remplace par un point d'extension explicite `_apres_fenetre()` -> voir [[lessons]] L9

## [2026-09-11] note | defaut trouve : le bouton de filtre actif s'affichait vide | avec `indicatoron=False`, Tk peint l'etat selectionne avec `selectcolor` et ignore `bg` ; libelle blanc sur fond blanc. `selectcolor` regle en meme temps que `bg`

## [2026-09-11] decision | `mplfinance` ecarte pour les bougies | exigerait pandas, dont le rejet figure au ledger. Le motif du rejet vise la couche donnees et non l'affichage, mais une `LineCollection` plus un `bar` suffisent : pas de raison d'ouvrir le debat pour un graphique

## [2026-09-11] note | correction de l'entree `feat` ci-dessus (log append-only : on corrige par ajout) | le compte exact est **1263 tests**, pas 1275

## [2026-09-11] fix | deux tests de graphiques se sautaient en silence ("aucun affichage disponible") alors que Tk fonctionnait | creer puis detruire une racine `Tk()` par test echoue par intermittence sur les derniers. Fixture passee en portee `module` : une seule racine partagee, 3 executions consecutives sans saut

## [2026-09-11] note | gabarit de specification ajoute : `examples/_moule.json` | tous les blocs d'une specification plus une strategie `rules@1` complete (entree composee, sortie a deux conditions, stop ATR, objectif ATR). Verifie en l'executant : 18 trades, Sharpe 0,39, empreinte 58a9d31a2dae3658. **Cette execution consomme un essai** au sens de [[lessons]] L2 -- a promouvoir en page d'experience si le chiffre est conserve

## [2026-09-11] note | sondage d'expressivite du vocabulaire, 5 configurations lancees sur ES quotidien | EXPRIMABLE : MACD (difference de deux `ema@1` par `arith`, Sharpe 0,81, 33 trades), ligne de signal par `rolling mean` (Sharpe 0,74, 115 trades), stop suiveur via `position.high_since_entry` (Sharpe 0,64, 18 trades). REFUSE : EMA d'un sous-arbre (`primitive` est une feuille, pas de champ `inner`), et deux granularites du meme instrument (`'ES.v.0' apparait deux fois`). **Ces 5 executions consomment 5 essais** au sens de [[lessons]] L2 -- non promues en pages d'experience, aucune n'ayant d'hypothese

## [2026-09-11] feat | vocabulaire etendu : 9 primitives et 5 types de noeuds ajoutes, plus 6 statistiques sur `rolling@1` | primitives 13 -> 22 (`macd@1` avec ligne de signal et histogramme, `atr_wilder@1`, `rsi_wilder@1`, `adx@1`, `cci@1`, `williams_r@1`, `efficiency_ratio@1`, `vwap@1`, `obv@1`) ; noeuds 15 -> 20 (`if_then_else`, `math`, `min_of`, `max_of`, `bars_since`) ; `rolling` gagne `ema`, `median`, `var`, `slope`, `rank`, `count_true`. Suite 1263 -> 1387 tests. **Les 5 empreintes d'exemples sont inchangees**

## [2026-09-11] decision | `rolling@1` gagne 6 statistiques par extension ADDITIVE, sans `rolling@2` | le levier structurel est `stat: "ema"` : avant lui, lisser une EXPRESSION etait impossible (`primitive` est une feuille), donc la ligne de signal d'un MACD etait inexprimable. Verification : les empreintes de `sma_es_daily`, `paire_es_nq`, `momentum`, `retour_moyenne` et `_moule` sont identiques avant et apres -> ledger

## [2026-09-11] decision | variantes de Wilder publiees sous des NOMS distincts, pas en `@2` | `registry.py:124` resout une reference sans version vers la plus recente : `atr@2` aurait fait basculer tout `"ref": "atr"` non epingle d'une moyenne simple a une exponentielle, en silence. Les docstrings de `atr@1` et `rsi@1` recommandent pourtant ce chemin -> ledger + [[lessons]] L10

## [2026-09-11] note | `examples/_moule_universel.json` : reference exhaustive du vocabulaire | 20/20 types de noeuds, 7 primitives nouvelles, long et short, stop adaptatif par `if_then_else`, objectif borne par `min_of`/`max_of`. Verifie a l'execution (66 trades, Sharpe 0,29, empreinte 5dd6973012b4c68b) et garde par `tests/unit/test_moule_universel.py`, qui nomme les types manquants. Mutation testee : retirer `time` fait echouer le test. **Cette execution consomme un essai** (L2)

## [2026-09-11] note | MACD verifie analytiquement, pas contre une seconde implementation | sur une droite de pente `s`, une EMA de fenetre `w` retarde de `s*(w-1)/2`, donc la ligne MACD vaut `s*(slow-fast)/2`. Mesure : 7,000000 pour s=1, fast=12, slow=26. ADX sature a 100 en tendance pure, OBV vaut exactement la somme des volumes, ratio d'efficience vaut 1 sur un chemin droit

## [2026-09-11] feat | `rsl squelette` : le vocabulaire presente comme un formulaire a remplir | nouveau `src/rsl/skeleton.py` + `schemas/squelette.json` (33 ko, ASCII pur). Chaque emplacement d'une specification y porte son type, ses choix, son defaut. Trois renvois croises rendus enumerables : `root` (10 instruments), `strategy.ref` (6), `primitive.ref` (22). ENGENDRE depuis les registres, garde par un test de derive comme `schemas/` (L4)

## [2026-09-11] note | suffisance du squelette verifiee, pas supposee | trois tests construisent, a partir du SEUL document, une specification valide, puis chaque type de noeud, puis chaque primitive. Verification pratique en plus : un script n'important pas `rsl` a lu le squelette, ecrit une strategie MACD + ADX + stop ATR de Wilder, et l'a executee -> 50 trades, +65,59 %, code 0, empreinte 104e266aa7bdfaf6. **Cette execution consomme un essai** (L2)

## [2026-09-11] note | les cles de `rules` ne sont plus recopiees nulle part | elles etaient enumerees trois fois dans `rules.py` ; le squelette les DERIVE de `RuleStrategy.describe()` plutot que d'en faire une quatrieme copie

## [2026-09-11] decision | proposition d'extensions "seance" recue et arbitree : 2 ajouts sur 4 retenus | RETENUS : `sizing.kind: "vol_target"` (dimensionnement en volatilite cible, distinct de `risk_fraction` qui dimensionne sur la distance au stop) et `rolling.stride` (pas d'echantillonnage, qui couvre le besoin de `across: sessions_same_offset` sans deviner de frontiere). ECARTES : noeuds `session` et `cumulative` -> ledger. Suite 1405 -> 1434 tests, 4 empreintes d'exemples inchangees

## [2026-09-11] note | la cible de `vol_target` est PAR BARRE, pas annualisee -- correction de la proposition | elle demandait `vol_window` "en SEANCES" et une cible implicitement annuelle. Le ledger a deja ecarte les fenetres exprimees autrement qu'en barres, et l'annualisation par facteur suppose (gonflement d'un facteur ~2 sur donnees minute). Une regle de dimensionnement ne connait pas le pas d'annualisation, qui se mesure apres coup sur l'echantillon

## [2026-09-11] note | le decalage d'une periode exige par la proposition est inutile ICI, et je l'ai omis | le `Context` n'expose que des barres closes et l'execution est retardee (`lag_bars >= 1`) : lire la barre courante n'est pas lire son propre resultat. `RiskFraction` herite deja de cette garantie pour son ATR sans regle supplementaire. Ajouter un decalage aurait ete un reglage sans effet, donc une fausse precaution

## [2026-09-11] note | piege trouve en testant `vol_target` : la troncature peut annuler la strategie | `int(1 * 0.9)` vaut 0 : avec `contracts: 1` et un facteur d'echelle sous 1, aucune position n'est jamais prise, sans erreur ni avertissement. Documente dans la regle et couvert par un test ; remede = une base assez grande (`contracts: 10` donne dix paliers)

## [2026-09-11] note | `vol_target` verifie sur le mecanisme, pas sur un resultat | doubler la volatilite divise la taille par deux : 494, 197, 98, 49, 19 contrats pour des volatilites de 0,002 a 0,050 par barre. Piege d'interpretation observe au passage : une cible de 1 % PAR BARRE sur du quotidien avec une base de 20 donne ~18 contrats ES sur 100 k d'equity -- un levier considerable, meme famille de piege que celui deja documente pour `equity_fraction`. **3 executions sur donnees reelles, donc 3 essais** (L2)

## [2026-09-11] feat | calendrier de seance DECLARE par instrument, et les deux noeuds qu'il debloque | nouveau `src/rsl/data/session.py` ; `data[].session` (start, end, timezone IANA) entre dans le `config_hash` ; `BarStore` porte un champ optionnel `sessions`, ce qui fait que `shifted`, `peer` et les deux feeds en heritent sans plomberie. Noeuds 20 -> 22 : `session@1` (feuille) et `cumulative@1` (fenetre a longueur variable). Suite 1434 -> 1460 tests

## [2026-09-11] decision | deux lignes du ledger REPRISES le jour meme de leur ecriture | `session` et `cumulative` avaient ete ecartes parce qu'il aurait fallu DEVINER la frontiere de seance. Une declaration ne devine rien : le motif du rejet tombe, et les deux lignes de reprise le disent en citant les anciennes. `reset: never` de `cumulative` reste ecarte -- son motif (historique non borne, warmup indefinissable) ne depend pas du calendrier

## [2026-09-11] note | la surface publique du `Context` s'est elargie, et un test adversarial l'a signale | `test_public_surface_is_the_declared_one` a echoue a l'ajout de `session_value` : il fait exactement son travail. Avant d'elargir la liste blanche, j'ai ecrit `tests/adversarial/test_session_closure.py` -- 26 tests dont le decisif : corrompre toutes les barres apres un point ne change AUCUNE valeur de seance lue avant. Les agregats de seance sont calcules a la construction du magasin, donc c'etait le canal de fuite plausible

## [2026-09-11] note | VWAP ancre sur la seance : exprimable par COMPOSITION, sans primitive nouvelle | `arith(/, cumulative(sum, prix*volume), cumulative(sum, volume))`. Verifie analytiquement : a volumes constants il vaut la moyenne des clotures depuis l'ouverture, exact au 1e-9. C'etait l'exemple motivant de la proposition

## [2026-09-11] note | P6 est ressorti puis re-masque, comme annonce | la suite a echoue sur `test_missing_data_sources_are_flagged` des que l'arbre est devenu propre (le hook avait commite), puis a repasse au vert des mes modifications suivantes. Le defaut `all(())` est intact : il n'est visible que sur un arbre propre

## [2026-09-11] fix | P6 corrige : `RunManifest.is_reproducible` ne ment plus par vacuite | `all(())` vaut `True`, donc un run sans AUCUNE source enregistree se declarait `Rejouable oui` -- le cas ou l'on en sait le moins etait celui ou l'on affirmait le plus. `bool(self.data_sources)` devient une condition a part entiere. Verifie en isolant l'etat git : aucune source -> False, une source hachee -> True, source sans hash -> False, arbre sale -> False. Les runs reels sont inchanges

## [2026-09-11] note | pourquoi P6 a survecu a 1400 tests alors qu'un test le visait | le test n'echouait que sur un arbre PROPRE : des que l'arbre etait modifie, `git.is_reproducible` valait deja `False` et masquait tout. Il passait au vert exactement pendant qu'on travaille. Deux tests de regression FIXENT desormais un `GitState` propre au lieu de subir celui du depot -> [[lessons]] L11

## [2026-09-11] fix | P1 RESOLU : motif `.gitignore` ancre en `/data/`, couche donnees enfin versionnee | 8 fichiers, 2 446 lignes, dont `session.py` ecrit aujourd'hui. Diagnostic au moment de pousser : `git ls-files src/` rendait 45 fichiers contre 53 sur le disque, et des tests DEJA pousses importaient `rsl.data.session`, absent du depot -- un clone frais etait casse. `data/` a la racine reste ignore, verifie

## [2026-09-11] note | effet de bord decouvert en designorant : ruff respecte `.gitignore` | la couche donnees n'avait donc JAMAIS ete analysee. 7 defauts dormaient dans du code central (4 `__slots__` non tries, 2 blocs d'imports, 1 generateur). Corriges ; les empreintes de `sma_es_daily`, `paire_es_nq` et `_moule` sont identiques avant et apres, ce qui prouve la neutralite. A ne pas confondre avec les 28 `I001` du ledger, qui etaient des symptomes de l'ABSENCE du paquet -> [[lessons]] L12

## [2026-09-11] note | frontiere du « sans code » mesuree apres les ajouts du jour | le vocabulaire RECONSTRUIT `rsi@1` a partir de ses seuls noeuds : 240 points compares, ecart maximum 0.00e+00. Impossible avant `max_of` et `math`. Corollaire : le RSI d'un spread ES/NQ s'ecrit, alors qu'aucune primitive ne le calcule. Restent hors de portee : deux granularites du meme symbole (structurel), taille fonction d'un signal (`sizing` est un enum), optimisation de parametres et noeuds a memoire (tous deux au ledger). Aucun backtest lance : ces verifications construisent des signaux, elles ne consomment pas d'essai

## [2026-09-11] feat | les deux murs STRUCTURELS du « sans code » sont tombes | (1) `sizing.kind: "signal"` : la taille devient une expression du vocabulaire, avec `max_contracts` obligatoire -- une expression arbitraire n'est pas bornee. `engine.risk` depend du protocole `SupportsSignal`, pas de `strategies.signals` : la dependance continue d'aller de strategies vers engine. (2) `data[].alias` + `panel.allow_mixed_granularity` : le meme instrument a deux granularites, chacune sous son nom. Essai reel : ES quotidien filtre par SMA hebdo, Sharpe 1,14, 90 trades. Suite 1462 -> 1485 tests

## [2026-09-11] note | le multi-timeframe est LE piege de look-ahead du backtest : verifie, pas suppose | `tests/adversarial/test_multi_timeframe_closure.py`, 10 tests. Aucune ligne ne voit une barre hebdomadaire cloturant apres elle ; la barre vue est la plus RECENTE close (voir plus ancien serait un autre defaut, aussi silencieux) ; corrompre le futur ne change rien avant la coupure ; le report est borne et marque `is_stale`

## [2026-09-11] decision | deux garde-fous rendus DECLARABLES plutot que supprimes | l'unicite du symbole devient l'unicite du NOM publie (un alias distingue une duplication voulue d'un accident), et l'homogeneite des granularites reste le defaut mais s'ouvre par `allow_mixed_granularity`. Motif : le second protege les strategies transversales, ou comparer un rendement hebdomadaire a un rendement quotidien n'a pas de sens. Constate au passage : `Panel.granularity` n'a AUCUN consommateur dans le depot ; il vaut desormais la granularite la plus fine, pour ne pas mentir

## [2026-09-11] note | les deux murs restants ne sont pas des manques | optimisation de parametres et noeuds a memoire sont au ledger avec leur mecanisme : ils cassent respectivement le perimetre declare du runner et la reproductibilite bit-a-bit. Les lever couterait ce que le depot protege. La table de [[reference/vocabulaire-signaux]] distingue desormais « leve » de « debout, par decision »
