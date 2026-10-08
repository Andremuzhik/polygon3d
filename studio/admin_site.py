from django.contrib.admin import AdminSite

from .dashboard import dashboard_stats


class StudioAdminSite(AdminSite):
    """Главная страница админки с показателями студии."""

    def index(self, request, extra_context=None):
        extra_context = dict(extra_context or {})
        if request.user.has_perm(
            "studio.view_order"
        ):  # цифры по заказам — только тем, кто видит заказы
            extra_context["dashboard"] = dashboard_stats()
        return super().index(request, extra_context)
