import os

import pytest
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("E2E_BASE_URL", "https://e2e.internal").rstrip("/")
ADMIN_USER = os.environ.get("E2E_ADMIN_USER", "e2e_admin")
ADMIN_PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD", "")


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        # SwiftShader: WebGL без видеокарты, нужен для 3D-просмотрщика
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        yield browser
        browser.close()


@pytest.fixture
def base_url():
    return BASE_URL


@pytest.fixture
def new_page(browser):
    """Фабрика страниц: у каждой свой контекст (куки, сессия) и список ошибок консоли в page.problems."""
    contexts = []

    def make(**options):
        context = browser.new_context(ignore_https_errors=True, locale="ru-RU", **options)
        context.set_default_timeout(30_000)
        contexts.append(context)
        page = context.new_page()
        page.problems = []
        page.on(
            "console",
            lambda msg: (
                page.problems.append(f"console.{msg.type}: {msg.text}")
                if msg.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda err: page.problems.append(f"pageerror: {err}"))
        return page

    yield make
    for context in contexts:
        context.close()


@pytest.fixture
def page(new_page):
    return new_page()


@pytest.fixture
def mobile_page(new_page):
    return new_page(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )


@pytest.fixture
def admin_page(new_page):
    admin = new_page()
    admin.goto(f"{BASE_URL}/admin/login/")
    admin.fill("#id_username", ADMIN_USER)
    admin.fill("#id_password", ADMIN_PASSWORD)
    admin.get_by_role("button", name="Войти").click()
    admin.wait_for_url("**/admin/")
    return admin
