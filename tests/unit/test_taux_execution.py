"""Le taux d'execution s'affiche a cote du rendement.

Ce qui est en jeu
------------------
Le 2026-09-13, un run rendait **-25,62 % avec 2 trades** sur 10,6 ans. Lu comme
un resultat, c'etait une strategie qui perd. Ce n'en etait pas un : **5 080
ordres sur 5 084 avaient ete refuses pour marge**, la strategie demandant
4 contrats NQ - 108 000 de marge - sur un compte de 100 000.

Le chiffre etait dans le JSON (`risk_stats.n_rejected_margin`) et nulle part
dans le resume imprime. Troisieme occurrence de la meme famille apres
[[lessons]] L18 et L25 : **un backtest empeche produit un nombre lisible**, et
rien ne distingue « la strategie n'a pas gagne » de « elle n'a jamais joue ».

Ce que ces tests fixent
------------------------
Que la ligne existe TOUJOURS des qu'un ordre a ete emis - une ligne absente ne
se distingue pas d'une fonctionnalite oubliee - et qu'elle AVERTIT quand le
taux s'effondre. Le motif dominant doit etre nomme : `margin` ne releve d'aucun
plafond de portefeuille declare, et c'est pourtant lui qui avait mordu.
"""

from __future__ import annotations

import pytest

from rsl.report import BacktestReport


class Porteur:
    """Un porteur minimal : ces deux methodes ne lisent que `self.run`.

    Construire un `BacktestReport` complet exigerait une specification, un
    manifeste et des metriques - rien de tout cela n'intervient ici, et les
    fabriquer rendrait le test sensible a des changements sans rapport.
    """

    def __init__(self, run: dict[str, object]) -> None:
        self.run = run

    _lignes_d_execution = BacktestReport._lignes_d_execution
    _detail_des_refus = BacktestReport._detail_des_refus
    # Appelee par `_lignes_d_execution` depuis le 2026-09-15 : la perte
    # par troncature se lit A COTE du taux d'execution, les deux disant
    # ensemble ce que le rendement affiche ne mesure pas.
    _ligne_de_troncature = BacktestReport._ligne_de_troncature


def run(
    *, emis: int, fills: int, **refus: int
) -> dict[str, object]:
    return {
        "counters": {"n_orders_submitted": emis},
        "n_fills": fills,
        "risk_stats": dict(refus),
    }


def rendu(charge: dict[str, object]) -> str:
    return "\n".join(Porteur(charge)._lignes_d_execution())


class TestLeCasQuiAMotiveLaLigne:
    """Les chiffres exacts du run Zarattini du 2026-09-13."""

    ZARATTINI = run(emis=5084, fills=4, n_rejected_margin=5080)

    def test_le_taux_effondre_est_affiche(self):
        texte = rendu(self.ZARATTINI)
        assert "4 fill(s) sur 5084 ordre(s) emis" in texte
        assert "taux 0.1 %" in texte

    def test_le_motif_dominant_est_nomme(self):
        """`margin` ne releve d'aucun plafond declare. L'ancienne ligne `Refus`
        ne couvrait que les quatre motifs de `risk.limits`, donc elle serait
        restee muette sur exactement le cas qui comptait."""
        assert "margin 5080" in rendu(self.ZARATTINI)

    def test_un_avertissement_dit_que_le_rendement_ne_mesure_pas_la_strategie(self):
        texte = rendu(self.ZARATTINI)
        assert "AVERTISSEMENT" in texte
        assert "ne mesure PAS la strategie declaree" in texte


class TestLaLigneEstToujoursLa:
    def test_un_run_sain_affiche_quand_meme_son_taux(self):
        """Cent pour cent est une information. Une ligne absente ne se
        distingue pas d'une fonctionnalite oubliee - l'erreur meme que cette
        ligne repare."""
        texte = rendu(run(emis=2482, fills=2482))
        assert "2482 fill(s) sur 2482 ordre(s) emis" in texte
        assert "taux 100.0 %" in texte

    def test_un_run_sain_n_avertit_pas(self):
        assert "AVERTISSEMENT" not in rendu(run(emis=2482, fills=2482))

    def test_aucun_ordre_emis_n_affiche_rien(self):
        """Rien a dire : il n'y a pas de taux d'execution sans ordre."""
        assert rendu(run(emis=0, fills=0)) == ""

    def test_un_rapport_sans_compteurs_ne_leve_pas(self):
        """Les rapports archives avant cette ligne n'ont pas a la porter."""
        assert rendu({}) == ""
        assert rendu({"counters": {}}) == ""


class TestLeSeuilDAvertissement:
    @pytest.mark.parametrize(
        ("emis", "fills", "attendu"),
        [
            (100, 100, False),
            (100, 95, False),
            (100, 90, False),   # exactement au seuil : pas d'avertissement
            (100, 89, True),    # un ordre de plus perdu, et il apparait
            (100, 50, True),
            (100, 1, True),
        ],
    )
    def test_le_seuil_est_a_90_pour_cent(self, emis, fills, attendu):
        """Deliberement HAUT : un run sain remplit la quasi-totalite de ce
        qu'il emet. Des qu'un ordre sur dix tombe, le rendement affiche ne
        mesure plus la strategie declaree."""
        assert ("AVERTISSEMENT" in rendu(run(emis=emis, fills=fills))) is attendu


class TestLeDetailDesRefus:
    def test_les_motifs_sont_tries_du_plus_frequent_au_moins(self):
        """Celui qui explique le run doit venir en tete, pas celui dont le nom
        ouvre l'alphabet."""
        texte = rendu(run(
            emis=1000, fills=100,
            n_rejected_margin=300,
            n_dropped_sizing=500,
            n_rejected_positions=100,
        ))
        ordre = [texte.index(m) for m in ("sizing 500", "margin 300", "positions 100")]
        assert ordre == sorted(ordre), texte

    def test_les_compteurs_nuls_ne_sont_pas_montres(self):
        texte = rendu(run(emis=10, fills=1, n_rejected_margin=9, n_dropped_sizing=0))
        assert "margin 9" in texte
        assert "sizing" not in texte

    def test_un_avertissement_de_marge_n_est_pas_un_refus(self):
        """`n_warned_margin` compte des ordres PASSES. Le ranger parmi les
        refus ferait surcompter ce qui a ete bloque."""
        texte = rendu(run(emis=10, fills=10, n_warned_margin=7))
        assert "warned" not in texte
        assert "Refus" not in texte

    def test_sans_aucun_refus_aucune_ligne_de_detail(self):
        assert "Refus" not in rendu(run(emis=10, fills=10))
