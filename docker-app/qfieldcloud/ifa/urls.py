from django.urls import path

from qfieldcloud.ifa import plugin
from qfieldcloud.ifa.plugin_views import archive_plugin, metadonnees_plugin
from qfieldcloud.ifa.views import (
    DeverrouillerUniteView,
    OuvrirUniteView,
    PreparerFormulaireView,
    RechercheUnitesView,
)

urlpatterns = [
    path(
        "unites/recherche/",
        RechercheUnitesView.as_view(),
        name="ifa_unites_recherche",
    ),
    # Le code d'unité contient des tirets mais jamais de barre oblique : il
    # tient dans un segment d'URL.
    path(
        "unites/<str:une_code_ident>/ouvrir/",
        OuvrirUniteView.as_view(),
        name="ifa_unite_ouvrir",
    ),
    path(
        "unites/<str:une_code_ident>/deverrouiller/",
        DeverrouillerUniteView.as_view(),
        name="ifa_unite_deverrouiller",
    ),
    # Création d'une unité : le projet de saisie n'est pas rattaché à une unité
    # existante, d'où un chemin qui ne passe pas par `unites/`.
    path(
        "formulaire/preparer/",
        PreparerFormulaireView.as_view(),
        name="ifa_formulaire_preparer",
    ),
    # Distribution du plugin QField — publique, voir `plugin.py`. Le nom de
    # l'archive dans l'adresse est celui que QField donnera au dossier du
    # plugin installé.
    path(
        f"plugin/{plugin.NOM_METADONNEES}",
        metadonnees_plugin,
        name="ifa_plugin_metadonnees",
    ),
    path(
        f"plugin/{plugin.NOM_ARCHIVE}",
        archive_plugin,
        name="ifa_plugin_archive",
    ),
]
