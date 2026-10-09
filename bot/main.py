import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat
from django.conf import settings

from .handlers import admin_router, client_router, menu_router
from .outbox import outbox_loop

log = logging.getLogger(__name__)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # Порядок важен: кнопки меню должны срабатывать раньше состояний диалога.
    dp.include_routers(menu_router, admin_router, client_router)
    return dp


async def setup_commands(bot: Bot) -> None:
    """Меню команд: всем /start, менеджерам дополнительно /orders."""
    start = BotCommand(command="start", description="Главное меню")
    await bot.set_my_commands([start])
    for admin_id in settings.TELEGRAM_ADMIN_IDS:
        try:
            await bot.set_my_commands(
                [start, BotCommand(command="orders", description="Активные заказы")],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramAPIError as exc:  # менеджер ещё не нажимал /start у бота
            log.warning("Команды для менеджера %s не установлены: %s", admin_id, exc)


async def run() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN не задан — бот не запускается.")
        return

    bot = Bot(
        settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    me = await bot.get_me()
    log.info("Бот @%s запущен, менеджеров: %d", me.username, len(settings.TELEGRAM_ADMIN_IDS))

    await setup_commands(bot)
    outbox = asyncio.create_task(outbox_loop(bot))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        outbox.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await outbox
        await bot.session.close()
