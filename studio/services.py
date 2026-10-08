"""Бизнес-операции над заказом, общие для сайта и Telegram-бота."""

from django.db import transaction

from . import notifications
from .models import REVISIONS_INCLUDED, Order, OrderMessage


def accept_order(order: Order) -> bool:
    """Клиент принимает результат: заказ на согласовании становится выполненным."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.REVIEW:
            return False
        order.status = Order.Status.DONE
        order.save()
    notifications.client_accepted(order)
    return True


def request_revision(order: Order, text: str) -> int | None:
    """Клиент просит правки: заказ возвращается в работу. Возвращает номер правки или None."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.REVIEW:
            return None
        order.revisions_used += 1
        order.status = Order.Status.IN_PROGRESS
        order.save()
        number = order.revisions_used
        note = (
            f"правка {number}, сверх {REVISIONS_INCLUDED} включённых"
            if number > REVISIONS_INCLUDED
            else f"правка {number} из {REVISIONS_INCLUDED}"
        )
        OrderMessage.objects.create(
            order=order,
            sender=OrderMessage.Sender.CLIENT,
            text=f"✏️ Запрос правок ({note}):\n{text.strip()}",
        )
    return number
