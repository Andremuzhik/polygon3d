from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from . import notifications
from .models import Order, OrderMessage, Profile


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
        notifications.order_created(instance)
    elif getattr(instance, "_old_status", None) not in (None, instance.status):
        notifications.status_changed(instance)


@receiver(post_save, sender=OrderMessage)
def message_saved(sender, instance, created, **kwargs):
    if created:
        notifications.message_created(instance)
