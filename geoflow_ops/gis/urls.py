from django.urls import path

from . import views

app_name = "gis"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("projects/<uuid:project_id>/", views.project_dashboard, name="project_dashboard"),
    path("api/layers/", views.layer_registry_api, name="layer_registry_api"),
]
