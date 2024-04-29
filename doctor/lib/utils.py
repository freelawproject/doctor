import datetime
import io
import os
import re
import subprocess
import warnings
from collections import namedtuple
from decimal import Decimal
from typing import Any

import pdfplumber
from pdfplumber.ctm import CTM
from pathlib import Path

import six
from PyPDF2 import PdfMerger
from reportlab.pdfgen import canvas


class DoctorUnicodeDecodeError(UnicodeDecodeError):
    def __init__(self, obj, *args):
        self.obj = obj
        UnicodeDecodeError.__init__(self, *args)

    def __str__(self):
        original = UnicodeDecodeError.__str__(self)
        return f"{original}. You passed in {self.obj!r} ({type(self.obj)})"


def force_bytes(s, encoding="utf-8", strings_only=False, errors="strict"):
    """
    Similar to smart_bytes, except that lazy instances are resolved to
    strings, rather than kept as lazy objects.

    If strings_only is True, don't convert (some) non-string-like objects.
    """
    # Handle the common case first for performance reasons.
    if isinstance(s, bytes):
        if encoding == "utf-8":
            return s
        else:
            return s.decode("utf-8", errors).encode(encoding, errors)
    if strings_only and is_protected_type(s):
        return s
    if isinstance(s, six.memoryview):
        return bytes(s)
    if isinstance(s, Promise):
        return six.text_type(s).encode(encoding, errors)
    if not isinstance(s, six.string_types):
        try:
            if six.PY3:
                return six.text_type(s).encode(encoding)
            else:
                return bytes(s)
        except UnicodeEncodeError:
            if isinstance(s, Exception):
                # An Exception subclass containing non-ASCII data that doesn't
                # know how to print itself properly. We shouldn't raise a
                # further exception.
                return b" ".join(
                    force_bytes(arg, encoding, strings_only, errors)
                    for arg in s
                )
            return six.text_type(s).encode(encoding, errors)
    else:
        return s.encode(encoding, errors)


def force_text(s, encoding="utf-8", strings_only=False, errors="strict"):
    """
    Similar to smart_text, except that lazy instances are resolved to
    strings, rather than kept as lazy objects.

    If strings_only is True, don't convert (some) non-string-like objects.
    """
    # Handle the common case first for performance reasons.
    if issubclass(type(s), six.text_type):
        return s
    if strings_only and is_protected_type(s):
        return s
    try:
        if not issubclass(type(s), six.string_types):
            if six.PY3:
                if isinstance(s, bytes):
                    s = six.text_type(s, encoding, errors)
                else:
                    s = six.text_type(s)
            elif hasattr(s, "__unicode__"):
                s = six.text_type(s)
            else:
                s = six.text_type(bytes(s), encoding, errors)
        else:
            # Note: We use .decode() here, instead of six.text_type(s, encoding,
            # errors), so that if s is a SafeBytes, it ends up being a
            # SafeText at the end.
            s = s.decode(encoding, errors)
    except UnicodeDecodeError as e:
        if not isinstance(s, Exception):
            raise DoctorUnicodeDecodeError(s, *e.args)
        else:
            # If we get to here, the caller has passed in an Exception
            # subclass populated with non-ASCII bytestring data without a
            # working unicode method. Try to handle this without raising a
            # further exception by individually forcing the exception args
            # to unicode.
            s = " ".join(
                force_text(arg, encoding, strings_only, errors) for arg in s
            )
    return s


def smart_text(s, encoding="utf-8", strings_only=False, errors="strict"):
    """
    Returns a text object representing 's' -- unicode on Python 2 and str on
    Python 3. Treats bytestrings using the 'encoding' codec.

    If strings_only is True, don't convert (some) non-string-like objects.
    """
    if isinstance(s, Promise):
        # The input is the result of a gettext_lazy() call.
        return s
    return force_text(s, encoding, strings_only, errors)


class Promise(object):
    """
    This is just a base class for the proxy class created in
    the closure of the lazy function. It can be used to recognize
    promises in code.
    """

    pass


_PROTECTED_TYPES = six.integer_types + (
    type(None),
    float,
    Decimal,
    datetime.datetime,
    datetime.date,
    datetime.time,
)


def is_protected_type(obj):
    """Determine if the object instance is of a protected type.

    Objects of protected types are preserved as-is when passed to
    force_text(strings_only=True).
    """
    return isinstance(obj, _PROTECTED_TYPES)


def audio_encoder(data):
    return namedtuple("AudioFile", data.keys())(*data.values())


def ignore_warnings(test_func):
    def do_test(self, *args, **kwargs):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            warnings.simplefilter("ignore", DeprecationWarning)
            test_func(self, *args, **kwargs)

    return do_test


def make_png_thumbnail_for_instance(filepath, max_dimension):
    """Abstract function for making a thumbnail for a PDF

    See helper functions below for how to use this in a simple way.

    :param filepath: The attr where the PDF is located on the item
    :param max_dimension: The longest you want any edge to be
    :param response: Flask response object
    """
    command = [
        "pdftoppm",
        "-singlefile",
        "-f",
        "1",
        "-scale-to",
        str(max_dimension),
        filepath,
        "-png",
    ]
    p = subprocess.Popen(
        command, close_fds=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = p.communicate()
    return stdout, stderr.decode("utf-8"), str(p.returncode)


def make_png_thumbnails(filepath, max_dimension, pages, directory):
    """Abstract function for making a thumbnail for a PDF

    See helper functions below for how to use this in a simple way.

    :param filepath: The attr where the PDF is located on the item
    :param max_dimension: The longest you want any edge to be
    :param response: Flask response object
    """
    for page in pages:
        command = [
            "pdftoppm",
            "-singlefile",
            "-f",
            str(page),
            "-scale-to",
            str(max_dimension),
            filepath,
            "-png",
            f"{directory.name}/thumb-{page}",
        ]
        p = subprocess.Popen(
            command,
            close_fds=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        p.communicate()


def pdf_bytes_from_image_array(image_list, output_path) -> None:
    """Make a pdf given an array of Image files

    :param image_list: List of images
    :type image_list: list
    :return: pdf_data
    :type pdf_data: PDF as bytes
    """
    image_list[0].save(
        output_path,
        "PDF",
        resolution=100.0,
        save_all=True,
        append_images=image_list[1:],
    )
    del image_list


def strip_metadata_from_path(file_path):
    """Convert PDF file into PDF and remove metadata from it

    Stripping the metadata allows us to hash the PDFs

    :param pdf_bytes: PDF as binary content
    :return: PDF bytes with metadata removed.
    """
    with open(file_path, "rb") as f:
        pdf_merger = PdfMerger()
        pdf_merger.append(io.BytesIO(f.read()))
        pdf_merger.add_metadata({"/CreationDate": "", "/ModDate": ""})
        byte_writer = io.BytesIO()
        pdf_merger.write(byte_writer)
        return force_bytes(byte_writer.getvalue())


def strip_metadata_from_bytes(pdf_bytes):
    """Convert PDF bytes into PDF and remove metadata from it

    Stripping the metadata allows us to hash the PDFs

    :param pdf_bytes: PDF as binary content
    :return: PDF bytes with metadata removed.
    """
    pdf_merger = PdfMerger()
    pdf_merger.append(io.BytesIO(pdf_bytes))
    pdf_merger.add_metadata({"/CreationDate": "", "/ModDate": ""})
    byte_writer = io.BytesIO()
    pdf_merger.write(byte_writer)
    return force_bytes(byte_writer.getvalue())


def cleanup_form(form):
    """Clean up a form object"""
    os.remove(form.cleaned_data["fp"])


def make_file(filename, dir=None):
    filepath = f"{Path.cwd()}/doctor/test_assets/{filename}"
    with open(filepath, "rb") as f:
        return {"file": (filename, f.read())}


def make_buffer(filename, dir=None):
    filepath = f"{Path.cwd()}/doctor/test_assets/{filename}"
    with open(filepath, "rb") as f:
        return {"file": ("filename", f.read())}


def pdf_has_images(path: str) -> bool:
    """Check raw PDF for embedded images.

    We need to check if a PDF contains any large images.
    If a PDF contains images them we need to scan it.

    But somteimes a pdf can contain lots of small images as lines and we dont
    want to necessarily scan those so we should check the size of the images for
    anything substantial.

    :param path: Location of PDF to process.
    :return: Does the PDF contain images?
    """

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for img in page.images:
                if (
                    img.get("width")
                    / page.width
                    * img.get("height")
                    / page.height
                    > 0.1
                ):
                    return True


def make_page_with_text(page, data, h, w):
    """Make a page with text

    :param page:
    :param data:
    :param h:
    :param w:
    :return:
    """
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(w, h))
    # Set to a standard size and font for now.
    can.setFont("Helvetica", 9)
    # Make the text transparent
    can.setFillAlpha(0)
    for i in range(len(data["level"])):
        try:
            letter, (x, y, ww, hh), pg = (
                data["text"][i],
                (
                    data["left"][i],
                    data["top"][i],
                    data["width"][i],
                    data["height"][i],
                ),
                data["page_num"][i],
            )
        except:
            continue
        # Adjust the text to an 8.5 by 11 inch page
        sub = ((11 * 72) / h) * int(hh)
        x = ((8.5 * 72) / w) * int(x)
        y = ((11 * 72) / h) * int(y)
        yy = (11 * 72) - y
        if int(page) == int(pg):
            can.drawString(x, yy - sub, letter)
    can.showPage()
    can.save()
    packet.seek(0)
    return packet


def skew(obj):
    """"""
    if (matrix := obj.get("matrix")) is None:
        return True

    # Remove Skew
    my_char_ctm = CTM(*matrix)
    if my_char_ctm.skew_x != 0:
        return False
    return True


def detect_words_per_page(document_text, page_count) -> float:
    """Calculate word page frequency for the document

    Generally - less than ten words is a suspect document for the length
    of an entire document

    :param document_text: the docuemnt text
    :param page_count: number of pages
    :return: average words per page
    """
    word_matches = re.findall(r"(\b([A-Z]?[a-z]){1,20}\b)", document_text)
    list_of_words = list(set([matches[0] for matches in word_matches]))
    return len(list_of_words) / page_count


def page_has_text_annotations(path) -> bool:
    """Page contains annotations

    :param path: the path to the document
    :return: True if free text or widget annotations in PDF
    """
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if page.annots:
                anno_types = [
                    str(annot.get("data").get("Subtype"))
                    for annot in page.annots
                ]
                if "/'FreeText'" in anno_types or "/'Widget'" in anno_types:
                    return True
    return False


def get_page_text(page: pdfplumber.PDF.pages, strip_margin: bool):
    """Extract page text

    Using pdf plumber extract out the text of the document that is not
    skewed (ie a stamp of approval) and extract out text removing blue text

    :param page: pdf plumber page
    :param strip_margin: a flag to crop out the margin of a document and skewed content
    :return: text
    """
    if strip_margin:
        # Crop margins and remove skewed text
        bbox = (
            (1 / 8.5 * page.width),
            (1 / 11 * page.height),
            (7.5 / 8.5 * page.width),
            (10 / 11 * page.height),
        )
        doc_text = (
            page.crop(bbox)
            .filter(skew)
            .extract_text(layout=True, keep_blank_chars=True)
        )
    else:
        doc_text = page.extract_text(layout=True, keep_blank_chars=False)
    return doc_text


def extract_pdf_text(path: str, strip_margin: bool) -> str:
    """Extract content from a PDF per page

    :param path: Path to the pdf file
    :param strip_margin: If this is a recap document to strip margins
    :return: text on page
    """
    page_content = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = get_page_text(page, strip_margin=strip_margin).strip()
            page_content.append(text)
    return "\n".join(page_content)


def ocr_needed(path: str, content: str, page_count: int) -> [bool, Any]:
    """Check if OCR is needed on a PDF

    Check if images are in PDF or content is empty.
    This consists of a few different checks
    Reasons something should be OCR'd

    A pdf contains images
    A pdf contains freetext annotations or
    A pdf contains widgets that could have text that alters a document
    A pdf contains no text inside the margins
    A pdf contains garbled text due to lack of font embedding
    A pdf contains less than ten words on a page (normally around 90 to 200

    When calculating the words on a page - we should look at words inside
    the margin that contain lower case letters that are not skewed.

    :param path: The path to the PDF
    :param content: The content extracted from the PDF
    :param page_count: Length of PDF
    :return: Whether OCR should be run on the document and the error reason
    """

    if not content.strip():
        return True, "No content"
    elif "(cid:" in content:
        return True, "PDF missing fonts"
    elif pdf_has_images(path):
        return True, "PDF contains images"
    elif page_has_text_annotations(path):
        return True, "Pdf contains text annotations"
    elif detect_words_per_page(content, page_count) < 10:
        return True, "PDF likely gibberish"
    return False, ""
