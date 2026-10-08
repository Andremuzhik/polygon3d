import re

PUBLIC_PATHS = [
    "/",
    "/services/",
    "/services/game-assets/",
    "/portfolio/",
    "/portfolio/robot-courier/",
    "/reviews/",
    "/contacts/",
    "/order/",
    "/accounts/login/",
    "/accounts/register/",
]


def test_public_pages_load_without_errors_and_with_security_headers(page, base_url):
    for path in PUBLIC_PATHS:
        response = page.goto(base_url + path, wait_until="networkidle")
        assert response.status == 200, path
        headers = response.headers
        assert "script-src 'self'" in headers["content-security-policy"], path
        assert headers["x-content-type-options"] == "nosniff", path
        assert "server" not in headers, f"{path}: Caddy должен скрывать заголовок Server"
    assert page.problems == []


def test_custom_404_page(page, base_url):
    response = page.goto(base_url + "/no-such-page/")
    assert response.status == 404
    assert page.get_by_role("heading", name="Такой страницы нет").is_visible()
    assert page.problems == [] or all("404" in p for p in page.problems)  # сам документ вернул 404


def test_public_media_is_served_by_caddy_and_cached(page, base_url):
    response = page.request.get(base_url + "/media/public/models/robot-courier.glb")
    assert response.status == 200
    assert "max-age=2592000" in response.headers["cache-control"]
    assert response.body()[:4] == b"glTF"


def test_private_media_is_not_publicly_reachable(page, base_url):
    for path in ("/media/orders/anything.png", "/media/deliveries/anything.png", "/media/"):
        assert page.request.get(base_url + path).status == 404, path


def test_hashed_static_files_are_cached_forever(page, base_url):
    page.goto(base_url + "/")
    href = page.locator('link[rel="stylesheet"]').first.get_attribute("href")
    assert re.search(r"style\.[0-9a-f]{12}\.css", href), href
    response = page.request.get(base_url + href)
    assert response.status == 200
    assert "immutable" in response.headers["cache-control"]


def test_mobile_layout_has_no_horizontal_scroll_and_working_menu(mobile_page, base_url):
    for path in PUBLIC_PATHS:
        mobile_page.goto(base_url + path, wait_until="networkidle")
        fits = mobile_page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert fits, f"{path}: горизонтальная прокрутка на 390 px"

    mobile_page.goto(base_url + "/", wait_until="networkidle")
    burger = mobile_page.locator("[data-burger]")
    nav = mobile_page.locator("[data-nav]")
    assert not nav.is_visible()
    burger.click()
    assert nav.is_visible()
    assert burger.get_attribute("aria-expanded") == "true"
    assert mobile_page.problems == []


def test_3d_viewer_is_loaded_only_on_demand(page, base_url):
    page.goto(base_url + "/portfolio/robot-courier/", wait_until="networkidle")
    script_requests = []
    # в боевой сборке у файла хеш в имени (model-viewer.min.<хеш>.js)
    page.on(
        "request",
        lambda r: (
            script_requests.append(r.url)
            if "/vendor/model-viewer/model-viewer.min." in r.url
            else None
        ),
    )
    assert page.locator("model-viewer").count() == 0

    page.get_by_role("button", name="Крутить модель в 3D").click()
    page.wait_for_selector("model-viewer")
    page.wait_for_function(
        "document.querySelector('model-viewer')?.loaded === true", timeout=120_000
    )

    assert len(script_requests) == 1
    assert page.locator("[data-viewer-hint]").is_visible()
    assert page.problems == []  # в том числе нарушений CSP и ошибок WebAssembly


def test_order_form_validates_then_accepts(page, base_url):
    page.goto(base_url + "/order/")
    page.fill("#id_name", "Гость")
    page.fill("#id_description", "Нужна модель кружки для каталога")
    page.get_by_role("button", name="Отправить заявку").click()
    assert page.get_by_text("Укажите хотя бы один способ связи").is_visible()

    page.fill("#id_email", "guest@example.com")
    page.get_by_role("button", name="Отправить заявку").click()
    page.wait_for_url("**/order/thanks/**")
    assert re.search(r"Заявка №\d+ принята", page.locator("h1").inner_text())
