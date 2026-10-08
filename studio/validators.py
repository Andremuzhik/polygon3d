from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.deconstruct import deconstructible

REFERENCE_EXTENSIONS = ["jpg", "jpeg", "png", "pdf", "zip", "rar", "7z", "obj", "fbx", "stl", "glb"]
MODEL_EXTENSIONS = ["glb", "gltf"]


@deconstructible
class MaxFileSize:
    def __init__(self, megabytes: int):
        self.megabytes = megabytes

    def __call__(self, file):
        if file.size > self.megabytes * 1024 * 1024:
            raise ValidationError(f"Файл слишком большой (максимум {self.megabytes} МБ).")

    def __eq__(self, other):
        return isinstance(other, MaxFileSize) and self.megabytes == other.megabytes


validate_reference = [FileExtensionValidator(REFERENCE_EXTENSIONS), MaxFileSize(20)]
validate_model = [FileExtensionValidator(MODEL_EXTENSIONS), MaxFileSize(30)]
