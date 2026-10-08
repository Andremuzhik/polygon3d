from unittest import mock

from aiogram.exceptions import TelegramForbiddenError
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from studio.models import Notification, Order, OrderMessage, Profile, Service

from . import db, outbox

User = get_user_model()


@override_settings(TELEGRAM_BOT_TOKEN="t", TELEGRAM_ADMIN_IDS=[111])
class BotDbTests(TestCase):
    async def test_create_order_links_known_telegram_user(self):
        user = await User.objects.acreate_user("alice", "alice@example.com", "x")
        profile = await Profile.objects.aget(user=user)
        profile.telegram_id = 77
        await profile.asave()

        service = await Service.objects.acreate(
            title="S", slug="s", short_description="s", description="d"
        )
        order_id = await db.create_order(
            tg_id=77,
            tg_username="alice_tg",
            name="Alice",
            description="Нужен робот",
            service_id=service.pk,
            phone="+7900",
        )
        order = await Order.objects.aget(pk=order_id)
        self.assertEqual((order.user_id, order.source, order.telegram_id), (user.pk, "bot", 77))
        self.assertTrue(await Notification.objects.filter(chat_id=111, order=order).aexists())

    async def test_bad_reference_extension_is_rejected(self):
        with self.assertRaises(Exception):  # noqa: B017 - ValidationError
            await db.create_order(
                tg_id=1,
                tg_username="",
                name="X",
                description="desc desc desc",
                file=("evil.exe", b"MZ"),
            )
        self.assertFalse(await Order.objects.aexists())

    async def test_orders_are_scoped_to_owner(self):
        mine = await Order.objects.acreate(name="A", description="x", telegram_id=1)
        await Order.objects.acreate(name="B", description="y", telegram_id=2)
        self.assertEqual([o["id"] for o in await db.list_orders(1)], [mine.pk])
        self.assertIsNone(await db.get_order(2, mine.pk))
        self.assertFalse(await db.add_client_message(2, mine.pk, "hack"))
        self.assertTrue(await db.add_client_message(1, mine.pk, "hello"))
        self.assertEqual(await OrderMessage.objects.acount(), 1)

    async def test_claim_order_only_once(self):
        order = await Order.objects.acreate(name="A", description="x")
        hex_id = order.public_id.hex
        self.assertEqual(await db.claim_order(hex_id, 5, "tg"), order.pk)
        self.assertIsNone(await db.claim_order(hex_id, 6, "other"))
        self.assertIsNone(await db.claim_order("not-a-uuid", 6, "other"))
        await order.arefresh_from_db()
        self.assertEqual(order.telegram_id, 5)

    async def test_link_account_moves_telegram_id(self):
        user = await User.objects.acreate_user("bob", "b@b.ru", "x")
        profile = await Profile.objects.aget(user=user)
        self.assertTrue(await db.link_account(profile.link_token.hex, 99, "bob_tg"))
        await profile.arefresh_from_db()
        self.assertEqual(profile.telegram_id, 99)
        self.assertFalse(await db.link_account("zzz", 99, ""))

    async def test_set_status_validates_and_notifies(self):
        order = await Order.objects.acreate(name="A", description="x", telegram_id=5)
        self.assertIsNone(await db.set_status(order.pk, "bogus"))
        self.assertEqual(await db.set_status(order.pk, "done"), "Выполнен")
        note = await Notification.objects.aget(kind=Notification.Kind.CLIENT_STATUS)
        self.assertEqual(note.chat_id, 5)


class OutboxTests(TestCase):
    async def test_deliver_marks_sent_and_gives_up_on_forbidden(self):
        await Notification.objects.acreate(chat_id=1, kind="client_status", text="ok")
        await Notification.objects.acreate(chat_id=2, kind="client_status", text="blocked")
        bot = mock.AsyncMock()

        async def send(chat_id, text, reply_markup=None):
            if chat_id == 2:
                raise TelegramForbiddenError(method=mock.Mock(), message="bot was blocked")

        bot.send_message.side_effect = send
        self.assertEqual(await outbox.deliver_pending(bot), 1)

        ok = await Notification.objects.aget(chat_id=1)
        blocked = await Notification.objects.aget(chat_id=2)
        self.assertIsNotNone(ok.sent_at)
        self.assertIsNone(blocked.sent_at)
        self.assertEqual(blocked.attempts, db.MAX_ATTEMPTS)
        self.assertEqual(await outbox.deliver_pending(bot), 0)  # больше не повторяем
