"""Pictures, videos and files uploaded in the post editor (/manage/).

Each file is uploaded on its own as soon as it is chosen (with a progress bar in the browser);
the post itself only sends the ids. Uploads that end up unused are removed by cleanup_media.
"""

import io
from pathlib import PurePath

from django.conf import settings
from django.core.files.images import ImageFile
from PIL import Image as PILImage
from PIL import ImageOps
from wagtail.documents.models import Document
from wagtail.images.models import Image

from .blocks import VIDEO_EXTENSIONS

MB = 1024 * 1024
KINDS = ("image", "video", "file")
# Pillow format -> file extension of the formats every browser shows. Others (BMP, TIFF) become PNG.
WEB_IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}
# Formats every browser plays. Others (e.g. .mov from an iPhone) are accepted with a warning.
WEB_VIDEO_EXTENSIONS = {"mp4", "m4v", "webm"}
THUMBNAIL = "max-320x240"


class UploadRefused(Exception):
    """The file can't be used. The message is shown to the user as is."""


def limit_mb(kind):
    return settings.INFOHUB_LIMITS_MB[kind]


def _extension(name):
    return PurePath(name).suffix.lower().lstrip(".")


def file_extensions():
    """Allowed types for „Файл за изтегляне“ (videos go in a video block)."""
    return [e for e in settings.WAGTAILDOCS_EXTENSIONS if e not in VIDEO_EXTENSIONS]


def save_upload(uploaded, kind, collection, user):
    """Store an uploaded file as a Wagtail Image or Document. Returns (object, warning or "")."""
    if kind not in KINDS:
        raise UploadRefused("Неизвестен вид файл.")
    if uploaded.size > limit_mb(kind) * MB:
        label = {"image": "Снимката", "video": "Видеото", "file": "Файлът"}[kind]
        tip = " Намалете видеото (напр. 720p) или го разделете на по-кратки части." if kind == "video" else ""
        raise UploadRefused(f"{label} „{uploaded.name}“ е {uploaded.size / MB:.0f} MB, а максимумът е {limit_mb(kind)} MB.{tip}")
    if kind == "image":
        return _save_image(uploaded, collection, user), ""

    extension = _extension(uploaded.name)
    warning = ""
    if kind == "video":
        if extension not in VIDEO_EXTENSIONS:
            raise UploadRefused(f"„{uploaded.name}“ не е видео. Качете MP4 файл.")
        if extension not in WEB_VIDEO_EXTENSIONS:
            warning = f"Видеото „{uploaded.name}“ може да не тръгне във всеки браузър. Препоръчително е MP4."
    elif extension not in file_extensions():
        allowed = ", ".join(e.upper() for e in file_extensions())
        raise UploadRefused(f"Файлове от вида .{extension or '?'} не се приемат. Може: {allowed}.")

    document = Document(title=PurePath(uploaded.name).stem[:255], collection=collection, uploaded_by_user=user)
    document.file.save(PurePath(uploaded.name).name, uploaded, save=False)
    document.save()
    if kind == "file":
        from .previews import make_preview

        make_preview(document)  # Word/Excel/PowerPoint: a PDF copy to show in the post
    return document, warning


def _save_image(uploaded, collection, user):
    data = uploaded.read()
    try:
        picture = PILImage.open(io.BytesIO(data))
        picture.load()
    except Exception:
        raise UploadRefused(f"„{uploaded.name}“ не е снимка или е повреден файл.")

    extension = WEB_IMAGE_FORMATS.get(picture.format)
    if extension is None:
        # e.g. BMP/TIFF from old tools: convert to PNG
        data, extension = _encode(picture, "PNG"), ".png"
    elif picture.format != "GIF":  # GIFs may be animated: keep them as they are
        data = _shrink(picture, data)

    image = Image(
        title=PurePath(uploaded.name).stem[:255] or "снимка",
        collection=collection,
        uploaded_by_user=user,
        file=ImageFile(io.BytesIO(data), name=f"snimka{extension}"),
    )
    image.save()
    return image


def _encode(picture, image_format):
    buffer = io.BytesIO()
    if image_format == "JPEG":
        picture.convert("RGB").save(buffer, "JPEG", quality=85, optimize=True)
    else:
        picture.save(buffer, image_format, optimize=True)
    return buffer.getvalue()


def _shrink(picture, data):
    """Pictures wider than INFOHUB_IMAGE_MAX_WIDTH are scaled down (saves disk; the site never shows more)."""
    max_width = settings.INFOHUB_IMAGE_MAX_WIDTH
    if picture.width <= max_width:
        return data
    image_format = picture.format
    picture = ImageOps.exif_transpose(picture)  # phone photos: keep them the right way up
    picture.thumbnail((max_width, max_width * 10))
    return _encode(picture, image_format)


def describe(obj):
    """What the editor needs to show an uploaded image or document."""
    if isinstance(obj, Image):
        return {"id": obj.pk, "title": obj.title, "thumb": obj.get_rendition(THUMBNAIL).url}
    return {
        "id": obj.pk,
        "title": obj.title,
        "name": PurePath(obj.file.name).name,
        "size": obj.get_file_size() or 0,
        "url": obj.url,
    }
