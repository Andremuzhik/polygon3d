import asyncio

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Запускает Telegram-бота (long polling) и доставку уведомлений."

    def handle(self, *args, **options):
        from bot.main import run

        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            self.stdout.write("Бот остановлен.")
