"""Vues de distribution du plugin QField « IFA 2.0 — Menu ».

Deux vues publiques, que lisent les appareils (voir `plugin.py`) :

    GET /api/v1/ifa/plugin/metadata.txt
    GET /api/v1/ifa/plugin/ifa_menu.zip

et une page d'administration, réservée au personnel, pour déposer une nouvelle
version : `<admin>/ifa/plugin/`, accessible par le menu du haut de l'admin.

Vues Django simples et non DRF : les téléchargements ne doivent passer par
aucune authentification — `installFromUrl()` de QField n'envoie pas de jeton.
"""

from __future__ import annotations

import datetime
import logging

from django import forms
from django.contrib import messages
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from qfieldcloud.ifa import plugin

logger = logging.getLogger(__name__)


# ===========================================================================
#  Téléchargements publics
# ===========================================================================
def _servir(nom: str, type_contenu: str) -> FileResponse:
    depot = plugin.stockage()

    if not depot.exists(nom):
        raise Http404("Aucune version du plugin n'a encore été publiée.")

    reponse = FileResponse(
        depot.open(nom, "rb"),
        content_type=type_contenu,
        as_attachment=nom.endswith(".zip"),
        filename=nom,
    )
    # La version change sans que l'adresse change : aucun cache ne doit
    # resservir l'ancienne.
    reponse["Cache-Control"] = "no-store"
    return reponse


@require_GET
def metadonnees_plugin(request: HttpRequest) -> FileResponse:
    return _servir(plugin.NOM_METADONNEES, "text/plain; charset=utf-8")


@require_GET
def archive_plugin(request: HttpRequest) -> FileResponse:
    return _servir(plugin.NOM_ARCHIVE, "application/zip")


# ===========================================================================
#  Page d'administration
# ===========================================================================
class FormulairePlugin(forms.Form):
    archive = forms.FileField(
        label="Archive du plugin (.zip)",
        help_text="Produite par « python install.py --zip » dans formulaires/plugins/ifa_menu/.",
    )
    metadonnees = forms.FileField(
        label="metadata.txt",
        help_text="Le metadata.txt de la même construction : c'est sa ligne « version= » que comparent les appareils.",
    )


def page_plugin(request: HttpRequest, admin_site) -> HttpResponse:
    """Dépôt d'une nouvelle version. Appelée par `QfcAdminSite`, derrière
    `admin_view()` — donc réservée au personnel connecté."""
    actuel = plugin.publie()

    if request.method == "POST":
        formulaire = FormulairePlugin(request.POST, request.FILES)

        if formulaire.is_valid():
            archive = formulaire.cleaned_data["archive"].read()
            metadonnees = formulaire.cleaned_data["metadonnees"].read()

            try:
                version = plugin.verifier(archive, metadonnees)

                # Republier la même version, ou une plus ancienne, ne ferait
                # rien sur les appareils à jour : ils ne comparent que les
                # numéros. Le dire plutôt que laisser croire à un déploiement.
                if actuel and actuel.version != "?" and plugin.comparer_versions(version, actuel.version) <= 0 and not request.POST.get("forcer"):
                    formulaire.add_error(
                        None,
                        f"La version déposée ({version}) n'est pas plus récente que celle "
                        f"publiée ({actuel.version}) : les appareils ne la proposeront pas. "
                        "Augmentez « version= » dans metadata.txt, ou cochez « Publier quand même ».",
                    )
                else:
                    plugin.publier(archive, metadonnees)
                    logger.info("[IFA] plugin %s publie par %s", version, request.user)
                    messages.success(
                        request,
                        f"Version {version} publiée. Les appareils la proposeront au prochain démarrage de QField.",
                    )
                    return redirect("admin:ifa_plugin")
            except plugin.PluginInvalideError as erreur:
                formulaire.add_error(None, str(erreur))
    else:
        formulaire = FormulairePlugin()

    base = request.build_absolute_uri("/api/v1/ifa/plugin/")

    contexte = {
        **admin_site.each_context(request),
        "title": "Plugin QField IFA 2.0",
        "formulaire": formulaire,
        "actuel": actuel,
        "publie_le": (
            timezone.localtime(datetime.datetime.fromtimestamp(actuel.publie_le, tz=datetime.timezone.utc))
            if actuel
            else None
        ),
        "url_archive": base + plugin.NOM_ARCHIVE,
        "url_metadonnees": base + plugin.NOM_METADONNEES,
    }

    return render(request, "admin/ifa_plugin.html", contexte)
