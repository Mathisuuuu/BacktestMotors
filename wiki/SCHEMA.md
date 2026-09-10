---
type: hub
updated: 2026-09-10
---

# SCHEMA — le reglement du wiki

Ce fichier dit **comment** ecrire dans le wiki. Il ne contient aucune
connaissance sur le projet : uniquement des gabarits, des recettes et une
procedure de controle.

Trois regles qui priment sur tout le reste :

1. **Le wiki ne duplique jamais une source.** Le code, les donnees, les
   documents normatifs de `docs/`, les rapports de run JSON sont la verite
   terrain. Une page de wiki *pointe* vers eux. Si une page et le code se
   contredisent, c'est la page qui a tort.
2. **`log.md` est append-only.** On y ajoute une ligne, on n'en retire jamais.
3. **`hot.md` est genere.** Ne jamais l'editer a la main, sauf dans le bloc
   `Next Actions` qui est prevu pour ca.

---

## 1. Gabarits de page

Chaque page porte un frontmatter YAML. Les champs `type` et `updated` sont
obligatoires partout. Les dates sont absolues, au format `YYYY-MM-DD` : jamais
« la semaine derniere ».

### 1.1 Entree d'index (`index.md`)

Une seule ligne par page, jamais un paragraphe :

```markdown
- [[experiments/sma-es-daily-walkforward|SMA ES quotidien — walk-forward]] — 9 plis, 57 % du resultat dans un seul pli. Verdict : `fragile`.
```

Forme : `- [[chemin|Titre]] — resume en une phrase. Verdict/Statut : X.`

### 1.2 Experience (`experiments/*.md`) — l'unite de travail

Une page = **un essai** : une strategie evaluee sur un echantillon donne avec
une configuration donnee. Un changement de parametre est un essai de plus, donc
une ligne de plus dans le tableau des variantes. Ce comptage n'est pas
decoratif : c'est l'entree `n_trials` du Deflated Sharpe.

```markdown
---
type: experiment
updated: YYYY-MM-DD
statut: en-cours | termine | abandonne
verdict: prometteur | fragile | rejete | non-conclusif | n/a
strategie: rules@1
instruments: [ES.v.0]
essais: 8
---

# <Titre>

## Hypothese
Ce qu'on cherche a savoir, en une ou deux phrases, sous forme falsifiable :
« X bat Y sur Z », pas « explorer X ».

## Montage
- Config : [examples/xxx.json](../../examples/xxx.json)
- Donnees : symbole, granularite, periode, nombre de barres
- Commande : `rsl run ...`
- Rapport : chemin du JSON (non versionne) + empreinte de resultat

## Resultat
Chiffres bruts, colles depuis la sortie. Ne jamais arrondir a la main.

## Lecture
Ce que les chiffres disent et surtout **ce qu'ils ne disent pas** : nombre
d'essais consommes, concentration du resultat, ce qui reste non teste.

## Verdict
Une phrase tranchee. Si `rejete` ou `abandonne` : ajouter une ligne a
[[Failed Ideas/ledger]] et lier les deux pages l'une a l'autre.

## Liens
[[concepts/...]], [[reference/...]], experiences voisines.
```

### 1.3 Concept (`concepts/*.md`)

Une page = **un terme du vocabulaire**, pour qu'un mot veuille dire la meme
chose dans la conversation et dans le code.

```markdown
---
type: concept
updated: YYYY-MM-DD
statut: stable | en-debat
alias: [autre nom, sigle]
---

# <Terme>

## Definition
Deux ou trois phrases. Pas de digression.

## Dans ce depot
Ou le concept est implemente ou impose. Liens vers le code et les documents
normatifs. **Ne pas recopier le contenu de la source.**

## Pourquoi ca compte
Ce qui casse si on l'ignore.

## Liens
[[...]]
```

### 1.4 Recherche (`research/*.md`)

Une page = **une source externe** : papier, article, jeu de donnees, billet.

```markdown
---
type: research
updated: YYYY-MM-DD
statut: a-ingerer | ingere | ecarte
source: <auteur, annee, titre>
url: <lien ou chemin local>
---

# <Titre de la source>

## Ce que la source affirme
Resume fidele. Distinguer ce que la source demontre de ce qu'elle suppose.

## Ce qu'on en retient ici
Applicable a ce depot, ou pas, et pourquoi.

## Contradictions
Points ou la source contredit une page existante du wiki, avec le lien.

## Statut d'ingestion
Ce qui a ete integre, dans quelles pages. Ce qui reste a faire.

## Liens
[[...]]
```

### 1.5 Routeur (`reference/*.md`)

Une page = **une entree vers l'autorite d'un sujet**. Un routeur ne contient
aucun detail : uniquement des liens, et une phrase disant ce qu'on trouve
derriere chacun. C'est la page qu'on lit quand on ne sait pas ou chercher.

```markdown
---
type: reference
updated: YYYY-MM-DD
autorite: <chemin du fichier qui fait foi>
---

# <Sujet>

> Page routeur. Elle ne fait autorite sur rien : elle dit ou est l'autorite.

| Question | Reponse faisant autorite |
|---|---|
| ... | [chemin](../../chemin) §X |

## Liens wiki
[[...]]
```

### 1.6 Ledger des idees abandonnees (`Failed Ideas/ledger.md`)

Tableau unique, une ligne par idee abandonnee. **Jamais de suppression de
ligne** : une idee reprise plus tard devient une nouvelle ligne qui reference
l'ancienne.

Colonnes : `Date | Idee | Ce qui a ete tente | Pourquoi ca a echoue | A retenter si | Lien`.

La colonne **Pourquoi** est la seule qui compte vraiment. « Ne marchait pas »
n'est pas une raison. Une raison est un mecanisme, un chiffre, ou une
contradiction avec une garantie du socle.

---

## 2. Recettes

### 2.1 Debut de session — obligatoire

1. Lire [[index]].
2. Lire [[Failed Ideas/ledger]], pour ne pas reprendre un chemin deja mort.
3. Lire [[hot]] : etat courant et actions suivantes.
4. Ouvrir les pages que l'index designe comme pertinentes pour la tache.

### 2.2 Une experience est terminee

1. Creer `wiki/experiments/<slug>.md` depuis le gabarit 1.2.
2. Coller les chiffres bruts, sans les retoucher.
3. Ajouter une ligne a [[index]].
4. Appendre a [[log]] :
   `## [YYYY-MM-DD] experiment | <slug> | <verdict + chiffre cle>`
5. Si le verdict est `rejete` ou `abandonne` : ajouter une ligne au
   [[Failed Ideas/ledger]], et lier les deux pages l'une a l'autre.
6. Si une lecon depasse cette experience : l'ajouter a [[lessons]].

### 2.3 Une source externe est ingeree

1. Creer `wiki/research/<slug>.md` depuis le gabarit 1.4.
2. Mettre a jour les pages `concepts/` que la source precise ou contredit.
3. Si la source invalide une experience passee : le noter dans `Contradictions`
   **et** dans la page de l'experience concernee.
4. Ligne d'index, puis ligne de log
   (`## [YYYY-MM-DD] ingest | <source> | <ce qui a change>`).

### 2.4 Un terme nouveau apparait

Si un terme est employe deux fois et n'a pas de page : creer
`wiki/concepts/<slug>.md`. C'est bon marche, et l'absence de page est la
premiere cause de malentendu.

### 2.5 Une decision de design est prise

Le wiki **ne stocke pas** la decision : `docs/` fait foi. Le wiki cree ou met a
jour un routeur `reference/` qui pointe vers la section concernee, puis logue
`## [YYYY-MM-DD] decision | <sujet> | <fichier docs mis a jour>`.

### 2.6 Fin de session — obligatoire

1. Mettre a jour les pages touchees (`updated:` au jour du jour).
2. Appendre au moins une ligne a [[log]].
3. Ligne au ledger si quelque chose a ete abandonne.
4. Ne pas toucher a `hot.md` : le hook `Stop` le regenere.

---

## 3. Lint — controle periodique

A lancer sur demande, et spontanement toutes les ~10 entrees de log. Corriger
ce qui est mecanique, poser les questions pour le reste.

| # | Controle | Comment |
|---|---|---|
| 1 | **Pages orphelines** | Toute page de `wiki/` doit etre citee par [[index]] ou par une autre page. Lister celles qui ne le sont pas. |
| 2 | **Liens morts** | Tout `[[...]]` doit resoudre ; tout lien relatif vers `src/`, `docs/`, `examples/` doit exister sur le disque. Ignorer les blocs de code : les `[[...]]` des gabarits ci-dessus sont des emplacements, pas des liens. |
| 3 | **Entrees perimees** | Une page dont le `updated:` precede un changement du code qu'elle decrit. Verifier avec `git log -1 --format=%ad -- <chemin>`. |
| 4 | **Contradictions** | Deux pages incompatibles. Trancher avec la source, jamais entre les deux pages. |
| 5 | **Concepts manquants** | Un terme employe dans 3 pages ou plus sans page `concepts/`. |
| 6 | **Duplication de source** | Une page qui recopie plus de ~5 lignes de `docs/` ou de `src/` : la remplacer par un lien. |
| 7 | **Ledger incomplet** | Une experience `rejete` sans ligne au ledger, ou une ligne de ledger sans raison exploitable. |
| 8 | **Index desynchronise** | Une page sur disque et absente de l'index, ou l'inverse. |

Commandes utiles :

```bash
grep -roh "\[\[[^]]*\]\]" wiki | sort -u
```

```bash
grep "^## \[" wiki/log.md | tail -5
```

Consigner le passage :
`## [YYYY-MM-DD] lint | <n> controles | <ce qui a ete corrige>`.
