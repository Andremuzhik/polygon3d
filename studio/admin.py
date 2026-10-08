import csv
import re

from django.contrib import admin
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Notification,
    Order,
    OrderDelivery,
    OrderEvent,
    OrderMessage,
    PortfolioItem,
    Profile,
    Review,
    Service,
)

CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
PHONE_LIKE = re.compile(r"^\+[\d\s()\-]+$")


def csv_safe(value) -> str:
    """Защита от CSV-инъекции: ячейка, начинающаяся с = + - @, в Excel станет формулой."""
    text = "" if value is None else str(value)
    if text.startswith(CSV_FORMULA_PREFIXES) and not PHONE_LIKE.match(text):
        return "'" + text
    return text


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("title", "price_from", "duration", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title",)


@admin.register(PortfolioItem)
class PortfolioItemAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "has_model", "is_published", "created_at")
    list_filter = ("category", "is_published")
    list_editable = ("is_published",)
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "description")

    @admin.display(boolean=True, description="3D")
    def has_model(self, obj):
        return bool(obj.model_file)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("author", "rating", "is_published", "created_at")
    list_editable = ("is_published",)


class OrderMessageInline(admin.TabularInline):
    model = OrderMessage
    extra = 1
    fields = ("sender", "text", "created_at")
    readonly_fields = ("sender", "created_at")

    class Media:
        css = {"all": ("css/admin-inline.css",)}

    def has_change_permission(self, request, obj=None):
        return False


class OrderDeliveryInline(admin.TabularInline):
    model = OrderDelivery
    extra = 1
    fields = ("title", "file", "note", "download_link", "created_at")
    readonly_fields = ("download_link", "created_at")

    @admin.display(description="Скачать")
    def download_link(self, obj):
        if not obj.pk:
            return "—"
        return format_html(
            '<a href="{}">{}</a>', reverse("delivery-download", args=[obj.pk]), obj.filename
        )


class OrderEventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    fields = ("created_at", "text")
    readonly_fields = ("created_at", "text")
    can_delete = False
    verbose_name_plural = "история заказа"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "service", "status", "source", "contact", "created_at")
    list_filter = ("status", "source", "service")
    list_editable = ("status",)
    search_fields = ("name", "email", "phone", "telegram_username", "description")
    date_hierarchy = "created_at"
    readonly_fields = (
        "public_id",
        "user",
        "telegram_id",
        "source",
        "created_at",
        "revisions_used",
        "reference_link",
    )
    exclude = ("reference_file",)
    inlines = [OrderDeliveryInline, OrderMessageInline, OrderEventInline]
    actions = ["mark_in_progress", "mark_done", "export_csv"]

    @admin.display(description="Контакты")
    def contact(self, obj):
        return (
            obj.email or obj.phone or (f"@{obj.telegram_username}" if obj.telegram_username else "")
        )

    @admin.display(description="Референсы")
    def reference_link(self, obj):
        if not obj.pk or not obj.reference_file:
            return "—"
        url = reverse("order-file", args=[obj.pk])
        return format_html(
            '<a href="{}">Скачать {}</a>', url, obj.reference_file.name.split("/")[-1]
        )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, OrderMessage) and instance.pk is None:
                instance.sender = OrderMessage.Sender.MANAGER
            instance.save()
        formset.save_m2m()

    @admin.action(description="Взять в работу")
    def mark_in_progress(self, request, queryset):
        for order in queryset:
            order.status = Order.Status.IN_PROGRESS
            order.save()

    @admin.action(description="Выгрузить выбранные заказы в CSV")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="orders.csv"'
        response.write("\ufeff")  # BOM: Excel сразу открывает кириллицу правильно
        writer = csv.writer(
            response, delimiter=";"
        )  # «;» — разделитель по умолчанию в русском Excel
        writer.writerow(
            [
                "№",
                "Создан",
                "Статус",
                "Источник",
                "Услуга",
                "Имя",
                "Email",
                "Телефон",
                "Telegram (ник)",
                "Бюджет",
                "Срок",
                "Правок",
                "Описание",
            ]
        )
        for order in queryset.select_related("service").order_by("pk"):
            writer.writerow(
                csv_safe(value)
                for value in (
                    order.pk,
                    timezone.localtime(order.created_at).strftime("%d.%m.%Y %H:%M"),
                    order.get_status_display(),
                    order.get_source_display(),
                    order.service.title if order.service else "",
                    order.name,
                    order.email,
                    order.phone,
                    order.telegram_username,  # без «@»: ячейка с «@» в начале считалась бы формулой
                    order.budget,
                    order.deadline.strftime("%d.%m.%Y") if order.deadline else "",
                    order.revisions_used,
                    order.description,
                )
            )
        return response

    @admin.action(description="Отметить выполненными")
    def mark_done(self, request, queryset):
        for order in queryset:
            order.status = Order.Status.DONE
            order.save()


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "telegram_id", "telegram_username")
    search_fields = ("user__username", "telegram_username")
    readonly_fields = ("link_token",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "chat_id", "sent_at", "attempts", "error")
    list_filter = ("kind",)
    readonly_fields = [f.name for f in Notification._meta.fields]

    def has_add_permission(self, request):
        return False
