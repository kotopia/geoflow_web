# control/urls.py
from django.urls import path, include
from .views_auth import post_login_redirect, set_password_view, logout_view
from .views_signup import signup_view
from .views_groups import group_search_view, group_select_view
from .views_join import my_join_requests_view, join_requests_pending_view, join_request_decide_view
# from .views_people import people_list, people_detail, change_role, people_invite
from .views_groups_admin import group_list_admin, group_create_admin, group_edit_admin
from .views_onboarding import no_tenant_view
from .views_users_admin import users_list_admin, users_detail_admin, users_assign_group_admin, set_password_view, users_delete_admin, dashboard
from .views_categories import categories_page, category_options

app_name = "control"

urlpatterns = [
    path('', dashboard, name='dashboard'),  # /control/ 진입점
    # 로그인 후 최초 이동
    # path("after-login/", post_login_redirect, name="post_login_redirect"),
    path("no-tenant/", no_tenant_view, name="no_tenant"),
    path("logout/", logout_view, name="logout"),

    # 그룹 직접 선택(코드/UUID로)
    # path("select-group/<str:group_code_or_legacy_or_uuid>/", select_group, name="select_group"),

    # 회원가입
    path("signup/", signup_view, name="signup"),

    path("set-password/<uuid:token>/", set_password_view, name="set_password"),

    # 그룹 검색/선택
    path("groups/search/", group_search_view, name="group_search"),
    path("groups/select/<uuid:group_id>/", group_select_view, name="group_select"),

    # 합류요청
    # path("join-requests/create/<uuid:group_id>/", join_request_create_view, name="join_request_create"),
    path("join-requests/my/", my_join_requests_view, name="my_join_requests"),
    path("mgmt/join-requests/", join_requests_pending_view, name="join_requests_pending"),
    path("mgmt/join-requests/<uuid:req_id>/<str:action>/",   join_request_decide_view, name="join_request_decide"),

    # (그룹관리자) 대기중 요청 승인/거절
    path("mgmt/users/", users_list_admin, name="users_list_admin"),
    path("mgmt/users/<uuid:user_id>/", users_detail_admin, name="users_detail_admin"),
    path("mgmt/users/<uuid:user_id>/assign/", users_assign_group_admin, name="users_assign_group_admin"),
    path("mgmt/users/<uuid:user_id>/delete/", users_delete_admin, name="users_delete_admin"),

    # group
    path("central/groups/", group_list_admin, name="group_list_admin"),
    path("central/groups/new/", group_create_admin, name="group_create_admin"),
    path("central/groups/<uuid:group_id>/edit/", group_edit_admin, name="group_edit_admin"),

    # password
    path("account/set-password/<str:token>/", set_password_view, name="account_set_password"),

    path("categories/", categories_page, name="ctrl_categories_page"),
    path("categories/options/", category_options, name="ctrl_category_options"),
]
