"""Тесты диалогов бота: реальный Dispatcher, поддельная сессия Telegram, настоящая БД."""

import io
import itertools
import logging
import tempfile
import time
from collections.abc import AsyncGenerator
from unittest import mock

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, GetMe, SendDocument, SendMessage, SendPhoto
from aiogram.types import Chat, Message, Update, User
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from studio.models import Notification, Order, OrderDelivery, OrderMessage, Profile, Service

from . import keyboards as kb
from .main import build_dispatcher

AUTH_User = get_user_model()
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
ADMIN_ID = 9001
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-body" * 4
_ids = itertools.count(1000)
_dispatcher = None


def get_dispatcher():
    """Роутеры можно подключить только к одному Dispatcher, поэтому он общий на процесс."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = build_dispatcher()
    return _dispatcher


class FakeSession(BaseSession):
    """Запоминает вызовы Bot API и отвечает так, как ответил бы Telegram."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs) -> AsyncGenerator[bytes]:
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Studio", username="studio_test_bot")
        if isinstance(method, SendMessage | SendPhoto | SendDocument):
            return Message(
                message_id=len(self.calls),
                date=int(time.time()),
                chat=Chat(id=method.chat_id, type="private"),
            )
        return True


class Dialog:
    """Один пользователь Telegram, который пишет боту."""

    def __init__(self, bot: Bot, user_id: int | None = None, name="Иван", username="ivan"):
        self.bot, self.dp = bot, get_dispatcher()
        self.id = user_id or next(_ids)
        self.name, self.username = name, username
        self._n = itertools.count(1)

    def _from(self, *, is_bot=False):
        data = {"id": self.id, "is_bot": is_bot, "first_name": self.name}
        if self.username and not is_bot:
            data["username"] = self.username
        return data

    def _message(self, **extra):
        return {
            "message_id": next(self._n),
            "date": int(time.time()),
            "chat": {"id": self.id, "type": "private"},
            "from": self._from(),
            **extra,
        }

    async def _feed(self, **payload):
        before = len(self.bot.session.calls)
        update = Update.model_validate(
            {"update_id": next(self._n), **payload}, context={"bot": self.bot}
        )
        await self.dp.feed_update(self.bot, update)
        return self.bot.session.calls[before:]

    async def say(self, text=None, **extra):
        return await self._feed(message=self._message(text=text, **extra))

    async def press(self, data):
        bot_message = self._message(text="menu")
        bot_message["from"] = {"id": 1, "is_bot": True, "first_name": "Studio"}
        return await self._feed(
            callback_query={
                "id": str(next(self._n)),
                "from": self._from(),
                "chat_instance": "test",
                "data": data,
                "message": bot_message,
            }
        )


def texts(calls) -> str:
    return "\n".join(c.text for c in calls if isinstance(c, SendMessage))


def sent(calls) -> list[SendMessage]:
    return [c for c in calls if isinstance(c, SendMessage)]


def button_data(message: SendMessage) -> list[str]:
    markup = message.reply_markup
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


@override_settings(
    TELEGRAM_BOT_TOKEN="test-token",
    TELEGRAM_ADMIN_IDS=[ADMIN_ID],
    SITE_URL="https://site.test",
    SITE_NAME="Polygon3D",
)
class HandlerTestCase(TestCase):
    def setUp(self):
        self.bot = Bot(
            "123456:TEST",
            session=FakeSession(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.service = Service.objects.create(
            title="Робот",
            slug="robot",
            short_description="s",
            description="Описание робота",
            price_from=5000,
        )

    def dialog(self, **kwargs):
        return Dialog(self.bot, **kwargs)


class StartAndMenuTests(HandlerTestCase):
    async def test_start_greets_with_menu(self):
        calls = await self.dialog(name="Анна").say("/start")
        message = sent(calls)[0]
        self.assertIn("Привет, Анна", message.text)
        self.assertIn("Polygon3D", message.text)
        self.assertEqual(message.reply_markup, kb.main_menu())

    async def test_start_links_site_account(self):
        user = await AUTH_User.objects.acreate_user("bob", "b@b.ru", "x")
        profile = await Profile.objects.aget(user=user)
        dialog = self.dialog(username="bob_tg")

        calls = await dialog.say(f"/start link_{profile.link_token.hex}")

        await profile.arefresh_from_db()
        self.assertEqual((profile.telegram_id, profile.telegram_username), (dialog.id, "bob_tg"))
        self.assertIn("привязан", texts(calls))

    async def test_start_with_bad_link_token(self):
        calls = await self.dialog().say("/start link_" + "0" * 32)
        self.assertIn("недействительна", texts(calls))

    async def test_start_claims_site_order(self):
        order = await Order.objects.acreate(name="A", description="x")
        dialog = self.dialog()

        calls = await dialog.say(f"/start order_{order.public_id.hex}")

        await order.arefresh_from_db()
        self.assertEqual(order.telegram_id, dialog.id)
        self.assertIn(f"Заказ №{order.pk} привязан", texts(calls))

    async def test_claimed_order_cannot_be_taken_over(self):
        order = await Order.objects.acreate(name="A", description="x", telegram_id=42)
        calls = await self.dialog().say(f"/start order_{order.public_id.hex}")
        await order.arefresh_from_db()
        self.assertEqual(order.telegram_id, 42)
        self.assertIn("Не удалось привязать", texts(calls))

    async def test_services_list_and_card(self):
        dialog = self.dialog()
        listing = sent(await dialog.say(kb.BTN_SERVICES))[0]
        self.assertEqual(button_data(listing), [f"svc:{self.service.pk}"])

        calls = await dialog.press(f"svc:{self.service.pk}")

        card = sent(calls)[0]
        self.assertIn("от 5 000 ₽", card.text)
        self.assertIn("Описание робота", card.text)
        self.assertIn("https://site.test/services/robot/", card.text)
        self.assertEqual(button_data(card), [f"order:{self.service.pk}"])
        self.assertTrue(any(isinstance(c, AnswerCallbackQuery) for c in calls))

    async def test_contacts_and_unknown_text(self):
        dialog = self.dialog()
        self.assertIn("https://site.test", texts(await dialog.say(kb.BTN_CONTACTS)))
        self.assertIn("Не понял", texts(await dialog.say("абракадабра")))

    async def test_html_in_user_name_is_escaped(self):
        calls = await self.dialog(name="<b>Hacker</b>").say("/start")
        self.assertIn("&lt;b&gt;Hacker&lt;/b&gt;", sent(calls)[0].text)


class OrderFlowTests(HandlerTestCase):
    async def start_order(self, dialog):
        await dialog.say(kb.BTN_ORDER)
        await dialog.press(f"order:{self.service.pk}")

    async def test_full_order_flow(self):
        dialog = self.dialog(name="Игорь Власов", username="igor")
        await self.start_order(dialog)

        self.assertIn("подробнее", texts(await dialog.say("коротко")))
        self.assertIn("телефон", texts(await dialog.say("Нужен low-poly робот для мобильной игры")))
        self.assertIn("референсы", texts(await dialog.say("+7 900 111-22-33")))
        calls = await dialog.say(kb.BTN_SKIP)

        order = await Order.objects.aget(telegram_id=dialog.id)
        self.assertEqual(
            (order.name, order.telegram_username, order.phone, order.source, order.service_id),
            ("Игорь Власов", "igor", "+7 900 111-22-33", Order.Source.BOT, self.service.pk),
        )
        self.assertEqual(order.description, "Нужен low-poly робот для мобильной игры")
        self.assertIn(f"Заказ №{order.pk} принят", texts(calls))
        note = await Notification.objects.aget(kind=Notification.Kind.ADMIN_ORDER)
        self.assertEqual(note.chat_id, ADMIN_ID)

    async def test_contact_can_be_skipped_and_shared(self):
        skipper = self.dialog()
        await self.start_order(skipper)
        await skipper.say("Нужна модель кружки для каталога")
        await skipper.say(kb.BTN_SKIP)
        await skipper.say(kb.BTN_SKIP)
        self.assertEqual((await Order.objects.aget(telegram_id=skipper.id)).phone, "")

        sharer = self.dialog()
        await self.start_order(sharer)
        await sharer.say("Нужна модель кружки для каталога")
        await sharer.say(contact={"phone_number": "+79001112233", "first_name": "Иван"})
        await sharer.say(kb.BTN_SKIP)
        self.assertEqual((await Order.objects.aget(telegram_id=sharer.id)).phone, "+79001112233")

    async def test_order_without_service(self):
        dialog = self.dialog()
        await dialog.say(kb.BTN_ORDER)
        await dialog.press("order:0")
        await dialog.say("Хочу что-нибудь особенное, пока не знаю что")
        await dialog.say(kb.BTN_SKIP)
        await dialog.say(kb.BTN_SKIP)
        self.assertIsNone((await Order.objects.aget(telegram_id=dialog.id)).service_id)

    async def test_photo_reference_is_saved(self):
        dialog = self.dialog()
        await self.start_order(dialog)
        await dialog.say("Нужна модель по моему эскизу")
        await dialog.say(kb.BTN_SKIP)
        photo = {"file_id": "f", "file_unique_id": "u", "width": 10, "height": 10, "file_size": 9}

        with (
            tempfile.TemporaryDirectory() as media,
            override_settings(MEDIA_ROOT=media),
            mock.patch.object(
                Bot, "download", new=mock.AsyncMock(return_value=io.BytesIO(FAKE_JPEG))
            ),
        ):
            calls = await dialog.say(photo=[photo])
            order = await Order.objects.aget(telegram_id=dialog.id)
            self.assertTrue(order.reference_file.name.startswith("orders/"))
            self.assertTrue(order.reference_file.name.endswith(".jpg"))
            self.assertEqual(order.reference_file.read(), FAKE_JPEG)
        self.assertIn("принят", texts(calls))

    async def test_forbidden_document_keeps_dialog_open(self):
        dialog = self.dialog()
        await self.start_order(dialog)
        await dialog.say("Нужна модель по чертежу")
        await dialog.say(kb.BTN_SKIP)
        document = {"file_id": "f", "file_unique_id": "u", "file_name": "evil.exe", "file_size": 5}

        with (
            mock.patch.object(Bot, "download", new=mock.AsyncMock(return_value=io.BytesIO(b"MZ"))),
            self.assertLogs("bot.handlers", level="ERROR"),
        ):
            calls = await dialog.say(document=document)

        self.assertIn("Не получилось сохранить", texts(calls))
        self.assertFalse(await Order.objects.filter(telegram_id=dialog.id).aexists())
        self.assertIn("принят", texts(await dialog.say(kb.BTN_SKIP)))

    async def test_oversized_document_is_refused(self):
        dialog = self.dialog()
        await self.start_order(dialog)
        await dialog.say("Нужна модель по чертежу")
        await dialog.say(kb.BTN_SKIP)
        big = {"file_id": "f", "file_unique_id": "u", "file_name": "a.zip", "file_size": 25 * 2**20}

        calls = await dialog.say(document=big)

        self.assertIn("больше 20 МБ", texts(calls))
        self.assertFalse(await Order.objects.filter(telegram_id=dialog.id).aexists())

    async def test_cancel_resets_dialog(self):
        dialog = self.dialog()
        await self.start_order(dialog)
        self.assertIn("Отменено", texts(await dialog.say(kb.BTN_CANCEL)))
        self.assertIn("Не понял", texts(await dialog.say("Нужна модель дракона для игры")))
        self.assertFalse(await Order.objects.filter(telegram_id=dialog.id).aexists())

    async def test_menu_button_is_not_taken_as_description(self):
        dialog = self.dialog()
        await self.start_order(dialog)
        calls = await dialog.say(kb.BTN_MY_ORDERS)
        self.assertIn("пока нет заказов", texts(calls))
        self.assertFalse(await Order.objects.filter(telegram_id=dialog.id).aexists())


class ClientOrdersAndChatTests(HandlerTestCase):
    async def test_orders_are_scoped_to_the_user(self):
        dialog = self.dialog()
        mine = await Order.objects.acreate(name="A", description="x", telegram_id=dialog.id)
        other = await Order.objects.acreate(name="B", description="y", telegram_id=dialog.id + 1)

        listing = sent(await dialog.say(kb.BTN_MY_ORDERS))[0]
        self.assertEqual(button_data(listing), [f"my:{mine.pk}"])

        self.assertIn(f"Заказ №{mine.pk}", texts(await dialog.press(f"my:{mine.pk}")))
        self.assertIn("не найден", texts(await dialog.press(f"my:{other.pk}")))

    async def test_orders_of_linked_site_account_are_visible(self):
        user = await AUTH_User.objects.acreate_user("alice", "a@a.ru", "x")
        profile = await Profile.objects.aget(user=user)
        dialog = self.dialog()
        await dialog.say(f"/start link_{profile.link_token.hex}")
        order = await Order.objects.acreate(user=user, name="Alice", description="x")

        listing = sent(await dialog.say(kb.BTN_MY_ORDERS))[0]

        self.assertEqual(button_data(listing), [f"my:{order.pk}"])

    async def test_client_message_reaches_managers(self):
        dialog = self.dialog()
        order = await Order.objects.acreate(name="A", description="x", telegram_id=dialog.id)

        await dialog.press(f"chat:{order.pk}")
        calls = await dialog.say("Когда будет готово?")

        message = await OrderMessage.objects.aget(order=order)
        self.assertEqual((message.sender, message.text), ("client", "Когда будет готово?"))
        self.assertIn("отправлено менеджеру", texts(calls))
        note = await Notification.objects.aget(kind=Notification.Kind.ADMIN_MESSAGE)
        self.assertEqual(note.chat_id, ADMIN_ID)
        self.assertIn("Когда будет готово?", note.text)
        # Режим чата одноразовый: следующий текст уже не уходит менеджеру.
        await dialog.say("Ещё одно сообщение")
        self.assertEqual(await OrderMessage.objects.filter(order=order).acount(), 1)

    async def test_cannot_write_to_foreign_order(self):
        stranger = await Order.objects.acreate(name="B", description="y", telegram_id=1)
        dialog = self.dialog()

        calls = await dialog.press(f"chat:{stranger.pk}")
        await dialog.say("взлом")

        self.assertIn("не найден", texts(calls))
        self.assertFalse(await OrderMessage.objects.filter(order=stranger).aexists())

    async def test_order_card_shows_recent_messages(self):
        dialog = self.dialog()
        order = await Order.objects.acreate(name="A", description="x", telegram_id=dialog.id)
        await OrderMessage.objects.acreate(order=order, sender="manager", text="Принято в работу")

        card = texts(await dialog.press(f"my:{order.pk}"))

        self.assertIn("Принято в работу", card)
        self.assertIn("Менеджер", card)


class ManagerTests(HandlerTestCase):
    async def test_orders_command_is_admin_only(self):
        order = await Order.objects.acreate(name="Клиент", description="Нужна модель", status="new")

        stranger_reply = texts(await self.dialog().say("/orders"))
        admin_calls = await self.dialog(user_id=ADMIN_ID).say("/orders")

        self.assertIn("Не понял", stranger_reply)
        self.assertNotIn(f"Заказ №{order.pk}", stranger_reply)
        self.assertIn(f"Заказ №{order.pk}", texts(admin_calls))
        self.assertIn(f"areply:{order.pk}", button_data(sent(admin_calls)[0]))

    async def test_status_change_notifies_client(self):
        order = await Order.objects.acreate(name="A", description="x", telegram_id=555)

        calls = await self.dialog(user_id=ADMIN_ID).press(f"astatus:{order.pk}:in_progress")

        await order.arefresh_from_db()
        self.assertEqual(order.status, Order.Status.IN_PROGRESS)
        self.assertIn("Клиент уведомлён", texts(calls))
        note = await Notification.objects.aget(kind=Notification.Kind.CLIENT_STATUS)
        self.assertEqual(note.chat_id, 555)

    async def test_non_admin_cannot_change_status(self):
        order = await Order.objects.acreate(name="A", description="x")
        await self.dialog().press(f"astatus:{order.pk}:done")
        await order.arefresh_from_db()
        self.assertEqual(order.status, Order.Status.NEW)

    async def test_unknown_status_is_ignored(self):
        order = await Order.objects.acreate(name="A", description="x")
        await self.dialog(user_id=ADMIN_ID).press(f"astatus:{order.pk}:hacked")
        await order.arefresh_from_db()
        self.assertEqual(order.status, Order.Status.NEW)

    async def test_manager_reply_is_delivered_to_client(self):
        order = await Order.objects.acreate(name="A", description="x", telegram_id=555)
        admin = self.dialog(user_id=ADMIN_ID)

        await admin.press(f"areply:{order.pk}")
        calls = await admin.say("Готов показать первый рендер")

        message = await OrderMessage.objects.aget(order=order)
        self.assertEqual(
            (message.sender, message.text), ("manager", "Готов показать первый рендер")
        )
        self.assertIn(f"Отправлено по заказу №{order.pk}", texts(calls))
        note = await Notification.objects.aget(kind=Notification.Kind.CLIENT_MESSAGE)
        self.assertEqual(note.chat_id, 555)

    async def test_non_admin_cannot_start_reply(self):
        order = await Order.objects.acreate(name="A", description="x", telegram_id=555)
        stranger = self.dialog()

        await stranger.press(f"areply:{order.pk}")
        await stranger.say("я не менеджер")

        self.assertFalse(await OrderMessage.objects.filter(order=order).aexists())


class BotRateLimitTests(HandlerTestCase):
    async def test_too_many_orders_in_an_hour_are_refused(self):
        dialog = self.dialog()
        for _ in range(5):
            await Order.objects.acreate(name="A", description="x", telegram_id=dialog.id)

        await dialog.say(kb.BTN_ORDER)
        await dialog.press(f"order:{self.service.pk}")
        await dialog.say("Нужна ещё одна модель для игры")
        await dialog.say(kb.BTN_SKIP)
        calls = await dialog.say(kb.BTN_SKIP)

        self.assertIn("Слишком много заказов", texts(calls))
        self.assertEqual(await Order.objects.filter(telegram_id=dialog.id).acount(), 5)
        self.assertIn("Не понял", texts(await dialog.say("привет")))

    async def test_old_orders_do_not_count(self):
        from datetime import timedelta

        from django.utils import timezone

        dialog = self.dialog()
        for _ in range(5):
            order = await Order.objects.acreate(name="A", description="x", telegram_id=dialog.id)
            await Order.objects.filter(pk=order.pk).aupdate(
                created_at=timezone.now() - timedelta(hours=2)
            )

        await dialog.say(kb.BTN_ORDER)
        await dialog.press(f"order:{self.service.pk}")
        await dialog.say("Нужна новая модель для игры")
        await dialog.say(kb.BTN_SKIP)
        calls = await dialog.say(kb.BTN_SKIP)

        self.assertIn("принят", texts(calls))


class DeliveryDialogTests(HandlerTestCase):
    def setUp(self):
        super().setUp()
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)

    async def review_order(self, dialog, with_file=True):
        order = await Order.objects.acreate(
            name="A", description="x", telegram_id=dialog.id, status=Order.Status.REVIEW
        )
        if with_file:
            await OrderDelivery.objects.acreate(
                order=order,
                title="Рендеры v1",
                file=SimpleUploadedFile("render.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 16),
            )
            await Order.objects.filter(pk=order.pk).aupdate(status=Order.Status.REVIEW)
        await Notification.objects.all().adelete()
        return order

    async def test_delivery_notification_carries_review_buttons(self):
        from . import outbox

        markup = outbox._markup({"order_id": 7, "kind": Notification.Kind.CLIENT_DELIVERY})
        data = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertEqual(data, ["dacc:7", "drev:7", "dfiles:7", "chat:7"])

    async def test_order_card_offers_review_actions_only_in_review(self):
        dialog = self.dialog()
        order = await self.review_order(dialog)

        card = sent(await dialog.press(f"my:{order.pk}"))[0]
        self.assertIn(f"dacc:{order.pk}", button_data(card))
        self.assertIn(f"dfiles:{order.pk}", button_data(card))

        await Order.objects.filter(pk=order.pk).aupdate(status=Order.Status.DONE)
        card = sent(await dialog.press(f"my:{order.pk}"))[0]
        self.assertNotIn(f"dacc:{order.pk}", button_data(card))
        self.assertIn(f"dfiles:{order.pk}", button_data(card))

    async def test_client_accepts_the_work(self):
        dialog = self.dialog()
        order = await self.review_order(dialog)

        calls = await dialog.press(f"dacc:{order.pk}")

        await order.arefresh_from_db()
        self.assertEqual(order.status, Order.Status.DONE)
        self.assertIn("принята", texts(calls))
        self.assertTrue(
            await Notification.objects.filter(
                kind=Notification.Kind.ADMIN_EVENT, chat_id=ADMIN_ID
            ).aexists()
        )

    async def test_accept_is_refused_for_foreign_or_unfinished_orders(self):
        owner, stranger = self.dialog(), self.dialog()
        order = await self.review_order(owner)

        await stranger.press(f"dacc:{order.pk}")
        await order.arefresh_from_db()
        self.assertEqual(order.status, Order.Status.REVIEW)

        await Order.objects.filter(pk=order.pk).aupdate(status=Order.Status.IN_PROGRESS)
        calls = await owner.press(f"dacc:{order.pk}")
        self.assertIn("только заказ со статусом", texts(calls))

    async def test_client_requests_revisions(self):
        dialog = self.dialog()
        order = await self.review_order(dialog)

        self.assertIn("Опишите, что нужно изменить", texts(await dialog.press(f"drev:{order.pk}")))
        calls = await dialog.say("Поменяйте цвет корпуса на синий")

        await order.arefresh_from_db()
        self.assertEqual((order.status, order.revisions_used), (Order.Status.IN_PROGRESS, 1))
        self.assertIn("правка 1", texts(calls))
        message = await OrderMessage.objects.aget(order=order)
        self.assertIn("Поменяйте цвет корпуса на синий", message.text)
        self.assertTrue(
            await Notification.objects.filter(
                kind=Notification.Kind.ADMIN_MESSAGE, chat_id=ADMIN_ID
            ).aexists()
        )

    async def test_revision_is_refused_outside_review_and_for_strangers(self):
        owner, stranger = self.dialog(), self.dialog()
        order = await self.review_order(owner)

        refusal = texts(await stranger.press(f"drev:{order.pk}"))
        self.assertIn(
            "только у заказа", refusal
        )  # одинаковый ответ: наличие чужого заказа не раскрываем
        await stranger.say("взлом")
        self.assertFalse(await OrderMessage.objects.filter(order=order).aexists())

        await Order.objects.filter(pk=order.pk).aupdate(status=Order.Status.IN_PROGRESS)
        calls = await owner.press(f"drev:{order.pk}")
        self.assertIn("только у заказа", texts(calls))

    async def test_client_receives_files(self):
        dialog = self.dialog()
        order = await self.review_order(dialog)

        calls = await dialog.press(f"dfiles:{order.pk}")

        documents = [c for c in calls if isinstance(c, SendDocument)]
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].caption, "Рендеры v1")
        self.assertEqual(documents[0].document.filename, "render.png")

    async def test_stranger_gets_no_files(self):
        owner, stranger = self.dialog(), self.dialog()
        order = await self.review_order(owner)

        calls = await stranger.press(f"dfiles:{order.pk}")

        self.assertFalse([c for c in calls if isinstance(c, SendDocument)])
        self.assertIn("Файлов пока нет", texts(calls))
