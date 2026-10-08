from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.sitemaps.views import sitemap
from django.urls import path

from . import views
from .sitemaps import SITEMAPS
from .throttle import throttle

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    path("services/", views.service_list, name="services"),
    path("services/<slug:slug>/", views.service_detail, name="service-detail"),
    path("portfolio/", views.portfolio_list, name="portfolio"),
    path("portfolio/<slug:slug>/", views.portfolio_detail, name="portfolio-detail"),
    path("reviews/", views.reviews, name="reviews"),
    path("contacts/", views.contacts, name="contacts"),
    path("order/", views.order_create, name="order"),
    path("order/thanks/<uuid:public_id>/", views.order_thanks, name="order-thanks"),
    path(
        "accounts/login/",
        throttle("login", limit=10, window=900)(auth_views.LoginView.as_view()),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path(
        "accounts/password-reset/",
        throttle("password-reset", limit=5, window=3600)(
            auth_views.PasswordResetView.as_view(
                email_template_name="registration/password_reset_email.txt",
                subject_template_name="registration/password_reset_subject.txt",
                extra_email_context={"brand": settings.SITE_NAME},
            )
        ),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("cabinet/", views.cabinet, name="cabinet"),
    path("cabinet/orders/<int:pk>/", views.cabinet_order, name="cabinet-order"),
    path("cabinet/orders/<int:pk>/file/", views.order_reference, name="order-file"),
    path("cabinet/telegram/unlink/", views.telegram_unlink, name="telegram-unlink"),
]
