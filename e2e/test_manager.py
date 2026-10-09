"""Рабочее место менеджера: дашборд на главной админки и выгрузка заказов в CSV."""

import csv
import io
import re


def test_dashboard_shows_studio_metrics(admin_page, base_url):
    admin_page.goto(base_url + "/admin/")
    dashboard = admin_page.locator(".studio-dashboard")
    assert dashboard.is_visible()
    text = dashboard.inner_text()
    for label in (
        "Всего заказов",
        "Ждут решения клиента",
        "Средний срок выполнения",
        "Заказы по месяцам",
    ):
        assert label.lower() in text.lower(), label
    total = int(re.search(r"Всего заказов\s+(\d+)", text).group(1))
    assert total >= 1
    assert admin_page.problems == []


def test_orders_can_be_exported_to_csv_from_the_changelist(admin_page, base_url):
    admin_page.goto(base_url + "/admin/studio/order/")
    admin_page.locator("#action-toggle").check()
    admin_page.select_option('select[name="action"]', label="Выгрузить выбранные заказы в CSV")
    with admin_page.expect_download() as download_info:
        admin_page.locator('button[name="index"], button:has-text("Выполнить")').first.click()
    download = download_info.value

    assert download.suggested_filename == "orders.csv"
    content = open(download.path(), "rb").read().decode("utf-8")
    assert content.startswith("﻿")
    rows = list(csv.reader(io.StringIO(content.lstrip("﻿")), delimiter=";"))
    assert rows[0][:3] == ["№", "Создан", "Статус"]
    assert len(rows) >= 2
    assert any("Выполнен" in row for row in rows[1:])
