import asyncio
import base64
import io
import os
import pdfplumber
import re
import subprocess
from tempfile import NamedTemporaryFile
from typing import Any, AnyStr, ByteString, Dict, List

import eyed3
import magic
import requests
from django.utils.encoding import force_bytes
from eyed3 import id3
from lxml.etree import XMLSyntaxError
from lxml.html.clean import Cleaner
from PIL.Image import Image
from PyPDF2 import PdfFileMerger, PdfFileReader
from PyPDF2.errors import PdfReadError
from seal_rookery.search import seal, ImageSizes

from doctor.lib.mojibake import fix_mojibake
from doctor.lib.utils import (
    DoctorUnicodeDecodeError,
    force_bytes,
    force_text,
    ocr_needed,
    smart_text,
)


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


def pdf_bytes_from_images(image_list: List[Image]):
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


def make_pdftotext_process(path):
    """Make a subprocess to hand to higher-level code.

    :param path: File location
    :return: Subprocess results
    """

    process = subprocess.Popen(
        ["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    content, err = process.communicate()
    return content.decode(), err, process.returncode


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


def get_page_count(path, extension):
    """Get the number of pages, if appropriate mimetype.

    :param path: A path to a binary (pdf, wpd, doc, txt, html, etc.)
    :param extension: The extension of the binary.
    :return: The number of pages if possible, else return None
    """
    if extension == "pdf":
        try:
            reader = PdfFileReader(path)
            return int(reader.getNumPages())
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
            return 0

    elif extension == "wpd":
        # Best solution appears to be to dig into the binary format
        pass
    elif extension == "doc":
        # Best solution appears to be to dig into the XML of the file
        # itself: http://stackoverflow.com/a/12972502/64911
        pass
    return None


# def extract_from_pdf(tmp_tiff):
#     pipe = subprocess.PIPE
#     tesseract_cmd = ["tesseract", tmp_tiff, "stdout", "-l", "eng"]
#     process = subprocess.Popen(tesseract_cmd, stdout=pipe, stderr=pipe)
#     content, err = process.communicate()
#     return content.decode("utf-8"), err, process.returncode


def extract_from_pdf(
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
    :param opinion: The Opinion associated with the PDF
    :param ocr_available: Whether we should do OCR stuff
    :return Tuple of the content itself and any errors we received
    """
    content, err, returncode = make_pdftotext_process(path)
    extracted_by_ocr = False
    if err is not None:
        err = err.decode()

    if not ocr_available:
        if "e" not in content:
            # It's a corrupt PDF from ca9. Fix it.
            content = fix_mojibake(content)
    else:
        if ocr_needed(path, content):
            success, ocr_content = extract_by_ocr(path)
            if success:
                # Check content length and take the longer of the two
                if len(ocr_content) > len(content):
                    content = ocr_content
                    # opinion.extracted_by_ocr = True
                    extracted_by_ocr = True
            elif content == "" or not success:
                content = "Unable to extract document content."

    return content, err, returncode, extracted_by_ocr


def extract_by_ocr(path: str) -> (bool, str):
    """Extract the contents of a PDF using OCR."""
    fail_msg = (
        "Unable to extract the content from this file. Please try "
        "reading the original."
    )
    with NamedTemporaryFile(prefix="ocr_", suffix=".tiff", buffering=0) as tmp:
        out, err, returncode = rasterize_pdf(path, tmp.name)
        if returncode != 0:
            return False, fail_msg

        txt = convert_file_to_txt(tmp.name)
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


def convert_file_to_txt(path: str) -> str:
    tesseract_command = [
        "tesseract",
        path,
        "stdout",
        "-l",
        "eng",
        "-c",
        "tessedit_do_invert=0",  # Assume a white background for speed
    ]
    p = subprocess.Popen(
        tesseract_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return p.communicate()[0].decode()


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


def extract_from_doc(path):
    """Extract text from docs.

    We use antiword to pull the text out of MS Doc files.
    """
    process = subprocess.Popen(
        ["antiword", path, "-i", "1"],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
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
        stderr=subprocess.DEVNULL,
    )
    content, err = process.communicate()
    return content.decode("utf-8"), err, process.returncode


def extract_from_html(path):
    """Extract from html.

    A simple wrapper to go get content, and send it along.
    """
    for encoding in ["utf-8", "ISO8859", "cp1252", "latin-1"]:
        try:
            with open(path, "r", encoding=encoding) as f:
                content = f.read()
            content = get_clean_body_content(content)
            content = force_text(content, encoding=encoding)
            return content, "", 0
        except DoctorUnicodeDecodeError:
            pass
    # Fell through, therefore unable to decode the string.
    return "", "Could not encode content properly", 1


def get_clean_body_content(content):
    """Parse out the body from an html string, clean it up, and send it along."""
    cleaner = Cleaner(style=True, remove_tags=["a", "body", "font", "noscript", "img"])
    try:
        return cleaner.clean_html(content)
    except XMLSyntaxError:
        return (
            "Unable to extract the content from this file. Please try "
            "reading the original."
        )


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
        except DoctorUnicodeDecodeError:
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
        ["wpd2html", path],
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    content, err = process.communicate()
    content = get_clean_body_content(content)

    return content.decode("utf-8"), err, process.returncode


def download_images(sorted_urls) -> List:
    """Download images and convert to list of PIL images

    Once in an array of PIL.images we can easily convert this to a PDF.

    :param sorted_urls: List of sorted URLs for split financial disclosure
    :return: image_list
    """

    async def main(urls):
        image_list = []
        loop = asyncio.get_event_loop()
        futures = [loop.run_in_executor(None, requests.get, url) for url in urls]
        for response in await asyncio.gather(*futures):
            image_list.append(response.content)
        return image_list

    loop = asyncio.get_event_loop()
    image_list = loop.run_until_complete(main(sorted_urls))

    return image_list


# Audio

root = os.path.dirname(os.path.realpath(__file__))
assets_dir = os.path.join(root, "assets")


def convert_to_mp3(output_path: AnyStr, media: Any) -> None:

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

    ffmpeg_cmd = subprocess.Popen(
        av_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=False
    )
    ffmpeg_cmd.communicate(media.read())
    return output_path


def set_mp3_meta_data(audio_data: Dict, mp3_path: AnyStr) -> eyed3.core.AudioFile:
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


def convert_to_base64(tmp_path: AnyStr) -> AnyStr:
    """Convert file base64 and decode it.

    This allows us to safely return the file in json to CL.

    :param tmp_path:
    :return: Audio file encoded in base64 as a string
    """
    with open(tmp_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def best_case_name(audio_dict: Dict) -> AnyStr:
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


def get_header_stamp(obj: Dict) -> bool:
    """pdfplumber filter to extract the PDF header stamp.

    :param obj: The page object to evaluate.
    :return: True if the found it, otherwise False.
    """

    # This option works for most juridictions except for ca5
    if "LiberationSans" in obj.get("fontname", ""):
        return True
    # Exception for ca5
    if obj["y0"] > 750:
        return True
    return False


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

    # If not matches are found, let's fail it loud
    document_number = [dn for dn in document_number_matches[0] if dn]
    return clean_document_number(document_number[0])
