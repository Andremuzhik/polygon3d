"""Доставка уведомлений, созданных сайтом, в Telegram."""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from studio.models import Notification

from . import db
from . import keyboards as kb

log = logging.getLogger(__name__)

POLL_SECONDS = 2


def _markup(item: dict):
    if not item["order_id"]:
        return None
    if item["kind"] in (Notification.Kind.ADMIN_ORDER, Notification.Kind.ADMIN_MESSAGE):
        return kb.admin_order_actions(item["order_id"])
    if item["kind"] == Notification.Kind.CLIENT_MESSAGE:
        return kb.client_order_actions(item["order_id"])
    return None


async def deliver_pending(bot: Bot) -> int:
    sent = 0
    for item in await db.fetch_pending():
        try:
            await bot.send_message(item["chat_id"], item["text"], reply_markup=_markup(item))
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            break
        except TelegramForbiddenError as exc:
            # Пользователь заблокировал бота — повторять бессмысленно.
            await db.mark_failed(item["id"], str(exc), give_up=True)
        except TelegramAPIError as exc:
            log.warning("Не удалось доставить уведомление %s: %s", item["id"], exc)
            await db.mark_failed(item["id"], str(exc))
        else:
            await db.mark_sent(item["id"])
            sent += 1
    return sent


async def outbox_loop(bot: Bot) -> None:
    while True:
        try:
            await deliver_pending(bot)
        except Exception:
            log.exception("Ошибка в цикле доставки уведомлений")
        await asyncio.sleep(POLL_SECONDS)
