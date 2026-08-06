import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings

SUPPORTED_IMAGE_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class UnsafeImageError(ValueError):
    pass


@dataclass(frozen=True)
class SafeImage:
    content: bytes
    media_type: str
    width: int
    height: int


def create_safe_derivative(content: bytes, media_type: str, settings: Settings) -> SafeImage:
    expected_format = SUPPORTED_IMAGE_TYPES.get(media_type)
    if expected_format is None:
        raise UnsafeImageError("Unsupported image content type")
    if len(content) > settings.max_artifact_bytes:
        raise UnsafeImageError("Image exceeds configured size limit")
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            if image.format != expected_format:
                raise UnsafeImageError("Image bytes do not match declared content type")
            if max(image.size) > settings.max_image_dimension:
                raise UnsafeImageError("Image dimensions exceed configured limit")
            converted = image.convert("RGB") if expected_format == "JPEG" else image.copy()
            output = io.BytesIO()
            save_format = "PNG" if expected_format == "PNG" else expected_format
            converted.save(output, format=save_format, exif=b"")
            return SafeImage(output.getvalue(), media_type, image.width, image.height)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UnsafeImageError("Image is corrupt or unsafe") from exc
