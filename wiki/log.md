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
