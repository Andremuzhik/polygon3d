"""Сжатие загружаемых изображений: уменьшаем до разумного размера и пересохраняем в JPEG."""

import io
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600
JPEG_QUALITY = 82


def optimize_image(upload) -> ContentFile | None:
    """Возвращает сжатую JPEG-версию картинки или None, если файл не удалось разобрать."""
    try:
        upload.seek(0)
        with Image.open(upload) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return ContentFile(buffer.getvalue(), name=f"{Path(upload.name).stem}.jpg")


class OptimizeImageOnUpload:
    """Миксин для моделей с полем `image`: свежезагруженный файл сжимается при сохранении."""

    def save(self, *args, **kwargs):
        field = self.image
        if field and not field._committed:
            optimized = optimize_image(field.file)
            if optimized is not None:
                field.save(optimized.name, optimized, save=False)
        super().save(*args, **kwargs)
