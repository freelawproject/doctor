import io
import subprocess
from tempfile import NamedTemporaryFile

import magic
from PyPDF2 import PdfFileReader, PdfFileMerger
from PyPDF2.utils import PdfReadError
from lxml.etree import XMLSyntaxError
from lxml.html.clean import Cleaner

from src.utils.encoding_utils import (
    force_text,
    BTEUnicodeDecodeError,
    smart_text,
    force_bytes,
)

DEVNULL = open("/dev/null", "w")


class THUMBNAIL_STATUSES(object):
    NEEDED = 0
    COMPLETE = 1
    FAILED = 2
    NAMES = (
        (NEEDED, "Thumbnail needed"),
        (COMPLETE, "Thumbnail completed successfully"),
        (FAILED, "Unable to generate thumbnail"),
    )


def get_clean_body_content(content):
    """Parse out the body from an html string, clean it up, and send it along."""
    cleaner = Cleaner(
        style=True, remove_tags=["a", "body", "font", "noscript", "img"]
    )
    try:
        return cleaner.clean_html(content)
    except XMLSyntaxError:
        return (
            "Unable to extract the content from this file. Please try "
            "reading the original."
        )


def extract_from_doc(path):
    """Extract text from docs.

    We use antiword to pull the text out of MS Doc files.
    """
    process = subprocess.Popen(
        ["antiword", path, "-i", "1"],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=DEVNULL,
    )
    content, err = process.communicate()
    return content.decode("utf-8"), err, process.returncode


def extract_from_docx(path):
    """Extract text from docx files

    We use docx2txt to pull out the text. Pretty simple.
    """
    process = subprocess.Popen(
        ["docx2txt", path, "-"],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=DEVNULL,
    )
    content, err = process.communicate()
    return content.decode("utf-8"), err, process.returncode


def extract_from_html(path):
    """Extract from html.

    A simple wrapper to go get content, and send it along.
    """
    try:
        content = open(path).read().encode()
        content = get_clean_body_content(content)
        encodings = ["utf-8", "ISO8859", "cp1252"]
        for encoding in encodings:
            try:
                content = force_text(content, encoding=encoding)
            except BTEUnicodeDecodeError:
                return content, "BTE Unicode Decode Error", 1

        # Fell through, therefore unable to decode the string.
        return content, "", 0
    except Exception as e:
        return "", str(e), 1


def extract_from_pdf(tmp_tiff):
    pipe = subprocess.PIPE
    tesseract_cmd = ["tesseract", tmp_tiff.name, "stdout", "-l", "eng"]
    process = subprocess.Popen(tesseract_cmd, stdout=pipe, stderr=pipe)
    content, err = process.communicate()
    return content.decode("utf-8"), err, process.returncode


def make_pdftotext_process(path):
    """Make a subprocess to hand to higher-level code."""
    process = subprocess.Popen(
        ["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=DEVNULL,
    )
    content, err = process.communicate()
    return content.decode("utf-8"), err, process.returncode


def extract_from_txt(filepath):
    """Extract text from plain text files: A fool's errand.

    Unfortunately, plain text files lack encoding information, so we have to
    guess. We could guess ascii, but we may as well use a superset of ascii,
    cp1252, and failing that try utf-8, ignoring errors. Most txt files we
    encounter were produced by converting wpd or doc files to txt on a
    Microsoft box, so assuming cp1252 as our first guess makes sense.

    May we hope for a better world.
    """
    err = None
    error_code = 0
    try:
        with open(filepath, mode="r") as f:
            data = f.read()
        try:
            # Alas, cp1252 is probably still more popular than utf-8.
            content = smart_text(data, encoding="cp1252")
        except BTEUnicodeDecodeError:
            content = smart_text(data, encoding="utf-8", errors="ignore")
    except:
        try:
            blob = open(filepath, "rb").read()
            m = magic.Magic(mime_encoding=True)
            encoding = m.from_buffer(blob)
            with open(filepath, encoding=encoding, mode="r") as f:
                data = f.read()
            content = smart_text(data, encoding=encoding, errors="ignore")
        except:
            err = "An error occurred extracting txt file."
            content = ""
            error_code = 1
    return content, err, error_code


def extract_from_wpd(path):
    """Extract text from a Word Perfect file

    Yes, courts still use these, so we extract their text using wpd2html. Once
    that's done, we pull out the body of the HTML, and do some minor cleanup
    on it.
    """
    process = subprocess.Popen(
        ["wpd2html", path], shell=False, stdout=subprocess.PIPE, stderr=DEVNULL
    )
    content, err = process.communicate()
    content = get_clean_body_content(content)

    return content.decode("utf-8"), err, process.returncode


def convert_file_to_txt(path):
    tesseract_command = ["tesseract", path, "stdout", "-l", "eng"]
    process = subprocess.Popen(
        tesseract_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    content, err = process.communicate()
    return content.decode("utf-8"), err, process.returncode


def get_page_count(path, extension):
    """Get the number of pages, if appropriate mimetype.

    :param path: A path to a binary (pdf, wpd, doc, txt, html, etc.)
    :param extension: The extension of the binary.
    :return: The number of pages if possible, else return None
    """
    if extension == "pdf":
        try:
            reader = PdfFileReader(path)
            pg_count = int(reader.getNumPages())
        except (
            IOError,
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
            return None, "Error", 1
            pass
    elif extension == "wpd":
        # Best solution appears to be to dig into the binary format
        pass
    elif extension == "doc":
        # Best solution appears to be to dig into the XML of the file
        # itself: http://stackoverflow.com/a/12972502/64911
        pass
    return pg_count, "", 0


def rasterize_pdf(path, destination):
    """Convert the PDF into a multipage Tiff file.

    This function uses ghostscript for processing and borrows heavily from:

        https://github.com/jbarlow83/OCRmyPDF/blob/636d1903b35fed6b07a01af53769fea81f388b82/ocrmypdf/ghostscript.py#L11

    """
    # gs docs, see: http://ghostscript.com/doc/7.07/Use.htm
    # gs devices, see: http://ghostscript.com/doc/current/Devices.htm
    #
    # Compression is a trade off. It takes twice as long to convert PDFs, but
    # they're about 1-2% the size of the uncompressed version. They take about
    # 30% of the RAM when Tesseract processes them. See:
    # https://github.com/tesseract-ocr/tesseract/issues/431#issuecomment-250549208
    gs = [
        "gs",
        "-dQUIET",  # Suppress printing routine info
        "-dSAFER",  # Lock down the filesystem to only files on command line
        "-dBATCH",  # Exit after finishing file. Don't wait for more commands.
        "-dNOPAUSE",  # Don't pause after each page
        "-sDEVICE=tiffgray",
        "-sCompression=lzw",
        "-r300x300",  # Set the resolution to 300 DPI.
        "-o",
        destination,
        path,
    ]
    p = subprocess.Popen(
        gs,
        close_fds=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    stdout, stderr = p.communicate()
    return stdout, stderr, p.returncode


def cleanup_ocr_text(txt):
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


def extract_by_ocr(tmp):
    with NamedTemporaryFile(suffix=".tiff") as tmp_tiff:
        out, err, returncode = rasterize_pdf(tmp.name, tmp_tiff.name)
        txt = convert_file_to_txt(tmp_tiff)
        txt = cleanup_ocr_text(txt)
    return True, txt


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


def make_pdf_from_image_array(image_list):
    """Make a pdf given an array of Image files

    :param image_list: List of images
    :type image_list: list
    :return: pdf_data
    :type pdf_data: PDF as bytes
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


def strip_metadata(pdf_content):
    pdf_merger = PdfFileMerger()
    pdf_merger.append(io.BytesIO(pdf_content))
    pdf_merger.addMetadata({"/CreationDate": "", "/ModDate": ""})
    byte_writer = io.BytesIO()
    pdf_merger.write(byte_writer)
    return force_bytes(byte_writer.getvalue())
