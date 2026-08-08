"""URL configuration for geoflow_project project."""
from django.contrib import admin
from django.urls import path, include
from control import views_auth
from control import views_signup
from control import views_legal

urlpatterns = [
    path('admin/', admin.site.urls),

    path('login/', views_auth.login_view, name='login'),
    path('after-login/', views_auth.post_login_redirect, name='after_login'),

    path('terms/', views_legal.terms_view, name='terms'),
    path('privacy/', views_legal.privacy_view, name='privacy'),

    path('signup/', views_signup.signup_view, name='signup'),
    path(
        'signup/resend/',
        views_signup.signup_email_verification_resend_view,
        name='signup_resend',
    ),
    path(
        'signup/verify/',
        views_signup.signup_email_verification_view,
        name='signup_verify',
    ),

    path('control/', include(('control.urls', 'control'), namespace='control')),
    path('api/catalog/', include(('control.catalog.urls', 'catalog'), namespace='catalog')),
    path('', include(('geoflow_ops.urls', 'tenant'), namespace='tenant')),
]
