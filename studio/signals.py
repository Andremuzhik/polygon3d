from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from . import events, notifications
from .models import Order, OrderDelivery, OrderEvent, OrderMessage, Profile


@receiver(post_save, sender=get_user_model())
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


@receiver(pre_save, sender=Order)
def remember_old_status(sender, instance, **kwargs):
    instance._old_status = (
        Order.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk
        else None
    )


@receiver(post_save, sender=Order)
def order_saved(sender, instance, created, **kwargs):
    if created:
        events.log(
            instance, OrderEvent.Kind.CREATED, f"Заказ создан ({instance.get_source_display()})"
        )
        notifications.order_created(instance)
    elif getattr(instance, "_old_status", None) not in (None, instance.status):
        old = events.status_label(instance._old_status)
        events.log(
            instance,
            OrderEvent.Kind.STATUS,
            f"Статус: {old} → {instance.get_status_display()}",
            to_status=instance.status,
        )
        notifications.status_changed(instance)


@receiver(post_save, sender=OrderMessage)
def message_saved(sender, instance, created, **kwargs):
    if not created:
        return
    if not getattr(instance, "_skip_event", False):
        who = "клиента" if instance.sender == OrderMessage.Sender.CLIENT else "менеджера"
        events.log(instance.order, OrderEvent.Kind.MESSAGE, f"Сообщение от {who}")
    notifications.message_created(instance)


@receiver(post_save, sender=OrderDelivery)
def delivery_saved(sender, instance, created, **kwargs):
    if not created:
        return
    before = Order.objects.filter(pk=instance.order_id).values_list("status", flat=True).first()
    notifications.delivery_created(instance)  # может перевести заказ на согласование
    after = Order.objects.filter(pk=instance.order_id).values_list("status", flat=True).first()

    events.log(
        instance.order, OrderEvent.Kind.DELIVERY, f"Загружен результат: {instance.display_title}"
    )
    if before != after:
        events.log(
            instance.order,
            OrderEvent.Kind.STATUS,
            f"Статус: {events.status_label(before)} → {events.status_label(after)}",
            to_status=after,
        )
