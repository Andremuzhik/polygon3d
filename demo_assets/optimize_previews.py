"""Пережимает отрендеренные превью (PNG) в JPEG 1200×900 и удаляет PNG. Нужен Pillow."""

from pathlib import Path

from PIL import Image

PREVIEWS = Path(__file__).parent / "previews"

for png in sorted(PREVIEWS.glob("*.png")):
    with Image.open(png) as image:
        image.convert("RGB").save(
            png.with_suffix(".jpg"), "JPEG", quality=82, optimize=True, progressive=True
        )
    png.unlink()
    print(f"{png.stem}.jpg: {png.with_suffix('.jpg').stat().st_size // 1024} КБ")
