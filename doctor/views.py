import mimetypes
import re
import shutil
from http.client import BAD_REQUEST
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Union

import eyed3
import img2pdf
import magic
import pytesseract
import requests
from django.core.exceptions import BadRequest
from django.http import FileResponse, HttpResponse, JsonResponse
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
    make_page_with_text,
    make_png_thumbnail_for_instance,
    make_png_thumbnails,
    strip_metadata_from_path,
)
from doctor.tasks import (
    convert_tiff_to_pdf_bytes,
    convert_to_mp3,
    download_images,
    extract_from_doc,
    extract_from_docx,
    extract_from_html,
    extract_from_pdf,
    extract_from_txt,
    extract_from_wpd,
    get_document_number_from_pdf,
    get_page_count,
    get_xray,
    make_pdftotext_process,
    rasterize_pdf,
    set_mp3_meta_data,
    strip_metadata_from_bytes,
    extract_recap_pdf,
)


def heartbeat(request) -> HttpResponse:
    """Heartbeat endpoint

    :param request: The request object
    :return: Heartbeat
    """
    return HttpResponse("Heartbeat detected.")


def image_to_pdf(request) -> HttpResponse:
    """"""

    form = DocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    image = Image.open(form.cleaned_data["fp"])
    pdf_bytes = convert_tiff_to_pdf_bytes(image)
    cleaned_pdf_bytes = strip_metadata_from_bytes(pdf_bytes)
    with NamedTemporaryFile(suffix=".pdf") as output:
        with open(output.name, "wb") as f:
            f.write(cleaned_pdf_bytes)
        cleanup_form(form)
        return HttpResponse(cleaned_pdf_bytes)


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
    strip_margin = form.cleaned_data["strip_margin"]
    content, extracted_by_ocr = extract_recap_pdf(
        filepath=filepath,
        strip_margin=strip_margin,
    )
    cleanup_form(form)
    return JsonResponse(
        {
            "content": content,
            "extracted_by_ocr": extracted_by_ocr,
        }
    )


def extract_doc_content(request) -> Union[JsonResponse, HttpResponse]:
    """Extract txt from different document types.

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
        content = ""
        err = "Unable to extract content due to unknown extension"

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

    :return: json with bounding boxes and text
    """
    try:
        form = DocumentForm(request.POST, request.FILES)
        if not form.is_valid():
            return JsonResponse(
                {"error": True, "msg": "Failed validation"}, status=BAD_REQUEST
            )
        extension = form.cleaned_data["extension"]
        if "pdf" != extension.casefold():
            return JsonResponse(
                {"error": True, "msg": "Failed file type"}, status=BAD_REQUEST
            )
        results = get_xray(form.cleaned_data["fp"])
        if results.get("error", False):
            return JsonResponse(results, status=BAD_REQUEST)
    except:
        pass
    finally:
        cleanup_form(form)
    return JsonResponse({"error": False, "results": results})


def page_count(request) -> HttpResponse:
    """Get page count from PDF

    :return: Page count
    """
    form = DocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    extension = form.cleaned_data["extension"]
    pg_count = get_page_count(form.cleaned_data["fp"], extension)
    cleanup_form(form)
    return HttpResponse(pg_count)


def extract_mime_type(request) -> Union[JsonResponse, HttpResponse]:
    """Identify the mime type of a document

    :return: Mime type
    """
    form = DocumentForm(request.GET, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    mime = form.cleaned_data["mime"]
    mimetype = magic.from_file(form.cleaned_data["fp"], mime=mime)
    cleanup_form(form)
    return JsonResponse({"mimetype": mimetype})


def extract_extension(request) -> HttpResponse:
    """A handful of workarounds for getting extensions we can trust."""
    form = MimeForm(request.GET, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    content = form.cleaned_data["file"].read()

    file_str = magic.from_buffer(content)
    if file_str.startswith("Composite Document File V2 Document"):
        # Workaround for issue with libmagic1==5.09-2 in Ubuntu 12.04. Fixed
        # in libmagic 5.11-2.
        mime = "application/msword"
    elif file_str == "(Corel/WP)":
        mime = "application/vnd.wordperfect"
    elif file_str == "C source, ASCII text":
        mime = "text/plain"
    elif file_str.startswith("WordPerfect document"):
        mime = "application/vnd.wordperfect"
    elif re.findall(
        r"(Audio file with ID3.*MPEG.*layer III)|(.*Audio Media.*)", file_str
    ):
        mime = "audio/mpeg"
    else:
        # No workaround necessary
        mime = magic.from_buffer(content, mime=True)
    extension = mimetypes.guess_extension(mime)
    if extension == ".obj":
        # It could be a wpd, if it's not a PDF
        if "PDF" in content[0:40]:
            # Does 'PDF' appear in the beginning of the content?
            extension = ".pdf"
        else:
            extension = ".wpd"

    # The extension is .bin, look in the content if we can infer the
    # content type as pdf. See: https://bugs.astron.com/view.php?id=446
    if extension == ".bin":
        # Check if %PDF-X.X is in the first 1024 bytes of content
        pattern = rb"%PDF-[0-9]+(\.[0-9]+)?"
        matches = re.search(pattern, content[:1024])
        if matches:
            # Document contains a pdf version, so the file must be a pdf
            extension = ".pdf"

    fixes = {
        ".htm": ".html",
        ".xml": ".html",
        ".wsdl": ".html",
        ".ksh": ".txt",
        ".asf": ".wma",
        ".dot": ".doc",
    }
    return HttpResponse(fixes.get(extension, extension).lower())


def pdf_to_text(request) -> Union[JsonResponse, HttpResponse]:
    """Extract text from text based PDFs immediately.

    :return:
    """
    form = DocumentForm(request.POST, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    content, err, _ = make_pdftotext_process(form.cleaned_data["fp"])
    cleanup_form(form)
    return JsonResponse(
        "content",
        content,
        "err",
        err,
    )


def images_to_pdf(request) -> HttpResponse:
    """

    :param request:
    :return:
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
    """Fetch audio duration from file."""
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


def convert_audio(request) -> Union[FileResponse, HttpResponse]:
    """Convert audio file to MP3 and update metadata on mp3.

    :return: Converted audio
    """
    form = AudioForm(request.GET, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    filepath = form.cleaned_data["fp"]
    media_file = form.cleaned_data["file"]
    audio_data = {k: v[0] for k, v in dict(request.GET).items()}
    convert_to_mp3(filepath, media_file)
    set_mp3_meta_data(audio_data, filepath)
    response = FileResponse(open(filepath, "rb"))
    cleanup_form(form)
    return response


def embed_text(request) -> Union[FileResponse, HttpResponse]:
    """Embed text onto an image PDF.

    :return: Embedded PDF
    """
    form = DocumentForm(request.GET, request.FILES)
    if not form.is_valid():
        return HttpResponse("Failed validation", status=BAD_REQUEST)
    fp = form.cleaned_data["fp"]
    with NamedTemporaryFile(suffix=".tiff") as destination:
        rasterize_pdf(fp, destination.name)
        data = pytesseract.image_to_data(
            destination.name, output_type=Output.DICT
        )
        image = Image.open(destination.name)
        w, h = image.width, image.height
        output = PdfWriter()
        existing_pdf = PdfReader(open(fp, "rb"))
        for page in range(0, len(existing_pdf.pages)):
            packet = make_page_with_text(page + 1, data, h, w)
            new_pdf = PdfReader(packet)
            page = existing_pdf.pages[page]
            page.merge_page(new_pdf.pages[0])
            output.add_page(page)

        with NamedTemporaryFile(suffix=".pdf") as pdf_destination:
            outputStream = open(pdf_destination.name, "wb")
            output.write(outputStream)
            outputStream.close()
            img = open(pdf_destination.name, "rb")
            response = FileResponse(img)
            cleanup_form(form)
            return response


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
    document_number = get_document_number_from_pdf(fp)
    cleanup_form(form)
    return HttpResponse(document_number)
