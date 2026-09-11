---
type: hub
updated: 2026-09-11
generated: true
---

# hot — etat courant

> [!WARNING] FICHIER AUTO-GENERE — NE PAS EDITER A LA MAIN
> Produit par [`wiki/update_hot.py`](update_hot.py), relance par le hook
> `Stop` a chaque fin de session. Toute modification hors du bloc
> **Next Actions** sera ecrasee sans avertissement.
> Derniere generation : 2026-09-11.

## Current State

| Indicateur | Valeur |
|---|---|
| Pages de wiki | 22 |
| Entrees de log | 81 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 16 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 42, fix × 16, feat × 10, decision × 9, setup × 1, lint × 1, experiment × 1, audit × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — fix | `adosc@1` : une contrainte entre parametres rendait la primitive inutilisable depuis le squelette | `window` etait la fenetre RAPIDE et la lente un defaut fige a 10, donc toute fenetre >= 10 etait refusee. Une machine qui lit le squelette remplit le champ obligatoire avec un entier quelconque et echouait. `window` devient la fenetre LENTE, la rapide un petit defaut. Trouve par `test_skeleton.py::test_chaque_primitive_se_construit_avec_ses_defauts`, qui construit chaque primitive comme le ferait une machine
- **2026-09-11** — fix | trois defauts trouves par le parcours le jour de sa mise en place | (1) `zlema@1` sous-declarait son warmup de `(window-1)/2` barres et aurait leve en plein run ; (2) `inertia@1` rendait `NaN` sur serie plate -- `np.std` d'un tableau vide vaut `NaN`, et `NaN <= 0` est faux, donc la garde ne gardait rien ; (3) `t3@1` empile six EMA et n'en recevait l'historique que pour cinq : il rendait `None` a CHAQUE barre des que la fenetre depassait 5, en passant tous les autres tests. Aucun des trois n'etait visible en relecture -> [[lessons]] L16
- **2026-09-11** — decision | verifier une bibliotheque par PARCOURS du registre plutot qu'indicateur par indicateur | `tests/adversarial/test_registre_primitives.py` derive les parametres du SCHEMA de chaque primitive et applique sept proprietes a toutes : futur corrompu sans effet, warmup honnete, ni NaN ni infini, determinisme, serie plate sans erreur, resume publiable, parametre inconnu refuse. Une primitive ajoutee demain est couverte sans qu'une ligne soit ecrite. Les valeurs, elles, restent verifiees une a une par forme fermee ou equivalence -- aucun parcours ne peut voir qu'une moyenne ponderee a les mauvais poids
- **2026-09-11** — feat | 22 -> 136 primitives : parite avec les bibliotheques de reference | 114 indicateurs ajoutes en six familles -- moyennes (16), transformations de barre (11), bandes et canaux (6), oscillateurs de momentum (27), tendance et direction (11), volatilite (13), flux de volume (13), statistiques (13). 209 sorties nommees au total. Les noyaux de lissage sont partages (`lissage.py`) pour que l'amorce d'une EMA ne soit pas reecrite dix fois avec dix conventions. Suite 1552 -> 3350 tests. **Les 7 empreintes d'exemples sont inchangees**
- **2026-09-11** — note | erreur de manipulation rattrapee, a ne pas refaire | `rsl schema --out schemas/rsl.schema.json` sans `--what all` ecrase le schema complet par le SEUL schema des signaux : le defaut de `--what` est `signals`. Le diff (616 insertions, 1505 suppressions) m'a d'abord fait croire que le fichier commite etait perime. Il ne l'etait pas -- verifie en le regenerant depuis un worktree au commit precedent
- **2026-09-11** — fix | effet de bord de P1.b : une cle de `rules` inconnue etait IGNOREE | `rules` est un `dict[str, object]`, le `extra=forbid` de pydantic ne s'y applique pas. `exit_lng` au lieu de `exit_long` donnait une strategie qui entre et ne sort jamais, sans un mot -- un backtest faux, pas un backtest en erreur. Le schema publie annoncait meme `additionalProperties: true`, donc plus permissif que le code : il porte maintenant `propertyNames.enum`, derive de la meme liste. 1548 -> 1552 tests, 7 empreintes d'exemples inchangees
- **2026-09-11** — fix | P1.b : les neuf cles de `rules` cessent d'etre recopiees quatre fois | champs de la classe, `warmup_bars`, `describe()`, `from_spec`, plus une derivation de contournement dans `skeleton.py` qui construisait une strategie temoin pour lire les cles de son descripteur. Desormais `RULE_KEYS`, derive des champs `Signal | None`. Les quatre copies etaient d'accord : le defaut n'etait pas une divergence mais le fait qu'un oubli echoue en silence, et differemment selon l'endroit
- **2026-09-11** — fix | P1.a : `orders.py` sort de `engine/` et le sens unique redevient verifiable | `import rsl.strategies` chargeait SEPT modules de moteur : le runner a besoin du protocole `Strategy`, les strategies ont besoin d'`Order`. Le cycle ne plantait pas -- trois tentatives de le casser en reordonnant les imports ont echoue, `orders` etant une feuille -- donc le cout etait l'impossibilite de raisonner sur une couche seule, pas un risque d'erreur. `Order` et `Fill` n'appartiennent a aucune des deux couches : places sous les deux, avec `errors.py`. 33 modules charges -> 27. `tests/unit/test_couches.py` le tient ferme dans un interpreteur neuf, ce qu'aucun outil du depot ne sait faire

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

Etat au 2026-09-11, apres P1 de l'audit d'architecture et le passage a 136
primitives : **3350 tests passent, aucun n'echoue** ; `ruff` et `mypy --strict` sont propres sur `src` et `tests` ;
les **7 empreintes d'exemples sont inchangees** depuis l'avant-derniere
session. (L'audit du meme jour partait de 1179 tests dont 1 echouait ; cet
echec est le P6 ci-dessous, corrige.)

## Plan de l'audit d'architecture (2026-09-11)

Numerotation PROPRE a cet audit, sans rapport avec les P1..P7 de la liste
suivante, qui viennent de l'audit fonctionnel du 2026-09-10.

- [x] **A-P0 fait** -- valider avant de lire (6,1 s -> 0,89 s pour rejeter une
      specification fausse), et rapporter `execution_stats`, qui etait calcule
      puis jete.
- [x] **A-P1 fait** -- `orders.py` sort de `engine/` : le sens unique entre les
      couches redevient verifiable ([[lessons]] L14). Et les neuf cles de
      `rules` cessent d'etre recopiees quatre fois, ce qui permet enfin de
      **refuser une cle inconnue** ([[lessons]] L15).
- [ ] **A-P2 devient PLUS urgent avec 136 primitives.** La bibliotheque ne
      change rien au cout unitaire d'un `rolling`, mais elle multiplie les
      occasions d'en ecrire un. Arbitrage a rendre, pas tache a executer : `rolling(zscore,120)`
      sur un `arith` de deux primitives coute **1549 us/barre**, soit 1,6 h pour
      un signal sur les 3,7 M de barres minute d'ES et 14,4 h sur l'univers de
      dix. Trois voies, aucune gratuite : elimination des sous-expressions
      communes DANS une barre (~2x, sans toucher a une garantie) ;
      memoisation ENTRE barres (rapide, mais se heurte au rejet des noeuds a
      etat, [[Failed Ideas/ledger]]) ; primitives dediees (deja « en attente »
      au ledger). Recommandation : la troisieme, apres avoir mesure quels cas
      la justifient.
- [ ] **A-P3** -- `signals.py` fait 1915 lignes ; `gui/app.py:275` injecte un
      attribut `teinte` sur un `tk.Label` ; un seul test porte le marqueur
      `slow`.

- [x] **P1 RESOLU (2026-09-11)** -- `rsl.data` est **revenu
      sur le disque** (7 fichiers, 2063 lignes, tests verts) mais reste **non
      versionne** : `.gitignore:1` porte encore `data/` non ancre.
      `git ls-files src/` = 36 fichiers contre 43 sur le disque, et
      `git status` affiche « propre ». Un `git clean -xfd` ou un clone frais
      reperd tout. **Corrige** : motif ancre en `/data/`, et les 8 fichiers de
      `src/rsl/data/` (2 446 lignes) sont versionnes. `data/` a la racine reste
      ignore. Effet de bord decouvert a cette occasion : ruff n'avait jamais
      analyse ce paquet -- 7 defauts corriges, empreintes inchangees ([[lessons]] L12).
- [x] **P6 resolu (2026-09-11)** -- `RunManifest.is_reproducible` mentait par vacuite :
      `all(s.source_hash for s in self.data_sources)` vaut `True` sur un tuple
      vide, donc un run **sans aucune source enregistree** se declare
      `Rejouable oui`. `tests/unit/test_manifest.py::test_missing_data_sources_are_flagged`
      echoue et a raison. Le champ que [[concepts/determinisme]] designe comme
      le seul qui compte est exactement celui qui se trompe.
      Corrige : `bool(self.data_sources)` est desormais une condition a part
      entiere. Deux tests de regression FIXENT l'etat git, parce que l'ancien
      ne voyait le defaut que sur un arbre propre -- voir [[lessons]] L11.
- [ ] **P7 nouveau** -- `rsl schema > fichier.json` ecrit du **CP1252**, pas de
      l'UTF-8 (`ensure_ascii=False` + stdout Windows). Le `§` sort en octet
      `0xA7` et le fichier devient illisible en UTF-8. `--out` ecrit
      correctement : seul le chemin de redirection est touche. Aujourd'hui le
      seul caractere concerne est encodable en CP1252 -- le jour ou une
      docstring portera un `≥` ou une fleche, la commande levera.
- [x] **P2 fait (2026-09-10)**, revu le 2026-09-11 : le `.venv` tourne
      desormais en **Python 3.11.9** avec **numpy 2.4.6**, conforme au manifeste
      archive du README.
- [x] **P3 resolu (constate 2026-09-11)** -- plus aucun point `[A ARBITRER]`
      dans `docs/` (`grep` rend 0).
- [x] **P4 resolu (constate 2026-09-11)** -- `mypy` rend
      `Success: no issues found in 43 source files`. Le retour a numpy 2.4.6 +
      Python 3.11.9 a supprime l'erreur de stubs.
- [x] **P5 resolu (2026-09-10)** -- push operationnel vers
      `Mathisuuuu/BacktestMotors`.
- [x] **`ruff --fix` : le piege est leve** -- la prediction du ledger est
      verifiee. `ruff check src tests` rend `All checks passed!` sans qu'aucun
      fichier de test ait ete touche : les 28 `I001` ont bien disparu d'
      elles-memes au retour de `rsl.data`.
- [ ] Relancer les deux experiences seminales **avec manifeste et empreinte
      archives** -- l'audit a montre qu'elles se reproduisent
      (`sma_es_daily` : Sharpe 0,60, empreinte `e96832fb121b91fb`,
      `verify` identique ; walk-forward 9 plis, 57 % dans un pli), mais rien
      n'a ete archive en `runs/` a cette occasion.
- [ ] Obtenir et ingerer la source du Deflated Sharpe (independance des essais).
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
