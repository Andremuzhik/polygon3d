import re
import tempfile

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.views.defaults import server_error

from .models import Notification, Order, OrderMessage, PortfolioItem, Review, Service

User = get_user_model()

TELEGRAM = {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_ADMIN_IDS": [111, 222]}

ORDER_DATA = {
    "name": "Иван",
    "email": "ivan@example.com",
    "description": "Нужна модель робота для игры",
    "website": "",
}


class PublicPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            title="Персонажи", slug="characters", short_description="s", description="d"
        )
        cls.work = PortfolioItem.objects.create(
            title="Робот", slug="robot", category=PortfolioItem.Category.CHARACTER
        )
        Review.objects.create(author="Анна", text="Отлично", rating=4)

    def test_pages_render(self):
        for name, args in [
            ("home", []),
            ("services", []),
            ("service-detail", ["characters"]),
            ("portfolio", []),
            ("portfolio-detail", ["robot"]),
            ("reviews", []),
            ("contacts", []),
            ("order", []),
            ("login", []),
            ("register", []),
        ]:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_healthz(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual((response.status_code, response.content), (200, b"ok"))

    def test_hidden_items_are_404(self):
        Service.objects.filter(pk=self.service.pk).update(is_active=False)
        PortfolioItem.objects.filter(pk=self.work.pk).update(is_published=False)
        self.assertEqual(
            self.client.get(reverse("service-detail", args=["characters"])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("portfolio-detail", args=["robot"])).status_code, 404
        )

    def test_portfolio_category_filter(self):
        PortfolioItem.objects.create(
            title="Дом", slug="house", category=PortfolioItem.Category.ARCHITECTURE
        )
        response = self.client.get(reverse("portfolio"), {"category": "architecture"})
        self.assertEqual([w.slug for w in response.context["page"]], ["house"])

    def test_prefilled_service_from_query(self):
        response = self.client.get(reverse("order"), {"service": "characters"})
        self.assertEqual(response.context["form"].initial["service"], self.service)


@override_settings(**TELEGRAM)
class OrderFlowTests(TestCase):
    def test_site_order_creates_order_and_notifies_admins(self):
        response = self.client.post(reverse("order"), ORDER_DATA)
        order = Order.objects.get()
        self.assertRedirects(response, reverse("order-thanks", args=[order.public_id]))
        self.assertEqual(order.source, Order.Source.SITE)
        notes = Notification.objects.filter(kind=Notification.Kind.ADMIN_ORDER)
        self.assertEqual(sorted(notes.values_list("chat_id", flat=True)), [111, 222])
        self.assertIn(f"№{order.pk}", notes[0].text)

    def test_user_text_is_html_escaped_in_notifications(self):
        self.client.post(reverse("order"), {**ORDER_DATA, "description": "<b>boom</b> & more"})
        text = Notification.objects.first().text
        self.assertIn("&lt;b&gt;boom&lt;/b&gt; &amp; more", text)

    def test_contact_required(self):
        data = {**ORDER_DATA, "email": ""}
        response = self.client.post(reverse("order"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.exists())

    def test_honeypot_blocks_bots(self):
        response = self.client.post(reverse("order"), {**ORDER_DATA, "website": "http://spam"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.exists())

    def test_bad_file_extension_rejected(self):
        bad = SimpleUploadedFile("virus.exe", b"MZ")
        response = self.client.post(reverse("order"), {**ORDER_DATA, "reference_file": bad})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.exists())

    def test_status_change_notifies_client_only_when_linked(self):
        order = Order.objects.create(name="A", email="a@a.ru", description="x")
        order.status = Order.Status.IN_PROGRESS
        order.save()
        self.assertFalse(Notification.objects.filter(kind=Notification.Kind.CLIENT_STATUS).exists())

        order.telegram_id = 555
        order.status = Order.Status.DONE
        order.save()
        note = Notification.objects.get(kind=Notification.Kind.CLIENT_STATUS)
        self.assertEqual(note.chat_id, 555)
        self.assertIn("Выполнен", note.text)

    def test_saving_without_status_change_does_not_notify(self):
        order = Order.objects.create(name="A", email="a@a.ru", description="x", telegram_id=5)
        Notification.objects.all().delete()
        order.manager_note = "заметка"
        order.save()
        self.assertFalse(Notification.objects.exists())

    def test_messages_route_to_right_side(self):
        order = Order.objects.create(name="A", email="a@a.ru", description="x", telegram_id=555)
        Notification.objects.all().delete()
        OrderMessage.objects.create(order=order, sender=OrderMessage.Sender.CLIENT, text="привет")
        self.assertEqual(sorted(Notification.objects.values_list("chat_id", flat=True)), [111, 222])
        Notification.objects.all().delete()
        OrderMessage.objects.create(
            order=order, sender=OrderMessage.Sender.MANAGER, text="здравствуйте"
        )
        note = Notification.objects.get()
        self.assertEqual((note.chat_id, note.kind), (555, Notification.Kind.CLIENT_MESSAGE))

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_no_notifications_when_bot_not_configured(self):
        self.client.post(reverse("order"), ORDER_DATA)
        self.assertFalse(Notification.objects.exists())


class CabinetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "alice@example.com", "pass-12345-x")
        cls.bob = User.objects.create_user("bob", "bob@example.com", "pass-12345-x")
        cls.order = Order.objects.create(
            user=cls.alice, name="Alice", email="a@a.ru", description="x"
        )

    def test_profile_created_with_user(self):
        self.assertTrue(hasattr(self.alice, "profile"))

    def test_login_required(self):
        response = self.client.get(reverse("cabinet"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_cannot_open_foreign_order(self):
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(reverse("cabinet-order", args=[self.order.pk])).status_code, 404
        )

    def test_owner_can_write_message(self):
        self.client.force_login(self.alice)
        url = reverse("cabinet-order", args=[self.order.pk])
        self.client.post(url, {"text": "Вопрос по сроку"})
        message = self.order.messages.get()
        self.assertEqual((message.sender, message.text), ("client", "Вопрос по сроку"))

    def test_order_from_cabinet_is_linked_to_user(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("order"), ORDER_DATA)
        self.assertEqual(Order.objects.filter(user=self.alice).count(), 2)

    def test_reference_file_is_private(self):
        order = Order.objects.create(
            user=self.alice,
            name="A",
            email="a@a.ru",
            description="x",
            reference_file=SimpleUploadedFile("ref.png", b"png-bytes"),
        )
        url = reverse("order-file", args=[order.pk])
        self.assertEqual(self.client.get(url).status_code, 302)  # аноним → логин
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(url).status_code, 200)
        staff = User.objects.create_user("staff", "s@s.ru", "pass-12345-x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_unlink_telegram(self):
        profile = self.alice.profile
        profile.telegram_id = 42
        profile.save()
        self.client.force_login(self.alice)
        self.client.post(reverse("telegram-unlink"))
        profile.refresh_from_db()
        self.assertIsNone(profile.telegram_id)

    def test_registration_logs_user_in(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "newbie",
                "email": "new@example.com",
                "password1": "very-Strong-pass-77",
                "password2": "very-Strong-pass-77",
            },
        )
        self.assertRedirects(response, reverse("cabinet"))
        self.assertTrue(User.objects.filter(username="newbie").exists())


class SeedDemoTests(TestCase):
    def test_seed_attaches_assets_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            call_command("seed_demo", verbosity=0)
            call_command("seed_demo", verbosity=0)

            works = PortfolioItem.objects.all()
            self.assertEqual(works.count(), 6)
            self.assertTrue(all(w.image and w.model_file for w in works))
            self.assertTrue(all(s.image for s in Service.objects.all()))
            self.assertEqual(Review.objects.count(), 3)


class PasswordResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", "alice@example.com", "old-pass-12345")

    def test_login_page_links_to_reset(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, reverse("password_reset"))

    def test_full_reset_flow(self):
        response = self.client.post(reverse("password_reset"), {"email": "alice@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["alice@example.com"])
        self.assertIn("Восстановление пароля", message.subject)
        self.assertIn("alice", message.body)
        link = re.search(r"https?://[^/\s]+(/accounts/reset/\S+)", message.body).group(1)

        form_page = self.client.get(link, follow=True)
        self.assertContains(form_page, "Новый пароль")
        form_url = form_page.redirect_chain[-1][0]
        new_password = "brand-New-pass-91"
        done = self.client.post(
            form_url, {"new_password1": new_password, "new_password2": new_password}
        )
        self.assertRedirects(done, reverse("password_reset_complete"))

        self.assertTrue(self.client.login(username="alice", password=new_password))
        self.client.logout()
        self.assertFalse(self.client.login(username="alice", password="old-pass-12345"))

    def test_link_is_single_use(self):
        self.client.post(reverse("password_reset"), {"email": "alice@example.com"})
        link = re.search(r"(/accounts/reset/\S+)", mail.outbox[0].body).group(1)
        form_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        password = "brand-New-pass-91"
        self.client.post(form_url, {"new_password1": password, "new_password2": password})

        reused = self.client.get(link, follow=True)

        self.assertContains(reused, "Ссылка недействительна")

    def test_unknown_email_does_not_leak_account_existence(self):
        response = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(mail.outbox, [])

    def test_bad_token(self):
        response = self.client.get("/accounts/reset/MQ/bad-token/", follow=True)
        self.assertContains(response, "Ссылка недействительна")


class SeoAndErrorPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            title="Видимая", slug="visible", short_description="s", description="d"
        )
        Service.objects.create(
            title="Скрытая", slug="hidden", short_description="s", description="d", is_active=False
        )
        cls.work = PortfolioItem.objects.create(
            title="Опубликованная", slug="shown", category=PortfolioItem.Category.PRINT
        )
        PortfolioItem.objects.create(
            title="Черновик",
            slug="draft",
            category=PortfolioItem.Category.PRINT,
            is_published=False,
        )

    def test_robots_txt(self):
        response = self.client.get(reverse("robots"))
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertContains(response, "Disallow: /admin/")
        self.assertContains(response, "Disallow: /cabinet/")
        self.assertContains(response, "Sitemap: http://testserver/sitemap.xml")

    def test_sitemap_lists_only_public_pages(self):
        body = self.client.get(reverse("sitemap")).content.decode()
        self.assertIn("http://testserver/services/visible/", body)
        self.assertIn("http://testserver/portfolio/shown/", body)
        self.assertIn("http://testserver/order/", body)
        self.assertNotIn("hidden", body)
        self.assertNotIn("draft", body)
        self.assertNotIn("/admin/", body)
        self.assertNotIn("/cabinet/", body)

    def test_open_graph_defaults(self):
        body = self.client.get(reverse("home")).content.decode()
        self.assertIn(
            'property="og:image" content="http://testserver/static/img/og-cover.png"', body
        )
        self.assertIn('rel="canonical" href="http://testserver/"', body)
        self.assertIn('rel="icon"', body)

    def test_detail_pages_override_open_graph(self):
        service = self.client.get(self.service.get_absolute_url()).content.decode()
        self.assertIn('property="og:title" content="Видимая — Polygon3D"', service)
        self.assertIn("og-cover.png", service)  # у услуги нет картинки → запасная

        work = self.client.get(self.work.get_absolute_url()).content.decode()
        self.assertIn('property="og:title" content="Опубликованная — Polygon3D"', work)
        self.assertIn("Модели для 3D-печати", work)

    def test_custom_404(self):
        response = self.client.get("/no-such-page/")
        self.assertContains(response, "Такой страницы нет", status_code=404)
        self.assertContains(response, "На главную", status_code=404)

    def test_custom_500_is_standalone(self):
        request = RequestFactory().get("/boom/")
        response = server_error(request)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Что-то пошло не так", response.content.decode())
