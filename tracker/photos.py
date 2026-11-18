"""Photo storage: resize, make a thumbnail, save under a random name."""

import uuid
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "MPO"}


def _shrink(image, edge):
    copy = image.copy()
    copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    return copy


def process_upload(uploaded_file):
    """Validate an uploaded image and save a resized copy and a thumbnail.

    Returns (file_name, thumbnail_file_name, size_in_bytes). Raises
    ValidationError if the file is too big or not an image.
    """
    if uploaded_file.size > settings.PHOTO_MAX_UPLOAD_BYTES:
        raise ValidationError(f"{uploaded_file.name} is too large (limit {settings.PHOTO_MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    try:
        image = Image.open(uploaded_file)
        image_format = image.format
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationError(f"{uploaded_file.name} is not a photo this program can read (use JPEG or PNG).") from None
    if image_format not in ALLOWED_FORMATS:
        raise ValidationError(f"{uploaded_file.name}: {image_format} images are not supported (use JPEG or PNG).")

    image = ImageOps.exif_transpose(image)  # phones store rotation in EXIF
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    stem = uuid.uuid4().hex
    file_name, thumb_name = f"{stem}.jpg", f"{stem}_thumb.jpg"
    folder = settings.PHOTOS_DIR

    full = _shrink(image, settings.PHOTO_MAX_EDGE)
    buffer = BytesIO()
    full.save(buffer, "JPEG", quality=85, optimize=True)  # EXIF (incl. GPS) is dropped
    (folder / file_name).write_bytes(buffer.getvalue())

    thumb = _shrink(image, settings.PHOTO_THUMB_EDGE)
    thumb.save(folder / thumb_name, "JPEG", quality=80)

    return file_name, thumb_name, len(buffer.getvalue())
