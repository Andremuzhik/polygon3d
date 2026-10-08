from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import PortfolioItem, Service


class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = "monthly"

    def items(self):
        return ["home", "services", "portfolio", "reviews", "contacts", "order"]

    def location(self, item):
        return reverse(item)


class ServiceSitemap(Sitemap):
    priority = 0.7
    changefreq = "monthly"

    def items(self):
        return Service.objects.filter(is_active=True)


class PortfolioSitemap(Sitemap):
    priority = 0.6
    changefreq = "monthly"

    def items(self):
        return PortfolioItem.objects.filter(is_published=True)

    def lastmod(self, obj):
        return obj.created_at


SITEMAPS = {"static": StaticViewSitemap, "services": ServiceSitemap, "portfolio": PortfolioSitemap}
