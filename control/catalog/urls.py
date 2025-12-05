from django.urls import path
from . import views

app_name = 'catalog'

urlpatterns = [
    # NEW: 4-컬럼 SSR 보드
    path('admin/board/', views.categories_board, name='categories_board'),
    path('admin/categories/', views.categories_board, name='categories_admin'),

    # L1
    # path('admin/l1/', views.l1_admin_list, name='l1_admin_list'),
    path('admin/l1/create/', views.l1_admin_create, name='l1_admin_create'),
    path('admin/l1/<uuid:pk>/edit/', views.l1_admin_update, name='l1_admin_update'),
    path('admin/l1/<uuid:pk>/delete/', views.l1_admin_delete, name='l1_admin_delete'),

    # L2 (NEW)
    path('admin/l2/create/', views.l2_admin_create, name='l2_admin_create'),
    path('admin/l2/<uuid:pk>/edit/', views.l2_admin_update, name='l2_admin_update'),
    path('admin/l2/<uuid:pk>/delete/', views.l2_admin_delete, name='l2_admin_delete'),

    # L2 연결 관리 + 옵션팩 연결
    path('admin/nodes/<uuid:node_id>/links/', views.node_link_admin, name='node_link_admin'),
    path('admin/nodes/<uuid:node_id>/option-sets/create/', views.option_set_create, name='option_set_create'),
    path('admin/option-sets/<uuid:set_id>/delete/', views.option_set_delete, name='option_set_delete'),

    # 규칙
    path('admin/nodes/<uuid:node_id>/rules/', views.option_rule_list, name='option_rule_list'),
    path('admin/nodes/<uuid:node_id>/rules/create/', views.option_rule_create, name='option_rule_create'),
    path('admin/rules/<uuid:rule_id>/delete/', views.option_rule_delete, name='option_rule_delete'),

    # ── L2(중분류) 리스트 & L2에 붙은 옵션팩 관리(링크 화면)
    path('admin/nodes/', views.node_admin_list, name='node_admin_list'),

    # ── 옵션팩(팩 자체) 목록/추가/수정/삭제
    path('admin/facets/', views.facet_admin_list, name='facet_admin_list'),
    path('admin/facets/create/', views.facet_admin_create, name='facet_admin_create'),
    path('admin/facets/<uuid:pk>/edit/', views.facet_admin_update, name='facet_admin_update'),
    path('admin/facets/<uuid:pk>/delete/', views.facet_admin_delete, name='facet_admin_delete'),

    # ── 옵션팩 내부 옵션(항목) 목록/추가/수정/삭제
    path('admin/facets/<uuid:facet_id>/options/', views.option_admin_list, name='option_admin_list'),
    path('admin/facets/<uuid:facet_id>/options/create/', views.option_admin_create, name='option_admin_create'),
    path('admin/options/<uuid:pk>/edit/', views.option_admin_update, name='option_admin_update'),
    path('admin/options/<uuid:pk>/delete/', views.option_admin_delete, name='option_admin_delete'),

    # ── 특정 옵션팩의 활성 옵션 목록(JSON)
    path('facet-options/', views.facet_options, name='facet_options'),
]
