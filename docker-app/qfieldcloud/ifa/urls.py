from django.urls import path

from qfieldcloud.ifa import plugin
from qfieldcloud.ifa.plugin_views import archive_plugin, metadonnees_plugin
from qfieldcloud.ifa.views import (
    DeverrouillerUniteView,
    ModifierProjetView,
    OuvrirUniteView,
    PreparerFormulaireView,
    ProjetSondageView,
    ProjetsSondageView,
    RechercheUnitesView,
    SupprimerProjetView,
    SupprimerUniteView,
    TypesDuProjetView,
    TypesUeView,
    UniteView,
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
    # Une unité : ce que sa suppression emporterait, et les droits ; puis la
    # suppression elle-même — « Consulter une UE ».
    path(
        "unites/<str:une_code_ident>/",
        UniteView.as_view(),
        name="ifa_unite",
    ),
    path(
        "unites/<str:une_code_ident>/supprimer/",
        SupprimerUniteView.as_view(),
        name="ifa_unite_supprimer",
    ),
    # Création d'une unité : le projet de saisie n'est pas rattaché à une unité
    # existante, d'où un chemin qui ne passe pas par `unites/`.
    path(
        "formulaire/preparer/",
        PreparerFormulaireView.as_view(),
        name="ifa_formulaire_preparer",
    ),
    # Projets de sondage (`proje_sonda`) — à ne pas confondre avec les projets
    # QFieldCloud, que gère `projets.py`.
    path(
        "projets-sondage/",
        ProjetsSondageView.as_view(),
        name="ifa_projets_sondage",
    ),
    # Les types d'UE d'un projet — « Créer une UE » y restreint sa liste.
    # Avant `<pro_code_ident>/`, qui l'avalerait sinon.
    path(
        "projets-sondage/types-ue/",
        TypesDuProjetView.as_view(),
        name="ifa_projet_sondage_types",
    ),
    # Un projet, désigné par son identifiant (UUID) : consulter, modifier,
    # supprimer — « Modifier / Afficher / Supprimer un projet ».
    path(
        "projets-sondage/<str:pro_code_ident>/",
        ProjetSondageView.as_view(),
        name="ifa_projet_sondage",
    ),
    path(
        "projets-sondage/<str:pro_code_ident>/modifier/",
        ModifierProjetView.as_view(),
        name="ifa_projet_sondage_modifier",
    ),
    path(
        "projets-sondage/<str:pro_code_ident>/supprimer/",
        SupprimerProjetView.as_view(),
        name="ifa_projet_sondage_supprimer",
    ),
    # Les types d'UE qu'un projet peut prévoir — la liste à cocher de
    # « Créer un projet ».
    path(
        "types-ue/",
        TypesUeView.as_view(),
        name="ifa_types_ue",
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
