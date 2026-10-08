import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from django.conf import settings

from .handlers import admin_router, client_router, menu_router
from .outbox import outbox_loop

log = logging.getLogger(__name__)


async def run() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан — бот не может стартовать.")

    bot = Bot(
        settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    # Порядок важен: кнопки меню должны срабатывать раньше состояний диалога.
    dp.include_routers(menu_router, admin_router, client_router)

    me = await bot.get_me()
    log.info("Бот @%s запущен, менеджеров: %d", me.username, len(settings.TELEGRAM_ADMIN_IDS))

    outbox = asyncio.create_task(outbox_loop(bot))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        outbox.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await outbox
        await bot.session.close()
