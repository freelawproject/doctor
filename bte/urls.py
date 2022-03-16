from django.urls import path

from . import views

urlpatterns = [
    # Server
    path("", views.heartbeat, name="heartbeat"),
    # Extractors
    path("text/", views.extract_pdf, name="text"),
    path("extract-doc-content/", views.extract_doc_content, name="extract-doc-content"),
    path("pg-count/", views.page_count, name="page_count"),
    path("mime-type/", views.extract_mime_type, name="mime_type"),
    path("document/pdf-to-text/", views.pdf_to_text, name="pdf-to-text"),
    # Converters
    path("image-to-pdf/", views.image_to_pdf, name="image-to-pdf"),
    path("thumbnail/", views.make_png_thumbnail, name="thumbnail"),
    path("images-to-pdf/", views.images_to_pdf, name="images-to-pdf"),
    # Audio files
    path("convert-audio/", views.convert_audio, name="convert-audio"),
    # Legacy URLs
    path("document/page_count", views.page_count, name="page_count"),
    path("document/thumbnail", views.make_png_thumbnail, name="thumbnail"),
]
