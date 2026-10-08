import logging
from html import escape

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Notification, Order, OrderDelivery, OrderMessage

TELEGRAM_LIMIT = 3800
logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def _clip(text: str) -> str:
    return text if len(text) <= TELEGRAM_LIMIT else text[:TELEGRAM_LIMIT] + "…"


def _notify_admins(kind: str, order: Order, text: str) -> None:
    Notification.objects.bulk_create(
        [
            Notification(chat_id=admin_id, kind=kind, order=order, text=_clip(text))
            for admin_id in settings.TELEGRAM_ADMIN_IDS
        ]
    )


def _notify_client(kind: str, order: Order, text: str) -> None:
    chat_id = order.client_chat_id
    if chat_id:
        Notification.objects.create(chat_id=chat_id, kind=kind, order=order, text=_clip(text))


def _email_client(order: Order, subject: str, lines: list[str]) -> None:
    """Письмо клиенту. Не зависит от Telegram; сбой почты не должен ломать сохранение заказа."""
    if not (settings.EMAIL_NOTIFICATIONS and order.email):
        return
    body = [f"Здравствуйте, {order.name}!", "", *lines]
    if order.user_id:
        body += ["", f"Заказ в личном кабинете: {settings.SITE_URL}/cabinet/orders/{order.pk}/"]
    body += ["", f"— {settings.SITE_NAME}"]
    try:
        send_mail(
            f"{settings.SITE_NAME}: {subject}",
            "\n".join(body),
            settings.DEFAULT_FROM_EMAIL,
            [order.email],
        )
    except Exception:
        logger.exception("Не удалось отправить письмо по заказу №%s", order.pk)


def order_created(order: Order) -> None:
    _email_client(
        order,
        f"заявка №{order.pk} принята",
        [f"Мы получили вашу заявку №{order.pk}. Менеджер скоро свяжется с вами и уточнит детали."],
    )
    if not _enabled():
        return
    contacts = " · ".join(
        filter(
            None,
            [
                order.email,
                order.phone,
                f"@{order.telegram_username}" if order.telegram_username else "",
            ],
        )
    )
    lines = [
        f"🆕 <b>Новый заказ №{order.pk}</b> ({order.get_source_display()})",
        f"Услуга: {escape(order.service.title) if order.service else 'не выбрана'}",
        f"Клиент: {escape(order.name)}" + (f" — {escape(contacts)}" if contacts else ""),
    ]
    if order.budget:
        lines.append(f"Бюджет: {escape(order.budget)}")
    if order.deadline:
        lines.append(f"Срок: {order.deadline:%d.%m.%Y}")
    lines += ["", escape(order.description)]
    lines.append(f"\n{settings.SITE_URL}/admin/studio/order/{order.pk}/change/")
    _notify_admins(Notification.Kind.ADMIN_ORDER, order, "\n".join(lines))


def status_changed(order: Order) -> None:
    _email_client(
        order,
        f"заказ №{order.pk}, статус «{order.get_status_display()}»",
        [f"Статус вашего заказа №{order.pk} изменён на «{order.get_status_display()}»."],
    )
    if not _enabled():
        return
    _notify_client(
        Notification.Kind.CLIENT_STATUS,
        order,
        f"📦 Заказ №{order.pk}: статус изменён на <b>{order.get_status_display()}</b>",
    )


def message_created(message: OrderMessage) -> None:
    order = message.order
    if message.sender == OrderMessage.Sender.MANAGER:
        _email_client(
            order,
            f"сообщение по заказу №{order.pk}",
            [f"Менеджер написал вам по заказу №{order.pk}:", "", message.text],
        )
    if not _enabled():
        return
    body = escape(message.text)
    if message.sender == OrderMessage.Sender.CLIENT:
        _notify_admins(
            Notification.Kind.ADMIN_MESSAGE,
            order,
            f"💬 <b>Заказ №{order.pk}</b>, {escape(order.name)}:\n\n{body}",
        )
    else:
        _notify_client(
            Notification.Kind.CLIENT_MESSAGE,
            order,
            f"💬 <b>Менеджер по заказу №{order.pk}:</b>\n\n{body}",
        )


def delivery_created(delivery: OrderDelivery) -> None:
    """Менеджер загрузил результат: заказ уходит на согласование, клиент получает уведомление."""
    order = delivery.order
    # Условный update() в БД, а не проверка по объекту в памяти: он мог устареть.
    # И update(), а не save(), чтобы клиенту пришло одно уведомление «результат готов»,
    # без отдельного о смене статуса.
    moved = Order.objects.filter(
        pk=order.pk, status__in=[Order.Status.NEW, Order.Status.IN_PROGRESS]
    ).update(status=Order.Status.REVIEW, updated_at=timezone.now())
    if moved:
        order.status = Order.Status.REVIEW
    _email_client(
        order,
        f"по заказу №{order.pk} готов результат",
        [
            f"По заказу №{order.pk} готов результат: {delivery.display_title}.",
            "Посмотрите файлы, затем примите работу или попросите правки.",
        ],
    )
    if not _enabled():
        return
    note = f"\n{escape(delivery.note)}" if delivery.note else ""
    _notify_client(
        Notification.Kind.CLIENT_DELIVERY,
        order,
        f"📎 <b>Заказ №{order.pk}: результат готов</b>\n{escape(delivery.display_title)}{note}\n\n"
        "Посмотрите файлы, затем примите работу или попросите правки.",
    )


def client_accepted(order: Order) -> None:
    if not _enabled():
        return
    _notify_admins(
        Notification.Kind.ADMIN_EVENT,
        order,
        f"✅ <b>Клиент принял работу по заказу №{order.pk}</b> ({escape(order.name)})",
    )
