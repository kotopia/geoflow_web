from django.urls import path
from . import views_contracts, views_projects, views_employees, views_catalog, views_myinfo, views_uploads, views_events, views_workboard, views_contract_access, views_calendar
from . import security_views, upload_guard_views, employee_security_views, event_security_views, settings_security_views, myinfo_security_views, finance_security_views, finance_import_views_v3, finance_attachment_views, finance_documents_views
from .views_home_security import tenant_home

app_name = "tenant"

urlpatterns = [
    path('', tenant_home, name='home'),
    path('calendar/', views_calendar.calendar_page, name='calendar'),
    path('api/calendar/events/', views_calendar.calendar_events, name='calendar_events'),

    path('contracts/', security_views.contract_list, name='contract_list'),
    path("contracts/new/", security_views.contract_create, name="contract_create"),
    path("contracts/<uuid:pk>/", security_views.contract_detail, name="contract_detail"),
    path("contracts/<uuid:pk>/json/", security_views.contract_json, name="contract_json"),
    path("contracts/<uuid:contract_id>/finance-summary/", finance_security_views.contract_finance_summary, name="contract_finance_summary"),
    path("contracts/<uuid:contract_id>/document-access/request/", views_contract_access.request_contract_document_access, name="contract_document_access_request"),
    path("contracts/document-access/<uuid:request_id>/decide/", views_contract_access.decide_contract_document_access, name="contract_document_access_decide"),

    path('partners/', security_views.partner_list, name='partner_list'),
    path("partners/new/", security_views.partner_create, name="partner_create"),
    path('partners/<uuid:pk>/', security_views.partner_detail, name='partner_detail'),
    path('partners/<uuid:pk>/json/', security_views.partner_json, name='partner_detail_json'),
    path('partners/options/', security_views.partner_options, name='partner_options'),

    path("finance/", finance_security_views.finance_page, name="finance_page"),
    path("finance/import/", finance_import_views_v3.finance_import, name="finance_import"),
    path("finance/documents/", finance_documents_views.finance_documents, name="finance_documents"),
    path("finance/attachments/presign/", finance_attachment_views.finance_attachment_presign, name="finance_attachment_presign"),
    path("finance/attachments/commit/", finance_attachment_views.finance_attachment_commit, name="finance_attachment_commit"),
    path("finance/attachments/<str:record_type>/<uuid:record_id>/download/", finance_attachment_views.finance_attachment_download, name="finance_attachment_download"),
    path("finance/claims/save/", finance_security_views.claim_save, name="finance_claim_save"),
    path("finance/invoices/save/", finance_security_views.invoice_save, name="finance_invoice_save"),
    path("finance/payment-requests/save/", finance_security_views.payment_request_save, name="finance_payment_request_save"),
    path("finance/transactions/save/", finance_security_views.transaction_save, name="finance_transaction_save"),
    path("finance/accounts/save/", finance_security_views.account_save, name="finance_account_save"),
    path("finance/<str:kind>/<uuid:record_id>/delete/", finance_security_views.record_soft_delete, name="finance_record_delete"),
    path("finance/<str:kind>/<uuid:record_id>/restore/", finance_security_views.record_restore, name="finance_record_restore"),
    path("finance/<str:kind>/<uuid:record_id>/purge/", finance_security_views.record_hard_delete, name="finance_record_purge"),

    path("catalog/board/", security_views.catalog_board, name="catalog_board"),

    path("projects/", security_views.project_list, name="project_list"),
    path("projects/<uuid:pk>/", security_views.project_detail, name="project_detail"),
    path("projects/<uuid:pk>/json/", security_views.project_json, name="project_detail_json"),
    path("projects/<uuid:pk>/members/", security_views.project_members_panel, name="project_members_panel"),
    path("projects/<uuid:pk>/members/save/", security_views.project_member_save, name="project_member_save"),
    path("projects/<uuid:pk>/members/<uuid:member_id>/revoke/", security_views.project_member_revoke, name="project_member_revoke"),
    path("projects/<uuid:pk>/summary/", security_views.project_summary, name="project_summary"),
    path("projects/<uuid:pk>/summary-save/", security_views.project_summary_save, name="project_summary_save"),
    path("projects/<uuid:pk>/scope-modal/", security_views.project_scope_modal, name="project_scope_modal"),
    path("projects/<uuid:pk>/scope-save/", security_views.project_scope_save, name="project_scope_save"),
    path("projects/<uuid:pk>/scope-summary/", security_views.project_scope_summary, name="project_scope_summary"),
    path("projects/<uuid:pk>/scope-data/", security_views.project_scope_data, name="project_scope_data"),

    path("api/projects/mine/", security_views.my_projects_api, name="my_projects_api"),
    path("api/projects/<uuid:pk>/access/", security_views.project_access_api, name="project_access_api"),

    path("employees/", employee_security_views.employee_list, name="employees_list"),
    path("employees/me/", employee_security_views.employee_me, name="employees_me"),
    path("employees/new/", employee_security_views.employee_create, name="employees_create"),
    path("employees/<uuid:emp_id>/", employee_security_views.employee_detail, name="employees_detail"),
    path("employees/<uuid:emp_id>/delete/", employee_security_views.employee_soft_delete, name="employees_soft_delete"),
    path("employees/<uuid:emp_id>/restore/", employee_security_views.employee_restore, name="employees_restore"),
    path("employees/<uuid:emp_id>/request-role/", employee_security_views.employee_role_request, name="employees_request_role"),
    path("employees/<uuid:emp_id>/history/save/", employee_security_views.employee_history_save, name="employee_history_save"),
    path("employees/<uuid:emp_id>/history/<str:section>/<uuid:record_id>/attachments/presign/", employee_security_views.employee_history_attachment_presign, name="employee_history_attachment_presign"),
    path("employees/<uuid:emp_id>/history/<str:section>/<uuid:record_id>/attachments/commit/", employee_security_views.employee_history_attachment_commit, name="employee_history_attachment_commit"),
    path("api/hr/options/<str:category>/", employee_security_views.hr_options, name="hr_options"),

    path("settings/", settings_security_views.settings_page, name="settings_page"),
    path("settings/node/save/", settings_security_views.settings_node_save, name="settings_node_save"),
    path("settings/department/save/", settings_security_views.department_save, name="settings_department_save"),

    path("myinfo/org-units/", security_views.orgunit_list, name="myinfo_orgunit_list"),
    path("myinfo/org-units/new/", security_views.orgunit_create, name="myinfo_orgunit_create"),
    path("myinfo/org-units/<uuid:pk>/", security_views.orgunit_detail, name="myinfo_orgunit_detail"),
    path("myinfo/org-units/<uuid:pk>/edit/", security_views.orgunit_update, name="myinfo_orgunit_update"),
    path("myinfo/org-units/<uuid:pk>/departments/save/", myinfo_security_views.orgunit_department_save, name="myinfo_department_save"),
    path("myinfo/org-units/<uuid:pk>/job-grades/save/", myinfo_security_views.job_grade_save, name="myinfo_job_grade_save"),
    path("myinfo/org-units/<uuid:pk>/job-positions/save/", myinfo_security_views.job_position_save, name="myinfo_job_position_save"),

    path("api/uploads/presign-put/", upload_guard_views.presign_put, name="upload_presign_put"),
    path("api/uploads/commit/", upload_guard_views.commit, name="upload_commit"),
    path("api/uploads/presign-get/<uuid:attachment_id>/", upload_guard_views.presign_get, name="upload_presign_get"),
    path("attachments/preview/<uuid:attachment_id>/", upload_guard_views.preview, name="upload_preview"),
    path("api/uploads/delete/<uuid:attachment_id>/", views_uploads.delete_attachment, name="upload_delete"),

    path("api/events/create/", event_security_views.event_create, name="event_create"),
    path("api/events/list/", event_security_views.event_list, name="event_list"),
    path("api/events/workflow-options/", event_security_views.workflow_options, name="event_workflow_options"),
    path("api/events/assignment-options/", views_workboard.assignment_options, name="event_assignment_options"),
    path("api/events/update/<uuid:event_id>/", event_security_views.event_update, name="event_update"),
    path("api/events/delete/<uuid:event_id>/", views_events.delete_event, name="event_delete"),
    path("events/ui/modal/", security_views.event_modal_ui, name="event_modal_ui"),
]
