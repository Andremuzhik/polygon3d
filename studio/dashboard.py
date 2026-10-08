"""Показатели для главной страницы админки."""

from datetime import timedelta

from django.db.models import Count, Min, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Order, OrderEvent

MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
STALE_AFTER = timedelta(days=1)


def _month_start(moment):
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_months(moment, delta):
    index = moment.year * 12 + moment.month - 1 + delta
    return moment.replace(year=index // 12, month=index % 12 + 1)


def dashboard_stats(now=None) -> dict:
    now = timezone.localtime(now or timezone.now())
    month_start = _month_start(now)
    orders = Order.objects.all()
    total = orders.count()

    counts = dict(orders.values_list("status").annotate(n=Count("pk")))
    statuses = [
        {"code": code, "label": label, "count": counts.get(code, 0)}
        for code, label in Order.Status.choices
    ]
    done = counts.get(Order.Status.DONE, 0)

    # Срок выполнения: от создания до первого перехода в «Выполнен» (по журналу событий).
    finished = Order.objects.filter(status=Order.Status.DONE).annotate(
        done_at=Min(
            "events__created_at",
            filter=Q(events__kind=OrderEvent.Kind.STATUS, events__to_status=Order.Status.DONE),
        )
    )
    durations = [o.done_at - o.created_at for o in finished if o.done_at]
    average_days = (
        round(sum(d.total_seconds() for d in durations) / len(durations) / 86400, 1)
        if durations
        else None
    )

    first_month = _shift_months(month_start, -5)
    per_month = {
        (row["month"].year, row["month"].month): row["n"]
        for row in orders.filter(created_at__gte=first_month)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(n=Count("pk"))
    }
    months = []
    for shift in range(-5, 1):
        month = _shift_months(month_start, shift)
        months.append(
            {"label": MONTHS[month.month - 1], "count": per_month.get((month.year, month.month), 0)}
        )
    peak = max(m["count"] for m in months)
    for month in months:
        month["height"] = round(month["count"] * 100 / peak) if peak else 0

    return {
        "total": total,
        "created_this_month": orders.filter(created_at__gte=month_start).count(),
        "done_this_month": OrderEvent.objects.filter(
            kind=OrderEvent.Kind.STATUS, to_status=Order.Status.DONE, created_at__gte=month_start
        )
        .values("order")
        .distinct()
        .count(),
        "stale_new": orders.filter(
            status=Order.Status.NEW, created_at__lt=now - STALE_AFTER
        ).count(),
        "waiting_client": counts.get(Order.Status.REVIEW, 0),
        "completion_rate": round(done * 100 / total) if total else 0,
        "average_days": average_days,
        "statuses": statuses,
        "months": months,
        "sources": [
            {"label": label, "count": orders.filter(source=code).count()}
            for code, label in Order.Source.choices
        ],
        "top_services": list(
            orders.exclude(service=None)
            .values("service__title")
            .annotate(n=Count("pk"))
            .order_by("-n", "service__title")[:5]
        ),
        "recent": list(orders.select_related("service")[:6]),
    }
