from django.core.management.base import BaseCommand

from studio.models import PortfolioItem, Review, Service

SERVICES = [
    (
        "Моделирование персонажей",
        "character-modeling",
        "Стилизованные и реалистичные персонажи для игр и анимации.",
        15000,
        "5–14 дней",
    ),
    (
        "Предметная визуализация",
        "product-visualization",
        "Фотореалистичные 3D-рендеры товаров для каталогов и маркетплейсов.",
        3000,
        "2–5 дней",
    ),
    (
        "Интерьеры и архитектура",
        "interior-architecture",
        "3D-визуализация помещений и фасадов по чертежам или эскизам.",
        8000,
        "5–10 дней",
    ),
    (
        "Игровые ассеты",
        "game-assets",
        "Low-poly модели с PBR-текстурами, готовые для Unity и Unreal Engine.",
        2500,
        "2–7 дней",
    ),
    (
        "Модели для 3D-печати",
        "3d-printing",
        "Подготовка и проектирование моделей под FDM и SLA-печать.",
        2000,
        "1–4 дня",
    ),
]

WORKS = [
    ("Робот-курьер", "robot-courier", PortfolioItem.Category.CHARACTER, "Blender"),
    ("Кофейная кружка", "coffee-mug", PortfolioItem.Category.PRODUCT, "Blender, Substance Painter"),
    ("Лофт-гостиная", "loft-living-room", PortfolioItem.Category.INTERIOR, "3ds Max, Corona"),
    (
        "Набор фэнтези-оружия",
        "fantasy-weapons",
        PortfolioItem.Category.GAME_ASSET,
        "Blender, ZBrush",
    ),
    ("Небольшой коттедж", "small-cottage", PortfolioItem.Category.ARCHITECTURE, "SketchUp, Lumion"),
    ("Подставка для телефона", "phone-stand", PortfolioItem.Category.PRINT, "Fusion 360"),
]

REVIEWS = [
    (
        "Алексей, инди-студия",
        "Сделали набор ассетов для нашей игры за неделю. Модели сразу встали в Unity без доработок.",
        5,
    ),
    (
        "Марина, интернет-магазин",
        "Рендеры товаров подняли конверсию карточек. Менеджер всегда на связи в Telegram.",
        5,
    ),
    (
        "Дмитрий, архитектор",
        "Визуализация по чертежам получилась точной, правки внесли в тот же день.",
        4,
    ),
]


class Command(BaseCommand):
    help = "Заполняет сайт демо-данными (идемпотентно)."

    def handle(self, *args, **options):
        for order, (title, slug, short, price, duration) in enumerate(SERVICES, start=1):
            Service.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "short_description": short,
                    "description": f"{short}\n\nВ стоимость входят две итерации правок. "
                    "Сдача в форматах .blend, .fbx, .obj, .glb — по договорённости.",
                    "price_from": price,
                    "duration": duration,
                    "sort_order": order * 10,
                },
            )
        for title, slug, category, software in WORKS:
            PortfolioItem.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "category": category,
                    "software": software,
                    "description": "Демо-работа. Замените превью и загрузите .glb в админке — "
                    "на странице появится интерактивный 3D-просмотр.",
                },
            )
        for author, text, rating in REVIEWS:
            Review.objects.get_or_create(author=author, defaults={"text": text, "rating": rating})
        self.stdout.write(self.style.SUCCESS("Демо-данные созданы."))
