from django.contrib.auth.decorators import login_required
from django.urls import path
from django.views.decorators.http import require_POST

from control.decorators import require_central_admin

from . import views

app_name = 'catalog'


def _admin(view):
    return require_central_admin(view)


def _admin_post(view):
    return require_central_admin(require_POST(view))


urlpatterns = [
    # 중앙 카탈로그 관리 화면/CRUD는 모두 중앙 관리자 전용.
    path('admin/board/', _admin(views.categories_board), name='categories_board'),
    path('admin/categories/', _admin(views.categories_board), name='categories_admin'),

    # L1
    path('admin/l1/create/', _admin(views.l1_admin_create), name='l1_admin_create'),
    path('admin/l1/<uuid:pk>/edit/', _admin(views.l1_admin_update), name='l1_admin_update'),
    path('admin/l1/<uuid:pk>/delete/', _admin_post(views.l1_admin_delete), name='l1_admin_delete'),

    # L2
    path('admin/l2/create/', _admin(views.l2_admin_create), name='l2_admin_create'),
    path('admin/l2/<uuid:pk>/edit/', _admin(views.l2_admin_update), name='l2_admin_update'),
    path('admin/l2/<uuid:pk>/delete/', _admin_post(views.l2_admin_delete), name='l2_admin_delete'),

    # L2 연결 관리 + 옵션팩 연결
    path('admin/nodes/<uuid:node_id>/links/', _admin(views.node_link_admin), name='node_link_admin'),
    path('admin/nodes/<uuid:node_id>/option-sets/create/', _admin(views.option_set_create), name='option_set_create'),
    path('admin/option-sets/<uuid:set_id>/delete/', _admin_post(views.option_set_delete), name='option_set_delete'),

    # 규칙
    path('admin/nodes/<uuid:node_id>/rules/', _admin(views.option_rule_list), name='option_rule_list'),
    path('admin/nodes/<uuid:node_id>/rules/create/', _admin(views.option_rule_create), name='option_rule_create'),
    path('admin/rules/<uuid:rule_id>/delete/', _admin_post(views.option_rule_delete), name='option_rule_delete'),

    # L2 리스트
    path('admin/nodes/', _admin(views.node_admin_list), name='node_admin_list'),

    # 옵션팩
    path('admin/facets/', _admin(views.facet_admin_list), name='facet_admin_list'),
    path('admin/facets/create/', _admin(views.facet_admin_create), name='facet_admin_create'),
    path('admin/facets/<uuid:pk>/edit/', _admin(views.facet_admin_update), name='facet_admin_update'),
    path('admin/facets/<uuid:pk>/delete/', _admin_post(views.facet_admin_delete), name='facet_admin_delete'),

    # 옵션팩 내부 옵션
    path('admin/facets/<uuid:facet_id>/options/', _admin(views.option_admin_list), name='option_admin_list'),
    path('admin/facets/<uuid:facet_id>/options/create/', _admin(views.option_admin_create), name='option_admin_create'),
    path('admin/options/<uuid:pk>/edit/', _admin(views.option_admin_update), name='option_admin_update'),
    path('admin/options/<uuid:pk>/delete/', _admin_post(views.option_admin_delete), name='option_admin_delete'),

    # 테넌트/관리 UI 내부 조회용. 공개 anonymous API로 노출하지 않는다.
    path('facet-options/', login_required(views.facet_options), name='facet_options'),
]
