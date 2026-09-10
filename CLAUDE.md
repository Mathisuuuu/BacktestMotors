# CLAUDE.md

`research-strategy-lab` — socle de backtest event-driven, deterministe, dans
lequel le look-ahead bias est structurellement impossible. Python 3.11+, polars
/ numpy / pydantic, `ruff` + `mypy --strict` sans exception.

Les documents de `docs/` sont **normatifs** : un comportement du code qui les
contredit est un bug du code, pas du document.

## Wiki

Ce depot porte un wiki maintenu par l'agent, dans `wiki/`. Il n'est pas de la
documentation : c'est de la **memoire entre sessions**. Deux regles permanentes
le font fonctionner, et elles ne sont pas optionnelles.

### Regle 1 — avant tout travail de fond

Lire, dans cet ordre :

1. `wiki/index.md` — le catalogue de tout ce qui est su.
2. `wiki/Failed Ideas/ledger.md` — les idees deja tentees et abandonnees, avec
   la raison. **Proposer une idee qui figure au ledger sans traiter la raison de
   son abandon est une erreur.**

Puis `wiki/hot.md` pour l'etat courant, et les pages que l'index designe comme
pertinentes.

Ne pas fouiller le code pour redecouvrir ce que le wiki dit deja.

### Regle 2 — avant de finir

1. Mettre a jour la ou les pages concernees (`updated:` au jour du jour).
2. Appendre une ligne datee a `wiki/log.md` :
   `## [YYYY-MM-DD] <type> | <ce qui s'est passe> | <resultat>`
   Le log est **append-only** : on n'y modifie ni n'y efface jamais rien.
3. Si quelque chose a ete abandonne : une ligne au ledger, **avec un motif
   exploitable** — un mecanisme, un chiffre, ou une contradiction avec une
   garantie du socle. « Ne marchait pas » est refuse.

Les gabarits de page, les recettes et la procedure de lint sont dans
`wiki/SCHEMA.md`. S'y conformer.

### Regle d'immuabilite

Le wiki **lie** vers les sources — code, donnees, `docs/`, `examples/`,
`schemas/`, rapports de run. Il ne recopie jamais leur contenu comme s'il en
etait la verite. Les sources font foi ; une page de wiki qui contredit le code a
tort, et se corrige.

Corollaire pratique : dans `wiki/reference/`, une page **routeur** ne contient
que des liens et ne fait autorite sur rien. Un chiffre ou une regle recopie
depuis `docs/` deviendra faux sans prevenir le jour ou `docs/` changera.

### Unite de travail : l'essai

Une page de `wiki/experiments/` = une strategie evaluee sur un echantillon avec
une configuration = **une ligne du compteur d'essais**. Ce comptage est une
entree du Deflated Sharpe : un essai fait et non enregistre gonfle mecaniquement
le DSR de tous les autres, sans que rien ne le signale. Enregistrer aussi les
essais qui ratent.

### `hot.md` est genere

`wiki/hot.md` est produit par `wiki/update_hot.py` (bibliotheque standard
uniquement) et regenere par le hook `Stop`. **Ne jamais l'editer a la main**,
sauf entre les marqueurs `<!-- NEXT-ACTIONS:START -->` et
`<!-- NEXT-ACTIONS:END -->`, seul bloc que le generateur preserve.

## Automatisation

`.claude/settings.json` declare deux hooks PowerShell, tous deux ecrits pour ne
jamais faire echouer une session (chaque etape isolee, code de sortie toujours
`0`) :

| Hook | Script | Effet |
|---|---|---|
| `SessionStart` | `.claude/hooks/session-start.ps1` | `git pull --ff-only`, au mieux ; en cas de divergence, echoue en silence et laisse l'humain arbitrer |
| `Stop` | `.claude/hooks/stop-wiki.ps1` | regenere `hot.md`, puis commite et pousse si l'arbre a change |

Les deux actions du `Stop` sont dans **un seul** script parce que l'ordre
compte : hot.md doit etre regenere *avant* le commit, sinon il part avec une
session de retard.

Le commit automatique porte sur **tout l'arbre de travail** (`git add -A`).
Basculer `$WikiOnly = $true` en tete de `stop-wiki.ps1` pour le restreindre a
`wiki/` si des travaux en cours ne doivent pas partir sur `main`.

Les scripts `.ps1` doivent rester en **ASCII pur**. PowerShell 5.1 lit un `.ps1`
sans BOM en CP1252 : un tiret cadratin UTF-8 y devient une sequence dont le
dernier octet est un guillemet fermant typographique, que PowerShell accepte
comme delimiteur de chaine — le script ne parse plus. Verifier avec
`grep -n -P '[^\x00-\x7F]' .claude/hooks/*.ps1`.

## Obsidian

Le vault est la **racine du depot**, pas `wiki/` : les wikilinks doivent pouvoir
resoudre vers `docs/`, `src/` et `examples/`, et `.obsidian/` a sa place dans le
depot.

`.obsidian/graph.json` porte les groupes de couleur par chemin, ecrits comme
requetes **mutuellement exclusives** (negations `-path:`) pour qu'une nouvelle
page prenne sa couleur sans maintenance. **Obsidian reecrit ce fichier pendant
qu'il tourne** : ne le modifier que si Obsidian est ferme, sinon la modification
sera ecrasee.
