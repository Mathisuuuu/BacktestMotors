# Contrat anti-look-ahead

Ce document définit le contrat que le moteur `rsl` garantit, ce qu'il ne
garantit pas, et **par quel mécanisme** chaque garantie tient. Il complète
[`execution-model.md`](./execution-model.md), qui fixe la sémantique
d'exécution.

Principe directeur : **la fuite d'information future n'est pas interdite, elle
est rendue impossible à exprimer.** On ne compte ni sur la discipline du
développeur, ni sur la relecture, ni sur des conventions de nommage. Si une
stratégie peut écrire l'expression qui triche, le socle est raté.

Statut : décisions de design, avant implémentation.

---

## 1. Modèle de menace

Sept voies par lesquelles le futur entre dans un backtest. Le socle doit fermer
les six premières par construction ; la septième ne se ferme pas par du code et
doit être rendue visible.

| # | Fuite | Fermée par |
|---|---|---|
| 1 | La stratégie reçoit le DataFrame complet et lit `df[t+1]` | §2 — `Context` à curseur, aucune référence au tableau complet |
| 2 | Confusion étiquette/clôture : la barre `t` est réputée connue à `ts_event(t)` | §3 — `ts_close` distinct, cursor avancé à la clôture |
| 3 | Exécution au `close` de la barre qui a produit le signal | `execution-model.md` §2.1 — `execution_lag >= 1`, non contournable |
| 4 | Normalisation sur l'échantillon complet (z-score global, min-max global) | §5 — primitives à fenêtre glissante uniquement |
| 5 | Forward-fill silencieux d'un instrument absent | §4 — absence ≠ dernier prix, ffill explicite et compté |
| 6 | Biais de survie / univers figé a posteriori | §4.2 — appartenance à l'univers calculée à `t` |
| 7 | Le chercheur choisit la stratégie après avoir vu les données | **Non fermable.** §7 — compteur d'essais et Deflated Sharpe |

---

## 2. Le `Context`

### 2.1 Ce que c'est

Une vue **en lecture seule, à curseur**, sur un magasin de barres immuable.

```python
class Context(Protocol):
    @property
    def ts(self) -> datetime: ...          # ts_close de la barre courante
    @property
    def bar(self) -> Bar: ...              # la barre courante, close
    def history(self, n: int) -> BarWindow: ...
    def value(self, field: Field, lag: int = 0) -> float: ...
    @property
    def n_bars_seen(self) -> int: ...
```

Le `Context` détient :

- une référence au magasin de colonnes `numpy` (immuable, partagé, jamais
  copié) ;
- un entier `_i`, l'index de la barre courante ;
- **rien d'autre**.

### 2.2 Les cinq règles

1. **Aucune méthode ne renvoie de données d'index `> _i`.** `history(n)` renvoie
   les barres `[_i - n + 1, _i]`, toutes closes.
2. **`_i` n'est modifiable que par le runner**, via une méthode privée
   `_advance()`, en un seul point du code. Le `Context` remis à la stratégie
   n'expose aucun setter.
3. **Les tableaux renvoyés sont des vues non modifiables.** Les vues `numpy`
   sortent avec `flags.writeable = False` : une stratégie ne peut pas
   corrompre l'historique d'une autre barre, ni celui d'un autre run.
4. **La longueur totale du jeu de données n'est pas exposée.** Il n'y a pas de
   `__len__`, pas de `total_bars`, pas de `end_date`. Une stratégie qui
   connaîtrait la fin de l'échantillon pourrait s'en servir (liquider à
   l'avant-dernière barre, dimensionner en fonction du temps restant). Seul
   `n_bars_seen` est disponible.
5. **Aucune référence au tableau brut ne fuit.** Pas d'attribut public pointant
   sur le magasin, pas de `.df`, pas de `.raw`.

### 2.3 Historique insuffisant

`history(n)` avec `n > n_bars_seen` **lève `InsufficientHistoryError`**. Elle ne
renvoie ni un tableau court, ni un tableau complété de `NaN`.

Motif : un `NaN` se propage silencieusement dans une moyenne, un z-score, une
comparaison — et une comparaison avec `NaN` est `False`, ce qui produit
« pas de signal » au lieu d'« erreur ». Le backtest tourne, le résultat est
faux, personne ne le voit. Une exception, elle, arrête le run.

Corollaire pour les stratégies : elles doivent déclarer leur `warmup_bars`. Le
runner ne les appelle qu'à partir de `_i >= warmup_bars`. Les barres de
préchauffage sont **exclues du calcul des métriques** et le rapport indique
combien ont été consommées.

### 2.4 Accès interdit

Toute tentative d'accès à un index `> _i` lève `LookAheadError`, sous-classe
de `RuntimeError`. Elle n'est **jamais rattrapée** par le moteur : un
`LookAheadError` fait échouer le run entier. Un backtest qui a tenté de tricher
ne produit pas de résultat dégradé, il ne produit pas de résultat.

C'est le test adversarial n° 2.

### 2.5 L'état de position, et pourquoi il ne rompt rien

Le `Context` expose `position` : quantité détenue, barres écoulées depuis
l'entrée, prix d'entrée, plus haut et plus bas atteints depuis l'entrée.

C'est une entorse **apparente** à la pauvreté délibérée du §2.1. Elle est
justifiée, et il faut dire précisément par quoi.

**Ces valeurs décrivent le passé de la stratégie, pas l'avenir du marché.**
Elles sont calculées à partir des fills — qui viennent de barres déjà closes —
et des extrêmes des barres traversées depuis l'entrée. Aucune n'existe avant
que la position n'existe. Une stratégie qui les lit n'apprend rien qu'elle
n'ait elle-même provoqué.

**C'est le runner qui les calcule, pas un nœud à mémoire.** La distinction
n'est pas cosmétique. Un nœud de signal qui mémoriserait son état survivrait
d'un run à l'autre : deux backtests identiques donneraient des résultats
différents selon ce qui a tourné avant, et le test de corruption du futur
perdrait son sens. Le runner, lui, repart de zéro à chaque `run()` par
construction, et son suivi ne survit pas à la fin de `run()`.

**Hors runner, la position est toujours à plat.** Un `Context` construit à la
main ne peut pas inventer une position que personne n'a prise.

**Une vue reculée voit la position de SA barre** (depuis le 2026-09-11). Le
runner enregistre l'état à chaque barre dans un historique **borné** porté par
le feed, et `ctx.shifted(k)` y lit l'état de la barre `i-k`. Auparavant il
recopiait l'état courant : `rolling(mean, 20, position("bars_held"))` lisait
vingt fois la même valeur, sans que rien ne le signale.

Cela ne déplace pas la frontière du §2.5, et il faut voir pourquoi :

- l'historique est écrit par le **runner**, pas par un nœud. L'argument
  ci-dessus tient mot pour mot — c'est toujours le runner qui calcule ;
- il est **reconstruit à chaque run** : les contextes sont créés par le feed à
  chaque `run()`, donc rien ne survit d'un backtest à l'autre ;
- il ne contient que des états **déjà exposés** à la stratégie. Le relire plus
  tard ne révèle rien de neuf, et surtout rien de postérieur ;
- il est borné par le `warmup_bars` que la stratégie **déclare**. Au-delà, le
  socle lève `InsufficientHistoryError` plutôt que de rendre un état plat qui
  passerait pour une mesure. Avant la première barre enregistrée, en revanche,
  « à plat » est une **déduction** et non un défaut choisi : le runner
  n'appelle pas la stratégie pendant le préchauffage, donc aucun ordre n'a pu
  être émis.

Ce que cela rend exprimable : les sorties temporelles (« sortir après dix
barres ») et les sorties calées sur un extrême atteint depuis l'entrée, dont le
stop suiveur — **évalué à la clôture**, puis exécuté à la barre suivante. Un
stop suiveur qui se déclenche *en cours* de barre reste une affaire de moteur,
pas de signal ; les deux ne donnent pas le même prix de sortie sur une barre
violente, et confondre les deux serait flatteur.

Le test de corruption du futur est rejoué sur une stratégie qui lit
`bars_held` : bruiter les barres après `k` ne change rien avant `k`.

---

## 3. Ordre temporel du runner

Une itération, dans cet ordre exact :

```
1. avancer le curseur      -> la barre i est close, elle devient visible
2. evaluer les stops armes -> contre OHLC(i)          [poses a une barre < i]
3. remplir les ordres dus  -> contre OHLC(i)          [soumis a i - lag]
4. marquer le portefeuille -> equity(i) avec close(i)
5. appeler on_bar(ctx)     -> nouveaux ordres, dus a i + lag
6. enregistrer l'etat
```

L'étape 5 est **la dernière**. Rien de ce que la stratégie retourne à l'étape 5
ne peut affecter les étapes 1 à 4 de la même itération. C'est ce qui rend le
lag structurel et non conventionnel.

Le curseur n'avance qu'à l'étape 1 et nulle part ailleurs.

Deux ordres relatifs comptent, et pour des raisons différentes.

**Les stops (2) avant les fills (3).** Un stop attaché à un ordre rempli à la
barre `i` ne doit pas être évalué contre cette même barre `i` : il est armé à
partir de `i+1` (`execution-model.md` §2.2). Évaluer les stops avant les fills
implémente cette règle sans code supplémentaire — au moment de l'étape 2, le
stop de l'étape 3 n'existe pas encore.

**Les fills (3) avant le marquage (4).** L'equity enregistrée à l'étape 6 doit
refléter les exécutions de la barre. Marquer avant de remplir enregistrerait une
equity périmée d'une barre, et l'invariante comptable serait vérifiée sur un
état qui n'est celui d'aucun instant.

*Note : cet ordre corrige celui de la première rédaction de ce document, qui
plaçait le marquage en position 2. La propriété qui compte — `on_bar` en
dernier — est inchangée.*

---

## 4. Données manquantes et multi-instruments

### 4.1 Aucun forward-fill implicite

Sur le calendrier commun d'un panier multi-instruments, si l'instrument `X` n'a
pas de barre à `t`, alors **`X` est absent de la coupe transversale à `t`**. Il
n'a pas « le prix d'avant ». `ctx_multi.symbols()` ne le liste pas, et
`ctx_multi["X"]` lève `SymbolNotAvailableError`.

Motif : reporter le dernier prix d'un instrument fermé mélange deux instants.
Un momentum cross-sectionnel qui classe un actif fermé sur son prix de la
veille lui attribue un rendement nul artificiel et le fait remonter dans le
tri.

Le forward-fill reste possible, mais :

- il est **explicite** : `align_policy="ffill"` (les autres valeurs sont
  `"drop"` — défaut — et `"error"`) ;
- il est **borné** : `max_ffill_bars`, obligatoire si `align_policy="ffill"` ;
- il est **journalisé** : le nombre de barres rancies par instrument
  (`n_stale_bars`) figure dans le rapport de run et dans le manifeste ;
- une barre rancie est **marquée** (`is_stale=True`) et la stratégie peut la
  lire.

### 4.2 Appartenance à l'univers

L'univers d'un rebalancement à `t` est calculé **avec l'information disponible
à `t`** :

```
X est dans l'univers a t  <=>  X a au moins min_history barres closes a t
                          et   X a imprime une barre dans les
                               max_staleness dernieres barres
```

Aucun pré-filtrage sur la disponibilité en fin d'échantillon. C'est ce qui
permet de traiter FDAX (1,46 an d'historique, démarrant en mars 2025) sans
biais : il entre dans l'univers quand il a assez d'historique, pas avant, et
personne ne « sait » d'avance qu'il existera.

Les instruments qui cessent d'imprimer sortent de l'univers ; leurs positions
sont liquidées au rebalancement suivant, au prix de la dernière barre close
disponible, et l'événement est compté (`n_forced_liquidations`).

### 4.3 Rééchantillonnage causal

Toute agrégation (minute → journalier, journalier → mensuel) obéit à la même
règle : **une barre agrégée n'existe qu'une fois sa période terminée**. Une
barre mensuelle partielle n'est jamais visible.

**Quel instant porte la disponibilité.** `ts_close` d'une barre agrégée est la
**frontière de période** — le premier instant de la période suivante — et non la
clôture de sa dernière barre constituante.

La première rédaction de ce document disait le contraire, et c'était une
erreur. Mesuré sur les dix contrats du jeu de données : un mois où 6B imprime sa
dernière barre à 23:56 et les autres à 00:00 produit **deux lignes de panneau au
lieu d'une**, chacune avec un univers amputé. Le panneau mensuel comptait 181
lignes pour 128 mois, dont 47 à un seul instrument. Un momentum transversal y
classait 8 instruments sur 9 sans qu'aucune règle ne le demande — le tri était
faussé par l'horaire de clôture d'une place, pas par un signal.

La frontière de période est **postérieure ou égale** à toutes les clôtures
constituantes. Elle est donc strictement plus conservatrice — elle n'anticipe
rien — et elle fait coïncider exactement les instruments d'une même période.

Conséquence assumée : la dernière barre agrégée d'un échantillon porte un
`ts_close` postérieur à la dernière donnée disponible (une barre d'août 2026 est
datée du 1er septembre). C'est un libellé de disponibilité, pas une prétention
sur des données ; et l'erreur va dans le sens prudent.

`close_stamp="last_bar"` rétablit l'ancien comportement pour l'analyse
mono-instrument, où la question ne se pose pas.

Le rééchantillonnage est effectué **une fois, en amont**, et produit un
magasin de barres ordinaire. Il n'y a pas de rééchantillonnage à la volée
depuis le `Context` : ce serait le chemin le plus court vers une barre
partielle traitée comme complète.

---

## 5. Primitives et statistiques roulantes

### 5.1 Signature contrainte

```python
Primitive = Callable[[Context, ParamsT], float | None]
```

Une primitive ne reçoit **que** le `Context`. Elle ne peut donc pas voir
au-delà de `_i` : la garantie du §2 se propage à toute la bibliothèque sans
règle supplémentaire.

Le registre est **statique** : le décorateur `@primitive` enregistre au moment
de l'import, dans un `dict` dont l'ordre d'insertion est stable et dont
l'itération est triée par clé partout où l'ordre pourrait influencer un
résultat.

### 5.2 Interdits

Sont bannis de `primitives/` et de `strategies/` :

- toute statistique sur l'échantillon complet — moyenne, écart-type, min, max,
  quantile, rang — utilisée pour normaliser ;
- toute lecture directe d'un fichier de données ;
- tout import de `rsl.data.loader` (les stratégies ne chargent pas de données).

Les deux derniers sont vérifiés par un test statique qui inspecte les imports
des modules de `primitives/` et `strategies/`. Le premier ne se vérifie pas
statiquement : il est fermé par le fait qu'une primitive n'a aucun moyen
d'obtenir l'échantillon complet (§2.2, règles 1, 4 et 5).

### 5.3 Fenêtres

`zscore`, `sma`, `ema`, `atr`, `rolling_high`, `rolling_low`, `returns` prennent
toutes une fenêtre `n` explicite et l'appliquent aux `n` dernières barres
closes. Aucune n'a de mode « échantillon complet ». `n` est en **nombre de
barres**, jamais en durée (cf. `execution-model.md` §5.1).

---

## 6. Le test de corruption du futur

C'est le test qui donne sa valeur au reste. Le contrat ci-dessus est une
intention ; ce test est sa vérification.

**Protocole.** Pour un jeu de données de `N` barres, une stratégie `S` et un
index `k < N` :

1. Exécuter `S` sur les données intactes, en arrêtant le run à la barre `k`.
   Résultat `R_ref`.
2. Remplacer toutes les barres d'index `> k` par du bruit aléatoire seedé
   (prix, volumes, tout — en conservant seulement la validité OHLC, pour que le
   loader ne rejette pas).
3. Réexécuter `S` sur les données corrompues, en arrêtant le run à `k`.
   Résultat `R_corrompu`.
4. **Exiger `R_ref == R_corrompu`, à l'identique.** Pas « à l'epsilon près » :
   à l'identique, sur la courbe d'equity complète, la liste des fills, les
   compteurs et le hash du rapport.

Appliqué aux trois stratégies de référence, à plusieurs valeurs de `k`
(début, milieu, fin) et sur plusieurs fixtures (série constante, rampe,
sinusoïde, marche aléatoire seedée).

Ce test attrape ce que la revue de code ne voit pas : un `shift(-1)` égaré, un
`rolling(center=True)`, un `mean()` calculé une fois sur tout le tableau au
chargement, un tri qui touche l'ordre du calendrier.

---

## 7. Ce que le socle ne garantit pas

L'honnêteté sur les limites fait partie du contrat. Le moteur ne protège pas
contre :

1. **Le look-ahead du chercheur.** Choisir une stratégie, une fenêtre, un
   univers ou une période après avoir regardé les données est invisible au
   moteur. Seule réponse : compter les essais et corriger le Sharpe
   (Deflated Sharpe Ratio, Bailey & López de Prado). Le compteur d'essais est
   un champ **obligatoire** du rapport, pas une option.

2. **La construction du contrat continu.** Les séries `.v.0` roulent au
   basculement de volume. Ce basculement est déterminé à partir du volume du
   jour, ce qui est causal en principe ; mais la désignation du contrat de
   référence par le fournisseur peut avoir été lissée a posteriori, et le
   projet n'a aucun moyen de le vérifier. **Risque résiduel assumé et
   documenté.** De plus, les séries ne sont pas ajustées au roulement :
   discontinuités de ~1,1-1,3 % groupées sur les dates de roulement
   trimestrielles (p95 des gaps quotidiens : 0,29 %). Elles ne sont donc pas
   des séries de prix détenables, ce qui affecte l'interprétation du buy & hold
   sur données réelles.

3. **Les révisions de données.** Le jeu est un instantané au 2026-08-31. Si le
   fournisseur a restaté des barres anciennes, le backtest utilise des données
   que personne n'avait à l'époque. Non détectable ici ; le hash du fichier
   dans le manifeste permet au moins de savoir *quel* instantané a été utilisé.

4. **L'impact de marché.** Aucun modèle d'impact. Le slippage est un coût fixe
   par ordre, indépendant de la taille. Une stratégie qui traite 500 contrats
   ES à la minute serait modélisée comme une qui en traite 1.

5. **L'ordre intra-barre.** Cf. `execution-model.md` §4.4. Le pessimisme par
   défaut est une hypothèse, pas une vérité ; le compteur d'ambiguïté indique à
   quel point le résultat en dépend.

---

## 8. Résumé opérationnel

Ce qu'une stratégie peut faire :

- lire la barre courante close et les `n` précédentes ;
- émettre des ordres qui seront exécutés au plus tôt à la barre suivante ;
- déclarer un `warmup_bars`.

Ce qu'elle ne peut pas faire, non par convention mais parce que l'expression
n'existe pas :

- lire une barre non close ;
- connaître la longueur ou la date de fin de l'échantillon ;
- être exécutée à la clôture qui a produit son signal ;
- normaliser sur l'échantillon complet ;
- voir un instrument absent comme s'il cotait.
