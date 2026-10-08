from pathlib import Path

from django.conf import settings
from django.core.files import File
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
    ("Робот-курьер", "robot-courier", PortfolioItem.Category.CHARACTER),
    ("Кофейная кружка", "coffee-mug", PortfolioItem.Category.PRODUCT),
    ("Лофт-гостиная", "loft-living-room", PortfolioItem.Category.INTERIOR),
    ("Набор фэнтези-оружия", "fantasy-weapons", PortfolioItem.Category.GAME_ASSET),
    ("Небольшой коттедж", "small-cottage", PortfolioItem.Category.ARCHITECTURE),
    ("Подставка для телефона", "phone-stand", PortfolioItem.Category.PRINT),
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

ASSETS = Path(settings.BASE_DIR) / "demo_assets"

# Услуге подбираем превью из подходящей работы портфолио.
SERVICE_PREVIEWS = {
    "character-modeling": "robot-courier",
    "product-visualization": "coffee-mug",
    "interior-architecture": "loft-living-room",
    "game-assets": "fantasy-weapons",
    "3d-printing": "phone-stand",
}


def attach(instance, field: str, path: Path) -> bool:
    """Прикрепляет файл, только если поле пустое (повторный запуск ничего не дублирует)."""
    if getattr(instance, field) or not path.exists():
        return False
    with path.open("rb") as f:
        getattr(instance, field).save(path.name, File(f), save=True)
    return True


class Command(BaseCommand):
    help = (
        "Заполняет сайт демо-данными (повторный запуск безопасен; тексты демо-работ обновляются)."
    )

    def handle(self, *args, **options):
        for order, (title, slug, short, price, duration) in enumerate(SERVICES, start=1):
            service, _ = Service.objects.get_or_create(
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
            preview = SERVICE_PREVIEWS[slug]
            attach(service, "image", ASSETS / "previews" / f"{preview}.jpg")
        for title, slug, category in WORKS:
            work, _ = PortfolioItem.objects.update_or_create(
                slug=slug,
                defaults={
                    "title": title,
                    "category": category,
                    "software": "Python, glTF 2.0",
                    "description": "Демо-модель, собранная из примитивов скриптом "
                    "demo_assets/generate_models.py. Её можно вращать мышью или пальцем. "
                    "Свои работы загружаются в админке: превью и файл .glb.",
                },
            )
            attach(work, "image", ASSETS / "previews" / f"{slug}.jpg")
            attach(work, "model_file", ASSETS / "models" / f"{slug}.glb")
        for author, text, rating in REVIEWS:
            Review.objects.get_or_create(author=author, defaults={"text": text, "rating": rating})
        self.stdout.write(self.style.SUCCESS("Демо-данные созданы."))
