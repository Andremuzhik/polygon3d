from django.contrib.admin.apps import AdminConfig


class StudioAdminConfig(AdminConfig):
    """Подключает собственный AdminSite с дашбордом (вместо стандартного)."""

    default_site = "studio.admin_site.StudioAdminSite"
