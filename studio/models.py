import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from .images import OptimizeImageOnUpload
from .validators import validate_delivery, validate_model, validate_reference

REVISIONS_INCLUDED = 2  # правок, входящих в стоимость


class Service(OptimizeImageOnUpload, models.Model):
    title = models.CharField("Название", max_length=120)
    slug = models.SlugField("Слаг (URL)", unique=True)
    short_description = models.CharField("Краткое описание", max_length=220)
    description = models.TextField("Подробное описание")
    price_from = models.PositiveIntegerField("Цена от, ₽", null=True, blank=True)
    duration = models.CharField("Срок", max_length=60, blank=True, help_text="Например: 3–7 дней")
    image = models.ImageField("Изображение", upload_to="public/services/", blank=True)
    is_active = models.BooleanField("Показывать на сайте", default=True)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=100)

    class Meta:
        ordering = ["sort_order", "title"]
        verbose_name = "услуга"
        verbose_name_plural = "услуги"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("service-detail", args=[self.slug])


class PortfolioItem(OptimizeImageOnUpload, models.Model):
    class Category(models.TextChoices):
        CHARACTER = "character", "Персонажи"
        ARCHITECTURE = "architecture", "Архитектура"
        PRODUCT = "product", "Предметная визуализация"
        INTERIOR = "interior", "Интерьеры"
        GAME_ASSET = "game_asset", "Игровые ассеты"
        PRINT = "print", "Модели для 3D-печати"

    title = models.CharField("Название", max_length=120)
    slug = models.SlugField("Слаг (URL)", unique=True)
    category = models.CharField("Категория", max_length=20, choices=Category.choices)
    description = models.TextField("Описание", blank=True)
    image = models.ImageField("Превью", upload_to="public/portfolio/", blank=True)
    model_file = models.FileField(
        "3D-модель (.glb / .gltf)",
        upload_to="public/models/",
        blank=True,
        validators=validate_model,
        help_text="Если загрузить, посетители смогут вращать модель на странице работы.",
    )
    software = models.CharField("Софт", max_length=120, blank=True, help_text="Blender, ZBrush…")
    is_published = models.BooleanField("Опубликовано", default=True)
    created_at = models.DateTimeField("Добавлено", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "элемент портфолио"
        verbose_name_plural = "портфолио"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("portfolio-detail", args=[self.slug])


class Review(models.Model):
    author = models.CharField("Автор", max_length=80)
    text = models.TextField("Отзыв")
    rating = models.PositiveSmallIntegerField(
        "Оценка", default=5, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    is_published = models.BooleanField("Опубликовано", default=True)
    created_at = models.DateTimeField("Дата", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "отзыв"
        verbose_name_plural = "отзывы"

    def __str__(self):
        return f"{self.author} ({self.rating}/5)"

    @property
    def stars(self) -> str:
        return "★" * self.rating


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    telegram_id = models.BigIntegerField("Telegram ID", null=True, blank=True, unique=True)
    telegram_username = models.CharField("Telegram username", max_length=64, blank=True)
    link_token = models.UUIDField("Токен привязки", default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        verbose_name = "профиль"
        verbose_name_plural = "профили"

    def __str__(self):
        return f"Профиль {self.user}"


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новый"
        IN_PROGRESS = "in_progress", "В работе"
        REVIEW = "review", "На согласовании"
        DONE = "done", "Выполнен"
        CANCELLED = "cancelled", "Отменён"

    class Source(models.TextChoices):
        SITE = "site", "Сайт"
        BOT = "bot", "Telegram-бот"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    service = models.ForeignKey(
        Service,
        verbose_name="Услуга",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    name = models.CharField("Имя", max_length=80)
    email = models.EmailField("Email", blank=True)
    phone = models.CharField("Телефон", max_length=32, blank=True)
    telegram_username = models.CharField("Telegram", max_length=64, blank=True)
    telegram_id = models.BigIntegerField("Telegram ID", null=True, blank=True, db_index=True)
    description = models.TextField("Описание задачи")
    budget = models.CharField("Бюджет", max_length=60, blank=True)
    deadline = models.DateField("Желаемый срок", null=True, blank=True)
    reference_file = models.FileField(
        "Референсы", upload_to="orders/%Y/%m/", blank=True, validators=validate_reference
    )
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.NEW)
    source = models.CharField(
        "Источник", max_length=10, choices=Source.choices, default=Source.SITE
    )
    manager_note = models.TextField("Внутренняя заметка", blank=True)
    revisions_used = models.PositiveSmallIntegerField("Запрошено правок", default=0, editable=False)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "заказ"
        verbose_name_plural = "заказы"

    def __str__(self):
        return f"Заказ №{self.pk} — {self.name}"

    @property
    def client_chat_id(self) -> int | None:
        """Telegram-чат, куда слать уведомления клиенту."""
        if self.telegram_id:
            return self.telegram_id
        if self.user_id:
            profile = Profile.objects.filter(user_id=self.user_id).first()
            return profile.telegram_id if profile else None
        return None


class OrderDelivery(models.Model):
    """Файл с результатом работы: лежит в приватном хранилище, скачивают владелец заказа и менеджеры."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="deliveries")
    title = models.CharField(
        "Название", max_length=120, blank=True, help_text="Например: Рендеры, версия 1"
    )
    file = models.FileField("Файл", upload_to="deliveries/%Y/%m/", validators=validate_delivery)
    note = models.CharField("Комментарий", max_length=255, blank=True)
    created_at = models.DateTimeField("Загружен", auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "результат"
        verbose_name_plural = "результаты"

    def __str__(self):
        return self.display_title

    @property
    def filename(self) -> str:
        return self.file.name.rsplit("/", 1)[-1]

    @property
    def display_title(self) -> str:
        return self.title or self.filename


class OrderEvent(models.Model):
    """Журнал заказа: что и когда происходило. Показывается клиенту и менеджеру."""

    class Kind(models.TextChoices):
        CREATED = "created", "Заказ создан"
        STATUS = "status", "Смена статуса"
        MESSAGE = "message", "Сообщение"
        DELIVERY = "delivery", "Результат"
        REVISION = "revision", "Запрос правок"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField("Тип", max_length=10, choices=Kind.choices)
    text = models.CharField("Описание", max_length=255)
    to_status = models.CharField("Новый статус", max_length=20, blank=True)
    created_at = models.DateTimeField("Время", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "событие"
        verbose_name_plural = "история заказа"

    def __str__(self):
        return f"{self.created_at:%d.%m %H:%M} {self.text}"


class OrderMessage(models.Model):
    class Sender(models.TextChoices):
        CLIENT = "client", "Клиент"
        MANAGER = "manager", "Менеджер"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField("Отправитель", max_length=10, choices=Sender.choices)
    text = models.TextField("Сообщение")
    created_at = models.DateTimeField("Время", auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "сообщение"
        verbose_name_plural = "сообщения"

    def __str__(self):
        return f"{self.get_sender_display()}: {self.text[:40]}"


class Notification(models.Model):
    """Очередь исходящих сообщений в Telegram; её разбирает бот."""

    class Kind(models.TextChoices):
        ADMIN_ORDER = "admin_order", "Менеджеру: новый заказ"
        ADMIN_MESSAGE = "admin_message", "Менеджеру: сообщение клиента"
        CLIENT_STATUS = "client_status", "Клиенту: смена статуса"
        CLIENT_MESSAGE = "client_message", "Клиенту: ответ менеджера"
        CLIENT_DELIVERY = "client_delivery", "Клиенту: результат готов"
        ADMIN_EVENT = "admin_event", "Менеджеру: событие по заказу"

    chat_id = models.BigIntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления Telegram"
        indexes = [models.Index(fields=["sent_at", "attempts"])]

    def __str__(self):
        return f"{self.get_kind_display()} → {self.chat_id}"
