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
