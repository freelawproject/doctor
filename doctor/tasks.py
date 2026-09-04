import asyncio
import base64
import fnmatch
import hashlib
import io
import logging
import os
import re
import time
from collections.abc import ByteString
from tempfile import NamedTemporaryFile
from typing import Any, AnyStr
from urllib.parse import urlparse

import eyed3
import httpx
import magic
import pdfplumber
import requests
import xray
from django.conf import settings
from eyed3 import id3
from httpx import AsyncClient
from lxml.html.clean import Cleaner
from PIL.Image import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from seal_rookery.search import ImageSizes, seal

from doctor.lib.bitonal import BitonalError
from doctor.lib.mojibake import fix_mojibake
from doctor.lib.text_extraction import (
    extract_with_ocr,
    get_page_text,
    page_needs_ocr,
    remove_excess_whitespace,
)
from doctor.lib.utils import (
    DoctorUnicodeDecodeError,
    force_text,
    ocr_needed,
    smart_text,
)

logger = logging.getLogger(__name__)


def pdf_bytes_from_images(image_list: list[Image]):
    """Make a pdf given an array of Image files

    :param image_list: List of images
    :type image_list: list
    :return: PDF as bytes
    """
    with io.BytesIO() as output:
        image_list[0].save(
            output,
            "PDF",
            resolution=100.0,
            save_all=True,
            append_images=image_list[1:],
        )
        pdf_data = output.getvalue()

    return pdf_data


async def make_pdftotext_process(path):
    """Make a subprocess to hand to higher-level code.

    :param path: File location
    :return: Subprocess results
    """

    process = await asyncio.create_subprocess_exec(
        "pdftotext",
        "-layout",
        "-enc",
        "UTF-8",
        path,
        "-",
        shell=False,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    content, err = await process.communicate()
    return content.decode(), err, process.returncode


async def rasterize_pdf(
    path: str,
    destination: str,
    first_page: int | None = None,
    last_page: int | None = None,
):
    """Convert the PDF, or a page range of it, into a multipage Tiff file.

    This function uses ghostscript for processing and borrows heavily from:

        https://github.com/jbarlow83/OCRmyPDF/blob/636d1903b35fed6b07a01af53769fea81f388b82/ocrmypdf/ghostscript.py#L11

    :param path: The PDF to rasterize
    :param destination: Where to write the TIFF
    :param first_page: 1-based first page to render; None means page 1
    :param last_page: 1-based last page to render; None means the last page
    :return: ghostscript's stdout, stderr and return code
    """
    # gs docs, see: http://ghostscript.com/doc/7.07/Use.htm
    # gs devices, see: http://ghostscript.com/doc/current/Devices.htm
    #
    # Compression is a trade off. It takes twice as long to convert PDFs, but
    # they're about 1-2% the size of the uncompressed version. They take about
    # 30% of the RAM when Tesseract processes them. See:
    # https://github.com/tesseract-ocr/tesseract/issues/431#issuecomment-250549208
    # destination = "/tmp/tmppzo3zzah.tiff"
    # gs -dQUIET -dSAFER -dBATCH -dNOPAUSE -sDEVICE=tiffgray -sCompression=lzw -r300x300 -o
    gs = [
        "gs",
        "-dQUIET",  # Suppress printing routine info
        "-dSAFER",  # Lock down the filesystem to only files on command line
        "-dBATCH",  # Exit after finishing file. Don't wait for more commands.
        "-dNOPAUSE",  # Don't pause after each page
        "-sDEVICE=tiffgray",
        "-sCompression=lzw",
        "-r300x300",  # Set the resolution to 300 DPI.
    ]
    if first_page is not None:
        gs.append(f"-dFirstPage={first_page}")
    if last_page is not None:
        gs.append(f"-dLastPage={last_page}")
    gs += ["-o", destination, path]

    p = await asyncio.create_subprocess_exec(
        *gs,
        close_fds=True,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await p.communicate()
    return stdout, stderr, p.returncode


def get_xray(path):
    """Get bad redactions

    :param path: A path to the file
    :return: dictionary of bounding boxes.
    """
    try:
        bad_redactions = xray.inspect(path)
        return bad_redactions
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AssertionError,
        PdfReadError,
    ):
        return {"error": True, "msg": "Exception"}
    except Exception:
        return {"error": True, "msg": "Exception"}
    # not reached


def get_page_count(path, extension):
    """Get the number of pages, if appropriate mimetype.

    :param path: A path to a binary (pdf, wpd, doc, txt, html, etc.)
    :param extension: The extension of the binary.
    :return: The number of pages if possible, else return None
    """
    if extension == "pdf":
        try:
            reader = PdfReader(path)
            return len(reader.pages)
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AssertionError,
            PdfReadError,
        ):
            # IOError: File doesn't exist. My bad.
            # ValueError: Didn't get an int for the page count. Their bad.
            # TypeError: NumberObject has no attribute '__getitem__'. Ugh.
            # KeyError, AssertionError: assert xrefstream["/Type"] == "/XRef". WTF?
            # PdfReadError: Something else. I have no words.
            return 0

    elif extension == "wpd":
        # Best solution appears to be to dig into the binary format
        pass
    elif extension == "doc":
        # Best solution appears to be to dig into the XML of the file
        # itself: http://stackoverflow.com/a/12972502/64911
        pass
    return None


async def extract_from_pdf(
    path: str,
    ocr_available: bool = False,
) -> Any:
    """Extract text from pdfs.

    Start with pdftotext. If we we enabled OCR - and the the content is empty
    or the PDF contains images, use tesseract. This pattern occurs because PDFs
    can be images, text-based and a mix of the two. We check for images to
    make sure we do OCR on mix-type PDFs.

    If a text-based PDF we fix corrupt PDFs from ca9.

    :param path: The path to the PDF
    :param ocr_available: Whether we should do OCR stuff
    :return Tuple of the content itself and any errors we received
    """
    content, err, returncode = await make_pdftotext_process(path)
    extracted_by_ocr = False
    if err is not None:
        err = err.decode()

    if not ocr_available:
        if "e" not in content:
            # It's a corrupt PDF from ca9. Fix it.
            content = fix_mojibake(content)
    else:
        if ocr_needed(path, content):
            success, ocr_content = await extract_by_ocr(path)
            if success:
                # Check content length and take the longer of the two
                if len(ocr_content) > len(content):
                    content = ocr_content
                    extracted_by_ocr = True
                    returncode = 0
            elif content == "" or not success:
                content = "Unable to extract document content."

    return content, err, returncode, extracted_by_ocr


OCR_FAIL_MSG = (
    "Unable to extract the content from this file. Please try "
    "reading the original."
)

# Tesseract separates the pages of a multi-page TIFF with a form feed and
# emits none after the last page, so joining the slices with one gives the
# same text as a single pass over the whole document.
OCR_PAGE_SEPARATOR = "\f"


async def extract_by_ocr(path: str) -> tuple[bool, str]:
    """Extract the contents of a PDF using OCR.

    The document is rasterized and OCRed in slices of
    ``settings.DOCTOR_OCR_PAGES_PER_SLICE`` pages, one slice at a time, so
    ghostscript, tesseract and /tmp each hold at most one slice however
    long the document is. A document that fits in one slice takes a
    single pass, as does one whose page count pypdf cannot read.

    The slice boundaries come from pypdf's page count, but the count is
    not trusted to be the end of the document: the last slice is left
    open-ended so ghostscript renders every page it finds past the count,
    and the loop stops early if ghostscript finds no pages in a slice.
    No page is lost when pypdf and ghostscript disagree on the count.

    :param path: The path to the file
    :return Tuple with success or fail boolean and text
    """
    pages_per_slice = max(1, settings.DOCTOR_OCR_PAGES_PER_SLICE)
    page_count = get_page_count(path, "pdf") or 0
    if page_count <= pages_per_slice:
        success, text = await _ocr_page_range(path)
        return success, text or ""

    parts: list[str] = []
    for first in range(1, page_count + 1, pages_per_slice):
        last: int | None = first + pages_per_slice - 1
        if last >= page_count:
            # Render through the real end of the file, wherever it is.
            last = None
        last_label = last if last is not None else "end"
        started = time.monotonic()
        success, text = await _ocr_page_range(path, first, last)
        if not success:
            logger.warning(
                "OCR failed on pages %d-%s of %d of %s",
                first,
                last_label,
                page_count,
                path,
            )
            return False, OCR_FAIL_MSG
        if text is None:
            logger.warning(
                "pypdf counted %d pages in %s but ghostscript found none "
                "from page %d; stopping there",
                page_count,
                path,
                first,
            )
            break
        logger.info(
            "OCRed pages %d-%s of %d of %s in %.1fs, %d chars",
            first,
            last_label,
            page_count,
            path,
            time.monotonic() - started,
            len(text),
        )
        parts.append(text)
        if last is None:
            break
    return True, OCR_PAGE_SEPARATOR.join(parts)


async def _ocr_page_range(
    path: str,
    first_page: int | None = None,
    last_page: int | None = None,
) -> tuple[bool, str | None]:
    """Rasterize one page range to a temporary TIFF and OCR it.

    The TIFF is removed when this returns, so only one range's worth of
    pixels is ever on disk.

    :param path: The path to the PDF
    :param first_page: 1-based first page, None for the whole document
    :param last_page: 1-based last page, None for the whole document; a
        last page past the end of the document renders up to the end
    :return (False, message) if ghostscript failed; (True, None) if the
        range starts past the end of the document, so ghostscript rendered
        no pages; otherwise (True, text)
    """
    with NamedTemporaryFile(prefix="ocr_", suffix=".tiff", buffering=0) as tmp:
        out, err, returncode = await rasterize_pdf(
            path, tmp.name, first_page, last_page
        )
        if returncode != 0:
            return False, OCR_FAIL_MSG
        if os.path.getsize(tmp.name) == 0:
            # ghostscript exits 0 with no output when first_page is past
            # the last page of the document.
            return True, None

        txt = await convert_file_to_txt(tmp.name)
        txt = cleanup_ocr_text(txt)

    return True, txt


def cleanup_ocr_text(txt: str) -> str:
    """Do some basic cleanup to make OCR text better.

    Err on the side of safety. Don't make fixes that could cause other issues.

    :param txt: The txt output from the OCR engine.
    :return: Txt output, cleaned up.
    """
    simple_replacements = (
        ("Fi|ed", "Filed"),
        (" Il ", " II "),
    )
    for replacement in simple_replacements:
        txt = txt.replace(replacement[0], replacement[1])
    return txt


async def convert_file_to_txt(path: str) -> str:
    """Converts a file to plain text

    :param path: The path to the file
    :return The extracted text content from the file
    """
    tesseract_command = [
        "tesseract",
        path,
        "stdout",
        "-l",
        "eng",
        "-c",
        "tessedit_do_invert=0",  # Assume a white background for speed
    ]
    p = await asyncio.create_subprocess_exec(
        *tesseract_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out = await p.communicate()
    return out[0].decode()


def convert_tiff_to_pdf_bytes(single_tiff_image: Image) -> ByteString:
    """Split long tiff into page sized image

    :param single_tiff_image: One long tiff file
    :return: PDF Bytes
    """
    width, height = single_tiff_image.size
    image_list = []
    i, page_width, page_height = 0, width, (1046 * (float(width) / 792))
    while i < (height / page_height):
        single_page = single_tiff_image.crop(
            (0, (i * page_height), page_width, (i + 1) * page_height)
        )
        image_list.append(single_page)
        i += 1

    pdf_bytes = pdf_bytes_from_images(image_list)
    return pdf_bytes


async def extract_from_doc(path) -> tuple[str, bytes, int]:
    """Extract text from docs.
    We use antiword to pull the text out of MS Doc files.

    :param path: The path to the file
    :return: A tuple containing the extracted text, any error output, and the subprocess return code
    """
    process = await asyncio.create_subprocess_exec(
        "antiword",
        path,
        "-i",
        "1",
        shell=False,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    content, err = await process.communicate()
    return content.decode("utf-8"), err, process.returncode


async def extract_from_docx(path) -> tuple[str, bytes, int]:
    """Extract text from docx files
    We use docx2txt to pull out the text. Pretty simple.

    :param path: The path to the .docx file
    :return: A tuple containing the extracted text, any error output (empty bytes), and the subprocess return code
    """
    process = await asyncio.create_subprocess_exec(
        "docx2txt",
        path,
        "-",
        shell=False,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    content, err = await process.communicate()
    return content.decode("utf-8"), err, process.returncode


def extract_from_html(path: str) -> tuple[str, str, int]:
    """Extract from html file by attempting various encodings

    A simple wrapper to go get content, and send it along.

    :param path: The file path to the HTML file.
    :return: A tuple containing:
             - The extracted and cleaned text content (str), or an empty string on failure.
             - An error message (str), or an empty string on success.
             - A return code (int), typically 0 on success, 1 on failure.
    """
    for encoding in ["utf-8", "ISO8859", "cp1252", "latin-1"]:
        try:
            with open(path, encoding=encoding) as f:
                content = f.read()
            content = get_clean_body_content(content)
            content = force_text(content, encoding=encoding)
            return content, "", 0
        except (UnicodeDecodeError, DoctorUnicodeDecodeError):
            pass
    # Fell through, therefore unable to decode the string.
    return "", "Could not encode content properly", 1


def get_clean_body_content(content: str) -> str:
    """Parse out the body from an html string, clean it up, and send it along.

    :param content: The HTML content as a string
    :return: The cleaned HTML body content as a string, or a default error string on failure
    """
    cleaner = Cleaner(
        style=True, remove_tags=["a", "body", "font", "noscript", "img"]
    )
    return cleaner.clean_html(content)


def extract_from_txt(filepath: str):
    """Extract text from plain text files: A fool's errand.

    Unfortunately, plain text files lack encoding information, so we have to
    guess. We could guess ascii, but we may as well use a superset of ascii,
    cp1252, and failing that try utf-8, ignoring errors. Most txt files we
    encounter were produced by converting wpd or doc files to txt on a
    Microsoft box, so assuming cp1252 as our first guess makes sense.

    May we hope for a better world.

    :param filepath: The path to the file
    :return: A tuple containing the extracted text, any error output, and the error code
    """
    err = None
    error_code = 0
    try:
        with open(filepath) as f:
            data = f.read()
        try:
            # Alas, cp1252 is probably still more popular than utf-8.
            content = smart_text(data, encoding="cp1252")
        except DoctorUnicodeDecodeError:
            content = smart_text(data, encoding="utf-8", errors="ignore")
    except Exception:
        try:
            with open(filepath, "rb") as f:
                blob = f.read()
            m = magic.Magic(mime_encoding=True)
            encoding = m.from_buffer(blob)
            with open(filepath, encoding=encoding) as f:
                data = f.read()
            content = smart_text(data, encoding=encoding, errors="ignore")
        except Exception:
            err = "An error occurred extracting txt file."
            content = ""
            error_code = 1
    return content, err, error_code


async def extract_from_wpd(path: str) -> tuple[str, bytes, int]:
    """Extract text from a Word Perfect file

    Yes, courts still use these, so we extract their text using wpd2html. Once
    that's done, we pull out the body of the HTML, and do some minor cleanup
    on it.

    :param path: The file path to the Word Perfect (.wpd) file.
    :return: A tuple containing:
             - The extracted and cleaned text content (str)
             - The standard error output from the wpd2html subprocess (bytes)
             - The return code of the wpd2html subprocess (int). Returns 1 on Python-level errors
    """
    process = await asyncio.create_subprocess_exec(
        "wpd2html",
        path,
        shell=False,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    content_bytes, err = await process.communicate()
    content_str = content_bytes.decode("utf-8")
    content = get_clean_body_content(content_str)

    return content, err, process.returncode


# Presigned URL transport for the bitonal endpoint. Transient
# failures (network errors, 5xx) are retried with backoff; a 403
# means the presigned signature expired, so retrying the same URL
# cannot succeed and the caller must re-presign.
EGRESS_MAX_ATTEMPTS = 3
EGRESS_BACKOFF_SECONDS = 1.0
EGRESS_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def validate_egress_url(url: str) -> None:
    """Check a caller-supplied URL against the egress policy.

    When DOCTOR_EGRESS_ALLOWED_HOSTS is set, the URL must be https
    and its host must match one of the configured fnmatch patterns.
    An empty setting disables the check.

    :param url: The URL doctor was asked to fetch from or upload to.
    :raises BitonalError: EGRESS_BLOCKED when the URL is not allowed.
    """
    allowed_hosts = settings.DOCTOR_EGRESS_ALLOWED_HOSTS
    if not allowed_hosts:
        return
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https" or not any(
        fnmatch.fnmatch(hostname, pattern) for pattern in allowed_hosts
    ):
        raise BitonalError(
            "EGRESS_BLOCKED",
            f"URL blocked by egress policy: {parsed.scheme}://{hostname}",
            status=400,
        )


class _TransientTransferError(Exception):
    """A transfer failure worth retrying: a network error or a 5xx."""


def _classify_status(
    status: int, expired_code: str, failed_code: str, direction: str
) -> None:
    """Raise for any non-2xx response, classified for retry policy.

    2xx passes. 403 means the presigned signature expired: retrying
    the same URL cannot succeed, so it fails fast with expired_code.
    5xx is transient and retried. Everything else — including 3xx,
    which follow_redirects=False hands back as-is and which must
    never count as a completed transfer — fails fast with
    failed_code.

    :param status: The HTTP status code of the response.
    :param expired_code: Error code for an expired signature (403).
    :param failed_code: Error code for other terminal failures.
    :param direction: "input" or "output", for the error message.
    """
    if 200 <= status < 300:
        return
    if status == 403:
        raise BitonalError(
            expired_code,
            f"{direction} URL returned 403; the signature has expired "
            "and a retry cannot succeed",
            status=502,
        )
    if status >= 500:
        raise _TransientTransferError(f"HTTP {status}")
    raise BitonalError(
        failed_code,
        f"{direction} URL returned HTTP {status}",
        status=502,
    )


def _transfer_with_retries(attempt, failed_code: str, failure_prefix: str):
    """Run one transfer attempt under the shared retry/backoff policy.

    Retries _TransientTransferError and httpx transport errors with
    exponential backoff. BitonalError — the fail-fast
    classifications from _classify_status — propagates immediately,
    and a malformed URL (httpx.InvalidURL) fails fast as a terminal
    4xx with failed_code.

    :param attempt: Zero-argument callable performing one attempt.
    :param failed_code: Error code raised when attempts are exhausted.
    :param failure_prefix: Human prefix for the exhaustion message.
    :return: Whatever attempt() returns.
    """
    last_error = ""
    for attempt_number in range(EGRESS_MAX_ATTEMPTS):
        if attempt_number:
            time.sleep(EGRESS_BACKOFF_SECONDS * 2 ** (attempt_number - 1))
        try:
            return attempt()
        except httpx.InvalidURL as e:
            # Not an httpx.HTTPError: raised when the request is
            # built, for a malformed port or host that urlparse (and
            # so validate_egress_url) accepts. A broken URL can never
            # succeed, so it must neither retry here nor escape to
            # the retryable INTERNAL_ERROR catch-all.
            raise BitonalError(
                failed_code, f"invalid URL: {e}", status=400
            ) from e
        except (_TransientTransferError, httpx.HTTPError) as e:
            last_error = str(e)
    raise BitonalError(
        failed_code,
        f"{failure_prefix} after {EGRESS_MAX_ATTEMPTS} attempts: {last_error}",
        status=502,
    )


def stream_url_to_file(url: str, output_path: str) -> str:
    """Download a presigned GET URL to a file, streaming.

    Never buffers the body in memory: shards can reach hundreds of
    megabytes while the pod's memory allowance is under 500 MiB.

    :param url: Presigned GET URL of the input document.
    :param output_path: Where to write the body.
    :return: sha256 hex digest of the downloaded bytes.
    :raises BitonalError: INPUT_URL_EXPIRED on 403, INPUT_TOO_LARGE
        when the body exceeds DOCTOR_BITONAL_MAX_DOWNLOAD_BYTES,
        INPUT_DOWNLOAD_FAILED otherwise.
    """
    validate_egress_url(url)
    # Cap the download: input_url is caller-supplied and an oversized
    # object would fill the pod's shared disk. Content-Length fails
    # fast; the streamed count catches missing or lying headers. No
    # retries — the object will not shrink.
    max_bytes = settings.DOCTOR_BITONAL_MAX_DOWNLOAD_BYTES

    def attempt() -> str:
        with (
            httpx.Client(
                follow_redirects=False, timeout=EGRESS_TIMEOUT
            ) as client,
            client.stream("GET", url) as response,
        ):
            _classify_status(
                response.status_code,
                "INPUT_URL_EXPIRED",
                "INPUT_DOWNLOAD_FAILED",
                "input",
            )
            content_length = response.headers.get("Content-Length", "")
            if (
                max_bytes
                and content_length.isdigit()
                and int(content_length) > max_bytes
            ):
                raise BitonalError(
                    "INPUT_TOO_LARGE",
                    f"input Content-Length {content_length} exceeds "
                    f"the {max_bytes}-byte limit",
                    status=400,
                )
            digest = hashlib.sha256()
            received = 0
            with open(output_path, "wb") as f:
                for chunk in response.iter_bytes(1024 * 1024):
                    received += len(chunk)
                    if max_bytes and received > max_bytes:
                        raise BitonalError(
                            "INPUT_TOO_LARGE",
                            f"input exceeded the {max_bytes}-byte "
                            "limit while streaming",
                            status=400,
                        )
                    f.write(chunk)
                    digest.update(chunk)
            return digest.hexdigest()

    return _transfer_with_retries(
        attempt, "INPUT_DOWNLOAD_FAILED", "input download failed"
    )


def put_file_to_url(url: str, input_path: str, content_type: str) -> str:
    """Upload a file to a presigned PUT URL, streaming.

    A single PUT is atomic on S3: a partial upload never becomes a
    gettable object, so the object's existence implies all of its
    bytes are there. Content-Type is sent explicitly because the
    presigned signature covers it; Content-Length keeps the body
    unchunked. The digest is computed while streaming, mirroring
    stream_url_to_file, so the caller never re-reads the file.

    :param url: Presigned PUT URL for the result object.
    :param input_path: File to upload.
    :param content_type: Content type the URL was signed with.
    :return: sha256 hex digest of the uploaded bytes.
    :raises BitonalError: RESULT_URL_EXPIRED on 403,
        RESULT_UPLOAD_FAILED otherwise.
    """
    validate_egress_url(url)
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(os.path.getsize(input_path)),
    }

    def attempt() -> str:
        # A fresh digest per attempt: a retried upload re-reads the
        # file from the start.
        digest = hashlib.sha256()
        with (
            open(input_path, "rb") as f,
            httpx.Client(
                follow_redirects=False, timeout=EGRESS_TIMEOUT
            ) as client,
        ):

            def hashing_body():
                while chunk := f.read(1024 * 1024):
                    digest.update(chunk)
                    yield chunk

            response = client.put(url, content=hashing_body(), headers=headers)
        _classify_status(
            response.status_code,
            "RESULT_URL_EXPIRED",
            "RESULT_UPLOAD_FAILED",
            "output",
        )
        return digest.hexdigest()

    return _transfer_with_retries(
        attempt, "RESULT_UPLOAD_FAILED", "result upload failed"
    )


async def download_images(sorted_urls) -> list:
    """Download images and convert to list of PIL images

    Once in an array of PIL.images we can easily convert this to a PDF.

    :param sorted_urls: List of sorted URLs for split financial disclosure
    :return: image_list
    """

    image_list = []
    async with AsyncClient(http2=True, follow_redirects=True) as client:
        futures = [client.get(url) for url in sorted_urls]
        for response in await asyncio.gather(*futures):
            image_list.append(response.content)
    return image_list


# Audio

root = os.path.dirname(os.path.realpath(__file__))
assets_dir = os.path.join(root, "assets")


async def convert_to_mp3[AnyStr: (bytes, str)](
    output_path: AnyStr, media: Any
) -> None:
    """Convert audio bytes to mp3 at temporary path

    :param output_path: Audio file bytes sent to Doctor
    :param media: Temporary filepath for output of audioprocess
    :return:
    """
    av_command = [
        "ffmpeg",
        "-i",
        "/dev/stdin",
        "-ar",
        "22050",
        "-ab",
        "48k",
        "-f",
        "mp3",
        output_path,
    ]

    ffmpeg_cmd = await asyncio.create_subprocess_exec(
        *av_command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        shell=False,
    )
    await ffmpeg_cmd.communicate(media.read())
    return output_path


async def convert_to_ogg[AnyStr: (bytes, str)](
    output_path: AnyStr, media: Any
) -> None:
    """Converts audio data to the ogg format (.ogg)

    This function uses ffmpeg to convert the audio data provided in `media` to
    the ogg format with the following specifications:

    * Single audio channel (`-ac 1`)
    * 8 kHz sampling rate (`-b:a 8k`)
    * Optimized for voice over IP applications (`-application voip`)

    :param output_path: Audio file bytes sent to Doctor
    :param media: Temporary filepath for output of audioprocess
    :return:
    """
    av_command = [
        "ffmpeg",
        "-i",
        "/dev/stdin",
        "-vn",
        "-map_metadata",
        "-1",
        "-ac",
        "1",
        "-c:a",
        "libopus",
        "-b:a",
        "8k",
        "-application",
        "voip",
        "-f",
        "ogg",
        output_path,
    ]

    ffmpeg_cmd = await asyncio.create_subprocess_exec(
        *av_command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        shell=False,
    )
    await ffmpeg_cmd.communicate(media.read())
    return output_path


def set_mp3_meta_data[AnyStr: (bytes, str)](
    audio_data: dict, mp3_path: AnyStr
) -> eyed3.core.AudioFile:
    """Set the metadata in audio_data to an mp3 at path.

    :param audio_data: The new metadata to embed in the mp3.
    :param mp3_path: The path to the mp3 to be converted.
    :return: Eyed3 audio file object
    """

    # Load the file, delete the old tags and create a new one.
    audio_file = eyed3.load(mp3_path)
    # Undocumented API from eyed3.plugins.classic.ClassicPlugin#handleRemoves
    id3.Tag.remove(
        audio_file.tag.file_info.name,
        id3.ID3_ANY_VERSION,
        preserve_file_time=False,
    )
    audio_file.initTag()
    audio_file.tag.title = best_case_name(audio_data)
    date_argued = audio_data["date_argued"]
    docket_number = audio_data["docket_number"]
    audio_file.tag.album = (
        f"{audio_data['court_full_name']}, {audio_data['date_argued_year']}"
    )
    audio_file.tag.artist = audio_data["court_full_name"]
    audio_file.tag.artist_url = audio_data["court_url"]
    audio_file.tag.audio_source_url = audio_data["download_url"]

    audio_file.tag.comments.set(
        f"Argued: {date_argued}. Docket number: {docket_number}"
    )
    audio_file.tag.genre = "Speech"
    audio_file.tag.publisher = "Free Law Project"
    audio_file.tag.publisher_url = "https://free.law"
    audio_file.tag.recording_date = date_argued

    # Add images to the mp3. If it has a seal, use that for the Front Cover
    # and use the FLP logo for the Publisher Logo. If it lacks a seal, use the
    # Publisher logo for both the front cover and the Publisher logo.
    url = seal(court=audio_data["court_pk"], size=ImageSizes.MEDIUM)

    flp_image_frames = [
        3,  # "Front Cover". Complete list at eyed3/id3/frames.py
        14,  # "Publisher logo".
    ]

    if url:
        seal_content = requests.get(url, timeout=30).content
        audio_file.tag.images.set(
            3,
            seal_content,
            "image/png",
            f"Seal for {audio_data['court_short_name']}",
        )
        flp_image_frames.remove(3)

    for frame in flp_image_frames:
        cover_art_fp = os.path.join(assets_dir, "producer-300x300.png")
        with open(cover_art_fp, "rb") as cover_art:
            audio_file.tag.images.set(
                frame,
                cover_art.read(),
                "image/png",
                "Created for the public domain by Free Law Project",
            )

    audio_file.tag.save()
    return audio_file


def convert_to_base64[AnyStr: (bytes, str)](tmp_path: AnyStr) -> AnyStr:
    """Convert file base64 and decode it.

    This allows us to safely return the file in json to CL.

    :param tmp_path:
    :return: Audio file encoded in base64 as a string
    """
    with open(tmp_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def best_case_name(audio_dict: dict) -> AnyStr:
    """Take an object and return the highest quality case name possible.

    In general, this means returning the fields in an order like:

        - case_name
        - case_name_full
        - case_name_short

    Assumes that the object passed in has all of those attributes.
    """
    if audio_dict.get("case_name"):
        return audio_dict.get("case_name")
    elif audio_dict.get("case_name_full"):
        return audio_dict["case_name_full"]
    else:
        return audio_dict.get("case_name_short", "")


def get_header_stamp(obj: dict) -> bool:
    """pdfplumber filter to extract the PDF header stamp.

    :param obj: The page object to evaluate.
    :return: True if the found it, otherwise False.
    """

    # This option works for most juridictions except for ca5
    if "LiberationSans" in obj.get("fontname", ""):
        return True
    # Exception for ca5
    return obj["y0"] > 750


def clean_document_number(document_number: str) -> str:
    """Removes #, leading and ending whitespaces from the document number.

    :param document_number: The document number to clean
    :return: The cleaned document number.
    """
    document_number = document_number.strip()
    document_number = document_number.replace("#", "")
    return document_number


def get_document_number_from_pdf(path: str) -> str:
    """Get PACER document number from PDF.

    :param path: The path to the PDF
    :return: The PACER document number.
    """

    with pdfplumber.open(path) as f:
        header_stamp = f.pages[0].filter(get_header_stamp).extract_text()

    # regex options to extract the document number
    regex = r"Document:(.[0-9.\-.\#]+)|Document(.[0-9.\-.\#]+)|Doc:(.[0-9.\-.\#]+)|DktEntry:(.[0-9.\-.\#]+)"
    document_number_matches = re.findall(regex, header_stamp)

    # If not matches return a empty string.
    if not document_number_matches:
        return ""
    document_number = [dn for dn in document_number_matches[0] if dn]
    return clean_document_number(document_number[0])


def extract_recap_pdf(
    filepath: str,
    strip_margin: bool = False,
) -> tuple[str, bool]:
    """Extract from RECAP PDF

    :param filepath: The path to the PDF
    :param strip_margin: Whether to remove 1 inch margin from text extraction
    :return: A tuple containing the text and a boolean indicating ocr usage
    """
    content = ""
    extracted_by_ocr = False
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = get_page_text(page, strip_margin=strip_margin)
            if page_needs_ocr(page, page_text):
                extracted_by_ocr = True
                page_text = extract_with_ocr(page, strip_margin=strip_margin)
            content += f"\n{page_text}"
    content = remove_excess_whitespace(content)
    return content, extracted_by_ocr
