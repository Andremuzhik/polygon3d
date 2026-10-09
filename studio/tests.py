import csv
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
        self.assertEqual(self.client.get(url).status_code, 302)
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
        self.assertIn("og-cover.png", service)

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


@override_settings(TELEGRAM_BOT_TOKEN="")
class ThrottleTests(TestCase):
    def post_order(self, ip="10.0.0.1", **extra):
        return self.client.post(reverse("order"), ORDER_DATA, REMOTE_ADDR=ip, **extra)

    def test_order_form_is_limited_per_ip(self):
        for _ in range(8):
            self.assertEqual(self.post_order().status_code, 302)

        blocked = self.post_order()

        self.assertContains(blocked, "Слишком много попыток", status_code=429)
        self.assertEqual(Order.objects.count(), 8)

    def test_other_ip_is_not_affected(self):
        for _ in range(9):
            self.post_order("10.0.0.1")
        self.assertEqual(self.post_order("10.0.0.2").status_code, 302)

    def test_get_requests_are_never_limited(self):
        for _ in range(30):
            self.assertEqual(
                self.client.get(reverse("order"), REMOTE_ADDR="10.0.0.1").status_code, 200
            )

    def test_window_expiry_reopens_the_gate(self):
        from django.core.cache import cache

        for _ in range(9):
            self.post_order()
        self.assertEqual(self.post_order().status_code, 429)

        cache.delete("throttle:order:10.0.0.1")  # то же, что истечение окна

        self.assertEqual(self.post_order().status_code, 302)

    def test_forwarded_header_ignored_without_proxy(self):
        for i in range(9):  # злоумышленник подделывает заголовок, чтобы обойти лимит
            self.post_order(HTTP_X_FORWARDED_FOR=f"1.2.3.{i}")
        self.assertEqual(self.post_order(HTTP_X_FORWARDED_FOR="9.9.9.9").status_code, 429)

    @override_settings(BEHIND_PROXY=True)
    def test_forwarded_header_used_behind_proxy(self):
        for _ in range(9):
            self.post_order("172.18.0.5", HTTP_X_FORWARDED_FOR="203.0.113.7")
        # тот же адрес прокси, но другой клиент — лимит у него свой
        self.assertEqual(
            self.post_order("172.18.0.5", HTTP_X_FORWARDED_FOR="203.0.113.8").status_code, 302
        )
        # клиент не сбросит счётчик, дописав свой адрес: берётся последний, добавленный прокси
        self.assertEqual(
            self.post_order("172.18.0.5", HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.7").status_code,
            429,
        )

    def test_login_is_limited(self):
        data = {"username": "nobody", "password": "wrong"}
        for _ in range(10):
            self.assertEqual(
                self.client.post(reverse("login"), data, REMOTE_ADDR="10.1.1.1").status_code, 200
            )
        self.assertEqual(
            self.client.post(reverse("login"), data, REMOTE_ADDR="10.1.1.1").status_code, 429
        )

    def test_password_reset_and_register_are_limited(self):
        for _ in range(5):
            self.client.post(reverse("password_reset"), {"email": "a@a.ru"}, REMOTE_ADDR="10.2.2.2")
        blocked = self.client.post(
            reverse("password_reset"), {"email": "a@a.ru"}, REMOTE_ADDR="10.2.2.2"
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(len(mail.outbox), 0)

        for _ in range(8):
            self.client.post(reverse("register"), {}, REMOTE_ADDR="10.3.3.3")
        self.assertEqual(
            self.client.post(reverse("register"), {}, REMOTE_ADDR="10.3.3.3").status_code, 429
        )


def make_image(size=(3000, 2000), mode="RGB", color=(200, 30, 30), fmt="PNG", name="photo.png"):
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


class ImageOptimizationTests(TestCase):
    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        self._override = override_settings(MEDIA_ROOT=self._media.name)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def open_saved(self, field):
        from PIL import Image

        with Image.open(field.path) as image:
            return image.format, image.size, image.mode

    def test_large_upload_becomes_small_jpeg(self):
        original = make_image()
        work = PortfolioItem.objects.create(title="W", slug="w", category="print", image=original)

        self.assertTrue(work.image.name.endswith("photo.jpg"))
        fmt, size, mode = self.open_saved(work.image)
        self.assertEqual((fmt, mode), ("JPEG", "RGB"))
        self.assertEqual(max(size), 1600)
        self.assertEqual(size, (1600, 1067))
        self.assertLess(work.image.size, original.size)

    def test_small_image_is_not_upscaled(self):
        service = Service.objects.create(
            title="S",
            slug="s",
            short_description="s",
            description="d",
            image=make_image(size=(400, 300)),
        )
        self.assertEqual(self.open_saved(service.image)[1], (400, 300))

    def test_transparency_is_flattened_to_white(self):
        from PIL import Image

        service = Service.objects.create(
            title="S",
            slug="s",
            short_description="s",
            description="d",
            image=make_image(size=(50, 50), mode="RGBA", color=(0, 0, 0, 0)),
        )
        with Image.open(service.image.path) as image:
            r, g, b = image.getpixel((25, 25))
        self.assertGreater(min(r, g, b), 245)

    def test_resaving_does_not_recompress(self):
        service = Service.objects.create(
            title="S", slug="s", short_description="s", description="d", image=make_image()
        )
        name, mtime = (
            service.image.name,
            service.image.storage.get_modified_time(service.image.name),
        )

        service.title = "Новое имя"
        service.save()

        self.assertEqual(service.image.name, name)
        self.assertEqual(service.image.storage.get_modified_time(name), mtime)

    def test_broken_image_is_kept_untouched(self):
        broken = SimpleUploadedFile("broken.png", b"not an image at all", content_type="image/png")
        service = Service.objects.create(
            title="S", slug="s", short_description="s", description="d", image=broken
        )
        self.assertTrue(service.image.name.endswith("broken.png"))


class SecurityHeadersTests(TestCase):
    def test_site_pages_get_csp_and_permissions_policy(self):
        response = self.client.get(reverse("home"))
        csp = response["Content-Security-Policy"]
        self.assertIn("script-src 'self' 'wasm-unsafe-eval'", csp)
        self.assertNotIn("'unsafe-eval'", csp.replace("'wasm-unsafe-eval'", ""))
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("camera=()", response["Permissions-Policy"])

    def test_admin_keeps_django_defaults(self):
        response = self.client.get("/admin/login/")
        self.assertNotIn("Content-Security-Policy", response)
        self.assertIn("Permissions-Policy", response)

    @override_settings(DEBUG=True)
    def test_debug_error_pages_are_not_restricted(self):
        self.assertNotIn("Content-Security-Policy", self.client.get("/no-such-page/"))

    def test_pages_have_no_inline_scripts_or_handlers(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            PortfolioItem.objects.create(
                title="3D",
                slug="viewer",
                category="print",
                model_file=SimpleUploadedFile("m.glb", b"glTF" + b"\0" * 20),
            )
            user = User.objects.create_user("u", "u@example.com", "pass-12345-x")
            self.client.force_login(user)
            for url in [
                reverse("home"),
                reverse("services"),
                reverse("portfolio"),
                reverse("portfolio-detail", args=["viewer"]),
                reverse("order"),
                reverse("cabinet"),
                reverse("contacts"),
                reverse("reviews"),
                "/no-such-page/",
            ]:
                with self.subTest(url):
                    html = self.client.get(url).content.decode()
                    self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)", html), "inline <script>")
                    self.assertIsNone(re.search(r"\son\w+=", html), "inline event handler")

    def test_model_viewer_is_served_locally(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            PortfolioItem.objects.create(
                title="3D",
                slug="viewer",
                category="print",
                model_file=SimpleUploadedFile("m.glb", b"glTF" + b"\0" * 20),
            )
            html = self.client.get(reverse("portfolio-detail", args=["viewer"])).content.decode()
        self.assertIn("/static/vendor/model-viewer/model-viewer.min.js", html)
        self.assertNotIn("unpkg.com", html)


class ViewerAndAccessibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = Service.objects.create(
            title="Услуга", slug="svc", short_description="s", description="d"
        )
        cls.plain = PortfolioItem.objects.create(title="Без 3D", slug="plain", category="print")

    def test_3d_work_shows_a_lazy_facade_instead_of_loading_the_viewer(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            work = PortfolioItem.objects.create(
                title="С 3D",
                slug="with-3d",
                category="print",
                model_file=SimpleUploadedFile("m.glb", b"glTF" + b"\0" * 20),
            )
            html = self.client.get(work.get_absolute_url()).content.decode()
        self.assertIn("data-viewer-start", html)
        self.assertIn(f'data-src="{work.model_file.url}"', html)
        self.assertIn("/static/vendor/model-viewer/model-viewer.min.js", html)
        self.assertNotIn('<script type="module"', html)
        self.assertNotIn("<model-viewer", html)

    def test_work_without_model_has_no_viewer_controls(self):
        html = self.client.get(self.plain.get_absolute_url()).content.decode()
        self.assertNotIn("data-viewer", html)
        self.assertNotIn("Крутить модель", html)

    def test_list_pages_do_not_skip_heading_levels(self):
        for url in (reverse("services"), reverse("portfolio")):
            with self.subTest(url):
                html = self.client.get(url).content.decode()
                self.assertIn("<h2>", html)
                self.assertNotIn("<h3>", html)

    def test_home_cards_stay_h3_under_section_headings(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("<h3>", html)

    def test_layout_landmarks_and_skip_link(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn('class="skip-link" href="#main"', html)
        self.assertIn('<main id="main">', html)
        self.assertIn('aria-controls="site-nav"', html)
        self.assertIn('name="theme-color"', html)


class UploadContentTests(TestCase):
    """Файлы проверяются по содержимому, а не только по расширению."""

    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name, TELEGRAM_BOT_TOKEN="")
        override.enable()
        self.addCleanup(override.disable)

    def submit(self, upload):
        # у каждой отправки свой IP, чтобы тест не упирался в лимит частоты заявок
        self._ip_counter = getattr(self, "_ip_counter", 0) + 1
        return self.client.post(
            reverse("order"),
            {**ORDER_DATA, "reference_file": upload},
            REMOTE_ADDR=f"10.77.0.{self._ip_counter}",
        )

    def accepted(self, name, content):
        response = self.submit(SimpleUploadedFile(name, content))
        self.assertEqual(response.status_code, 302, f"{name} должен приниматься")
        return Order.objects.latest("pk")

    def rejected(self, name, content):
        before = Order.objects.count()
        response = self.submit(SimpleUploadedFile(name, content))
        self.assertEqual(response.status_code, 200, f"{name} должен отклоняться")
        self.assertContains(response, "не соответствует его расширению")
        self.assertEqual(Order.objects.count(), before)

    def test_real_files_are_accepted(self):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("model.obj", "v 0 0 0")
        self.accepted("sketch.png", make_image(size=(20, 20)).read())
        self.accepted("sketch.jpg", make_image(size=(20, 20), fmt="JPEG", name="x.jpg").read())
        self.accepted("brief.pdf", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")
        self.accepted("pack.zip", buffer.getvalue())
        self.accepted("scene.glb", b"glTF\x02\x00\x00\x00" + b"\0" * 16)
        self.accepted("model.obj", b"# exported\nv 0 0 0\nv 1 0 0\nf 1 2 1\n")
        self.accepted("part.stl", b"solid cube\n facet normal 0 0 1\nendsolid cube\n")
        self.accepted("binary.stl", bytes(80) + b"\x01\x00\x00\x00" + bytes(50))
        self.accepted("rig.fbx", b"Kaydara FBX Binary  \x00\x1a\x00" + bytes(30))
        self.accepted("ascii.fbx", b"; FBX 7.4.0 project file\n")

    def test_renamed_executables_are_rejected(self):
        self.rejected("photo.png", b"MZ\x90\x00\x03\x00\x00\x00 windows executable")
        self.rejected("photo.jpg", b"\x7fELF\x02\x01\x01 linux executable")

    def test_wrong_format_behind_a_valid_extension_is_rejected(self):
        self.rejected("brief.pdf", make_image(size=(10, 10)).read())  # PNG под видом PDF
        self.rejected("pack.zip", b"just some text, not an archive")
        self.rejected("scene.glb", b"<html><script>alert(1)</script></html>")
        self.rejected("rig.fbx", b"MZ not an fbx at all")

    def test_markup_and_scripts_disguised_as_text_formats_are_rejected(self):
        self.rejected("model.obj", b"<script>alert(document.cookie)</script>")
        self.rejected("model.obj", b"  <!DOCTYPE html><html></html>")
        self.rejected("part.stl", b"<?php system($_GET['c']); ?>")
        self.rejected("part.stl", b"#!/bin/sh\nrm -rf /\n")

    def test_stream_position_is_reset_after_check(self):
        order = self.accepted("brief.pdf", b"%PDF-1.4\nbody-of-the-file")
        self.assertEqual(order.reference_file.read(), b"%PDF-1.4\nbody-of-the-file")

    def test_portfolio_model_validation(self):
        from django.core.exceptions import ValidationError

        def check(name, content):
            item = PortfolioItem(title="T", slug="t", category="print")
            item.model_file = SimpleUploadedFile(name, content)
            item.full_clean(exclude=["image"])

        check("ok.glb", b"glTF\x02\x00\x00\x00" + b"\0" * 16)
        check("ok.gltf", b'  {"asset": {"version": "2.0"}}')
        for name, content in [
            ("fake.glb", b"<html></html>"),
            ("fake.gltf", b"MZ binary"),
            ("fake.glb", b"MZ\x90\x00 binary"),
        ]:
            with self.subTest(name, content=content[:6]), self.assertRaises(ValidationError):
                check(name, content)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


@override_settings(TELEGRAM_BOT_TOKEN="test-token", TELEGRAM_ADMIN_IDS=[111])
class DeliveryTests(TestCase):
    """Сдача результата: файлы, согласование, правки."""

    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.alice = User.objects.create_user("alice", "alice@example.com", "pass-12345-x")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pass-12345-x")
        self.order = Order.objects.create(
            user=self.alice,
            name="Alice",
            email="alice@example.com",
            description="x",
            status=Order.Status.IN_PROGRESS,
            telegram_id=555,
        )
        Notification.objects.all().delete()

    def deliver(self, order=None, name="render.png", content=PNG_BYTES, **extra):
        from .models import OrderDelivery

        return OrderDelivery.objects.create(
            order=order or self.order, file=SimpleUploadedFile(name, content), **extra
        )

    def test_delivery_sends_order_to_review_with_a_single_notification(self):
        self.deliver(title="Рендеры v1", note="Первый вариант")

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REVIEW)
        note = Notification.objects.get()
        self.assertEqual((note.kind, note.chat_id), (Notification.Kind.CLIENT_DELIVERY, 555))
        self.assertIn("Рендеры v1", note.text)
        self.assertIn("Первый вариант", note.text)

    def test_delivery_does_not_reopen_finished_orders(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.DONE)
        self.deliver()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DONE)

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_status_moves_to_review_even_without_telegram(self):
        self.deliver()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REVIEW)
        self.assertFalse(Notification.objects.exists())

    def test_display_title_falls_back_to_file_name(self):
        delivery = self.deliver(name="scene.glb", content=b"glTF" + b"\0" * 8)
        self.assertTrue(delivery.display_title.startswith("scene"))
        self.assertTrue(delivery.filename.endswith(".glb"))

    def test_download_permissions(self):
        delivery = self.deliver(title="Файл")
        url = reverse("delivery-download", args=[delivery.pk])
        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.alice)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), PNG_BYTES)

        staff = User.objects.create_user("staff", "s@s.ru", "pass-12345-x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_cabinet_shows_files_and_review_panel_only_in_review(self):
        self.deliver(title="Рендеры v1")
        self.client.force_login(self.alice)
        page = self.client.get(reverse("cabinet-order", args=[self.order.pk]))
        self.assertContains(page, "Рендеры v1")
        self.assertContains(page, "Принять работу")
        self.assertContains(page, "Запросить правки")

        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.DONE)
        page = self.client.get(reverse("cabinet-order", args=[self.order.pk]))
        self.assertContains(page, "Рендеры v1")
        self.assertNotContains(page, "Принять работу")

    def test_accept_marks_done_and_notifies_managers(self):
        self.deliver()
        Notification.objects.all().delete()
        self.client.force_login(self.alice)

        response = self.client.post(reverse("order-accept", args=[self.order.pk]))

        self.assertRedirects(response, reverse("cabinet-order", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DONE)
        kinds = set(Notification.objects.values_list("kind", flat=True))
        self.assertEqual(kinds, {Notification.Kind.CLIENT_STATUS, Notification.Kind.ADMIN_EVENT})
        admin_note = Notification.objects.get(kind=Notification.Kind.ADMIN_EVENT)
        self.assertEqual(admin_note.chat_id, 111)

    def test_accept_requires_review_status_owner_and_post(self):
        url = reverse("order-accept", args=[self.order.pk])
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.IN_PROGRESS)

        self.deliver()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REVIEW)

    def test_revision_returns_order_to_work_and_counts(self):
        self.deliver()
        self.client.force_login(self.alice)
        url = reverse("order-revision", args=[self.order.pk])

        self.client.post(url, {"text": "Сделайте глаза больше"})

        self.order.refresh_from_db()
        self.assertEqual(
            (self.order.status, self.order.revisions_used), (Order.Status.IN_PROGRESS, 1)
        )
        message = self.order.messages.get()
        self.assertEqual(message.sender, OrderMessage.Sender.CLIENT)
        self.assertIn("правка 1 из 2", message.text)
        self.assertIn("Сделайте глаза больше", message.text)
        self.assertTrue(
            Notification.objects.filter(kind=Notification.Kind.ADMIN_MESSAGE, chat_id=111).exists()
        )

    def test_revisions_beyond_the_included_ones_are_flagged(self):
        self.client.force_login(self.alice)
        url = reverse("order-revision", args=[self.order.pk])
        for i in range(3):
            self.deliver(title=f"v{i}")
            Order.objects.filter(pk=self.order.pk).update(status=Order.Status.REVIEW)
            self.client.post(url, {"text": f"Правка {i}"})

        texts = list(self.order.messages.values_list("text", flat=True))
        self.assertIn("правка 3, сверх 2 включённых", texts[-1])
        self.assertIn("правка 2 из 2", texts[1])

    def test_revision_needs_text_review_status_and_owner(self):
        url = reverse("order-revision", args=[self.order.pk])
        self.client.force_login(self.alice)
        self.client.post(url, {"text": "Правка вне согласования"})
        self.assertFalse(self.order.messages.exists())

        self.deliver()
        self.client.post(url, {"text": "  "})
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.revisions_used), (Order.Status.REVIEW, 0))

        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url, {"text": "чужой заказ"}).status_code, 404)

    def test_delivery_files_are_validated_by_content(self):
        from django.core.exceptions import ValidationError

        from .models import OrderDelivery

        def check(name, content):
            delivery = OrderDelivery(order=self.order, file=SimpleUploadedFile(name, content))
            delivery.full_clean()

        check("scene.blend", b"BLENDER-v400" + b"\0" * 16)
        check("renders.zip", b"PK\x03\x04" + b"\0" * 16)
        for name, content in [
            ("scene.blend", b"MZ\x90 not blender"),
            ("tool.exe", b"MZ\x90"),
            ("a.png", b"<html>"),
        ]:
            with self.subTest(name), self.assertRaises(ValidationError):
                check(name, content)


class OrderEventTests(TestCase):
    def setUp(self):
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        override = override_settings(MEDIA_ROOT=self._media.name, TELEGRAM_BOT_TOKEN="")
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user("alice", "alice@example.com", "pass-12345-x")
        self.order = Order.objects.create(user=self.user, name="Alice", description="x")

    def events(self):
        return list(self.order.events.values_list("kind", "text"))

    def test_creation_is_logged(self):
        self.assertEqual(self.events(), [("created", "Заказ создан (Сайт)")])

    def test_status_change_is_logged_with_labels_and_target_status(self):
        self.order.status = Order.Status.IN_PROGRESS
        self.order.save()
        event = self.order.events.get(kind="status")
        self.assertEqual(event.text, "Статус: Новый → В работе")
        self.assertEqual(event.to_status, "in_progress")

    def test_saving_without_status_change_logs_nothing(self):
        self.order.manager_note = "заметка"
        self.order.save()
        self.assertEqual(len(self.events()), 1)

    def test_messages_are_logged_by_sender(self):
        OrderMessage.objects.create(order=self.order, sender="client", text="вопрос")
        OrderMessage.objects.create(order=self.order, sender="manager", text="ответ")
        texts = [t for k, t in self.events() if k == "message"]
        self.assertEqual(texts, ["Сообщение от клиента", "Сообщение от менеджера"])
        self.assertNotIn(
            "вопрос", "".join(t for _, t in self.events())
        )  # текст переписки в журнал не копируется

    def test_delivery_logs_result_and_status_move(self):
        from .models import OrderDelivery

        self.order.status = Order.Status.IN_PROGRESS
        self.order.save()
        OrderDelivery.objects.create(
            order=self.order, title="Рендеры v1", file=SimpleUploadedFile("r.png", PNG_BYTES)
        )
        events = self.events()
        self.assertIn(("delivery", "Загружен результат: Рендеры v1"), events)
        self.assertIn(("status", "Статус: В работе → На согласовании"), events)

    def test_second_delivery_does_not_repeat_status_event(self):
        from .models import OrderDelivery

        for name in ("a.png", "b.png"):
            OrderDelivery.objects.create(order=self.order, file=SimpleUploadedFile(name, PNG_BYTES))
        self.assertEqual(self.order.events.filter(kind="status").count(), 1)
        self.assertEqual(self.order.events.filter(kind="delivery").count(), 2)

    def test_revision_is_one_event_without_duplicate_message_event(self):
        from . import services

        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.REVIEW)
        services.request_revision(self.order, "Сделайте ярче")
        kinds = [k for k, _ in self.events()]
        self.assertEqual(kinds.count("revision"), 1)
        self.assertEqual(kinds.count("message"), 0)
        self.assertIn(("revision", "Клиент запросил правки (правка 1 из 2)"), self.events())

    def test_acceptance_is_logged_as_status_change(self):
        from . import services

        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.REVIEW)
        services.accept_order(self.order)
        self.assertIn(("status", "Статус: На согласовании → Выполнен"), self.events())

    def test_cabinet_and_admin_show_the_history(self):
        self.order.status = Order.Status.IN_PROGRESS
        self.order.save()
        self.client.force_login(self.user)
        page = self.client.get(reverse("cabinet-order", args=[self.order.pk]))
        self.assertContains(page, "История заказа")
        self.assertContains(page, "Статус: Новый → В работе")

        staff = User.objects.create_superuser("boss", "b@b.ru", "pass-12345-x")
        self.client.force_login(staff)
        admin_page = self.client.get(f"/admin/studio/order/{self.order.pk}/change/")
        self.assertContains(admin_page, "Статус: Новый → В работе")


class EmailNotificationTests(TestCase):
    def setUp(self):
        override = override_settings(
            TELEGRAM_BOT_TOKEN="", SITE_URL="https://site.test", SITE_NAME="Polygon3D"
        )
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user("alice", "alice@example.com", "pass-12345-x")
        self.order = Order.objects.create(
            user=self.user, name="Алиса", email="alice@example.com", description="x"
        )
        mail.outbox.clear()

    def test_confirmation_for_a_new_order(self):
        Order.objects.create(name="Гость", email="guest@example.com", description="x")
        message = mail.outbox[0]
        self.assertEqual(message.to, ["guest@example.com"])
        self.assertIn("заявка №", message.subject)
        self.assertIn("Здравствуйте, Гость!", message.body)
        self.assertNotIn("/cabinet/", message.body)

    def test_cabinet_link_only_for_registered_clients(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.NEW)
        self.order.status = Order.Status.IN_PROGRESS
        self.order.save()
        body = mail.outbox[0].body
        self.assertIn(f"https://site.test/cabinet/orders/{self.order.pk}/", body)

    def test_status_change_email(self):
        self.order.status = Order.Status.IN_PROGRESS
        self.order.save()
        message = mail.outbox[0]
        self.assertIn("«В работе»", message.subject)
        self.assertIn("изменён на «В работе»", message.body)

    def test_manager_message_is_emailed_but_client_message_is_not(self):
        OrderMessage.objects.create(order=self.order, sender="client", text="мой вопрос")
        self.assertEqual(mail.outbox, [])
        OrderMessage.objects.create(
            order=self.order, sender="manager", text="Ответ <менеджера> & ко"
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            "Ответ <менеджера> & ко", mail.outbox[0].body
        )  # обычный текст, без HTML-экранирования

    def test_delivery_email(self):
        from .models import OrderDelivery

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            OrderDelivery.objects.create(
                order=self.order, title="Рендеры v1", file=SimpleUploadedFile("r.png", PNG_BYTES)
            )
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any("готов результат" in s for s in subjects))
        self.assertIn("Рендеры v1", mail.outbox[0].body)

    def test_nothing_is_sent_without_an_address(self):
        order = Order.objects.create(name="Из бота", description="x", telegram_id=7)
        order.status = Order.Status.DONE
        order.save()
        self.assertEqual(mail.outbox, [])

    @override_settings(EMAIL_NOTIFICATIONS=False)
    def test_can_be_switched_off(self):
        self.order.status = Order.Status.DONE
        self.order.save()
        Order.objects.create(name="Гость", email="g@example.com", description="x")
        self.assertEqual(mail.outbox, [])

    def test_mail_failure_does_not_break_saving(self):
        from smtplib import SMTPException
        from unittest import mock

        with (
            mock.patch("studio.notifications.send_mail", side_effect=SMTPException("down")),
            self.assertLogs("studio.notifications", level="ERROR"),
        ):
            self.order.status = Order.Status.DONE
            self.order.save()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DONE)


class DashboardStatsTests(TestCase):
    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        self.now = timezone.now()
        self.ago = lambda **kw: self.now - timedelta(**kw)
        self.timedelta = timedelta
        override = override_settings(TELEGRAM_BOT_TOKEN="", EMAIL_NOTIFICATIONS=False)
        override.enable()
        self.addCleanup(override.disable)

    def make(self, status=Order.Status.NEW, created=None, **kwargs):
        kwargs.setdefault("name", "Клиент")
        order = Order.objects.create(description="x", status=status, **kwargs)
        if created:
            Order.objects.filter(pk=order.pk).update(created_at=created)
            order.refresh_from_db()
        return order

    def test_empty_database_does_not_break_anything(self):
        from .dashboard import dashboard_stats

        stats = dashboard_stats()
        self.assertEqual(
            (stats["total"], stats["completion_rate"], stats["average_days"]), (0, 0, None)
        )
        self.assertEqual(len(stats["months"]), 6)
        self.assertTrue(all(m["count"] == 0 and m["height"] == 0 for m in stats["months"]))
        self.assertEqual(stats["recent"], [])

    def test_counts_statuses_sources_and_attention_flags(self):
        from .dashboard import dashboard_stats

        service = Service.objects.create(
            title="Роботы", slug="r", short_description="s", description="d"
        )
        self.make(Order.Status.NEW, created=self.ago(days=2))
        self.make(Order.Status.NEW)
        self.make(Order.Status.IN_PROGRESS, service=service, source=Order.Source.BOT)
        self.make(Order.Status.REVIEW, service=service)
        self.make(Order.Status.DONE)
        self.make(Order.Status.CANCELLED)

        stats = dashboard_stats()

        self.assertEqual(stats["total"], 6)
        by_code = {s["code"]: s["count"] for s in stats["statuses"]}
        self.assertEqual(
            by_code, {"new": 2, "in_progress": 1, "review": 1, "done": 1, "cancelled": 1}
        )
        self.assertEqual(stats["stale_new"], 1)
        self.assertEqual(stats["waiting_client"], 1)
        self.assertEqual(stats["completion_rate"], 17)
        self.assertEqual(
            {s["label"]: s["count"] for s in stats["sources"]}, {"Сайт": 5, "Telegram-бот": 1}
        )
        self.assertEqual(stats["top_services"], [{"service__title": "Роботы", "n": 2}])
        self.assertEqual(len(stats["recent"]), 6)

    def test_average_lead_time_comes_from_the_event_log(self):
        from .dashboard import dashboard_stats

        order = self.make(created=self.ago(days=10))
        order.status = Order.Status.DONE
        order.save()
        order.events.filter(to_status="done").update(created_at=self.ago(days=6))
        other = self.make(created=self.ago(days=5))
        other.status = Order.Status.DONE
        other.save()
        other.events.filter(to_status="done").update(created_at=self.ago(days=1))

        self.assertEqual(dashboard_stats()["average_days"], 4.0)

    def test_orders_are_bucketed_by_month_with_zero_fill(self):
        from .dashboard import dashboard_stats

        self.make(created=self.ago(days=95))
        self.make(created=self.ago(days=95))
        self.make()
        stats = dashboard_stats(self.now)

        counts = [m["count"] for m in stats["months"]]
        self.assertEqual(sum(counts), 3)
        self.assertEqual(counts[-1], 1)
        self.assertEqual(max(m["height"] for m in stats["months"]), 100)
        self.assertEqual(stats["created_this_month"], 1)

    def test_done_this_month_counts_each_order_once(self):
        from .dashboard import dashboard_stats

        order = self.make()
        for status in (Order.Status.DONE, Order.Status.IN_PROGRESS, Order.Status.DONE):
            order.status = status
            order.save()
        self.assertEqual(dashboard_stats()["done_this_month"], 1)

    def test_admin_index_shows_dashboard_only_to_those_who_may_see_orders(self):
        self.make(name="Заметный клиент")
        boss = User.objects.create_superuser("boss", "b@b.ru", "pass-12345-x")
        self.client.force_login(boss)
        page = self.client.get("/admin/")
        self.assertContains(page, "Всего заказов")
        self.assertContains(page, "Последние заказы")
        self.assertContains(page, "Заметный клиент")

        clerk = User.objects.create_user("clerk", "c@b.ru", "pass-12345-x", is_staff=True)
        self.client.force_login(clerk)
        self.assertNotContains(self.client.get("/admin/"), "Всего заказов")

        self.client.logout()
        self.assertEqual(self.client.get("/admin/").status_code, 302)


class OrderCsvExportTests(TestCase):
    def setUp(self):
        override = override_settings(TELEGRAM_BOT_TOKEN="", EMAIL_NOTIFICATIONS=False)
        override.enable()
        self.addCleanup(override.disable)
        self.boss = User.objects.create_superuser("boss", "b@b.ru", "pass-12345-x")
        self.client.force_login(self.boss)

    def export(self, *orders):
        return self.client.post(
            reverse("admin:studio_order_changelist"),
            {"action": "export_csv", "_selected_action": [o.pk for o in orders]},
        )

    def test_csv_has_bom_headers_and_data(self):
        service = Service.objects.create(
            title="Роботы", slug="r", short_description="s", description="d"
        )
        order = Order.objects.create(
            name="Иван",
            email="i@example.com",
            phone="+7 900 111-22-33",
            telegram_username="ivan",
            service=service,
            budget="15 000 ₽",
            description="Строка 1\nСтрока 2",
        )

        response = self.export(order)

        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("orders.csv", response["Content-Disposition"])
        text = response.content.decode("utf-8")
        self.assertTrue(text.startswith("﻿"))
        rows = list(csv.reader(text.lstrip("﻿").splitlines(keepends=True), delimiter=";"))
        self.assertEqual(rows[0][:3], ["№", "Создан", "Статус"])
        row = rows[1]
        self.assertEqual(row[0], str(order.pk))
        self.assertEqual(row[2:6], ["Новый", "Сайт", "Роботы", "Иван"])
        self.assertEqual(row[7], "+7 900 111-22-33")
        self.assertEqual(row[8], "ivan")
        self.assertIn("Строка 1\nСтрока 2", text)

    def test_formula_injection_is_neutralised(self):
        order = Order.objects.create(
            name='=HYPERLINK("http://evil.example","клик")',
            email="e@example.com",
            phone="+1+1",
            budget="@SUM(1+1)",
            description="-2+3",
        )
        text = self.export(order).content.decode("utf-8")
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("'+1+1", text)
        self.assertIn("'@SUM(1+1)", text)
        self.assertIn("'-2+3", text)
        self.assertNotIn(";=HYPERLINK", text)

    def test_only_staff_with_permission_can_export(self):
        order = Order.objects.create(name="A", description="x")
        self.client.logout()
        response = self.export(order)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])
