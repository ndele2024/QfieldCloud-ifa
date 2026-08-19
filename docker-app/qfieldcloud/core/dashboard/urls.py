"""Routes du tableau de bord, montées sur /dashboard/ (voir qfieldcloud/urls.py).

Elles ne peuvent pas rejoindre `core/urls.py`, qui est inclus sous /api/v1/.
"""

from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.ProjectsView.as_view(), name="projects"),
    path(
        "projets/<uuid:project_id>/",
        views.ProjectDetailView.as_view(),
        name="project_detail",
    ),
    path("profil/", views.ProfileView.as_view(), name="profile"),
    path("mot-de-passe/", views.PasswordView.as_view(), name="password"),
]
