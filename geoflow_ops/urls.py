from django.urls import path
from . import views
from . import views_contracts, views_projects, views_employees, views_catalog, views_myinfo, views_uploads, views_events
from . import views_employee_role_request, security_views, upload_guard_views

app_name = "tenant"

urlpatterns = [
    path('', views.home, name='home'),

    path('contracts/', views_contracts.contract_list, name='contract_list'),
    # path("contracts/new/", views_contracts.contract_new, name="contract_new"),
    path("contracts/new/", views_contracts.contract_create, name="contract_create"),
    path("contracts/<uuid:pk>/", views_contracts.contract_detail_page, name="contract_detail"),
    path("contracts/<uuid:pk>/json/", security_views.contract_json, name="contract_json"),

    path('partners/', views_contracts.partner_list, name='partner_list'),
    path("partners/new/", views_contracts.partner_create, name="partner_create"),
    path('partners/<uuid:pk>/', security_views.partner_detail, name='partner_detail'),
    path('partners/<uuid:pk>/json/', security_views.partner_json, name='partner_detail_json'),
    path('partners/options/', views_contracts.partners_options, name='partner_options'),

    path("catalog/board/", security_views.catalog_board, name="catalog_board"),

    path("projects/", security_views.project_list, name="project_list"),
    path("projects/<uuid:pk>/", security_views.project_detail, name="project_detail"),
    path("projects/<uuid:pk>/json/", views_projects.project_json, name="project_detail_json"),

    path("projects/<uuid:pk>/summary/", views_projects.project_summary, name="project_summary"),
    path("projects/<uuid:pk>/summary-save/", views_projects.project_summary_save, name="project_summary_save"),

    path("projects/<uuid:pk>/scope-modal/",   views_catalog.project_scope_modal,   name="project_scope_modal"),
    path("projects/<uuid:pk>/scope-save/",    views_catalog.project_scope_save,    name="project_scope_save"),
    path("projects/<uuid:pk>/scope-summary/", views_catalog.project_scope_summary, name="project_scope_summary"),
    path("projects/<uuid:pk>/scope-data/",    views_catalog.project_scope_data,    name="project_scope_data"),

    path("employees/", views_employees.employees_list, name="employees_list"),
    path("employees/new/", views_employees.employees_create, name="employees_create"),
    path("employees/<uuid:emp_id>/", views_employees.employees_detail, name="employees_detail"),
    path("employees/<uuid:emp_id>/request-role/", views_employee_role_request.employees_request_role_safe, name="employees_request_role"),

    path("api/hr/options/<str:category>/", views_employees.hr_options, name="hr_options"),

    path("myinfo/org-units/", security_views.orgunit_list,  name="myinfo_orgunit_list"),
    path("myinfo/org-units/new/", security_views.orgunit_create, name="myinfo_orgunit_create"),
    path("myinfo/org-units/<uuid:pk>/", security_views.orgunit_detail, name="myinfo_orgunit_detail"),
    path("myinfo/org-units/<uuid:pk>/edit/", security_views.orgunit_update, name="myinfo_orgunit_update"),

    path("api/uploads/presign-put/", upload_guard_views.presign_put, name="upload_presign_put"),
    path("api/uploads/commit/", upload_guard_views.commit, name="upload_commit"),
    path("api/uploads/presign-get/<uuid:attachment_id>/", upload_guard_views.presign_get, name="upload_presign_get"),
    path("api/uploads/delete/<uuid:attachment_id>/", views_uploads.delete_attachment, name="upload_delete"),

    path("api/events/create/", views_events.create_event, name="event_create"),
    path("api/events/list/", views_events.list_events, name="event_list"),
    path("api/events/update/<uuid:event_id>/", views_events.update_event, name="event_update"),
    path("api/events/delete/<uuid:event_id>/", views_events.delete_event, name="event_delete"),
    path("events/ui/modal/", security_views.event_modal_ui, name="event_modal_ui"),
]
