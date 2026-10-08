"""Ограничение частоты POST-запросов по IP (счётчики лежат в кэше в БД, общем для воркеров)."""

import math
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render


def client_ip(request) -> str:
    """IP клиента. X-Forwarded-For учитываем только за нашим прокси (Caddy перезаписывает заголовок)."""
    if settings.BEHIND_PROXY:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def allow(scope: str, key: str, limit: int, window: int) -> bool:
    """Регистрирует обращение и возвращает False, если за `window` секунд их стало больше `limit`."""
    cache_key = f"throttle:{scope}:{key}"
    if cache.add(cache_key, 1, window):  # первое обращение открывает окно
        return True
    try:
        return cache.incr(cache_key) <= limit
    except ValueError:  # окно истекло между add и incr
        cache.set(cache_key, 1, window)
        return True


def throttle(scope: str, limit: int, window: int):
    """Декоратор: не пускает POST-запросы сверх лимита (GET не ограничиваем)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method == "POST" and not allow(scope, client_ip(request), limit, window):
                return render(
                    request,
                    "429.html",
                    {"retry_minutes": math.ceil(window / 60)},
                    status=429,
                )
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
