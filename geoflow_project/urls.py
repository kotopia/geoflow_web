"""
URL configuration for geoflow_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from control import views_auth
from control import views_signup

urlpatterns = [
    path('admin/', admin.site.urls),

    # 로그인
    path('login/', views_auth.login_view, name='login'),
    path('after-login/', views_auth.post_login_redirect, name='after_login'),

    # ✅ signup 라우트 (로그인 템플릿에서 {% url 'signup' %} 호출을 만족시키기 위한 최소 엔드포인트)
    path('signup/', views_signup.signup_view, name='signup'),

    # ✅ 중앙 전용 라우트
    path('control/', include(('control.urls', 'control'), namespace='control')),
    path('api/catalog/', include(('control.catalog.urls', 'catalog'), namespace='catalog')),

    # ✅ 테넌트 라우트(루트). 기존 'tenant' 모듈이 아니라 geoflow_ops가 테넌트입니다.
    path('', include(('geoflow_ops.urls', 'tenant'), namespace='tenant')),
]