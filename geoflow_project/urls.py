"""URL configuration for geoflow_project project."""
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path, include
from control import views_auth
from control import views_signup
from control import views_legal
from control import views_password_reset
from control.views_login_security import login_view

urlpatterns = [
    path('login/', login_view, name='login'),
    path('after-login/', login_required(views_auth.post_login_redirect), name='after_login'),

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

    path(
        'password/forgot/',
        views_password_reset.forgot_password_view,
        name='password_forgot',
    ),
    path(
        'password/reset/',
        views_password_reset.reset_password_view,
        name='password_reset',
    ),

    path('control/', include(('control.urls', 'control'), namespace='control')),
    path('api/catalog/', include(('control.catalog.urls', 'catalog'), namespace='catalog')),
    path('gis/', include(('geoflow_ops.gis.urls', 'gis'), namespace='gis')),
    path('', include(('geoflow_ops.urls', 'tenant'), namespace='tenant')),
]

# Django's stock admin uses the separate auth_user authorization model and can
# operate on tenant-routed models. Keep it available for local development only;
# GeoFlow's production administration goes through the guarded control views.
if settings.DEBUG:
    urlpatterns.insert(0, path('admin/', admin.site.urls))