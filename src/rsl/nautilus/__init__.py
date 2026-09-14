"""Delegation de l'EXECUTION a `nautilus_trader`.

Decide le 2026-09-13. Ce paquet contient la frontiere entre ce que le depot
garde - vocabulaire declaratif, registre des essais, comptabilite du
surapprentissage - et ce qu'il delegue : le moteur event-driven, le
portefeuille, le modele d'execution.

Aucun module d'ici ne prend de decision de marche. Ils traduisent.
"""
