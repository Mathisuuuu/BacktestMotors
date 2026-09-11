"""Racine des donnees : resolution par l'environnement, et portabilite du hash.

Ces tests gardent la propriete qui justifie le mecanisme : deux machines dont
les cotations ne sont pas au meme endroit doivent produire le MEME
`config_hash` pour le meme run. Tant qu'un chemin absolu entrait dans la forme
canonique, cette egalite etait fausse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rsl.config import BacktestSpec
from rsl.env import DATA_ROOT_VAR, data_root, find_dotenv, parse_dotenv, resolve_data_path
from rsl.errors import ConfigurationError


def spec_avec(path: str) -> BacktestSpec:
    return BacktestSpec.model_validate(
        {
            "name": "portabilite",
            "initial_cash": 100_000.0,
            "seed": 0,
            "data": [{"root": "ES", "path": path, "granularity_minutes": 1}],
            "execution": {
                "fees": {"kind": "per_contract"},
                "slippage": {"kind": "tick", "ticks": 1.0},
                "lag_bars": 1,
            },
            "risk": {"sizing": {"kind": "fixed", "contracts": 1}},
            "strategy": {
                "ref": "sma_crossover@1",
                "params": {"symbol": "ES.v.0", "fast_window": 5, "slow_window": 20},
            },
        }
    )


class TestParseDotenv:
    def test_paires_simples(self):
        assert parse_dotenv("A=1\nB=deux\n") == {"A": "1", "B": "deux"}

    def test_commentaires_et_lignes_vides_ignores(self):
        assert parse_dotenv("# titre\n\nA=1\n   # autre\n") == {"A": "1"}

    def test_prefixe_export_tolere(self):
        assert parse_dotenv("export A=1\n") == {"A": "1"}

    def test_guillemets_retires(self):
        assert parse_dotenv('A="C:/avec espace"\nB=\'x\'\n') == {"A": "C:/avec espace", "B": "x"}

    def test_ligne_sans_egal_ignoree_plutot_que_fatale(self):
        """Un .env est un fichier de confort : il ne doit pas casser un run."""
        assert parse_dotenv("n'importe quoi\nA=1\n") == {"A": "1"}

    def test_valeur_contenant_un_egal_preservee(self):
        assert parse_dotenv("A=x=y\n") == {"A": "x=y"}


class TestDataRoot:
    def test_variable_d_environnement_prioritaire(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text(f"{DATA_ROOT_VAR}=depuis-le-fichier\n", encoding="utf-8")
        monkeypatch.setenv(DATA_ROOT_VAR, str(tmp_path / "depuis-l-environnement"))
        monkeypatch.chdir(tmp_path)
        assert data_root() == tmp_path / "depuis-l-environnement"

    def test_repli_sur_le_dotenv(self, tmp_path, monkeypatch):
        contenu = f"{DATA_ROOT_VAR}={tmp_path / 'cotations'}\n"
        (tmp_path / ".env").write_text(contenu, encoding="utf-8")
        monkeypatch.delenv(DATA_ROOT_VAR, raising=False)
        monkeypatch.chdir(tmp_path)
        assert data_root() == tmp_path / "cotations"

    def test_dotenv_cherche_dans_les_parents(self, tmp_path, monkeypatch):
        contenu = f"{DATA_ROOT_VAR}={tmp_path / 'cotations'}\n"
        (tmp_path / ".env").write_text(contenu, encoding="utf-8")
        profond = tmp_path / "a" / "b" / "c"
        profond.mkdir(parents=True)
        monkeypatch.delenv(DATA_ROOT_VAR, raising=False)
        monkeypatch.chdir(profond)
        assert find_dotenv() == tmp_path / ".env"
        assert data_root() == tmp_path / "cotations"

    def test_aucune_racine_declaree(self, tmp_path, monkeypatch):
        monkeypatch.delenv(DATA_ROOT_VAR, raising=False)
        monkeypatch.chdir(tmp_path)
        assert data_root() is None

    def test_valeur_vide_vaut_absence(self, tmp_path, monkeypatch):
        monkeypatch.setenv(DATA_ROOT_VAR, "   ")
        monkeypatch.chdir(tmp_path)
        assert data_root() is None


class TestResolveDataPath:
    def test_chemin_relatif_resolu_contre_la_racine(self, tmp_path, monkeypatch):
        monkeypatch.setenv(DATA_ROOT_VAR, str(tmp_path))
        assert resolve_data_path(Path("indices/ES.parquet")) == tmp_path / "indices/ES.parquet"

    def test_chemin_absolu_rendu_tel_quel(self, tmp_path, monkeypatch):
        monkeypatch.setenv(DATA_ROOT_VAR, str(tmp_path))
        absolu = tmp_path.resolve() / "ailleurs" / "ES.parquet"
        assert resolve_data_path(absolu) == absolu

    def test_relatif_sans_racine_leve_avec_le_remede(self, tmp_path, monkeypatch):
        """Pas de repli silencieux sur le repertoire courant : il dependrait
        de l'endroit d'ou la commande est lancee."""
        monkeypatch.delenv(DATA_ROOT_VAR, raising=False)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConfigurationError, match=DATA_ROOT_VAR):
            resolve_data_path(Path("indices/ES.parquet"))


class TestConfigHashPortable:
    def test_meme_hash_sous_deux_racines_differentes(self, tmp_path, monkeypatch):
        """La propriete centrale : la racine ne doit pas entrer dans le hash."""
        monkeypatch.setenv(DATA_ROOT_VAR, str(tmp_path / "chez-mathis"))
        chez_mathis = spec_avec("indices/ES_v0_1m.parquet").canonical()
        monkeypatch.setenv(DATA_ROOT_VAR, str(tmp_path / "tres" / "loin" / "chez-le-collab"))
        chez_le_collab = spec_avec("indices/ES_v0_1m.parquet").canonical()
        assert chez_mathis == chez_le_collab

    def test_forme_canonique_en_separateurs_posix(self, tmp_path, monkeypatch):
        r"""Sans cette normalisation, Windows hacherait `indices\ES` et Linux
        `indices/ES` : le hash cesserait d'etre portable entre systemes."""
        monkeypatch.setenv(DATA_ROOT_VAR, str(tmp_path))
        spec = spec_avec("indices/ES_v0_1m.parquet")
        assert spec.canonical()["data"][0]["path"] == "indices/ES_v0_1m.parquet"

    def test_chemin_absolu_reste_absolu_dans_le_hash(self, tmp_path):
        """Retrocompatibilite : les specifications anciennes ne changent pas de
        sens, elles restent seulement non portables."""
        absolu = (tmp_path / "ES_v0_1m.parquet").resolve()
        assert spec_avec(str(absolu)).canonical()["data"][0]["path"] == str(absolu)


class TestFrontiereDuDepot:
    """La recherche du `.env` ne doit jamais deborder hors du projet."""

    def test_arret_au_marqueur_de_racine(self, tmp_path, monkeypatch):
        """Un `.env` situe AU-DESSUS de la racine du depot est ignore : sinon
        un projet voisin, ou le repertoire personnel, imposerait sa racine."""
        (tmp_path / ".env").write_text(f"{DATA_ROOT_VAR}=intrus\n", encoding="utf-8")
        depot = tmp_path / "depot"
        (depot / ".git").mkdir(parents=True)
        monkeypatch.delenv(DATA_ROOT_VAR, raising=False)
        monkeypatch.chdir(depot)
        assert find_dotenv() is None
        assert data_root() is None

    def test_dotenv_du_depot_trouve_avant_le_marqueur(self, tmp_path, monkeypatch):
        depot = tmp_path / "depot"
        (depot / ".git").mkdir(parents=True)
        (depot / ".env").write_text(f"{DATA_ROOT_VAR}=bonne-racine\n", encoding="utf-8")
        monkeypatch.delenv(DATA_ROOT_VAR, raising=False)
        monkeypatch.chdir(depot)
        assert data_root() == Path("bonne-racine")


class TestEncodageDuDotenv:
    """PowerShell 5.1 ecrit ses redirections en UTF-16 : le cas est realiste."""

    @pytest.mark.parametrize("encodage", ["utf-8", "utf-8-sig", "utf-16", "cp1252"])
    def test_encodages_courants_lus(self, tmp_path, monkeypatch, encodage):
        depot = tmp_path / "depot"
        (depot / ".git").mkdir(parents=True)
        (depot / ".env").write_bytes(f"{DATA_ROOT_VAR}=C:/Cotations\n".encode(encodage))
        monkeypatch.delenv(DATA_ROOT_VAR, raising=False)
        monkeypatch.chdir(depot)
        assert data_root() == Path("C:/Cotations")
