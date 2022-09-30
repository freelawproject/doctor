import datetime
import io
import os
import re
import subprocess
import warnings
from collections import namedtuple
from decimal import Decimal
from pathlib import Path

import six
from PyPDF2 import PdfFileMerger
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
        pdf_merger = PdfFileMerger()
        pdf_merger.append(io.BytesIO(f.read()))
        pdf_merger.addMetadata({"/CreationDate": "", "/ModDate": ""})
        byte_writer = io.BytesIO()
        pdf_merger.write(byte_writer)
        return force_bytes(byte_writer.getvalue())


def strip_metadata_from_bytes(pdf_bytes):
    """Convert PDF bytes into PDF and remove metadata from it

    Stripping the metadata allows us to hash the PDFs

    :param pdf_bytes: PDF as binary content
    :return: PDF bytes with metadata removed.
    """
    pdf_merger = PdfFileMerger()
    pdf_merger.append(io.BytesIO(pdf_bytes))
    pdf_merger.addMetadata({"/CreationDate": "", "/ModDate": ""})
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

    We need to check if a PDF contains any images.  If a PDF contains images it
    likely has content that needs to be scanned.

    :param path: Location of PDF to process.
    :return: Does the PDF contain images?
    :type: bool
    """
    with open(path, "rb") as pdf_file:
        pdf_bytes = pdf_file.read()
        return True if re.search(rb"/Image ?/", pdf_bytes) else False


def ocr_needed(path: str, content: str) -> bool:
    """Check if OCR is needed on a PDF

    Check if images are in PDF or content is empty.

    :param path: The path to the PDF
    :param content: The content extracted from the PDF.
    :return: Whether OCR should be run on the document.
    """
    if content.strip() == "" or pdf_has_images(path):
        return True
    return False


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
