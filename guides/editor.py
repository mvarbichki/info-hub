"""The post editor in /manage/: its list of blocks <-> the guide's StreamField body.

The editor works with a flat list of blocks, sent as JSON:
    {"type": "step", "title": "...", "html": "<p>...</p>", "images": [{"id": 5}, ...]}
    {"type": "text", "html": "..."}            {"type": "heading", "text": "..."}
    {"type": "image", "image": {"id": 5}, "caption": "..."}
    {"type": "video", "document": {"id": 7}, "caption": "..."}
    {"type": "note", "style": "tip", "html": "..."}
    {"type": "file", "document": {"id": 8}, "title": "..."}
Steps that follow each other are stored as one numbered "steps" block and split again for editing.
Text is cleaned with Wagtail's own rich text whitelister (bold, italic, lists, links only).
"""

import json
from functools import cache

from bs4 import BeautifulSoup
from wagtail.admin.rich_text.converters.editor_html import EditorHTMLConverter
from wagtail.rich_text import RichText, expand_db_html

from .blocks import VIDEO_EXTENSIONS
from .media import describe

TEXT_FEATURES = ["bold", "italic", "ol", "ul", "link"]
NOTE_STYLES = ("info", "tip", "warning")
MAX_BLOCKS = 300
MAX_LINE = 255


class EditorError(Exception):
    """The content can't be saved. The message is shown to the user as is."""


@cache
def _converter():
    return EditorHTMLConverter(features=TEXT_FEATURES)


def clean_html(html):
    """Editor HTML -> Wagtail rich text. Empty text gives ""."""
    if not isinstance(html, str):
        return ""
    cleaned = _converter().to_database_format(html.replace("&nbsp;", " ").replace(" ", " "))
    if not BeautifulSoup(cleaned, "html.parser").get_text().strip():
        return ""
    # Wagtail's own editor uses <b>/<i>, so the posts can still be opened in /admin/.
    return cleaned.replace("<strong>", "<b>").replace("</strong>", "</b>").replace("<em>", "<i>").replace("</em>", "</i>")


def _line(value):
    return " ".join(value.split())[:MAX_LINE] if isinstance(value, str) else ""


def _media_id(value):
    if isinstance(value, dict):
        value = value.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# --- body -> editor -------------------------------------------------------------

def to_editor(body):
    """The editor's blocks for a guide's body (images/documents that no longer exist are left out)."""
    blocks = []
    for block in body:
        value = block.value
        if block.block_type == "heading":
            blocks.append({"type": "heading", "text": value})
        elif block.block_type == "text":
            blocks.append({"type": "text", "html": expand_db_html(value.source)})
        elif block.block_type == "steps":
            for step in value:
                blocks.append({
                    "type": "step",
                    "title": step["title"],
                    "html": expand_db_html(step["text"].source) if step["text"] else "",
                    "images": [describe(image) for image in step["images"] if image],
                })
        elif block.block_type == "image" and value["image"]:
            blocks.append({"type": "image", "image": describe(value["image"]), "caption": value["caption"]})
        elif block.block_type == "video" and value["video"]:
            blocks.append({"type": "video", "document": describe(value["video"]), "caption": value["caption"]})
        elif block.block_type == "note":
            blocks.append({"type": "note", "style": value["style"], "html": expand_db_html(value["text"].source)})
        elif block.block_type == "file" and value["document"]:
            blocks.append({"type": "file", "document": describe(value["document"]), "title": value["title"]})
    return blocks


# --- editor -> body -------------------------------------------------------------

def parse(raw):
    """The posted JSON as a list of block dicts (unknown entries are dropped)."""
    try:
        blocks = json.loads(raw or "[]")
    except ValueError:
        raise EditorError("Съдържанието не можа да бъде прочетено. Презаредете страницата и опитайте пак.")
    if not isinstance(blocks, list):
        raise EditorError("Съдържанието не можа да бъде прочетено. Презаредете страницата и опитайте пак.")
    if len(blocks) > MAX_BLOCKS:
        raise EditorError(f"Публикацията има над {MAX_BLOCKS} блока. Разделете я на няколко публикации.")
    return [b for b in blocks if isinstance(b, dict)]


def media_ids(blocks):
    """(image ids, document ids) the blocks refer to."""
    images, documents = [], []
    for block in blocks:
        if block.get("type") == "step" and isinstance(block.get("images"), list):
            images += [_media_id(i) for i in block["images"]]
        elif block.get("type") == "image":
            images.append(_media_id(block.get("image")))
        elif block.get("type") in ("video", "file"):
            documents.append(_media_id(block.get("document")))
    return [i for i in images if i], [d for d in documents if d]


def to_body(blocks, images, documents):
    """StreamField content for the blocks. `images`/`documents` map id -> object the user may use.

    Empty blocks are dropped. Returns (body, used images, used documents) in page order.
    """
    body, steps = [], []
    used_images, used_documents = [], []

    def image(value):
        image_id = _media_id(value)
        if image_id is None:
            return None
        if image_id not in images:
            raise EditorError("Една от снимките вече не съществува. Махнете я и я качете отново.")
        if images[image_id] not in used_images:
            used_images.append(images[image_id])
        return images[image_id]

    def document(value, video=False):
        document_id = _media_id(value)
        if document_id is None:
            return None
        if document_id not in documents:
            raise EditorError("Един от файловете вече не съществува. Махнете го и го качете отново.")
        found = documents[document_id]
        if video and found.file_extension.lower() not in VIDEO_EXTENSIONS:
            raise EditorError(f"„{found.title}“ не е видео.")
        if found not in used_documents:
            used_documents.append(found)
        return found

    def flush_steps():
        if steps:
            body.append(("steps", list(steps)))
            steps.clear()

    for block in blocks:
        kind = block.get("type")
        if kind == "step":
            raw_images = block.get("images") if isinstance(block.get("images"), list) else []
            step = {"title": _line(block.get("title")), "text": RichText(clean_html(block.get("html"))),
                    "images": [found for found in map(image, raw_images) if found]}
            if step["title"] or step["text"].source or step["images"]:
                steps.append(step)
            continue

        flush_steps()
        if kind == "heading":
            if _line(block.get("text")):
                body.append(("heading", _line(block.get("text"))))
        elif kind == "text":
            if html := clean_html(block.get("html")):
                body.append(("text", RichText(html)))
        elif kind == "image":
            if found := image(block.get("image")):
                body.append(("image", {"image": found, "caption": _line(block.get("caption"))}))
        elif kind == "video":
            if found := document(block.get("document"), video=True):
                body.append(("video", {"video": found, "caption": _line(block.get("caption"))}))
        elif kind == "note":
            if html := clean_html(block.get("html")):
                style = block.get("style") if block.get("style") in NOTE_STYLES else "info"
                body.append(("note", {"style": style, "text": RichText(html)}))
        elif kind == "file":
            if found := document(block.get("document")):
                body.append(("file", {"document": found, "title": _line(block.get("title"))}))
    flush_steps()
    return body, used_images, used_documents
