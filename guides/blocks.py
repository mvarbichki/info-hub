from wagtail import blocks
from wagtail.documents.blocks import DocumentChooserBlock
from wagtail.images.blocks import ImageChooserBlock

VIDEO_EXTENSIONS = {"mp4", "m4v", "webm", "mov", "ogv"}

SIMPLE_TEXT_FEATURES = ["bold", "italic", "ol", "ul", "link", "document-link"]


class ImageBlock(blocks.StructBlock):
    image = ImageChooserBlock(label="Снимка")
    caption = blocks.CharBlock(label="Надпис под снимката", required=False)

    class Meta:
        icon = "image"
        label = "Снимка"
        template = "guides/blocks/image.html"


class VideoBlock(blocks.StructBlock):
    video = DocumentChooserBlock(
        label="Видео файл",
        help_text="Изберете или качете (с плъзгане) видео файл – препоръчително MP4.",
    )
    caption = blocks.CharBlock(label="Надпис под видеото", required=False)

    class Meta:
        icon = "media"
        label = "Видео"
        template = "guides/blocks/video.html"

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context)
        document = value.get("video")
        context["is_video"] = bool(document) and document.file_extension.lower() in VIDEO_EXTENSIONS
        return context


class StepBlock(blocks.StructBlock):
    title = blocks.CharBlock(label="Какво да се направи", required=False)
    text = blocks.RichTextBlock(label="Подробности", required=False, features=SIMPLE_TEXT_FEATURES)
    images = blocks.ListBlock(ImageChooserBlock(), label="Снимки към стъпката", default=[])

    class Meta:
        icon = "list-ol"
        label = "Стъпка"


class NoteBlock(blocks.StructBlock):
    style = blocks.ChoiceBlock(
        label="Вид",
        choices=[("info", "Информация"), ("tip", "Съвет"), ("warning", "Внимание")],
        default="info",
    )
    text = blocks.RichTextBlock(label="Текст", features=SIMPLE_TEXT_FEATURES)

    class Meta:
        icon = "warning"
        label = "Забележка"
        template = "guides/blocks/note.html"


class FileBlock(blocks.StructBlock):
    document = DocumentChooserBlock(label="Файл")
    title = blocks.CharBlock(
        label="Текст на бутона", required=False, help_text="Ако е празно, се показва името на файла."
    )

    class Meta:
        icon = "doc-full"
        label = "Файл за изтегляне"
        template = "guides/blocks/file.html"


class GuideStreamBlock(blocks.StreamBlock):
    heading = blocks.CharBlock(label="Подзаглавие", icon="title", form_classname="title")
    text = blocks.RichTextBlock(label="Текст", icon="pilcrow", features=SIMPLE_TEXT_FEATURES)
    steps = blocks.ListBlock(
        StepBlock(), label="Стъпки (номерирани)", icon="list-ol", template="guides/blocks/steps.html"
    )
    image = ImageBlock()
    video = VideoBlock()
    note = NoteBlock()
    file = FileBlock()
