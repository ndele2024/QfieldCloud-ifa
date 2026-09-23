from django.urls import path

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
]
