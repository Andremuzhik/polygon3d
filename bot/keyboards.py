from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BTN_SERVICES = "🛠 Услуги"
BTN_PORTFOLIO = "🖼 Портфолио"
BTN_ORDER = "📝 Сделать заказ"
BTN_MY_ORDERS = "📦 Мои заказы"
BTN_CONTACTS = "☎️ Контакты"
BTN_CANCEL = "✖️ Отмена"
BTN_SKIP = "⏭ Пропустить"
BTN_SHARE_PHONE = "📱 Отправить мой номер"

MENU_BUTTONS = {BTN_SERVICES, BTN_PORTFOLIO, BTN_ORDER, BTN_MY_ORDERS, BTN_CONTACTS, BTN_CANCEL}


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SERVICES), KeyboardButton(text=BTN_PORTFOLIO)],
            [KeyboardButton(text=BTN_ORDER), KeyboardButton(text=BTN_MY_ORDERS)],
            [KeyboardButton(text=BTN_CONTACTS)],
        ],
        resize_keyboard=True,
    )


def cancel_menu(*, skip: bool = False, phone: bool = False) -> ReplyKeyboardMarkup:
    rows = []
    if phone:
        rows.append([KeyboardButton(text=BTN_SHARE_PHONE, request_contact=True)])
    if skip:
        rows.append([KeyboardButton(text=BTN_SKIP)])
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def services_kb(services: list[dict], *, prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in services:
        kb.button(text=s["title"], callback_data=f"{prefix}:{s['id']}")
    kb.adjust(1)
    return kb.as_markup()


def service_actions(service_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Заказать", callback_data=f"order:{service_id}")]
        ]
    )


def order_service_kb(services: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in services:
        kb.button(text=s["title"], callback_data=f"order:{s['id']}")
    kb.button(text="Другое / пока не знаю", callback_data="order:0")
    kb.adjust(1)
    return kb.as_markup()


def orders_kb(orders: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for o in orders:
        kb.button(text=f"{o['title']} — {o['status']}", callback_data=f"my:{o['id']}")
    kb.adjust(1)
    return kb.as_markup()


def client_order_actions(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Написать менеджеру", callback_data=f"chat:{order_id}")]
        ]
    )


def admin_order_actions(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Ответить", callback_data=f"areply:{order_id}")],
            [
                InlineKeyboardButton(
                    text="▶️ В работу", callback_data=f"astatus:{order_id}:in_progress"
                ),
                InlineKeyboardButton(
                    text="👀 Согласование", callback_data=f"astatus:{order_id}:review"
                ),
            ],
            [
                InlineKeyboardButton(text="✅ Выполнен", callback_data=f"astatus:{order_id}:done"),
                InlineKeyboardButton(
                    text="🚫 Отменить", callback_data=f"astatus:{order_id}:cancelled"
                ),
            ],
        ]
    )
