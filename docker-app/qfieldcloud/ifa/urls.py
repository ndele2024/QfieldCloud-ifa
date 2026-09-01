from django.urls import path

from qfieldcloud.ifa.views import RechercheUnitesView

urlpatterns = [
    path(
        "unites/recherche/",
        RechercheUnitesView.as_view(),
        name="ifa_unites_recherche",
    ),
]
