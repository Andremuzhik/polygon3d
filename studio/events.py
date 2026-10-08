from .models import Order, OrderEvent


def log(order: Order, kind: str, text: str, to_status: str = "") -> OrderEvent:
    return OrderEvent.objects.create(order=order, kind=kind, text=text[:255], to_status=to_status)


def status_label(code: str) -> str:
    return Order.Status(code).label if code in Order.Status.values else code
