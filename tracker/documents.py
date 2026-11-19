"""Document storage: check the file and save it under a random name in DOCUMENTS_DIR."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError

# Extension -> content type sent when the file is opened.
ALLOWED = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    "txt": "text/plain",
    "csv": "text/csv",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "zip": "application/zip",
}
# Opened in the browser tab; everything else is downloaded.
INLINE = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp", "text/plain"}


def allowed_list():
    return ", ".join(sorted({e.upper() for e in ALLOWED} - {"JPEG"}))


def save_document(uploaded_file):
    """Validate and store an upload. Returns (file_name, original_name, content_type, size)."""
    original = (uploaded_file.name or "document").replace("\\", "/").rsplit("/", 1)[-1][:255]
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED:
        raise ValidationError(f"{original}: this type of file can't be added. Use one of: {allowed_list()}.")
    limit = settings.DOCUMENT_MAX_UPLOAD_BYTES
    if uploaded_file.size > limit:
        raise ValidationError(f"{original} is too large (limit {limit // (1024 * 1024)} MB).")
    if uploaded_file.size == 0:
        raise ValidationError(f"{original} is empty.")
    file_name = f"{uuid.uuid4().hex}.{ext}"
    with open(settings.DOCUMENTS_DIR / file_name, "xb") as out:
        for chunk in uploaded_file.chunks():
            out.write(chunk)
    return file_name, original, ALLOWED[ext], uploaded_file.size
