"""Доступ бота к БД Django.

Все функции синхронные и оборачиваются в sync_to_async: они возвращают
простые dict, чтобы в async-коде не было ленивых обращений к ORM.
"""

import uuid
from datetime import timedelta
from functools import wraps

from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.db import close_old_connections, connection
from django.db.models import Q
from django.utils import timezone

from studio import services
from studio.models import Notification, Order, OrderMessage, PortfolioItem, Profile, Service
from studio.validators import validate_reference

MAX_ATTEMPTS = 5
MAX_ORDERS_PER_HOUR = 5


class RateLimited(Exception):
    """Слишком много заказов с одного Telegram-аккаунта за час."""


def db(fn):
    """Выполняет функцию в потоке с корректным управлением соединениями."""

    @wraps(fn)
    def sync_wrapper(*args, **kwargs):
        in_tx = connection.in_atomic_block  # в тестах всё идёт в одной транзакции
        if not in_tx:
            close_old_connections()
        try:
            return fn(*args, **kwargs)
        finally:
            if not in_tx:
                close_old_connections()

    return sync_to_async(sync_wrapper, thread_sensitive=True)


def _own_orders(tg_id: int):
    return Order.objects.filter(Q(telegram_id=tg_id) | Q(user__profile__telegram_id=tg_id))


def _order_dict(order: Order) -> dict:
    service = order.service.title if order.service else "Индивидуальный заказ"
    return {
        "id": order.pk,
        "title": f"№{order.pk} · {service}",
        "service": service,
        "status": order.get_status_display(),
        "status_code": order.status,
        "name": order.name,
        "description": order.description,
        "created": order.created_at,
    }


@db
def list_services() -> list[dict]:
    return [
        {
            "id": s.pk,
            "title": s.title,
            "short": s.short_description,
            "description": s.description,
            "price_from": s.price_from,
            "duration": s.duration,
            "slug": s.slug,
        }
        for s in Service.objects.filter(is_active=True)
    ]


@db
def get_service(service_id: int) -> dict | None:
    s = Service.objects.filter(pk=service_id, is_active=True).first()
    if not s:
        return None
    return {
        "id": s.pk,
        "title": s.title,
        "description": s.description,
        "price_from": s.price_from,
        "duration": s.duration,
        "slug": s.slug,
    }


@db
def latest_portfolio(limit: int = 5) -> list[dict]:
    return [
        {
            "title": w.title,
            "category": w.get_category_display(),
            "slug": w.slug,
            "image_path": w.image.path if w.image else None,
        }
        for w in PortfolioItem.objects.filter(is_published=True)[:limit]
    ]


@db
def create_order(
    *,
    tg_id: int,
    tg_username: str,
    name: str,
    description: str,
    service_id: int | None = None,
    phone: str = "",
    file: tuple[str, bytes] | None = None,
) -> int:
    recent = Order.objects.filter(
        telegram_id=tg_id, created_at__gte=timezone.now() - timedelta(hours=1)
    ).count()
    if recent >= MAX_ORDERS_PER_HOUR:
        raise RateLimited
    profile = Profile.objects.filter(telegram_id=tg_id).select_related("user").first()
    order = Order(
        user=profile.user if profile else None,
        service=Service.objects.filter(pk=service_id).first() if service_id else None,
        name=name[:80],
        email=profile.user.email if profile else "",
        phone=phone[:32],
        telegram_username=tg_username[:64],
        telegram_id=tg_id,
        description=description,
        source=Order.Source.BOT,
    )
    if file:
        filename, content = file
        upload = ContentFile(content, name=filename)
        for validator in validate_reference:  # save() валидаторы модели не запускает
            validator(upload)
        order.reference_file.save(filename, upload, save=False)
    order.save()
    return order.pk


@db
def list_orders(tg_id: int, limit: int = 10) -> list[dict]:
    qs = _own_orders(tg_id).select_related("service")[:limit]
    return [_order_dict(o) for o in qs]


@db
def get_order(tg_id: int, order_id: int) -> dict | None:
    order = _own_orders(tg_id).select_related("service").filter(pk=order_id).first()
    if not order:
        return None
    data = _order_dict(order)
    data["in_review"] = order.status == Order.Status.REVIEW
    data["deliveries"] = order.deliveries.count()
    data["revisions_used"] = order.revisions_used
    data["messages"] = [
        {"sender": m.sender, "text": m.text}
        for m in reversed(list(order.messages.order_by("-created_at")[:5]))
    ]
    return data


@db
def add_client_message(tg_id: int, order_id: int, text: str) -> bool:
    order = _own_orders(tg_id).filter(pk=order_id).first()
    if not order:
        return False
    OrderMessage.objects.create(order=order, sender=OrderMessage.Sender.CLIENT, text=text)
    return True


@db
def accept_order(tg_id: int, order_id: int) -> bool:
    order = _own_orders(tg_id).filter(pk=order_id).first()
    return bool(order and services.accept_order(order))


@db
def request_revision(tg_id: int, order_id: int, text: str) -> int | None:
    order = _own_orders(tg_id).filter(pk=order_id).first()
    return services.request_revision(order, text) if order else None


@db
def delivery_files(tg_id: int, order_id: int) -> list[dict]:
    order = _own_orders(tg_id).filter(pk=order_id).first()
    if not order:
        return []
    return [
        {"title": d.display_title, "filename": d.filename, "path": d.file.path}
        for d in order.deliveries.all()
    ]


@db
def add_manager_message(order_id: int, text: str) -> bool:
    order = Order.objects.filter(pk=order_id).first()
    if not order:
        return False
    OrderMessage.objects.create(order=order, sender=OrderMessage.Sender.MANAGER, text=text)
    return True


@db
def set_status(order_id: int, status: str) -> str | None:
    """Меняет статус; возвращает его человекочитаемое название."""
    if status not in Order.Status.values:
        return None
    order = Order.objects.filter(pk=order_id).first()
    if not order:
        return None
    order.status = status
    order.save()
    return order.get_status_display()


@db
def active_orders(limit: int = 10) -> list[dict]:
    qs = (
        Order.objects.filter(status__in=[Order.Status.NEW, Order.Status.IN_PROGRESS])
        .select_related("service")
        .order_by("-created_at")[:limit]
    )
    return [_order_dict(o) for o in qs]


@db
def link_account(token_hex: str, tg_id: int, username: str) -> bool:
    try:
        token = uuid.UUID(token_hex)
    except ValueError:
        return False
    profile = Profile.objects.filter(link_token=token).first()
    if not profile:
        return False
    Profile.objects.filter(telegram_id=tg_id).exclude(pk=profile.pk).update(telegram_id=None)
    profile.telegram_id = tg_id
    profile.telegram_username = username[:64]
    profile.save(update_fields=["telegram_id", "telegram_username"])
    return True


@db
def claim_order(public_hex: str, tg_id: int, username: str) -> int | None:
    """Привязывает заказ с сайта к Telegram клиента (по ссылке со страницы «Спасибо»)."""
    try:
        public_id = uuid.UUID(public_hex)
    except ValueError:
        return None
    order = Order.objects.filter(public_id=public_id, telegram_id__isnull=True).first()
    if not order:
        return None
    order.telegram_id = tg_id
    if not order.telegram_username:
        order.telegram_username = username[:64]
    order.save()
    return order.pk


# --- Очередь уведомлений ---


@db
def fetch_pending(limit: int = 20) -> list[dict]:
    qs = Notification.objects.filter(sent_at__isnull=True, attempts__lt=MAX_ATTEMPTS)[:limit]
    return [
        {"id": n.pk, "chat_id": n.chat_id, "kind": n.kind, "order_id": n.order_id, "text": n.text}
        for n in qs
    ]


@db
def mark_sent(notification_id: int) -> None:
    Notification.objects.filter(pk=notification_id).update(sent_at=timezone.now())


@db
def mark_failed(notification_id: int, error: str, give_up: bool = False) -> None:
    n = Notification.objects.filter(pk=notification_id).first()
    if n:
        n.attempts = MAX_ATTEMPTS if give_up else n.attempts + 1
        n.error = error[:255]
        n.save(update_fields=["attempts", "error"])
