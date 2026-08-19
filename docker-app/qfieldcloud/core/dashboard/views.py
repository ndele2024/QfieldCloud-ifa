"""Vues du tableau de bord.

Aucune ne dépend des permissions de l'admin Django : l'accès est déterminé par
`scope.py`, à partir de l'activité réelle de l'utilisateur.
"""

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView, UpdateView

from qfieldcloud.core.models import Job, Person
from qfieldcloud.filestorage.models import File

from . import scope
from .forms import ProfileForm

# Nombre de synchronisations affichées par page dans le détail d'un projet.
JOBS_PER_PAGE = 25


def index_redirect(request):
    """Aiguillage de la page d'accueil.

    Seul un superutilisateur garde l'admin comme point d'entrée ; tout autre
    compte connecté reçoit le tableau de bord.

    Envoyer un compte non superutilisateur vers l'admin provoquait une boucle
    de redirection : l'admin le renvoyait vers la page de connexion, laquelle,
    le voyant déjà authentifié, le renvoyait vers `LOGIN_REDIRECT_URL` — c'est
    à dire ici même. Le navigateur tournait jusqu'à abandonner.

    Un visiteur non identifié part directement vers la page de connexion ;
    `LOGIN_REDIRECT_URL` le ramènera ici, et il sera alors aiguillé.
    """
    user = request.user

    if not user.is_authenticated:
        return redirect(settings.LOGIN_URL)

    if user.is_superuser:
        return redirect("/" + settings.QFIELDCLOUD_ADMIN_URI)

    return redirect("dashboard:projects")


class DashboardContextMixin(LoginRequiredMixin):
    """Contexte commun à tout le tableau de bord.

    `menu` désigne l'entrée active ; `admin_uri` évite de figer « admin/ » dans
    le gabarit alors que le chemin est configurable.
    """

    menu = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["menu"] = self.menu
        context["admin_uri"] = settings.QFIELDCLOUD_ADMIN_URI
        return context


class DashboardView(DashboardContextMixin, TemplateView):
    pass


class ProjectsView(DashboardView):
    """Projets de l'utilisateur, séparés de ceux de ses équipes."""

    template_name = "dashboard/projects.html"
    menu = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        context["own_projects"] = scope.own_projects(user)
        context["team_projects"] = scope.team_projects(user)
        context["teams"] = scope.user_teams(user)

        return context


class ProjectDetailView(DashboardView):
    """Fichiers et synchronisations d'un projet.

    L'accès passe par `scope.visible_projects()` : un projet hors périmètre
    renvoie 404, sans divulguer qu'il existe.
    """

    template_name = "dashboard/project_detail.html"
    menu = "projects"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        project = get_object_or_404(
            scope.visible_projects(self.request.user).select_related("owner"),
            pk=kwargs["project_id"],
        )

        jobs = (
            Job.objects.filter(project=project)
            .select_related("created_by")
            .order_by("-created_at")
        )
        paginator = Paginator(jobs, JOBS_PER_PAGE)

        context["project"] = project
        context["files"] = (
            File.objects.filter(project=project)
            .select_related("latest_version")
            .order_by("name")
        )
        context["jobs_page"] = paginator.get_page(self.request.GET.get("page"))
        context["jobs_total"] = paginator.count

        return context


class ProfileView(DashboardContextMixin, UpdateView):
    """Informations personnelles du compte connecté."""

    template_name = "dashboard/profile.html"
    form_class = ProfileForm
    success_url = reverse_lazy("dashboard:profile")
    menu = "profile"

    def get_object(self, queryset=None):
        # `request.user` peut être une instance `User` : on recharge le
        # `Person` correspondant, seul type de compte qui se connecte et porte
        # les champs du formulaire. Un autre type donne 404 plutôt qu'une
        # erreur d'attribut.
        return get_object_or_404(Person, pk=self.request.user.pk)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Vos informations ont été enregistrées.")
        return response


class PasswordView(DashboardContextMixin, PasswordChangeView):
    """Changement de mot de passe.

    Écran maison plutôt que celui d'allauth : `accounts/password/change/` est
    volontairement neutralisé dans les URL racine (page non stylée).
    """

    template_name = "dashboard/password.html"
    success_url = reverse_lazy("dashboard:password")
    menu = "password"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        for field in form.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

        return form

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Votre mot de passe a été modifié.")
        return response
