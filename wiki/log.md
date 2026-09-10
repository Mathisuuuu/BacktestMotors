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
