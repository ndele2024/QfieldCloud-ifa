"""Ouverture d'une unité d'échantillonnage dans QField.

Le technicien choisit une unité dans la fenêtre « Consulter une UE » et demande
à l'ouvrir. Le serveur lui prépare alors, sous son propre compte, un projet
QFieldCloud qui ne contient que cette unité :

1. en mode modifiable, l'unité est verrouillée dans la base métier ;
2. `projets.preparer()` recopie le dernier paquet du projet modèle, remplit son
   GeoPackage des seuls inventaires de l'unité, fige les couches et demande le
   packaging ;
3. en consultation, toutes les couches du projet sont passées en lecture seule.

Ce module ne porte donc plus que ce qui distingue l'ouverture d'une unité des
autres préparations : le verrou, le choix du nom de projet, et le relâchement du
verrou si la préparation échoue. La mécanique commune vit dans `projets.py`, et
c'est là qu'est expliqué pourquoi les couches doivent être figées.

Un projet d'affichage par utilisateur et par mode, réutilisé d'une unité à la
suivante : l'appareil garde ses réglages et son cache de fonds de carte, et le
compte de l'utilisateur ne se remplit pas d'un projet par unité visitée.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from qfieldcloud.core.models import PackageJob, Person, Project
from qfieldcloud.ifa import inventaires, projets, verrou

logger = logging.getLogger(__name__)

# Définis dans `verrou.py` : c'est le verrou qui sépare les deux modes.
MODE_MODIFIABLE = verrou.MODE_MODIFIABLE
MODE_CONSULTATION = verrou.MODE_CONSULTATION
MODES = verrou.MODES


@dataclass
class Resultat:
    """Ce que le plugin a besoin de connaître pour enchaîner sur QField."""

    preparation: projets.Preparation
    mode: str

    @property
    def projet(self) -> Project:
        return self.preparation.projet

    @property
    def travail(self) -> PackageJob:
        return self.preparation.travail

    @property
    def lignes(self) -> int:
        return self.preparation.lignes

    def en_dictionnaire(self) -> dict[str, Any]:
        return {"mode": self.mode, **self.preparation.en_dictionnaire()}


def ouvrir(
    utilisateur: Person,
    une_code_ident: str,
    mode: str,
    raison: str = "",
) -> Resultat:
    """Prépare le projet d'affichage de l'unité et en constitue le paquet."""
    assert mode in MODES

    # Le modèle est retrouvé avant de poser le verrou : une installation sans
    # projet modèle ne doit pas laisser l'unité verrouillée derrière elle.
    paquet_modele = projets.dernier_paquet(projets.projet_modele())
    verrouille = False

    if mode == MODE_MODIFIABLE:
        verrou.poser(une_code_ident, utilisateur.username, raison)
        verrouille = True
    else:
        # Lecture seule : rien à écrire dans la base métier, mais l'unité doit
        # exister — `lire()` lève `UniteIntrouvableError` sinon.
        verrou.lire(une_code_ident)

    try:
        preparation = projets.preparer(
            utilisateur=utilisateur,
            nom=nom_projet_affichage(mode),
            description=description_projet(une_code_ident, mode),
            selection=inventaires.Selection.pour_unite(
                une_code_ident, settings.IFA_OUVERTURE_LIGNES_MAX
            ),
            lecture_seule=mode == MODE_CONSULTATION,
            # Le projet livré doit savoir quelle unité il porte : c'est ce que
            # le plugin lira pour proposer de la déverrouiller après une
            # synchronisation. Le nom du projet ne le dit pas — il est le même
            # d'une unité à la suivante.
            variables={"une_code_ident": une_code_ident},
            paquet_modele=paquet_modele,
        )
    except Exception:
        # Le verrou ne doit pas survivre à une ouverture qui n'a pas abouti :
        # l'unité resterait tenue par un projet que personne n'a jamais reçu.
        if verrouille:
            verrou.lever(une_code_ident, utilisateur.username)

        raise

    logger.info(
        "[IFA] unite %s ouverte en %s pour %s (projet %s, travail %s)",
        une_code_ident,
        mode,
        utilisateur.username,
        preparation.projet.id,
        preparation.travail.id,
    )

    return Resultat(preparation=preparation, mode=mode)


def nom_projet_affichage(mode: str) -> str:
    return (
        settings.IFA_PROJET_AFFICHAGE_MODIFIABLE
        if mode == MODE_MODIFIABLE
        else settings.IFA_PROJET_AFFICHAGE_CONSULTATION
    )


def description_projet(une_code_ident: str, mode: str) -> str:
    return (
        "Projet d'affichage IFA 2.0 — unité {code}, ouverte en {mode}. "
        "Son contenu est remplacé à chaque ouverture d'unité."
    ).format(
        code=une_code_ident,
        mode="modification" if mode == MODE_MODIFIABLE else "consultation",
    )
