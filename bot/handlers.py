import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from django.conf import settings

from . import db
from . import keyboards as kb

log = logging.getLogger(__name__)

menu_router = Router(name="menu")
admin_router = Router(name="admin")
client_router = Router(name="client")


class OrderFlow(StatesGroup):
    description = State()
    contact = State()
    reference = State()


class ClientChat(StatesGroup):
    writing = State()


class AdminReply(StatesGroup):
    writing = State()


def is_admin(user_id: int) -> bool:
    return user_id in settings.TELEGRAM_ADMIN_IDS


def money(value: int | None) -> str:
    return f"от {value:,} ₽".replace(",", " ") if value else "по договорённости"


# ---------------------------------------------------------------- меню / общие


@menu_router.message(Command("start"))
async def start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    user = message.from_user
    username = user.username or ""
    payload = command.args or ""
    note = ""
    if payload.startswith("link_"):
        if await db.link_account(payload.removeprefix("link_"), user.id, username):
            note = "✅ Аккаунт на сайте привязан — уведомления о заказах будут приходить сюда.\n\n"
        else:
            note = "⚠️ Ссылка привязки недействительна. Получите новую в личном кабинете.\n\n"
    elif payload.startswith("order_"):
        order_id = await db.claim_order(payload.removeprefix("order_"), user.id, username)
        if order_id:
            note = f"✅ Заказ №{order_id} привязан — буду сообщать о статусе и пересылать ответы менеджера.\n\n"
        else:
            note = "⚠️ Не удалось привязать заказ: ссылка устарела или он уже привязан.\n\n"
    await message.answer(
        f"{note}Привет, {escape(user.first_name)}! 👋\n"
        f"Я бот студии <b>{escape(settings.SITE_NAME)}</b>: покажу услуги и работы, "
        "приму заказ на 3D-моделирование и свяжу с менеджером.",
        reply_markup=kb.main_menu(),
    )


@menu_router.message(F.text == kb.BTN_CANCEL)
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=kb.main_menu())


@menu_router.message(F.text == kb.BTN_SERVICES)
async def services(message: Message, state: FSMContext):
    await state.clear()
    items = await db.list_services()
    if not items:
        await message.answer("Список услуг пока пуст.")
        return
    await message.answer("Выберите услугу:", reply_markup=kb.services_kb(items, prefix="svc"))


@menu_router.callback_query(F.data.startswith("svc:"))
async def service_card(call: CallbackQuery):
    service = await db.get_service(int(call.data.split(":")[1]))
    await call.answer()
    if not service:
        await call.message.answer("Услуга больше недоступна.")
        return
    duration = f"\nСрок: {escape(service['duration'])}" if service["duration"] else ""
    await call.message.answer(
        f"<b>{escape(service['title'])}</b>\n{money(service['price_from'])}{duration}\n\n"
        f"{escape(service['description'])}\n\n{settings.SITE_URL}/services/{service['slug']}/",
        reply_markup=kb.service_actions(service["id"]),
    )


@menu_router.message(F.text == kb.BTN_PORTFOLIO)
async def portfolio(message: Message, state: FSMContext):
    await state.clear()
    works = await db.latest_portfolio()
    if not works:
        await message.answer("Портфолио скоро появится.")
        return
    for work in works:
        caption = (
            f"<b>{escape(work['title'])}</b> · {work['category']}\n"
            f"{settings.SITE_URL}/portfolio/{work['slug']}/"
        )
        if work["image_path"]:
            await message.answer_photo(FSInputFile(work["image_path"]), caption=caption)
        else:
            await message.answer(caption)
    await message.answer(f"Больше работ: {settings.SITE_URL}/portfolio/")


@menu_router.message(F.text == kb.BTN_CONTACTS)
async def contacts(message: Message, state: FSMContext):
    await state.clear()
    lines = [f"<b>{escape(settings.SITE_NAME)}</b>", f"🌐 {settings.SITE_URL}"]
    if settings.CONTACT_EMAIL:
        lines.append(f"✉️ {escape(settings.CONTACT_EMAIL)}")
    if settings.CONTACT_PHONE:
        lines.append(f"📞 {escape(settings.CONTACT_PHONE)}")
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------- оформление заказа


@menu_router.message(F.text == kb.BTN_ORDER)
async def order_start(message: Message, state: FSMContext):
    await state.clear()
    items = await db.list_services()
    await message.answer(
        "Что нужно сделать? Выберите услугу:", reply_markup=kb.order_service_kb(items)
    )


@menu_router.callback_query(F.data.startswith("order:"))
async def order_service_chosen(call: CallbackQuery, state: FSMContext):
    service_id = int(call.data.split(":")[1])
    await state.clear()
    await state.update_data(service_id=service_id or None)
    await state.set_state(OrderFlow.description)
    await call.answer()
    await call.message.answer(
        "Опишите задачу: что моделируем, для чего, в каком стиле, есть ли референсы.",
        reply_markup=kb.cancel_menu(),
    )


@client_router.message(OrderFlow.description, F.text)
async def order_description(message: Message, state: FSMContext):
    if len(message.text) < 10:
        await message.answer("Опишите чуть подробнее (хотя бы пару предложений).")
        return
    await state.update_data(description=message.text)
    await state.set_state(OrderFlow.contact)
    await message.answer(
        "Оставьте телефон для связи или нажмите «Пропустить» — тогда напишу вам здесь, в Telegram.",
        reply_markup=kb.cancel_menu(skip=True, phone=True),
    )


@client_router.message(OrderFlow.contact, F.contact)
async def order_contact_shared(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await _ask_reference(message, state)


@client_router.message(OrderFlow.contact, F.text)
async def order_contact_text(message: Message, state: FSMContext):
    if message.text == kb.BTN_SKIP:
        await _ask_reference(message, state)
        return
    await state.update_data(phone=message.text.strip()[:32])
    await _ask_reference(message, state)


async def _ask_reference(message: Message, state: FSMContext):
    await state.set_state(OrderFlow.reference)
    await message.answer(
        "Прикрепите референсы (фото или файл до 20 МБ) или нажмите «Пропустить».",
        reply_markup=kb.cancel_menu(skip=True),
    )


@client_router.message(OrderFlow.reference, F.photo | F.document | (F.text == kb.BTN_SKIP))
async def order_reference(message: Message, state: FSMContext):
    file = None
    if message.photo or message.document:
        tg_file = message.photo[-1] if message.photo else message.document
        if (tg_file.file_size or 0) > 20 * 1024 * 1024:
            await message.answer("Файл больше 20 МБ. Пришлите другой или нажмите «Пропустить».")
            return
        name = "photo.jpg" if message.photo else (message.document.file_name or "reference")
        buffer = await message.bot.download(tg_file)
        file = (name, buffer.getvalue())

    data = await state.get_data()
    user = message.from_user
    try:
        order_id = await db.create_order(
            tg_id=user.id,
            tg_username=user.username or "",
            name=user.full_name,
            description=data["description"],
            service_id=data.get("service_id"),
            phone=data.get("phone", ""),
            file=file,
        )
    except db.RateLimited:
        await state.clear()
        await message.answer(
            "Слишком много заказов за последний час. Попробуйте позже или напишите менеджеру "
            "в чате по одному из ваших заказов.",
            reply_markup=kb.main_menu(),
        )
        return
    except Exception:
        # Например, недопустимое расширение файла референса.
        log.exception("Не удалось создать заказ из бота")
        await message.answer(
            "Не получилось сохранить заказ с этим файлом. Попробуйте другой формат "
            "(jpg, png, pdf, zip, obj, fbx, stl, glb) или нажмите «Пропустить».",
        )
        return
    await state.clear()
    await message.answer(
        f"✅ Заказ №{order_id} принят! Менеджер скоро свяжется с вами. "
        "Статус и ответы будут приходить сюда.",
        reply_markup=kb.main_menu(),
    )


@client_router.message(OrderFlow.reference)
async def order_reference_invalid(message: Message):
    await message.answer("Пришлите фото или файл, либо нажмите «Пропустить».")


# ---------------------------------------------------------------- мои заказы и чат


@menu_router.message(F.text == kb.BTN_MY_ORDERS)
async def my_orders(message: Message, state: FSMContext):
    await state.clear()
    orders = await db.list_orders(message.from_user.id)
    if not orders:
        await message.answer("У вас пока нет заказов. Нажмите «📝 Сделать заказ».")
        return
    await message.answer("Ваши заказы:", reply_markup=kb.orders_kb(orders))


@menu_router.callback_query(F.data.startswith("my:"))
async def order_card(call: CallbackQuery):
    order = await db.get_order(call.from_user.id, int(call.data.split(":")[1]))
    await call.answer()
    if not order:
        await call.message.answer("Заказ не найден.")
        return
    history = ""
    if order["messages"]:
        rows = [
            f"{'🧑 Вы' if m['sender'] == 'client' else '👨‍💼 Менеджер'}: {escape(m['text'][:300])}"
            for m in order["messages"]
        ]
        history = "\n\n<b>Последние сообщения:</b>\n" + "\n".join(rows)
    await call.message.answer(
        f"<b>Заказ №{order['id']}</b> · {escape(order['service'])}\n"
        f"Статус: <b>{order['status']}</b>\n"
        f"Создан: {order['created']:%d.%m.%Y}{history}",
        reply_markup=kb.client_order_actions(order["id"]),
    )


@client_router.callback_query(F.data.startswith("chat:"))
async def chat_start(call: CallbackQuery, state: FSMContext):
    order_id = int(call.data.split(":")[1])
    order = await db.get_order(call.from_user.id, order_id)
    await call.answer()
    if not order:
        await call.message.answer("Заказ не найден.")
        return
    await state.set_state(ClientChat.writing)
    await state.update_data(chat_order_id=order_id)
    await call.message.answer(
        f"Напишите сообщение менеджеру по заказу №{order_id}:", reply_markup=kb.cancel_menu()
    )


@client_router.message(ClientChat.writing, F.text)
async def chat_send(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data["chat_order_id"]
    ok = await db.add_client_message(message.from_user.id, order_id, message.text)
    await state.clear()
    if ok:
        await message.answer(
            f"✅ Сообщение по заказу №{order_id} отправлено менеджеру.", reply_markup=kb.main_menu()
        )
    else:
        await message.answer("Не удалось отправить: заказ не найден.", reply_markup=kb.main_menu())


# ---------------------------------------------------------------- менеджеры


admin_router.message.filter(F.from_user.func(lambda u: is_admin(u.id)))
admin_router.callback_query.filter(F.from_user.func(lambda u: is_admin(u.id)))


@admin_router.message(Command("orders"))
async def admin_orders(message: Message):
    orders = await db.active_orders()
    if not orders:
        await message.answer("Активных заказов нет 🎉")
        return
    for o in orders:
        await message.answer(
            f"<b>Заказ №{o['id']}</b> · {escape(o['service'])}\n"
            f"{escape(o['name'])} · {o['status']}\n\n{escape(o['description'][:500])}",
            reply_markup=kb.admin_order_actions(o["id"]),
        )


@admin_router.callback_query(F.data.startswith("astatus:"))
async def admin_status(call: CallbackQuery):
    _, order_id, status = call.data.split(":")
    label = await db.set_status(int(order_id), status)
    if label:
        await call.answer(f"Статус: {label}")
        await call.message.answer(f"Заказ №{order_id}: статус «{label}». Клиент уведомлён.")
    else:
        await call.answer("Заказ не найден", show_alert=True)


@admin_router.callback_query(F.data.startswith("areply:"))
async def admin_reply_start(call: CallbackQuery, state: FSMContext):
    order_id = int(call.data.split(":")[1])
    await state.set_state(AdminReply.writing)
    await state.update_data(reply_order_id=order_id)
    await call.answer()
    await call.message.answer(
        f"Ответ клиенту по заказу №{order_id} (следующее сообщение уйдёт клиенту):",
        reply_markup=kb.cancel_menu(),
    )


@admin_router.message(AdminReply.writing, F.text)
async def admin_reply_send(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data["reply_order_id"]
    ok = await db.add_manager_message(order_id, message.text)
    await state.clear()
    await message.answer(
        f"✅ Отправлено по заказу №{order_id}." if ok else "Заказ не найден.",
        reply_markup=kb.main_menu(),
    )


# ---------------------------------------------------------------- прочее


@client_router.message(StateFilter(None), F.text)
async def fallback(message: Message):
    await message.answer("Не понял 🤔 Воспользуйтесь меню ниже.", reply_markup=kb.main_menu())
