from django.urls import path

from . import views

urlpatterns = [
    # Server
    path("", views.heartbeat, name="heartbeat"),
    path(
        "extract/doc/text/",
        views.extract_doc_content,
        name="convert-doc-to-text",
    ),
    path("convert/image/pdf/", views.image_to_pdf, name="image-to-pdf"),
    path("convert/images/pdf/", views.images_to_pdf, name="images-to-pdf"),
    path("convert/pdf/thumbnail/", views.make_png_thumbnail, name="thumbnail"),
    path(
        "convert/pdf/thumbnails/",
        views.make_png_thumbnails_from_range,
        name="thumbnails",
    ),
    path("convert/audio/mp3/", views.convert_audio, name="convert-audio"),
    path("utils/page-count/pdf/", views.page_count, name="page_count"),
    path("utils/mime-type/", views.extract_mime_type, name="mime_type"),
    path(
        "utils/file/extension/", views.extract_extension, name="file-extension"
    ),
    path(
        "utils/audio/duration/",
        views.fetch_audio_duration,
        name="audio-duration",
    ),
    path("utils/add/text/pdf/", views.embed_text, name="add-text-to-pdf"),
    path(
        "utils/document-number/pdf/",
        views.get_document_number,
        name="document-number-pdf",
    ),
]
