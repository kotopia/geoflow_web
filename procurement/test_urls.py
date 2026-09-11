"""Isolated URL resolver, with placeholders only for unrelated navigation."""
from django.http import HttpResponse
from django.urls import include, path
from . import views_central


def unrelated(request):
    return HttpResponse()


control = [path("central/bids/", views_central.dashboard, name="central_bids"),
           path("central/bids/status/", views_central.status, name="central_bids_status")]
control += [path("unrelated/" + name, unrelated, name=name) for name in
            ("dashboard", "users_list_admin", "group_list_admin", "join_requests_pending",
             "signup_reviews_admin", "account_password_change", "logout")]
catalog = [path(name, unrelated, name=name) for name in ("categories_board", "facet_admin_list")]
urlpatterns = [path("control/", include((control, "control"))), path("catalog/", include((catalog, "catalog")))]
