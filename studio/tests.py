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
        # клиент не может сбросить счётчик, дописав свой адрес: берётся последний, добавленный прокси
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
        self.assertEqual(size, (1600, 1067))  # пропорции сохранены
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
        self.assertNotIn('<script type="module"', html)  # тяжёлый скрипт не грузится сразу
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
                self.assertNotIn("<h3>", html)  # под <h1> сразу идут <h2>

    def test_home_cards_stay_h3_under_section_headings(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("<h3>", html)

    def test_layout_landmarks_and_skip_link(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn('class="skip-link" href="#main"', html)
        self.assertIn('<main id="main">', html)
        self.assertIn('aria-controls="site-nav"', html)
        self.assertIn('name="theme-color"', html)
