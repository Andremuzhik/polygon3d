"""Сквозной сценарий: клиент оформляет заказ, менеджер сдаёт результат в админке, клиент принимает."""

import re
import uuid

PNG = b"\x89PNG\r\n\x1a\n" + b"e2e-render" * 8


def order_status(page):
    return page.locator(".status").first.inner_text().strip()


def manager_saves_delivery(admin, base_url, order_id, tmp_path, title, message=None, status=None):
    admin.goto(f"{base_url}/admin/studio/order/{order_id}/change/")
    if status:
        admin.select_option("#id_status", label=status)
    file = tmp_path / f"{uuid.uuid4().hex[:6]}.png"
    file.write_bytes(PNG)
    # в формсете есть скрытый шаблон «__prefix__»: берём только настоящую пустую строку
    admin.locator(
        'input[type=file][name^="deliveries-"]:not([name*="__prefix__"])'
    ).last.set_input_files(str(file))
    admin.locator('input[name^="deliveries-"][name$="-title"]:not([name*="__prefix__"])').last.fill(
        title
    )
    if message:
        admin.locator(
            'textarea[name^="messages-"][name$="-text"]:not([name*="__prefix__"])'
        ).last.fill(message)
    admin.locator('input[name="_continue"]').click()
    admin.locator(".messagelist .success").wait_for()


def test_customer_and_manager_journey(new_page, admin_page, base_url, tmp_path):
    suffix = uuid.uuid4().hex[:8]
    customer = new_page()

    # --- клиент: регистрация и заказ
    customer.goto(base_url + "/accounts/register/")
    customer.fill("#id_username", f"client_{suffix}")
    customer.fill("#id_email", f"client_{suffix}@example.com")
    customer.fill("#id_password1", "Journey-pass-4821")
    customer.fill("#id_password2", "Journey-pass-4821")
    customer.get_by_role("button", name="Создать аккаунт").click()
    customer.wait_for_url("**/cabinet/")

    customer.goto(base_url + "/order/")
    customer.select_option("#id_service", label="Игровые ассеты")
    customer.fill("#id_description", "Нужен набор из 20 low-poly предметов для мобильной игры")
    customer.get_by_role("button", name="Отправить заявку").click()
    customer.wait_for_url("**/order/thanks/**")
    order_id = int(re.search(r"Заявка №(\d+)", customer.locator("h1").inner_text()).group(1))

    # --- клиент пишет менеджеру из кабинета
    customer.goto(f"{base_url}/cabinet/orders/{order_id}/")
    customer.locator('form:not([action]) textarea[name="text"]').fill("Когда сможете начать?")
    customer.get_by_role("button", name="Отправить", exact=True).click()
    customer.get_by_text("Когда сможете начать?").wait_for()
    assert order_status(customer) == "Новый"
    assert "Заказ создан" in customer.locator(".timeline").inner_text()

    # --- менеджер: берёт в работу, загружает результат и отвечает (всё в админке)
    manager_saves_delivery(
        admin_page,
        base_url,
        order_id,
        tmp_path,
        "Рендеры, версия 1",
        message="Первая версия готова, посмотрите",
        status="В работе",
    )

    # --- клиент видит результат на согласовании
    customer.reload()
    assert order_status(customer) == "На согласовании"
    assert customer.get_by_role("link", name="Рендеры, версия 1").is_visible()
    assert customer.get_by_text("Первая версия готова, посмотрите").is_visible()
    assert customer.get_by_role("button", name="Принять работу").is_visible()

    # файл скачивается владельцем, а аноним видит только страницу входа
    href = customer.get_by_role("link", name="Рендеры, версия 1").get_attribute("href")
    download = customer.request.get(base_url + href)
    assert download.status == 200 and download.body() == PNG
    stranger = new_page()
    assert stranger.request.get(base_url + href, max_redirects=0).status == 302

    # --- клиент просит правки
    customer.locator('form[action$="/revision/"] textarea').fill("Сделайте цвета ярче")
    customer.get_by_role("button", name="Запросить правки").click()
    customer.get_by_text("Правки отправлены менеджеру").wait_for()
    assert order_status(customer) == "В работе"
    assert customer.get_by_role("button", name="Принять работу").count() == 0
    timeline = customer.locator(".timeline").inner_text()
    assert "Клиент запросил правки (правка 1 из 2)" in timeline
    assert "На согласовании → В работе" in timeline

    # --- менеджер сдаёт вторую версию, клиент принимает
    manager_saves_delivery(admin_page, base_url, order_id, tmp_path, "Рендеры, версия 2")
    customer.reload()
    assert order_status(customer) == "На согласовании"
    assert customer.get_by_role("link", name="Рендеры, версия 2").is_visible()
    customer.get_by_role("button", name="Принять работу").click()
    customer.get_by_text("Работа принята").wait_for()
    assert order_status(customer) == "Выполнен"
    assert customer.get_by_role("button", name="Запросить правки").count() == 0
    assert "На согласовании → Выполнен" in customer.locator(".timeline").inner_text()
    assert customer.problems == []

    # --- менеджер видит всю историю в админке
    admin_page.goto(f"{base_url}/admin/studio/order/{order_id}/change/")
    history = admin_page.locator(".inline-group").last.inner_text()
    assert "Заказ создан" in history and "Клиент запросил правки" in history
