from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("services/", views.service_list, name="services"),
    path("services/<slug:slug>/", views.service_detail, name="service-detail"),
    path("portfolio/", views.portfolio_list, name="portfolio"),
    path("portfolio/<slug:slug>/", views.portfolio_detail, name="portfolio-detail"),
    path("reviews/", views.reviews, name="reviews"),
    path("contacts/", views.contacts, name="contacts"),
    path("order/", views.order_create, name="order"),
    path("order/thanks/<uuid:public_id>/", views.order_thanks, name="order-thanks"),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("cabinet/", views.cabinet, name="cabinet"),
    path("cabinet/orders/<int:pk>/", views.cabinet_order, name="cabinet-order"),
    path("cabinet/orders/<int:pk>/file/", views.order_reference, name="order-file"),
    path("cabinet/telegram/unlink/", views.telegram_unlink, name="telegram-unlink"),
]
