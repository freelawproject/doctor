import logging
import mimetypes
import re
import shutil
from http.client import BAD_REQUEST
from tempfile import NamedTemporaryFile, TemporaryDirectory

import eyed3
import img2pdf
import magic
import pytesseract
import requests
from django.core.exceptions import BadRequest
from django.http import FileResponse, HttpResponse, JsonResponse
from lxml.etree import ParserError, XMLSyntaxError
from magika import Magika
from PIL import Image
from PyPDF2 import PdfReader, PdfWriter
from pytesseract import Output

from doctor.forms import (
    AudioForm,
    BaseFileForm,
    DocumentForm,
    ImagePdfForm,
    MimeForm,
    ThumbnailForm,
)
from doctor.lib.utils import (
    cleanup_form,
    log_sentry_event,
    make_page_with_text,
    make_png_thumbnail_for_instance,
    make_png_thumbnails,
    strip_metadata_from_bytes,
    strip_metadata_from_path,
    strip_metadata_with_exiftool,
)
from doctor.tasks import (
    convert_tiff_to_pdf_bytes,
    convert_to_mp3,
    convert_to_ogg,
    download_images,
    extract_from_doc,
    extract_from_docx,
    extract_from_html,
    extract_from_pdf,
    extract_from_txt,
    extract_from_wpd,
    extract_recap_pdf,
    get_document_number_from_pdf,
    get_page_count,
    get_xray,
    make_pdftotext_process,
    rasterize_pdf,
    set_mp3_meta_data,
)

logger = logging.getLogger(__name__)

magika = Magika()


def heartbeat(request) -> HttpResponse:
    """Heartbeat endpoint

    :param request: The request object
    :return: Heartbeat
    """
    return HttpResponse("Heartbeat detected.")


def image_to_pdf(request) -> HttpResponse:
    """Converts an uploaded image to a pdf and returns the bytes

    :param request: The request object
    :return: HttpResponse
    """

    form = DocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)

    fp = form.cleaned_data["fp"]

    try:
        image = Image.open(fp)
        pdf_bytes = convert_tiff_to_pdf_bytes(image)
        cleaned_pdf_bytes = strip_metadata_from_bytes(pdf_bytes)
        with NamedTemporaryFile(suffix=".pdf") as output:
            with open(output.name, "wb") as f:
                f.write(cleaned_pdf_bytes)
            return HttpResponse(cleaned_pdf_bytes)
    finally:
        cleanup_form(form)


def extract_recap_document(request) -> JsonResponse:
    """Extract Recap Documents

    :param request: The request object
    :return: JsonResponse
    """
    form = DocumentForm(request.GET, request.FILES)
    if not form.is_valid():
        return JsonResponse(
            {
                "err": "Failed validation",
            },
            status=BAD_REQUEST,
        )
    filepath = form.cleaned_data["fp"]

    try:
        strip_margin = form.cleaned_data["strip_margin"]
        content, extracted_by_ocr = extract_recap_pdf(
            filepath=filepath,
            strip_margin=strip_margin,
        )
        return JsonResponse(
            {
                "content": content,
                "extracted_by_ocr": extracted_by_ocr,
            }
        )
    finally:
        cleanup_form(form)


def extract_doc_content(request) -> JsonResponse | HttpResponse:
    """Extract txt from different document types.

    :param request: django request containing the uploaded file
    :return: The content of a document/error message.
    :type: json object
    """
    form = DocumentForm(request.GET, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    ocr_available = form.cleaned_data["ocr_available"]
    extension = form.cleaned_data["extension"]
    fp = form.cleaned_data["fp"]
    extracted_by_ocr = False
    err = ""
    # We keep the original file name to use it for debugging purposes, you can find it in local_path (Opinion) field
    # or filepath_local (AbstractPDF).
    original_filename = form.cleaned_data["original_filename"]
    try:
        if extension == "pdf":
            content, err, returncode, extracted_by_ocr = extract_from_pdf(
                fp, ocr_available
            )
        elif extension == "doc":
            content, err, returncode = extract_from_doc(fp)
        elif extension == "docx":
            content, err, returncode = extract_from_docx(fp)
        elif extension == "html":
            content, err, returncode = extract_from_html(fp)
        elif extension == "txt":
            content, err, returncode = extract_from_txt(fp)
        elif extension == "wpd":
            content, err, returncode = extract_from_wpd(fp)
        else:
            returncode = 1
            err = "Unable to extract content due to unknown extension"
            content = ""

        if returncode != 0:
            log_sentry_event(
                logger=logger,
                level=logging.ERROR,
                message="Unable to extract document content",
                extra={
                    "file_name": original_filename,
                    "err": err,
                },
                exc_info=True,
            )
            pass

    except (XMLSyntaxError, ParserError) as e:
        error_message = "HTML cleaning failed due to ParserError."
        if isinstance(e, XMLSyntaxError):
            error_message = "HTML cleaning failed due to XMLSyntaxError."

        log_sentry_event(
            logger=logger,
            level=logging.ERROR,
            message=error_message,
            extra={
                "file_name": original_filename,
                "exception_type": type(e).__name__,
                "exception_message": str(e),
            },
            exc_info=True,
        )
        content = "Unable to extract the content from this file. Please try reading the original."

    # Get page count if you can
    page_count = get_page_count(fp, extension)
    cleanup_form(form)
    return JsonResponse(
        {
            "content": content,
            "err": err,
            "extension": extension,
            "extracted_by_ocr": extracted_by_ocr,
            "page_count": page_count,
        }
    )


def make_png_thumbnail(request) -> HttpResponse:
    """Make a thumbnail of the first page of a PDF and return it.

    :param request: django request containing the uploaded file
    :return: A response containing our file and any errors
    :type: HTTPS response
    """
    form = ThumbnailForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    document = form.cleaned_data["file"]
    with NamedTemporaryFile(suffix=".pdf") as tmp:
        with open(tmp.name, "wb") as f:
            f.write(document.read())
        thumbnail, _, _ = make_png_thumbnail_for_instance(
            tmp.name, form.cleaned_data["max_dimension"]
        )
        return HttpResponse(thumbnail)


def make_png_thumbnails_from_range(request) -> HttpResponse:
    """Make a zip file that contains a thumbnail for each page requested.

    :param request: django request containing the uploaded file
    :return: A response containing our zip and any errors
    :type: HTTPS response
    """
    form = ThumbnailForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)

    directory = TemporaryDirectory()
    with NamedTemporaryFile(suffix=".pdf", mode="r+b") as temp_pdf:
        temp_pdf.write(form.cleaned_data["file"].read())

        make_png_thumbnails(
            temp_pdf.name,
            form.cleaned_data["max_dimension"],
            form.cleaned_data["pages"],
            directory,
        )

    with NamedTemporaryFile(suffix=".zip") as tmp_zip:
        filename = shutil.make_archive(
            f"{tmp_zip.name[:-4]}", "zip", directory.name
        )
        return FileResponse(open(filename, "rb"))


def xray(request) -> JsonResponse:
    """Check PDF for bad redactions

    :param request: django request containing the uploaded file
    :return: json with bounding boxes and text
    """
    form = DocumentForm(request.POST, request.FILES)
    try:
        if not form.is_valid():
            return JsonResponse(
                {"error": True, "msg": "Failed validation"}, status=BAD_REQUEST
            )
        extension = form.cleaned_data["extension"]
        if extension.casefold() != "pdf":
            return JsonResponse(
                {"error": True, "msg": "Failed file type"}, status=BAD_REQUEST
            )
        results = get_xray(form.cleaned_data["fp"])
        if results.get("error", False):
            return JsonResponse(results, status=BAD_REQUEST)
    finally:
        cleanup_form(form)
    return JsonResponse({"error": False, "results": results})


def page_count(request) -> HttpResponse:
    """Get page count from PDF

    :param request: django request containing the uploaded file
    :return: Page count
    """
    form = DocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)

    fp = form.cleaned_data["fp"]

    try:
        extension = form.cleaned_data["extension"]
        pg_count = get_page_count(fp, extension)
        return HttpResponse(pg_count)
    finally:
        cleanup_form(form)


def extract_mime_type(request) -> JsonResponse | HttpResponse:
    """Identify the MIME type of an uploaded document using Magika, with
    fallbacks for formats Magika fails to recognize.

    :param request: django request containing the file to check
    :return: MIME type as JSON
    """
    form = MimeForm(request.GET, request.FILES)
    if not form.is_valid():
        # Not valid, try to remove file
        cleanup_form(form)
        return HttpResponse("Failed validation", status=BAD_REQUEST)

    fp = form.cleaned_data["fp"]

    try:
        strip_metadata_with_exiftool(fp)

        with open(fp, "rb") as f:
            content = f.read()

        result = magika.identify_bytes(content)
        mime = result.output.mime_type

        # --- Fallbacks and corrections ---
        header = content[:64]

        # WordPerfect: Magika often returns pickle/octet-stream
        if mime in (
            "application/x-python-pickle",
            "application/octet-stream",
        ) and (header.startswith(b"\xffWPC") or b"WPC" in header[:8]):
            mime = "application/vnd.wordperfect"

        # ASF container → WMA/WMV
        elif header.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11"):
            if b"WMA" in header or b"WM/" in header:
                mime = "audio/x-ms-wma"
            else:
                mime = "video/x-ms-wmv"
        # PDF (misdetected as .bin)
        elif re.search(rb"%PDF-[0-9]+(\.[0-9]+)?", content[:1024]):
            mime = "application/pdf"
        # Audio: quick signature checks for FLAC/AAC/OGG/RM
        elif header.startswith(b"fLaC"):
            mime = "audio/flac"
        elif header[:2] in (b"\xff\xf1", b"\xff\xf9"):
            mime = "audio/aac"
        elif header.startswith(b"OggS"):
            mime = "audio/ogg"
        elif header.startswith(b"\x2e\x52\x4d\x46"):
            mime = "application/vnd.rn-realmedia"

        return JsonResponse({"mimetype": mime})
    finally:
        cleanup_form(form)


def extract_extension(request) -> HttpResponse:
    """A handful of workarounds for getting extensions we can trust

    :param request: django request containing the uploaded file
    :returns: the file extension as plain text
    """
    form = MimeForm(request.GET, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)

    fp = form.cleaned_data["fp"]

    try:
        # avoid "referenced before assignment" warnings from analyzer
        content = b""

        strip_metadata_with_exiftool(fp)

        with open(fp, "rb") as f:
            content = f.read()

        # Normalize to bytes
        if isinstance(content, str):
            content = content.encode("utf-8", errors="ignore")

        result = magika.identify_bytes(content)
        mime = result.output.mime_type
        exts = result.output.extensions or []

        if exts:
            # Usually the first one is the best
            extension = "." + exts[0]
        else:
            # Get default extension using magika mime, it could be ".bin"
            extension = mimetypes.guess_extension(mime)
            # If Magika produced octet-stream, try libmagic
            if mime == "application/octet-stream":
                mime_magic = magic.from_buffer(content, mime=True)

                # If libmagic provided a better mime, use it
                if mime_magic and mime_magic != "application/octet-stream":
                    mime = mime_magic
                    extension = mimetypes.guess_extension(mime)

            if not extension:
                # Fallback to mimetypes lib using magika mime
                log_sentry_event(
                    logger=logger,
                    level=logging.ERROR,
                    message="Magika failed to infer file extension, libmagic failed too.",
                    extra={
                        "file_name": form.cleaned_data["original_filename"],
                        "file_size": len(content),
                        "mimetype": mime,
                    },
                    exc_info=True,
                )

                # Default unknown extension, do not blank it
                extension = mimetypes.guess_extension(mime) or ".bin"

        # --- Handle common Magika misclassifications ---
        if mime == "application/vnd.rn-realmedia":
            extension = ".rm"
        if mime == "application/CDFV2" or mime.startswith("CDFV2"):
            mime = "application/msword"
            extension = ".doc"
        elif mime == "application/corel-wp":
            mime = "application/vnd.wordperfect"
            extension = ".wpd"
        elif mime in ("text/x-c", "text/x-csrc"):
            mime = "text/plain"
            extension = ".txt"
        elif mime == "application/vnd.wordperfect" or mime.startswith(
            "application/x-wordperfect"
        ):
            extension = ".wpd"
        else:
            # Fallback audio pattern
            if re.findall(
                r"(Audio file with ID3.*MPEG.*layer III)|(.*Audio Media.*)",
                str(content[:200]),
            ):
                mime = "audio/mpeg"
                extension = ".mp3"

        # --- WordPerfect misidentified as pickle or generic binary ---
        if mime in (
            "application/x-python-pickle",
            "application/octet-stream",
        ) and (content.startswith(b"\xffWPC") or b"WPC" in content[:8]):
            mime = "application/vnd.wordperfect"
            extension = ".wpd"

        # --- ASF/WMA header detection ---
        if content.startswith(b"\x30\x26\xb2\x75\x8e\x66\xcf\x11"):
            mime = "audio/x-ms-wma"
            extension = ".wma"

        # --- Misclassified .obj or .bin ---
        if extension == ".obj":
            if b"PDF" in content[0:40]:
                extension = ".pdf"
            else:
                extension = ".wpd"
        elif extension == ".bin":
            pattern = rb"%PDF-[0-9]+(\.[0-9]+)?"
            if re.search(pattern, content[:1024]):
                extension = ".pdf"

        fixes = {
            ".htm": ".html",
            ".wsdl": ".html",
            ".ksh": ".txt",
            ".asf": ".wma",
            ".dot": ".doc",
            ".mpga": ".mp3",
            ".x-ms-wma": ".wma",
            ".x-ms-wmv": ".wmv",
            ".vnd.wordperfect": ".wpd",
        }

        final_ext = fixes.get(extension, extension).lower()
        return HttpResponse(final_ext)
    finally:
        cleanup_form(form)


def pdf_to_text(request) -> JsonResponse | HttpResponse:
    """Extract text from text based PDFs immediately.

    :param request: The request object
    :return: JsonResponse object
    """
    form = DocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)

    filepath = form.cleaned_data["fp"]

    try:
        content, err, _ = make_pdftotext_process(filepath)
        return JsonResponse(
            "content",
            content,
            "err",
            err,
        )
    finally:
        cleanup_form(form)


def images_to_pdf(request) -> HttpResponse:
    """Converts a list of images from urls into a single pdf file

    :param request: The request object
    :return: HttpResponse object
    """
    form = ImagePdfForm(request.GET)
    if not form.is_valid():
        raise BadRequest("Invalid form")
    sorted_urls = form.cleaned_data["sorted_urls"]

    if len(sorted_urls) > 1:
        image_list = download_images(sorted_urls)
        with NamedTemporaryFile(suffix=".pdf") as tmp:
            with open(tmp.name, "wb") as f:
                f.write(img2pdf.convert(image_list))
            cleaned_pdf_bytes = strip_metadata_from_path(tmp.name)
    else:
        tiff_image = Image.open(
            requests.get(sorted_urls[0], stream=True, timeout=60 * 5).raw
        )
        pdf_bytes = convert_tiff_to_pdf_bytes(tiff_image)
        cleaned_pdf_bytes = strip_metadata_from_bytes(pdf_bytes)
    return HttpResponse(cleaned_pdf_bytes, content_type="application/pdf")


def fetch_audio_duration(request) -> HttpResponse:
    """Fetch audio duration from file.

    :param request: django request containing the uploaded file
    :return: HttpResponse object
    """
    try:
        form = AudioForm(request.GET, request.FILES)
        if not form.is_valid():
            return HttpResponse("Failed validation", status=BAD_REQUEST)
        with NamedTemporaryFile(suffix=".mp3") as tmp:
            with open(tmp.name, "wb") as f:
                for chunk in form.cleaned_data["file"].chunks():
                    f.write(chunk)
            mp3_file = eyed3.load(tmp.name)
            return HttpResponse(mp3_file.info.time_secs)
    except Exception as e:
        return HttpResponse(str(e))


def convert_audio(request, output_format: str) -> FileResponse | HttpResponse:
    """Converts an uploaded audio file to the specified output format and
    updates its metadata.

    :param request: django request containing the uploaded file
    :param output_format: audio format expected
    :return: Converted audio
    """
    form = AudioForm(request.GET, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)

    try:
        filepath = form.cleaned_data["fp"]
        media_file = form.cleaned_data["file"]
        audio_data = {k: v[0] for k, v in dict(request.GET).items()}
        match output_format:
            case "mp3":
                convert_to_mp3(filepath, media_file)
                set_mp3_meta_data(audio_data, filepath)
            case "ogg":
                convert_to_ogg(filepath, media_file)
            case _:
                raise NotImplementedError
        response = FileResponse(
            open(filepath, "rb")  # noqa: SIM115 FileResponse closes the file
        )
        return response
    finally:
        cleanup_form(form)


def embed_text(request) -> FileResponse | HttpResponse:
    """Embed text onto an image PDF.

    :param request: django request containing the uploaded file
    :return: Embedded PDF
    """
    form = DocumentForm(request.GET, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    fp = form.cleaned_data["fp"]

    try:
        with NamedTemporaryFile(suffix=".tiff") as destination:
            rasterize_pdf(fp, destination.name)
            data = pytesseract.image_to_data(
                destination.name, output_type=Output.DICT
            )
            image = Image.open(destination.name)
            w, h = image.width, image.height
            output = PdfWriter()
            with open(fp, "rb") as f:
                existing_pdf = PdfReader(f)
                for page in range(0, len(existing_pdf.pages)):
                    packet = make_page_with_text(page + 1, data, h, w)
                    new_pdf = PdfReader(packet)
                    page = existing_pdf.pages[page]
                    page.merge_page(new_pdf.pages[0])
                    output.add_page(page)

            with NamedTemporaryFile(suffix=".pdf") as pdf_destination:
                with open(pdf_destination.name, "wb") as outputStream:
                    output.write(outputStream)
                response = FileResponse(
                    open(  # noqa: SIM115 FileResponse closes the file
                        pdf_destination.name, "rb"
                    )
                )
                return response
    finally:
        cleanup_form(form)


def get_document_number(request) -> HttpResponse:
    """Get PACER document number from PDF

    :param request: The request object
    :return: PACER document number
    """

    form = BaseFileForm(request.GET, request.FILES)
    if not form.is_valid():
        validation_message = form.errors.get_json_data()["__all__"][0][
            "message"
        ]
        return HttpResponse(validation_message, status=BAD_REQUEST)
    fp = form.cleaned_data["fp"]

    try:
        document_number = get_document_number_from_pdf(fp)
        return HttpResponse(document_number)
    finally:
        cleanup_form(form)
