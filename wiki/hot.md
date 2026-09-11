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
| Entrees de log | 86 |
| Derniere activite | 2026-09-11 |
| Idees ecartees (ledger) | 17 |
| Idees en attente (ledger) | 3 |
| Pages `Failed Ideas/` | 1 |
| Pages `concepts/` | 6 |
| Pages `experiments/` | 3 |
| Pages `reference/` | 7 |
| Pages `research/` | 1 |

**Activite par type :** note × 44, fix × 17, feat × 11, decision × 10, setup × 1, lint × 1, experiment × 1, audit × 1

## Experiences

| Experience | Statut | Verdict | Essais | Maj |
|---|---|---|---|---|
| [[experiments/dsr-grille-sma-8-essais]] | `termine` | `non-conclusif` | 8 | 2026-09-10 |
| [[experiments/rsi-survendu-hors-lundi]] | `termine` | `non-conclusif` | 1 | 2026-09-11 |
| [[experiments/sma-es-daily-walkforward]] | `termine` | `fragile` | 1 | 2026-09-10 |

Le total des essais alimente le Deflated Sharpe : un essai non enregistre gonfle le DSR de tous les autres.

## Derniere activite — 8 entree(s)

- **2026-09-11** — note | `Context.data_token` rejoint la surface publique, et ce qu'il a fallu pour que ce soit acceptable | premiere version : le jeton ETAIT le magasin, ce qui donnait l'historique complet -- futur inclus -- a qui sait le caster. `test_forbidden_access.py` l'a refuse, et il avait raison. Corrige : le jeton est un `object()` NU porte par `BarStore`, sans aucun attribut. Ni le magasin (fuite), ni un entier d'identite (reattribue apres ramassage, donc deux series confondues en silence)
- **2026-09-11** — note | semantique de `peer` sous `rolling`, mise au jour par le travail sur la memoisation | dans `rolling(zscore, 120, close / peer(NQ, close))`, le terme NQ vaut la barre COURANTE pour les 120 decalages : il ne glisse pas avec la fenetre. Ce n'est ni documente ni evidemment voulu. NON corrige ici -- le changer modifierait l'empreinte archivee de `examples/paire_es_nq.json`, donc c'est une decision a prendre a part
- **2026-09-11** — fix | la memoisation a change une empreinte avant d'etre corrigee, et c'est ce qui l'a rendue sure | `examples/paire_es_nq.json` passait a 634 remplissages au lieu de 30. Cause : `BarContext.shifted` recopie le resolveur de pairs et l'etat de position, donc un sous-arbre contenant `peer` ou `position` ne depend PAS que de `(serie, barre)`. Regle demontree et non supposee : un `BarContext` porte exactement quatre attributs, la cle en couvre deux, les deux autres ne s'atteignent que par ces deux noeuds. Ces sous-arbres ne sont donc pas memoises -> [[lessons]] L17
- **2026-09-11** — feat | memoisation des sous-arbres de `rolling`, `bars_since` et `cumulative` | `rolling(zscore,120)` d'un `arith` de deux `sma` : **1 381 -> 116 us/barre**. `rolling` imbrique (MACD recompose) : 716 -> 45 us. De bout en bout sur ES quotidien : **5 427 -> 2 299 ms, empreinte identique**. Les 7 empreintes d'exemples sont inchangees, et `RSL_NO_MEMO=1` rejoue la suite entiere sans le mecanisme avec le meme resultat -- c'est la preuve la plus directe qu'aucun resultat n'en depend. Ledger : reprise PARTIELLE d'une idee ecartee le 2026-09-10, l'etat semantique restant interdit
- **2026-09-11** — decision | A-P2 tranche : memoisation, apres que le profil a INVALIDE la recommandation precedente | je recommandais des primitives dediees. Le profil montre que le cout de `rolling` est exactement `window x cout(sous-arbre)` -- `shifted` ne pese que 0,34 us, aucun gaspillage a recuperer. Une primitive ne prenant qu'un CHAMP de prix, elle ne peut pas remplacer un `rolling` sur une EXPRESSION : l'option ne traitait pas le cas mesure. L'elimination de sous-expressions communes ne le traitait pas non plus (les deux `sma` du cas mesure sont differentes). Restait la seule qui adresse la redondance ENTRE barres
- **2026-09-11** — fix | `adosc@1` : une contrainte entre parametres rendait la primitive inutilisable depuis le squelette | `window` etait la fenetre RAPIDE et la lente un defaut fige a 10, donc toute fenetre >= 10 etait refusee. Une machine qui lit le squelette remplit le champ obligatoire avec un entier quelconque et echouait. `window` devient la fenetre LENTE, la rapide un petit defaut. Trouve par `test_skeleton.py::test_chaque_primitive_se_construit_avec_ses_defauts`, qui construit chaque primitive comme le ferait une machine
- **2026-09-11** — fix | trois defauts trouves par le parcours le jour de sa mise en place | (1) `zlema@1` sous-declarait son warmup de `(window-1)/2` barres et aurait leve en plein run ; (2) `inertia@1` rendait `NaN` sur serie plate -- `np.std` d'un tableau vide vaut `NaN`, et `NaN <= 0` est faux, donc la garde ne gardait rien ; (3) `t3@1` empile six EMA et n'en recevait l'historique que pour cinq : il rendait `None` a CHAQUE barre des que la fenetre depassait 5, en passant tous les autres tests. Aucun des trois n'etait visible en relecture -> [[lessons]] L16
- **2026-09-11** — decision | verifier une bibliotheque par PARCOURS du registre plutot qu'indicateur par indicateur | `tests/adversarial/test_registre_primitives.py` derive les parametres du SCHEMA de chaque primitive et applique sept proprietes a toutes : futur corrompu sans effet, warmup honnete, ni NaN ni infini, determinisme, serie plate sans erreur, resume publiable, parametre inconnu refuse. Une primitive ajoutee demain est couverte sans qu'une ligne soit ecrite. Les valeurs, elles, restent verifiees une a une par forme fermee ou equivalence -- aucun parcours ne peut voir qu'une moyenne ponderee a les mauvais poids

## Next Actions

<!-- NEXT-ACTIONS:START -->
> Bloc edite a la main. Le generateur le recopie tel quel a chaque passage :
> c'est le seul endroit de ce fichier ou ecrire.

Etat au 2026-09-11, apres A-P0 a A-P2 de l'audit d'architecture et le passage
a 136 primitives : **3388 tests passent, aucun n'echoue** (3384 + 4 sautes avec
`RSL_NO_MEMO=1`) ; `ruff` et `mypy --strict` sont propres sur `src` et `tests` ;
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
- [ ] **A-P3** -- `signals.py` depasse desormais 1950 lignes ; `gui/app.py:275` injecte un
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
- [ ] **Decision a prendre : la semantique de `peer` sous `rolling`.** Le terme
      distant vaut la barre COURANTE pour tous les decalages de la fenetre - il
      ne glisse pas avec elle. Mis au jour par le travail sur la memoisation, ni
      documente ni evidemment voulu. Le corriger changerait l'empreinte archivee
      de `examples/paire_es_nq.json`.
- [ ] Relancer les deux experiences seminales **avec manifeste et empreinte
      archives** -- l'audit a montre qu'elles se reproduisent
      (`sma_es_daily` : Sharpe 0,60, empreinte `e96832fb121b91fb`,
      `verify` identique ; walk-forward 9 plis, 57 % dans un pli), mais rien
      n'a ete archive en `runs/` a cette occasion.
- [ ] Obtenir et ingerer la source du Deflated Sharpe (independance des essais).
<!-- NEXT-ACTIONS:END -->

---

Entrees : [[index]] · [[SCHEMA]] · [[log]] · [[lessons]] · [[Failed Ideas/ledger]]
