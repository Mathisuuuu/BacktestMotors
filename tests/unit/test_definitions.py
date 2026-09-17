"""`definitions` et `$ref` : ecrire une grandeur une fois, sans rien changer.

Ce que ce fichier garde
-----------------------
La factorisation n'a de valeur que si elle est **gratuite**. Trois proprietes
la rendent telle, et ce sont les trois que ce fichier verifie :

1. **Le `config_hash` ne bouge pas.** Une specification factorisee et son
   equivalent recopie a la main sont le MEME run. Sans cette propriete,
   factoriser une specification archivee l'aurait rendue incomparable a
   elle-meme - exactement le defaut que `_sans_plafonds_muets` evite pour un
   bloc `risk.limits` muet.
2. **Le moteur ne voit jamais un `$ref`.** La substitution est textuelle et
   precede toute validation : aucun type de noeud nouveau, aucun changement a
   `warmup_bars`, a la memoisation ni a `describe()`.
3. **Tout ce qui pourrait produire un resultat lisible mais faux est refuse.**
   Cinq ecritures, chacune pour une raison nommee. C'est la famille
   [[lessons]] L30 : une specification qui tourne et rend un chiffre, alors
   qu'elle ne dit pas ce qu'on croyait.

Le motif chiffre
----------------
Mesure le 2026-09-16 sur les formes distinctes de sous-arbre :
`intraday_vwap_reversion` porte 150 noeuds pour **41** formes distinctes,
`nq_zarattini_60_30_15` 164 pour **51**. Sur Zarattini, `sigma` est recopie
quatre fois. Rien ne verifiait que les quatre copies disaient la meme chose -
et quatre sigmas legerement differents forment une specification parfaitement
valide.
"""

from __future__ import annotations

import json

import pytest

from fixtures.exemples import STRATEGIES, attendues, montage, specification
from rsl.composition import StrategyFile, compose
from rsl.config import BacktestSpec
from rsl.definitions import BLOC, MARQUEUR, PLAFOND, expanser
from rsl.errors import ConfigurationError
from rsl.manifest import canonical_hash
from rsl.skeleton import build_skeleton

BASE = specification("sma_es_daily.json").model_dump(mode="json")

SIGMA = {
    "type": "rolling",
    "stat": "stdev",
    "window": 60,
    "inner": {"type": "price", "field": "close"},
}


def spec(**ajouts: object) -> BacktestSpec:
    return BacktestSpec.model_validate({**BASE, **ajouts})


class TestLaSubstitution:
    def test_un_nom_est_remplace_par_sa_valeur(self):
        rendu = expanser({BLOC: {"x": SIGMA}, "a": {MARQUEUR: "x"}})
        assert rendu["a"] == SIGMA

    def test_une_definition_peut_etre_un_scalaire(self):
        """Le cas le plus utile en pratique : un SEUIL ecrit quatre fois."""
        rendu = expanser({BLOC: {"k": 1.5}, "a": {MARQUEUR: "k"}, "b": {MARQUEUR: "k"}})
        assert rendu["a"] == 1.5 and rendu["b"] == 1.5

    def test_elle_agit_a_toute_profondeur_et_dans_les_listes(self):
        rendu = expanser(
            {BLOC: {"x": 7}, "a": {"b": [{"c": {MARQUEUR: "x"}}, {MARQUEUR: "x"}]}}
        )
        assert rendu["a"]["b"] == [{"c": 7}, 7]

    def test_une_definition_peut_en_referencer_une_autre(self):
        """Sans cela, la factorisation s'arreterait au premier niveau - or
        c'est justement la bande de Bollinger, qui contient sigma."""
        rendu = expanser(
            {
                BLOC: {
                    "sigma": SIGMA,
                    "bande": {
                        "type": "arith",
                        "op": "*",
                        "left": {MARQUEUR: "sigma"},
                        "right": {"type": "constant", "value": 2.0},
                    },
                },
                "a": {MARQUEUR: "bande"},
            }
        )
        assert rendu["a"]["left"] == SIGMA

    def test_l_ordre_de_declaration_est_indifferent(self):
        avant = expanser({BLOC: {"a": {MARQUEUR: "b"}, "b": 3}, "x": {MARQUEUR: "a"}})
        apres = expanser({BLOC: {"b": 3, "a": {MARQUEUR: "b"}}, "x": {MARQUEUR: "a"}})
        assert avant["x"] == apres["x"] == 3

    def test_un_document_sans_definitions_traverse_inchange(self):
        document = {"strategy": {"ref": "rules@1", "params": {"quantity": 1}}}
        assert expanser(document) == document

    def test_un_bloc_vide_est_inerte_et_non_refuse(self):
        """Meme traitement qu'un `risk.limits` entierement nul : l'absence et
        le bloc muet disent la meme chose, aucun des deux n'est une erreur."""
        assert expanser({BLOC: {}, "a": 1}) == {"a": 1}

    def test_deux_sites_recoivent_des_arbres_independants(self):
        """Un objet partage entre deux emplacements ferait qu'une mutation de
        l'un modifierait l'autre, a distance et sans trace."""
        rendu = expanser({BLOC: {"x": SIGMA}, "a": {MARQUEUR: "x"}, "b": {MARQUEUR: "x"}})
        assert rendu["a"] == rendu["b"]
        assert rendu["a"] is not rendu["b"]
        rendu["a"]["window"] = 999
        assert rendu["b"]["window"] == 60

    def test_le_bloc_survit_a_l_expansion(self):
        """Il reste lisible dans le document : on doit pouvoir relire ce qu'on
        a ecrit, meme si c'est la forme developpee qui tourne."""
        rendu = expanser({BLOC: {"x": 1}, "a": {MARQUEUR: "x"}})
        assert rendu[BLOC] == {"x": 1}


class TestLesCinqRefus:
    """Chacun evite une specification qui tournerait en disant autre chose."""

    def test_un_nom_inconnu(self):
        with pytest.raises(ConfigurationError, match="ne designe aucune definition"):
            expanser({BLOC: {"x": 1}, "a": {MARQUEUR: "absent"}})

    def test_l_erreur_nomme_les_definitions_declarees(self):
        """Sans la liste, l'auteur ne sait pas s'il s'est trompe de nom ou de
        fichier."""
        with pytest.raises(ConfigurationError, match=r"\['sigma', 'vwap'\]"):
            expanser(
                {
                    BLOC: {"sigma": 1, "vwap": 2},
                    "a": {MARQUEUR: "sigmaa"},
                    "b": {MARQUEUR: "vwap"},
                }
            )

    def test_un_cycle_direct(self):
        with pytest.raises(ConfigurationError, match="cycle a -> a"):
            expanser({BLOC: {"a": {MARQUEUR: "a"}}, "x": {MARQUEUR: "a"}})

    def test_un_cycle_indirect(self):
        with pytest.raises(ConfigurationError, match="cycle"):
            expanser(
                {BLOC: {"a": {MARQUEUR: "b"}, "b": {MARQUEUR: "a"}}, "x": {MARQUEUR: "a"}}
            )

    def test_un_marqueur_accompagne_d_autres_cles(self):
        """Le piege le plus probable : croire qu'on parametre une definition.
        Les cles seraient perdues en silence, la valeur remplacant l'objet."""
        with pytest.raises(ConfigurationError, match="doit etre SEUL"):
            expanser({BLOC: {"x": SIGMA}, "a": {MARQUEUR: "x", "window": 20}})

    def test_un_pointeur_json_schema(self):
        """Une IA entrainee sur JSON Schema ecrira spontanement cette forme.
        Le refus nomme la bonne."""
        with pytest.raises(ConfigurationError, match=r'\{"\$ref": "x"\}'):
            expanser({BLOC: {"x": 1}, "a": {MARQUEUR: "#/definitions/x"}})

    def test_une_definition_jamais_referencee(self):
        with pytest.raises(ConfigurationError, match=r"\['mort'\] n'est jamais reference"):
            expanser({BLOC: {"x": 1, "mort": 2}, "a": {MARQUEUR: "x"}})

    def test_une_definition_citee_par_une_morte_reste_morte(self):
        """L'usage se compte depuis le CORPS, pas depuis le bloc. Deux
        definitions qui se citent l'une l'autre sans etre appelees seraient
        sinon declarees vivantes."""
        with pytest.raises(ConfigurationError, match="jamais reference"):
            expanser(
                {
                    BLOC: {"a": 1, "b": {MARQUEUR: "a"}, "vive": 2},
                    "x": {MARQUEUR: "vive"},
                }
            )

    def test_une_cascade_qui_explose(self):
        """Dix definitions citant chacune deux fois la precedente font 1024
        copies de la premiere. Le plafond borne, au lieu de laisser ramer."""
        definitions: dict[str, object] = {"d0": SIGMA}
        for i in range(1, 16):
            definitions[f"d{i}"] = [{MARQUEUR: f"d{i - 1}"}, {MARQUEUR: f"d{i - 1}"}]
        with pytest.raises(ConfigurationError, match=f"depasse {PLAFOND}"):
            expanser({BLOC: definitions, "x": {MARQUEUR: "d15"}})

    def test_un_bloc_qui_n_est_pas_un_objet(self):
        with pytest.raises(ConfigurationError, match="doit etre un objet"):
            expanser({BLOC: ["x"], "a": 1})

    def test_un_nom_vide(self):
        with pytest.raises(ConfigurationError, match="nom de definition"):
            expanser({BLOC: {"  ": 1}, "a": {MARQUEUR: "  "}})


class TestCeQueLeConfigHashNeVoitPas:
    """La propriete sans laquelle la factorisation serait un piege."""

    def test_factoriser_ne_change_pas_le_config_hash(self):
        temoin = spec()
        factorise = spec(
            **{BLOC: {"capital": BASE["initial_cash"]}},
            initial_cash={MARQUEUR: "capital"},
        )
        assert canonical_hash(factorise.canonical()) == canonical_hash(temoin.canonical())

    def test_le_bloc_est_absent_de_la_forme_canonique(self):
        factorise = spec(
            **{BLOC: {"capital": BASE["initial_cash"]}},
            initial_cash={MARQUEUR: "capital"},
        )
        assert BLOC not in factorise.canonical()

    def test_il_est_absent_de_model_dump(self):
        """Meme dispositif que `note`, et c'est ce qui le retire du hachage."""
        factorise = spec(
            **{BLOC: {"capital": BASE["initial_cash"]}},
            initial_cash={MARQUEUR: "capital"},
        )
        assert BLOC not in factorise.model_dump(mode="json")

    def test_la_forme_developpee_se_revalide(self):
        """Aller-retour : ce qui sort d'une specification factorisee est une
        specification ordinaire, sans `$ref` restant."""
        factorise = spec(
            **{BLOC: {"capital": BASE["initial_cash"]}},
            initial_cash={MARQUEUR: "capital"},
        )
        charge = factorise.model_dump(mode="json")
        assert MARQUEUR not in json.dumps(charge)
        assert BacktestSpec.model_validate(charge).initial_cash == factorise.initial_cash


class TestSurLesSPECIFICATIONSDuDepot:
    """Les exemples FACTORISES, tels qu'ils sont commites.

    Depuis le 2026-09-17, quatre specifications du depot portent un bloc
    `definitions`. Ce sont elles que teste cette classe - pas une factorisation
    simulee. La version precedente factorisait Zarattini a la volee ; elle est
    devenue fausse le jour ou le fichier a ete factorise pour de bon, et elle
    l'a dit en echouant, ce qui est exactement son role ([[lessons]] L36).

    Reduction mesuree a l'ecriture :

    | Specification | lignes | definitions |
    |---|---|---|
    | `nq_zarattini_60_30_15` | 984 -> 491 | sigma_minute, vwap_ancre, bande_haute,
      bande_basse, points_de_controle, cloture_forcee |
    | `intraday_vwap_reversion` | 731 -> 375 | dispersion, grille_horaire, vwap_ancre |
    | `intraday_momentum_filtre_quotidien` | 582 -> 340 | grille_horaire, filtre_multi, vwap_ancre |
    | `intraday_opening_range` | 343 -> 293 | vwap_ancre |
    """

    FACTORISEES = (
        "nq_zarattini_60_30_15.json",
        "intraday_vwap_reversion.json",
        "intraday_opening_range.json",
        "intraday_momentum_filtre_quotidien.json",
    )

    def charger(self, nom: str) -> dict:
        charge = json.loads((STRATEGIES / nom).read_text(encoding="utf-8"))
        assert isinstance(charge, dict)
        return charge

    @pytest.mark.parametrize("nom", FACTORISEES)
    def test_elle_porte_un_bloc_definitions(self, nom: str):
        assert self.charger(nom)[BLOC], f"{nom} devait etre factorisee"

    @pytest.mark.parametrize("nom", FACTORISEES)
    def test_son_config_hash_est_celui_qui_est_archive(self, nom: str):
        """La propriete sans laquelle la factorisation aurait ete interdite :
        les empreintes du 2026-09-12 valent encore pour des fichiers reecrits
        de moitie."""
        charge = self.charger(nom)
        assemble = compose(
            StrategyFile.model_validate(charge),
            montage(nom),
            symbol=attendues()[nom].get("symbol"),
        )
        assert canonical_hash(assemble.canonical()) == attendues()[nom]["config_hash"]

    @pytest.mark.parametrize("nom", FACTORISEES)
    def test_la_forme_developpee_ne_garde_aucun_marqueur(self, nom: str):
        params = StrategyFile.model_validate(self.charger(nom)).strategy.params
        assert MARQUEUR not in json.dumps(params)

    @pytest.mark.parametrize("nom", FACTORISEES)
    def test_chaque_definition_sert_au_moins_une_fois(self, nom: str):
        """Garanti par le socle, verifie ici sur les vrais fichiers : une
        definition morte aurait fait LEVER le chargement."""
        charge = self.charger(nom)
        corps = json.dumps({c: v for c, v in charge.items() if c != BLOC})
        atteints = {n for n in charge[BLOC] if f'"{n}"' in corps}
        assert atteints, f"{nom} : aucune definition referencee depuis le corps"

    @pytest.mark.parametrize("nom", FACTORISEES)
    def test_elle_est_reellement_plus_courte_que_sa_forme_developpee(self, nom: str):
        """Le gain, mesure sur le fichier lui-meme plutot qu'annonce."""
        charge = self.charger(nom)
        factorise = len(json.dumps(charge, indent=2).splitlines())
        developpe = len(
            json.dumps(expanser(charge), indent=2).splitlines()
        ) - len(json.dumps({BLOC: charge[BLOC]}, indent=2).splitlines())
        assert factorise < developpe, f"{nom} : {factorise} vs {developpe} lignes"

    def test_le_moule_universel_n_est_pas_factorise(self):
        """Choix delibere : il existe pour MONTRER chaque type de noeud.

        Factoriser un catalogue cacherait derriere des noms ce qu'il est cense
        exposer, pour 3 % de lignes en moins - mesure avant de renoncer.
        """
        assert not self.charger("_moule_universel.json").get(BLOC)

class TestDansUnBlocTYPE:
    """La raison d'etre du `mode=\"before\"`.

    `risk.sizing.signal` n'est pas une region libre : pydantic le type. Un
    validateur `mode=\"after\"` arriverait quand l'objet `{\"$ref\": ...}` a
    deja ete refuse.
    """

    def test_un_ref_sert_dans_risk_sizing(self):
        assemble = spec(
            **{BLOC: {"taille": {"type": "constant", "value": 3.0}}},
            risk={
                "sizing": {
                    "kind": "signal",
                    "signal": {MARQUEUR: "taille"},
                    "max_contracts": 5,
                }
            },
        )
        assert assemble.risk.sizing.signal == {"type": "constant", "value": 3.0}

    def test_un_ref_sert_dans_data(self):
        factorise = spec(
            **{BLOC: {"fichier": BASE["data"][0]["path"]}},
            data=[{**BASE["data"][0], "path": {MARQUEUR: "fichier"}}],
        )
        assert str(factorise.data[0].path) == str(BASE["data"][0]["path"])


class TestLesMotsReserves:
    def test_le_seul_dollar_du_depot_est_le_marqueur(self):
        """Le choix du marqueur repose la-dessus : `$` ne collisionne avec rien.

        Ecrit d'abord comme « aucun `$` nulle part », ce test est devenu faux le
        2026-09-17 quand quatre specifications ont ete factorisees - et il l'a
        dit en echouant. Reformule sur ce qu'il voulait vraiment dire : aucune
        AUTRE cle du vocabulaire ne commence par un dollar. Si un noeud futur en
        introduisait une, il faudrait changer de marqueur, et ce test le dira.
        """
        def cles(valeur: object) -> set[str]:
            if isinstance(valeur, dict):
                return set(valeur) | {c for v in valeur.values() for c in cles(v)}
            if isinstance(valeur, list):
                return {c for v in valeur for c in cles(v)}
            return set()

        for chemin in sorted(STRATEGIES.glob("*.json")):
            charge = json.loads(chemin.read_text(encoding="utf-8"))
            dollars = {c for c in cles(charge) if c.startswith("$")}
            assert dollars <= {MARQUEUR}, f"{chemin.name} : {dollars}"

    def test_le_squelette_annonce_le_bloc(self):
        squelette = build_skeleton()
        assert BLOC in squelette["specification"]

    def test_le_squelette_explique_comment_s_en_servir(self):
        squelette = build_skeleton()
        texte = "\n".join(squelette["mode_d_emploi"] + squelette["contraintes"])
        assert MARQUEUR in texte
        assert "NE PAS SE REPETER" in texte

    def test_le_squelette_enumere_les_refus(self):
        """Un auteur machine doit connaitre les cinq refus AVANT d'ecrire."""
        contraintes = "\n".join(build_skeleton()["contraintes"])
        for attendu in ("cycle", "JAMAIS referencee", "pointeur"):
            assert attendu in contraintes

class TestLExempleDuSquelette:
    """Une forme MONTREE a un auteur et devenue invalide est pire qu'absente.

    C'est [[lessons]] L36 : deux verdicts sur quatre du recensement de
    couverture etaient perimes sans que rien ne le signale. Le squelette publie
    un extrait JSON complet ; ce test le RECONSTRUIT.
    """

    def extraire(self) -> dict:
        from rsl.skeleton import MODE_D_EMPLOI

        bloc = chr(10).join(ligne for ligne in MODE_D_EMPLOI if ligne.startswith("    "))
        charge = json.loads(bloc)
        assert isinstance(charge, dict)
        return charge

    def test_il_se_developpe_et_se_construit(self):
        from rsl.strategies.signals import build_signal

        document = self.extraire()
        document.update({"format": "rsl-strategy@1", "name": "demonstration"})
        document["strategy"]["params"].update({"symbol": None, "quantity": 1})
        fichier = StrategyFile.model_validate(document)
        droite = fichier.strategy.params["rules"]["entry_long"]["right"]
        assert MARQUEUR not in json.dumps(droite)
        assert build_signal(droite).warmup_bars == 60

    def test_il_montre_une_definition_qui_en_reference_une_autre(self):
        """Le point qu'un auteur ne devinerait pas depuis une prose."""
        definitions = self.extraire()[BLOC]
        assert MARQUEUR in json.dumps(definitions["bande_haute"])
