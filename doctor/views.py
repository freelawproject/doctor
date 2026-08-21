import contextlib
import logging
import mimetypes
import os
import re
import shutil
import time
from http.client import BAD_REQUEST
from tempfile import NamedTemporaryFile, TemporaryDirectory

import eyed3
import img2pdf
import magic
import pytesseract
import requests
from centralia import CourtNotReleased, UnknownCourt
from centralia import read as centralia_read
from django.core.exceptions import BadRequest
from django.http import FileResponse, HttpResponse, JsonResponse
from lxml.etree import ParserError, XMLSyntaxError
from magika import Magika
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pytesseract import Output

from doctor.forms import (
    AudioForm,
    BaseFileForm,
    BitonalPdfForm,
    DocumentForm,
    ImagePdfForm,
    MimeForm,
    StructuredOpinionForm,
    ThumbnailForm,
)
from doctor.lib.bitonal import BitonalError, convert_pdf_to_bitonal
from doctor.lib.utils import (
    cleanup_form,
    log_sentry_event,
    log_upload_lifecycle,
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
    put_file_to_url,
    rasterize_pdf,
    set_mp3_meta_data,
    stream_url_to_file,
    validate_egress_url,
)

logger = logging.getLogger(__name__)

magika = Magika()


def heartbeat(request) -> HttpResponse:
    """Heartbeat endpoint

    :param request: The request object
    :return: Heartbeat
    """
    return HttpResponse("Heartbeat detected.")


@log_upload_lifecycle
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


@log_upload_lifecycle
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


def extract_structured_opinion(request) -> JsonResponse:
    """Extract a structured opinion from a digital PDF with centralia.

    For text-based court PDFs this replaces pdftotext/OCR: instead of a
    flat string, centralia returns the case-level criteria, one entry
    per opinion with its own html and text, and Harvard casebody XML.
    The payload is passed through as centralia returns it.

    centralia reads only the courts it has been ported to. An id no
    court declares fails as UNKNOWN_COURT, and a court still being
    worked on fails as COURT_NOT_RELEASED unless allow_pending is set.

    Deliberately a sync view: extraction is CPU-bound, so it runs on
    the worker's thread pool instead of blocking the event loop.

    :param request: The request object
    :return: JsonResponse with centralia's payload, or a JSON error
        carrying an error_code.
    """
    # Accept the court id as form data or query params: CL's
    # microservice() helper sends some endpoints one way, some the other.
    form = StructuredOpinionForm(request.POST or request.GET, request.FILES)
    try:
        if not form.is_valid():
            return JsonResponse(
                {
                    "success": False,
                    "error_code": "VALIDATION_FAILED",
                    "msg": form.errors.get_json_data(),
                },
                status=BAD_REQUEST,
            )
        try:
            payload = centralia_read(
                form.cleaned_data["fp"],
                court_id=form.cleaned_data["court_id"],
                allow_pending=form.cleaned_data["allow_pending"],
            )
        except UnknownCourt as e:
            return JsonResponse(
                {
                    "success": False,
                    "error_code": "UNKNOWN_COURT",
                    "msg": str(e),
                },
                status=BAD_REQUEST,
            )
        except CourtNotReleased as e:
            return JsonResponse(
                {
                    "success": False,
                    "error_code": "COURT_NOT_RELEASED",
                    "msg": str(e),
                },
                status=BAD_REQUEST,
            )
        return JsonResponse({"success": True, **payload})
    except Exception as e:
        # Swallowing the exception also swallows Django's Sentry
        # report, so log it explicitly.
        log_sentry_event(
            logger=logger,
            level=logging.ERROR,
            message="Structured opinion extraction failed",
            extra={
                "court_id": form.data.get("court_id"),
                "err": str(e),
            },
            exc_info=True,
        )
        return JsonResponse(
            {
                "success": False,
                "error_code": "EXTRACTION_FAILED",
                "msg": str(e),
            },
            status=500,
        )
    finally:
        cleanup_form(form)


@log_upload_lifecycle
async def extract_doc_content(request) -> JsonResponse | HttpResponse:
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
            (
                content,
                err,
                returncode,
                extracted_by_ocr,
            ) = await extract_from_pdf(fp, ocr_available)
        elif extension == "doc":
            content, err, returncode = await extract_from_doc(fp)
        elif extension == "docx":
            content, err, returncode = await extract_from_docx(fp)
        elif extension == "html":
            content, err, returncode = extract_from_html(fp)
        elif extension == "txt":
            content, err, returncode = extract_from_txt(fp)
        elif extension == "wpd":
            content, err, returncode = await extract_from_wpd(fp)
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


@log_upload_lifecycle
async def make_png_thumbnail(request) -> HttpResponse:
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
        thumbnail, _, _ = await make_png_thumbnail_for_instance(
            tmp.name, form.cleaned_data["max_dimension"]
        )
        return HttpResponse(thumbnail)


@log_upload_lifecycle
async def make_png_thumbnails_from_range(request) -> HttpResponse:
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

        await make_png_thumbnails(
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


@log_upload_lifecycle
def convert_pdf_bitonal(request) -> HttpResponse | JsonResponse:
    """Convert a PDF (or a page range of it) to bitonal CCITT G4.

    Input is a multipart upload or a presigned GET URL. With an
    output_url the result is uploaded there via presigned PUT and a
    JSON summary is returned; without one the PDF comes back inline.

    Deliberately a sync view: it runs on the worker's thread pool, so
    a long conversion does not block the event loop and the heartbeat
    stays responsive for kubernetes probes.

    :param request: The request object
    :return: JSON summary, inline PDF bytes, or a JSON error carrying
        an error_code from the documented taxonomy.
    """
    form = BitonalPdfForm(request.POST, request.FILES)
    downloaded_fp = None
    # is_valid() runs inside the try: the form's clean() writes the
    # upload to a temp file, and an exception escaping mid-clean (a
    # failed write, an aborted upload) must still hit cleanup_form.
    try:
        if not form.is_valid():
            return JsonResponse(
                {
                    "success": False,
                    "error_code": "VALIDATION_FAILED",
                    "msg": form.errors.get_json_data(),
                },
                status=BAD_REQUEST,
            )

        start = time.monotonic()
        input_url = form.cleaned_data["input_url"]
        output_url = form.cleaned_data["output_url"]
        # Both URLs are checked before any work: a blocked output_url
        # must not be discovered only after a long conversion, and a
        # rejected URL surfaces as EGRESS_BLOCKED via BitonalError.
        for url in (input_url, output_url):
            if url:
                validate_egress_url(url)
        if input_url:
            with NamedTemporaryFile(delete=False, suffix=".pdf") as downloaded:
                downloaded_fp = downloaded.name
            source_sha256 = stream_url_to_file(input_url, downloaded_fp)
            input_fp = downloaded_fp
        else:
            input_fp = form.cleaned_data["fp"]
            source_sha256 = form.cleaned_data["source_sha256"]

        with NamedTemporaryFile(suffix=".pdf") as output:
            metadata = convert_pdf_to_bitonal(
                input_fp,
                output.name,
                dpi=form.cleaned_data["dpi"],
                threshold=form.cleaned_data["threshold"],
                first_page=form.cleaned_data["first_page"],
                last_page=form.cleaned_data["last_page"],
            )
            if not output_url:
                # Streams from the open fd; the temp file is unlinked
                # when the with-block exits but the fd stays valid,
                # the same pattern convert_audio and embed_text use.
                return FileResponse(
                    open(output.name, "rb"),  # noqa: SIM115 FileResponse closes the file
                    content_type="application/pdf",
                )
            result_sha256 = put_file_to_url(
                output_url, output.name, "application/pdf"
            )
            return JsonResponse(
                {
                    "success": True,
                    **metadata,
                    "bytes": os.path.getsize(output.name),
                    "sha256": result_sha256,
                    "source_sha256": source_sha256,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                }
            )
    except BitonalError as e:
        return JsonResponse(
            {"success": False, "error_code": e.error_code, "msg": e.message},
            status=e.status,
        )
    except Exception as e:
        # The daemon reads error_code, so even unexpected failures
        # must return the documented JSON shape, not an HTML 500.
        # INTERNAL_ERROR (unlike CONVERSION_FAILED) means retryable.
        # Swallowing the exception also swallows Django's Sentry
        # report, so log it explicitly.
        log_sentry_event(
            logger=logger,
            level=logging.ERROR,
            message="Unexpected error during bitonal conversion",
            extra={
                "exception_type": type(e).__name__,
                "exception_message": str(e),
            },
            exc_info=True,
        )
        return JsonResponse(
            {"success": False, "error_code": "INTERNAL_ERROR", "msg": str(e)},
            status=500,
        )
    finally:
        cleanup_form(form)
        if downloaded_fp:
            with contextlib.suppress(FileNotFoundError):
                os.remove(downloaded_fp)


@log_upload_lifecycle
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


@log_upload_lifecycle
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


@log_upload_lifecycle
async def extract_mime_type(request) -> JsonResponse | HttpResponse:
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
        await strip_metadata_with_exiftool(fp)

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


@log_upload_lifecycle
async def extract_extension(request) -> HttpResponse:
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

        await strip_metadata_with_exiftool(fp)

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


@log_upload_lifecycle
async def pdf_to_text(request) -> JsonResponse | HttpResponse:
    """Extract text from text based PDFs immediately.

    :param request: The request object
    :return: JsonResponse object
    """
    form = DocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)

    filepath = form.cleaned_data["fp"]

    try:
        content, err, _ = await make_pdftotext_process(filepath)
        return JsonResponse(
            "content",
            content,
            "err",
            err,
        )
    finally:
        cleanup_form(form)


async def images_to_pdf(request) -> HttpResponse:
    """Converts a list of images from urls into a single pdf file

    :param request: The request object
    :return: HttpResponse object
    """
    form = ImagePdfForm(request.GET)
    if not form.is_valid():
        raise BadRequest("Invalid form")
    sorted_urls = form.cleaned_data["sorted_urls"]

    if len(sorted_urls) > 1:
        image_list = await download_images(sorted_urls)
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


@log_upload_lifecycle
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


@log_upload_lifecycle
async def convert_audio(
    request, output_format: str
) -> FileResponse | HttpResponse:
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
                await convert_to_mp3(filepath, media_file)
                set_mp3_meta_data(audio_data, filepath)
            case "ogg":
                await convert_to_ogg(filepath, media_file)
            case _:
                raise NotImplementedError
        response = FileResponse(
            open(filepath, "rb")  # noqa: SIM115 FileResponse closes the file
        )
        return response
    finally:
        cleanup_form(form)


@log_upload_lifecycle
async def embed_text(request) -> FileResponse | HttpResponse:
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
            await rasterize_pdf(fp, destination.name)
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


@log_upload_lifecycle
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
