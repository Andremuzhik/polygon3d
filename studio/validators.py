from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.deconstruct import deconstructible

REFERENCE_EXTENSIONS = ["jpg", "jpeg", "png", "pdf", "zip", "rar", "7z", "obj", "fbx", "stl", "glb"]
MODEL_EXTENSIONS = ["glb", "gltf"]
DELIVERY_EXTENSIONS = [
    "jpg",
    "jpeg",
    "png",
    "pdf",
    "zip",
    "rar",
    "7z",
    "glb",
    "gltf",
    "fbx",
    "obj",
    "stl",
    "blend",
]

# Начало файла для форматов с сигнатурой. У obj, stl и ascii-fbx сигнатуры нет,
# для них — чёрный список ниже.
SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "pdf": (b"%PDF-",),
    "zip": (b"PK\x03\x04", b"PK\x05\x06"),
    "rar": (b"Rar!\x1a\x07",),
    "7z": (b"7z\xbc\xaf\x27\x1c",),
    "glb": (b"glTF",),
    "fbx": (b"Kaydara FBX Binary", b"; FBX"),
    "blend": (b"BLENDER",),
}
# Исполняемые файлы и веб-контент, которым нечего делать в 3D-референсах.
FORBIDDEN_PREFIXES = (
    b"MZ",
    b"\x7fELF",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"#!",
    b"<?php",
)
FORBIDDEN_MARKUP = (b"<!doctype", b"<html", b"<script", b"<svg", b"<?xml")
HEAD_SIZE = 512


@deconstructible
class MaxFileSize:
    def __init__(self, megabytes: int):
        self.megabytes = megabytes

    def __call__(self, file):
        if file.size > self.megabytes * 1024 * 1024:
            raise ValidationError(f"Файл слишком большой (максимум {self.megabytes} МБ).")

    def __eq__(self, other):
        return isinstance(other, MaxFileSize) and self.megabytes == other.megabytes


def validate_file_content(file):
    """Содержимое должно соответствовать расширению (защита от переименованных файлов)."""
    extension = Path(file.name).suffix.lower().lstrip(".")
    file.seek(0)
    head = file.read(HEAD_SIZE)
    file.seek(0)
    if isinstance(head, str):
        head = head.encode("utf-8", "ignore")

    mismatch = ValidationError(
        "Содержимое файла не соответствует его расширению. "
        "Загрузите настоящий файл нужного формата."
    )
    if extension == "gltf":
        if not head.lstrip().startswith(b"{"):
            raise mismatch
        return
    signatures = SIGNATURES.get(extension)
    if signatures:
        if not any(head.startswith(sig) for sig in signatures):
            raise mismatch
        return
    lowered = head.lstrip().lower()
    if head.startswith(FORBIDDEN_PREFIXES) or lowered.startswith(FORBIDDEN_MARKUP):
        raise mismatch


validate_reference = [
    FileExtensionValidator(REFERENCE_EXTENSIONS),
    MaxFileSize(20),
    validate_file_content,
]
validate_model = [FileExtensionValidator(MODEL_EXTENSIONS), MaxFileSize(30), validate_file_content]
validate_delivery = [
    FileExtensionValidator(DELIVERY_EXTENSIONS),
    MaxFileSize(40),  # лимит Telegram на отправку файла ботом — 50 МБ
    validate_file_content,
]
