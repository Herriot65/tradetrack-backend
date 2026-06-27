import uuid
from functools import lru_cache

from django.conf import settings

ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@lru_cache(maxsize=1)
def _get_client():
    from supabase import create_client

    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_ANON_KEY (or SUPABASE_SERVICE_ROLE_KEY) must be set."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


def upload_screenshot(trade_id: int, file_obj) -> str:
    """Upload an image file to Supabase Storage and return its public URL."""
    content_type = getattr(file_obj, "content_type", "")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(f"Unsupported file type '{content_type}'. Allowed: png, jpg, webp.")

    file_obj.seek(0, 2)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > MAX_FILE_SIZE:
        raise ValueError(f"File exceeds 10 MB limit ({size} bytes).")

    ext = file_obj.name.rsplit(".", 1)[-1].lower() if "." in file_obj.name else "jpg"
    path = f"{trade_id}/{uuid.uuid4()}.{ext}"

    client = _get_client()
    client.storage.from_(settings.SUPABASE_SCREENSHOTS_BUCKET).upload(
        path, file_obj.read(), {"content-type": content_type}
    )

    return client.storage.from_(settings.SUPABASE_SCREENSHOTS_BUCKET).get_public_url(path)


def delete_screenshot(image_url: str) -> None:
    """Remove a file from Supabase Storage given its public URL."""
    bucket = settings.SUPABASE_SCREENSHOTS_BUCKET
    # URL pattern: .../storage/v1/object/public/<bucket>/<path>
    marker = f"/object/public/{bucket}/"
    idx = image_url.find(marker)
    if idx == -1:
        return
    path = image_url[idx + len(marker):]
    _get_client().storage.from_(bucket).remove([path])
