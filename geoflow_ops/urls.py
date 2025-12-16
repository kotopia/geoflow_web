from django.urls import path
from . import views
from . import views_contracts, views_projects, views_employees, views_catalog, views_myinfo

app_name = "tenant"

urlpatterns = [
    path('', views.home, name='home'),

    path('contracts/', views_contracts.contract_list, name='contract_list'),
    # path("contracts/new/", views_contracts.contract_new, name="contract_new"),
    path("contracts/new/", views_contracts.contract_create, name="contract_create"),
    path("contracts/<uuid:pk>/", views_contracts.contract_detail_page, name="contract_detail"),
    path("contracts/<uuid:pk>/json/", views_contracts.contract_json, name="contract_json"),

    path('partners/', views_contracts.partner_list, name='partner_list'),
    path("partners/new/", views_contracts.partner_create, name="partner_create"),
    path('partners/<uuid:pk>/', views_contracts.partner_detail_page, name='partner_detail'),
    path('partners/<uuid:pk>/json/', views_contracts.partner_detail_json, name='partner_detail_json'),
    path('partners/options/', views_contracts.partners_options, name='partner_options'),

    path("catalog/board/", views_catalog.catalog_board, name="catalog_board"),

    path("projects/", views_projects.ProjectListView.as_view(), name="project_list"),
    path("projects/<uuid:pk>/", views_projects.project_detail_page, name="project_detail"),
    path("projects/<uuid:pk>/json/", views_projects.project_json, name="project_detail_json"),

    # 프로젝트 요약/편집 단일 페이지 & 저장
    path("projects/<uuid:pk>/summary/", views_projects.project_summary, name="project_summary"),
    path("projects/<uuid:pk>/summary-save/", views_projects.project_summary_save, name="project_summary_save"),

    # 프로젝트별 업무범위(스코프) 편집 모달/저장**
    path("projects/<uuid:pk>/scope-modal/",   views_catalog.project_scope_modal,   name="project_scope_modal"),
    path("projects/<uuid:pk>/scope-save/",    views_catalog.project_scope_save,    name="project_scope_save"),
    path("projects/<uuid:pk>/scope-summary/", views_catalog.project_scope_summary, name="project_scope_summary"),
    path("projects/<uuid:pk>/scope-data/",    views_catalog.project_scope_data,    name="project_scope_data"),

    path("employees/", views_employees.employees_list, name="employees_list"),
    path("employees/new/", views_employees.employees_create, name="employees_create"),
    path("employees/<uuid:emp_id>/", views_employees.employees_detail, name="employees_detail"),
    path("employees/<uuid:emp_id>/request-role/", views_employees.employees_request_role, name="employees_request_role"),

    # ▼ HR 참조 옵션 (로컬 → 이후 중앙으로 대체)
    path("api/hr/options/<str:category>/", views_employees.hr_options, name="hr_options"),

    path("myinfo/org-units/", views_myinfo.orgunit_list,  name="myinfo_orgunit_list"),
    path("myinfo/org-units/new/", views_myinfo.orgunit_create, name="myinfo_orgunit_create"),
    path("myinfo/org-units/<uuid:pk>/", views_myinfo.orgunit_detail, name="myinfo_orgunit_detail"),
    path("myinfo/org-units/<uuid:pk>/edit/", views_myinfo.orgunit_update, name="myinfo_orgunit_update"),
]
