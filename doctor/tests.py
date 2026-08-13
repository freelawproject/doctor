import glob
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch
from zipfile import ZipFile

import django
import eyed3
import numpy as np
import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader

from doctor.lib.text_extraction import (
    adjust_caption_lines,
    cleanup_content,
    get_word,
    insert_whitespace,
    remove_excess_whitespace,
)
from doctor.lib.utils import make_buffer, make_file

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doctor.settings")
django.setup()

asset_path = f"{Path.cwd()}/doctor/test_assets"


class HeartbeatTests(unittest.TestCase):
    def test_heartbeat(self):
        """Can we curl the heartbeat endpoint?"""
        response = requests.get("http://doctor:5050/")
        self.assertEqual(
            response.text, "Heartbeat detected.", msg="Heartbeat failed"
        )


class RECAPExtractionTests(unittest.TestCase):
    def test_recap_extraction(self):
        """Can we extract from the new recap text endpoint"""
        files = make_file(
            filename="recap_extract/gov.uscourts.cand.203070.27.0.pdf"
        )
        params = {"strip_margin": False}
        response = requests.post(
            "http://doctor:5050/extract/recap/text/",
            files=files,
            params=params,
        )
        first_line = response.json()["content"].splitlines()[0].strip()
        self.assertEqual(200, response.status_code, msg="Wrong status code")
        self.assertTrue(
            response.json()["extracted_by_ocr"], msg="Not extracted correctly"
        )
        self.assertEqual(
            "aséakOS- 08-0220 A25BA  BAD Gooonene 2627  Filed!  OL/2B/DE0IP ageahefi2of 2",
            first_line,
            msg="Wrong Text",
        )

    def test_recap_extraction_with_strip_margin(self):
        """Can we extract from the new recap text endpoint with strip margin?"""
        files = make_file(
            filename="recap_extract/gov.uscourts.cand.203070.27.0.pdf"
        )
        params = {"strip_margin": True}
        response = requests.post(
            "http://doctor:5050/extract/recap/text/",
            files=files,
            params=params,
        )
        first_line = response.json()["content"].splitlines()[0].strip()
        self.assertEqual(200, response.status_code, msg="Wrong status code")
        self.assertEqual(
            "1  || DONALD W. CARLSON  [Bar No. 79258]",
            first_line,
            msg="Wrong Text",
        )

    def test_recap_strip_marign_with_multiple_shaped_pdfs(self):
        """Can we extract atypical shape pdf with strip margin?"""

        files = make_file(
            filename="recap_extract/gov.uscourts.azd.1085839.3.0.pdf"
        )
        params = {"strip_margin": True}
        response = requests.post(
            "http://doctor:5050/extract/recap/text/",
            files=files,
            params=params,
        )
        first_line = response.json()["content"].splitlines()[0].strip()
        self.assertEqual(200, response.status_code, msg="Wrong status code")
        self.assertEqual(
            "1   WO",
            first_line,
            msg="Wrong Text",
        )

    def test_strip_margin_without_ocr(self):
        """Can we extract from the new recap text endpoint with strip margin?"""
        files = make_file(
            filename="recap_extract/gov.uscourts.cacd.652774.40.0.pdf"
        )
        params = {"strip_margin": True}
        response = requests.post(
            "http://doctor:5050/extract/recap/text/",
            files=files,
            params=params,
        )
        first_line = response.json()["content"].splitlines()[0].strip()
        self.assertEqual(200, response.status_code, msg="Wrong status code")
        self.assertEqual("1", first_line, msg="Wrong Text")


class ExtractionTests(unittest.TestCase):
    def test_pdf_to_text(self):
        """"""
        files = make_file(filename="vector-pdf.pdf")
        data = {"ocr_available": True}
        response = requests.post(
            "http://doctor:5050/extract/doc/text/", files=files, data=data
        )
        text = response.json()["content"][:100].replace("\n", "").strip()
        self.assertEqual(200, response.status_code, msg="Wrong status code")
        self.assertEqual(
            text,
            "(Slip Opinion)              OCTOBER TERM, 2012                                       1",
            msg=text,
        )

    def test_content_extraction(self):
        """"""
        files = make_file(filename="vector-pdf.pdf")
        data = {"ocr_available": False}
        response = requests.post(
            "http://doctor:5050/extract/doc/text/", files=files, data=data
        )
        self.assertTrue(response.ok, msg="Content extraction failed")
        self.assertEqual(
            response.json()["content"][:100].replace("\n", "").strip(),
            "(Slip Opinion)              OCTOBER TERM, 2012                                       1",
            msg="Failed to extract content from .pdf file",
        )
        self.assertFalse(
            response.json()["extracted_by_ocr"],
            msg="Failed to extract by OCR",
        )
        self.assertEqual(
            response.json()["page_count"],
            30,
            msg="Failed to extract by OCR",
        )

    def test_pdf_ocr_extraction(self):
        files = make_file(filename="image-pdf.pdf")
        params = {"ocr_available": True}
        response = requests.post(
            "http://doctor:5050/extract/doc/text/",
            files=files,
            params=params,
        )
        self.assertTrue(response.ok, msg="Content extraction failed")
        content = response.json()["content"][:100].replace("\n", "").strip()
        self.assertEqual(
            content,
            "(Slip Opinion) OCTOBER TERM, 2012 1SyllabusNOTE: Where it is feasible, a syllabus (headnote) wil",
            msg="Failed to extract content from image .pdf file",
        )
        self.assertTrue(
            response.json()["extracted_by_ocr"],
            msg="Failed to extract by OCR",
        )

    def test_pdf_v2_ocr_extraction(self):
        files = make_file(filename="ocr_pdf_variation.pdf")
        params = {"ocr_available": True}
        response = requests.post(
            "http://doctor:5050/extract/doc/text/",
            files=files,
            params=params,
        )
        self.assertTrue(response.ok, msg="Content extraction failed")
        content = response.json()["content"][:100].replace("\n", "").strip()
        self.assertIn(
            "UNITED",
            content,
            msg="Failed to extract content from ocr_pdf_variation .pdf file",
        )
        self.assertTrue(
            response.json()["extracted_by_ocr"],
            msg="Failed to extract by OCR",
        )

    def test_docx_format(self):
        files = make_file(filename="word-docx.docx")
        params = {"ocr_available": False}
        response = requests.post(
            "http://doctor:5050/extract/doc/text/",
            files=files,
            params=params,
        )
        self.assertTrue(response.ok, msg="Content extraction failed")
        self.assertEqual(
            response.json()["content"][:200].replace("\n", "").strip(),
            "ex- Cpl,                                                                                                 Current Discharge and Applicant's RequestApplication R",
            msg="Failed to extract content from .docx file",
        )

    def test_doc_format(self):
        files = make_file(filename="word-doc.doc")
        data = {"ocr_available": False}
        response = requests.post(
            "http://doctor:5050/extract/doc/text/", files=files, data=data
        )
        self.assertTrue(response.ok, msg="Content extraction failed")
        content = response.json()["content"][:100].replace("\n", "").strip()
        self.assertEqual(
            content,
            "Attorneys for Appellant                            Attorneys for AppelleeSteve Carter",
            msg="Failed to extract content from .doc file",
        )
        self.assertEqual(
            response.json()["page_count"],
            None,
            msg="Failed to extract by OCR",
        )

    def test_wpd_format(self):
        files = make_file(filename="word-perfect.wpd")
        data = {"ocr_available": False}
        response = requests.post(
            "http://doctor:5050/extract/doc/text/", files=files, data=data
        )
        self.assertTrue(response.ok, msg="Content extraction failed")
        self.assertIn(
            "ATTORNEY FOR APPELLANT",
            response.json()["content"],
            msg="Failed to extract content from WPD file",
        )
        self.assertEqual(
            14259,
            len(response.json()["content"]),
            msg="Failed to extract content from WPD file",
        )


class ThumbnailTests(unittest.TestCase):
    """Can we generate thumbnail images from PDF files"""

    def test_convert_pdf_to_thumbnail_png(self):
        """Can we generate four thumbanils a pdf?"""
        files = make_file(filename="image-pdf.pdf")
        data = {"max_dimension": 350}
        response = requests.post(
            "http://doctor:5050/convert/pdf/thumbnail/",
            files=files,
            data=data,
        )
        with open("doctor/test_assets/image-pdf-thumbnail.png", "rb") as f:
            answer = f.read()
        self.assertEqual(answer, response.content)

        files = make_file(filename="image-pdf-2.pdf")
        response = requests.post(
            "http://doctor:5050/convert/pdf/thumbnail/", files=files
        )
        with open("doctor/test_assets/image-pdf-2-thumbnail.png", "rb") as f:
            second_answer = f.read()
        self.assertEqual(second_answer, response.content)

        files = make_file(filename="empty.pdf")
        response = requests.post(
            "http://doctor:5050/convert/pdf/thumbnail/", files=files
        )
        self.assertEqual(response.status_code, 400, msg="Wrong status code")

    def test_thumbnail_range(self):
        """Can we generate a thumbnail for a range of pages?"""
        files = make_file(filename="vector-pdf.pdf")
        pages = [1, 2, 3, 4]
        data = {
            "max_dimension": 350,
            "pages": json.dumps(pages),
        }

        response = requests.post(
            "http://doctor:5050/convert/pdf/thumbnails/",
            files=files,
            data=data,
        )
        with NamedTemporaryFile(suffix=".zip") as tmp:
            with open(tmp.name, "wb") as f:
                f.write(response.content)
            with ZipFile(tmp.name, "r") as zipObj:
                listOfiles = sorted(zipObj.namelist())
        self.assertEqual(len(listOfiles), 4)
        self.assertEqual(
            ["thumb-1.png", "thumb-2.png", "thumb-3.png", "thumb-4.png"],
            listOfiles,
        )


class MetadataTests(unittest.TestCase):
    """Can we count page numbers in PDF files"""

    def test_page_count_pdf(self):
        """"""
        files = make_file(filename="image-pdf.pdf")
        page_count = requests.post(
            "http://doctor:5050/utils/page-count/pdf/", files=files
        ).text
        self.assertEqual(int(page_count), 2, "Failed to get page count")

    def test_mime_type(self):
        """"""
        files = make_file(filename="image-pdf.pdf")
        params = {"mime": True}
        response = requests.post(
            "http://doctor:5050/utils/mime-type/",
            files=files,
            params=params,
        ).json()
        self.assertEqual(
            response["mimetype"],
            "application/pdf",
            msg="Failed to get mime type",
        )

    def test_broken_mime_type(self):
        """"""
        files = make_buffer(filename="broken-mime.pdf")
        params = {"mime": True}
        response = requests.post(
            "http://doctor:5050/utils/file/extension/",
            files=files,
            params=params,
        )
        self.assertEqual(response.text, ".pdf", msg="Failed to get mime type")

        files = make_buffer(filename="missouri.pdf")
        params = {"mime": True}
        response = requests.post(
            "http://doctor:5050/utils/file/extension/",
            files=files,
            params=params,
        )
        self.assertEqual(response.text, ".pdf", msg="Failed to get mime type")

    def test_mime_type_unknown_name(self):
        """"""
        files = make_buffer(filename="image-pdf.pdf")
        response = requests.post(
            "http://doctor:5050/utils/mime-type/",
            files=files,
            params={"mime": True},
        ).json()
        self.assertEqual(
            response["mimetype"],
            "application/pdf",
            msg="Failed to get mime type",
        )

    def test_get_extension(self):
        """Verify that /utils/file/extension/ correctly infers extensions for common types."""
        test_files = [
            ("image-pdf.pdf", ".pdf"),
            ("broken-mime.pdf", ".pdf"),
            ("word-docx.docx", ".docx"),
            ("word-doc.doc", ".doc"),
            ("word-perfect.wpd", ".wpd"),
            ("1.wma", ".wma"),
            ("ander_v._leo.mp3", ".mp3"),
            ("long-image.tiff", ".tiff"),
            ("small_txt.txt", ".txt"),
            ("broken_html.html", ".html"),
            ("broken_html.txt", ".html"),
            ("small.xml", ".xml"),
            ("1.rm", ".rm"),
            (
                "adobe-metadata.pdf",
                ".pdf",
            ),  # PDF with Adobe XMP metadata (issue #223)
        ]

        for filename, expected_ext in test_files:
            with self.subTest(filename=filename):
                files = make_buffer(filename=filename)
                response = requests.post(
                    "http://doctor:5050/utils/file/extension/", files=files
                )
                self.assertEqual(
                    response.text.strip(),
                    expected_ext,
                    msg=f"Failed to detect extension for {filename}",
                )

    def test_temp_file_cleanup(self):
        """Verify that uploading a file creates a temp file that is cleaned up"""
        client = Client()

        created_temp_files = []

        # Wrapper around real NamedTemporaryFile to capture the filename
        real_named_temporary_file = tempfile.NamedTemporaryFile

        def capture_temp_file_creation(*args, **kwargs):
            fp = real_named_temporary_file(*args, **kwargs)
            created_temp_files.append(fp.name)
            return fp

        filename, expected_ext = ("image-pdf.pdf", ".pdf")
        files = make_buffer(filename=filename)
        file_bytes = files["file"][1]

        django_file = SimpleUploadedFile(
            name=filename,
            content=file_bytes,
            content_type="application/pdf",
        )

        with patch(
            "tempfile.NamedTemporaryFile",
            side_effect=capture_temp_file_creation,
        ):
            response = client.post(
                reverse("file-extension"),
                data={"file": django_file},
            )

        # Validate extension result to be sure that it is working
        self.assertEqual(
            response.content.decode().strip(),
            expected_ext,
        )

        # Validate file creation count
        self.assertEqual(len(created_temp_files), 1)

        # Validate main cleanup logic
        fp = created_temp_files[0]
        self.assertFalse(
            os.path.exists(fp),
            msg=f"Temporary file was NOT deleted: {fp}",
        )


def test_embedding_text_to_image_pdf(self):
    """Can we embed text into an image PDF?"""
    data = {"ocr_available": False}

    files = make_file(filename="image-pdf.pdf")
    image_response = requests.post(
        "http://doctor:5050/extract/doc/text/", files=files, data=data
    )
    self.assertEqual(
        "",
        image_response.json()["content"].strip("\x0c"),
        msg="PDF should have no text",
    )

    # Embed text into the image pdf and check that we get some text
    new_pdf = requests.post(
        "http://doctor:5050/utils/add/text/pdf/", files=files
    )
    with NamedTemporaryFile(suffix=".pdf") as tmp:
        with open(tmp.name, "wb") as f:
            f.write(new_pdf.content)
        with open(tmp.name, "rb") as f:
            files = {"file": (tmp.name, f.read())}

        # Confirm that text is now embedded in the PDF
        response = requests.post(
            "http://doctor:5050/extract/doc/text/",
            files=files,
            data=data,
        )
        self.assertIn(
            "(SlipOpinion)             OCTOBER TERM, 2012",
            response.json()["content"],
            msg=f"Got {response.json()}",
        )

    def test_get_document_number(self):
        """Check if the PACER document number is correctly extracted from
        documents from multiple jurisdictions.
        """

        filepath = f"{Path.cwd()}/doctor/test_assets/recap_documents/"
        for file in glob.glob(os.path.join(filepath, "*.pdf")):
            filename = os.path.relpath(file, filepath)
            filename_sans_ext = filename.split(".")[0]
            doc_num = filename_sans_ext.split("_")[1]

            with open(file, "rb") as f:
                files = {"file": (filename, f.read())}

                document_number = requests.post(
                    "http://doctor:5050/utils/document-number/pdf/",
                    files=files,
                ).text

            self.assertEqual(doc_num, document_number)


class RedactionTest(unittest.TestCase):
    def test_xray_no_pdf(self):
        """Are we able to discover bad redacts?"""
        filepath = f"{Path.cwd()}/doctor/test_assets/x-ray/"
        test_files = (
            "*yes*.pdf",
            "*no*.pdf",
        )
        for pattern in test_files:
            direction = re.search("yes", pattern)
            for file in glob.glob(os.path.join(filepath, pattern)):
                filename = os.path.relpath(file, filepath)

                with open(file, "rb") as f:
                    files = {"file": (filename, f.read())}
                    response = requests.post(
                        "http://doctor:5050/utils/check-redactions/pdf/",
                        files=files,
                    )
                    # Break up the assertion so that testers can see which
                    # part is actually failing
                    self.assertTrue(response.ok)
                    bb = response.json()
                    self.assertFalse(bb["error"])
                    if not direction:
                        self.assertTrue(len(bb["results"]) == 0)
                    else:
                        self.assertFalse(len(bb["results"]) == 0)


class ImageDisclosuresTest(unittest.TestCase):
    def test_images_to_pdf(self):
        """Do we create a PDF from several tiffs successfully?"""
        base = "https://com-courtlistener-storage.s3-us-west-2.amazonaws.com/financial-disclosures/2011/A-E/Armstrong-SB%20J3.%2009.%20CAN_R_11/Armstrong-SB%20J3.%2009.%20CAN_R_11_Page"
        sorted_urls = [
            f"{base}_1.tiff",
            f"{base}_2.tiff",
        ]
        params = {"sorted_urls": json.dumps(sorted_urls)}
        response = requests.post(
            "http://doctor:5050/convert/images/pdf/",
            params=params,
        )
        self.assertEqual(response.status_code, 200, msg="Failed status code.")
        self.assertEqual(
            b"%PDF-1.3\n",
            response.content[:9],
            msg="PDF generation failed",
        )


class AudioConversionTests(unittest.TestCase):
    """Test Audio Conversion"""

    def test_wma_to_mp3(self):
        """Can we convert to mp3 with metadata"""

        audio_details = {
            "court_full_name": "Testing Supreme Court",
            "court_short_name": "Testing Supreme Court",
            "court_pk": "mad",
            "court_url": "http://www.example.com/",
            "docket_number": "docket number 1 005",
            "date_argued": "2020-01-01",
            "date_argued_year": "2020",
            "case_name": "SEC v. Frank J. Custable, Jr.",
            "case_name_full": "case name full",
            "case_name_short": "short",
            "download_url": "http://media.ca7.uscourts.gov/sound/external/gw.15-1442.15-1442_07_08_2015.mp3",
        }

        files = make_file(filename="1.wma")
        response = requests.post(
            "http://doctor:5050/convert/audio/mp3/",
            files=files,
            params=audio_details,
        )
        self.assertEqual(response.status_code, 200, msg="Bad status code")

        # Validate some metadata in the MP3.
        with NamedTemporaryFile(suffix=".mp3") as tmp:
            with open(tmp.name, "wb") as mp3_data:
                mp3_data.write(response.content)
                mp3_file = eyed3.load(tmp.name)

            self.assertEqual(
                mp3_file.tag.publisher,
                "Free Law Project",
                msg="Publisher metadata failed.",
            )
            self.assertEqual(
                mp3_file.tag.title,
                "SEC v. Frank J. Custable, Jr.",
                msg="Title metadata failed.",
            )
            self.assertEqual(
                mp3_file.type,
                eyed3.core.AUDIO_MP3,
                msg="Audio conversion to mp3 failed.",
            )

    def test_audio_duration(self):
        files = make_file(filename="1.mp3")
        response = requests.post(
            "http://doctor:5050/utils/audio/duration/",
            files=files,
        )
        self.assertEqual(51.64, float(response.text), msg="Bad duration")


def render_pdf_page_to_gray(pdf_bytes: bytes, page: int) -> np.ndarray:
    """Rasterize one page of a PDF to a grayscale array at 100 dpi."""
    with NamedTemporaryFile(suffix=".pdf") as tmp:
        with open(tmp.name, "wb") as f:
            f.write(pdf_bytes)
        out = subprocess.run(
            [
                "pdftoppm",
                "-singlefile",
                "-gray",
                "-r",
                "100",
                "-f",
                str(page),
                tmp.name,
            ],
            capture_output=True,
            check=True,
        ).stdout
    return np.asarray(Image.open(io.BytesIO(out)).convert("L"))


def marker_index(gray: np.ndarray) -> int:
    """Decode the page index encoded in a fixture page's marker bar.

    The bitonal fixtures draw a black bar at x 40-140px whose height
    is (page index * 60px), so the index survives any conversion that
    preserves the raster and is wrong if pages are reordered.
    """
    column = gray[:, 90]
    return round((column < 128).sum() / 60)


class BitonalConversionTests(unittest.TestCase):
    """Inline (multipart) mode of /convert/pdf/bitonal/."""

    endpoint = "http://doctor:5050/convert/pdf/bitonal/"
    fixture = "bitonal_marker_scan.pdf"

    def convert(self, data=None, filename=None):
        return requests.post(
            self.endpoint,
            files=make_file(filename=filename or self.fixture),
            data={"dpi": 100, "threshold": 128, **(data or {})},
        )

    def test_bitonal_structure(self):
        """Is every output page a 1-bit raw CCITT G4 image?"""
        response = self.convert()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/pdf")
        source = PdfReader(f"{asset_path}/{self.fixture}")
        result = PdfReader(io.BytesIO(response.content))
        self.assertEqual(len(result.pages), len(source.pages))
        for source_page, result_page in zip(source.pages, result.pages):
            self.assertEqual(
                [float(v) for v in source_page.mediabox],
                [float(v) for v in result_page.mediabox],
                msg="MediaBox must be copied from the source page",
            )
            image = result_page["/Resources"]["/XObject"]["/Im0"]
            self.assertEqual(image["/Filter"], "/CCITTFaxDecode")
            self.assertEqual(image["/BitsPerComponent"], 1)
            self.assertEqual(image["/DecodeParms"]["/K"], -1)
        source_size = os.path.getsize(f"{asset_path}/{self.fixture}")
        self.assertLess(
            len(response.content),
            source_size / 2,
            msg="bitonal output should be much smaller than the scan",
        )

    def test_page_order_and_polarity(self):
        """Are pages in order, black-on-white, after conversion?"""
        response = self.convert()
        for page in range(1, 6):
            gray = render_pdf_page_to_gray(response.content, page)
            self.assertGreater(
                (gray > 128).mean(),
                0.5,
                msg=f"page {page} should be mostly white paper",
            )
            self.assertEqual(
                marker_index(gray),
                page,
                msg=f"page {page} marker decodes to the wrong index",
            )

    def test_page_range(self):
        """Does a 1-indexed inclusive page range subset correctly?"""
        response = self.convert(data={"first_page": 2, "last_page": 4})
        self.assertEqual(response.status_code, 200)
        result = PdfReader(io.BytesIO(response.content))
        self.assertEqual(len(result.pages), 3)
        for position, source_index in enumerate([2, 3, 4], start=1):
            gray = render_pdf_page_to_gray(response.content, position)
            self.assertEqual(marker_index(gray), source_index)

    def test_thresholding_does_not_dither(self):
        """Does a gradient threshold to one clean step, not speckle?"""
        response = self.convert(filename="bitonal_gradient.pdf")
        self.assertEqual(response.status_code, 200)
        gray = render_pdf_page_to_gray(response.content, 1)
        row = gray[gray.shape[0] // 2] > 128
        transitions = int((row[1:] != row[:-1]).sum())
        self.assertLessEqual(
            transitions,
            5,
            msg="a thresholded gradient must be a single black/white "
            "step; many transitions mean dithering happened",
        )
        self.assertFalse(row[0], msg="dark side should threshold black")
        self.assertTrue(row[-1], msg="light side should threshold white")

    def test_validation_failures(self):
        """Are bad parameters rejected with the error taxonomy?"""
        no_input = requests.post(self.endpoint, data={"dpi": 100})
        self.assertEqual(no_input.status_code, 400)
        self.assertEqual(no_input.json()["error_code"], "VALIDATION_FAILED")
        for bad in ({"dpi": 1200}, {"threshold": 300}, {"first_page": 0}):
            response = self.convert(data=bad)
            self.assertEqual(response.status_code, 400, msg=str(bad))
            self.assertEqual(
                response.json()["error_code"],
                "VALIDATION_FAILED",
                msg=str(bad),
            )

    def test_page_range_beyond_document(self):
        response = self.convert(data={"first_page": 99})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "PAGE_RANGE_INVALID")


class StubS3Server(ThreadingHTTPServer):
    """An in-process stand-in for presigned S3 GET/PUT targets.

    Behavior is a per-instance queue of status codes so tests can
    script sequences like [500, 500, 200] to exercise retries.
    """

    def __init__(self, fixture_bytes: bytes):
        super().__init__(("127.0.0.1", 0), StubS3Handler)
        self.fixture_bytes = fixture_bytes
        self.get_statuses: list[int] = []
        self.put_statuses: list[int] = []
        self.get_count = 0
        self.put_count = 0
        self.received_puts: list[dict] = []


class StubS3Handler(BaseHTTPRequestHandler):
    server: StubS3Server

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.get_count += 1
        status = (
            self.server.get_statuses.pop(0)
            if self.server.get_statuses
            else 200
        )
        if status != 200:
            self.send_response(status)
            self.end_headers()
            return
        body = self.server.fixture_bytes
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        self.server.put_count += 1
        body = self.rfile.read(int(self.headers["Content-Length"]))
        status = (
            self.server.put_statuses.pop(0)
            if self.server.put_statuses
            else 200
        )
        if status == 200:
            self.server.received_puts.append(
                {
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "bytes": len(body),
                    "content_type": self.headers["Content-Type"],
                }
            )
        self.send_response(status)
        self.end_headers()


class BitonalTransportTests(unittest.TestCase):
    """Presigned GET/PUT mode of /convert/pdf/bitonal/.

    The stub server runs in this test process; the suite executes
    inside the doctor container, so the service reaches it on
    127.0.0.1.
    """

    endpoint = "http://doctor:5050/convert/pdf/bitonal/"
    fixture = "bitonal_marker_scan.pdf"

    def setUp(self):
        with open(f"{asset_path}/{self.fixture}", "rb") as f:
            self.fixture_bytes = f.read()
        self.server = StubS3Server(self.fixture_bytes)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        port = self.server.server_address[1]
        self.input_url = f"http://127.0.0.1:{port}/in/shard_0001.pdf"
        self.output_url = f"http://127.0.0.1:{port}/out/shard_0001.pdf"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def convert(self, **extra):
        return requests.post(
            self.endpoint,
            data={
                "input_url": self.input_url,
                "output_url": self.output_url,
                "dpi": 100,
                "threshold": 128,
                **extra,
            },
        )

    def test_presigned_roundtrip(self):
        """Happy path: GET the input, PUT the result, JSON summary."""
        response = self.convert()
        self.assertEqual(response.status_code, 200, msg=response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["pages"], 5)
        self.assertEqual(
            payload["source_sha256"],
            hashlib.sha256(self.fixture_bytes).hexdigest(),
        )
        self.assertEqual(len(self.server.received_puts), 1)
        received = self.server.received_puts[0]
        self.assertEqual(received["sha256"], payload["sha256"])
        self.assertEqual(received["bytes"], payload["bytes"])
        self.assertEqual(received["content_type"], "application/pdf")

    def test_input_url_expired(self):
        """A 403 on the input URL must fail fast, without retries."""
        self.server.get_statuses = [403]
        response = self.convert()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error_code"], "INPUT_URL_EXPIRED")
        self.assertEqual(self.server.get_count, 1)
        self.assertEqual(self.server.put_count, 0)

    def test_input_url_5xx_is_retried(self):
        self.server.get_statuses = [500, 500, 200]
        response = self.convert()
        self.assertEqual(response.status_code, 200, msg=response.text)
        self.assertEqual(self.server.get_count, 3)

    def test_result_url_expired(self):
        """A 403 on the output URL must fail fast, without retries."""
        self.server.put_statuses = [403]
        response = self.convert()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error_code"], "RESULT_URL_EXPIRED")
        self.assertEqual(self.server.put_count, 1)

    def test_result_upload_5xx_is_retried(self):
        self.server.put_statuses = [500, 500, 200]
        response = self.convert()
        self.assertEqual(response.status_code, 200, msg=response.text)
        self.assertEqual(self.server.put_count, 3)

    def test_result_upload_exhausts_retries(self):
        self.server.put_statuses = [500, 500, 500]
        response = self.convert()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error_code"], "RESULT_UPLOAD_FAILED")
        self.assertEqual(self.server.put_count, 3)


class EgressPolicyTests(unittest.TestCase):
    """Unit tests for the egress allowlist validator."""

    def test_egress_policy(self):
        from django.test import override_settings

        from doctor.lib.bitonal import BitonalError
        from doctor.tasks import validate_egress_url

        with override_settings(
            DOCTOR_EGRESS_ALLOWED_HOSTS=["*.amazonaws.com"]
        ):
            validate_egress_url(
                "https://bucket.s3.amazonaws.com/key?X-Amz-Signature=x"
            )
            for blocked in (
                "http://bucket.s3.amazonaws.com/key",  # not https
                "https://evil.example.com/key",  # host not allowed
                "https://127.0.0.1:9/key",  # host not allowed
            ):
                with self.assertRaises(BitonalError, msg=blocked) as ctx:
                    validate_egress_url(blocked)
                self.assertEqual(ctx.exception.error_code, "EGRESS_BLOCKED")
        with override_settings(DOCTOR_EGRESS_ALLOWED_HOSTS=[]):
            validate_egress_url("http://anything.example.com/key")


class TestFailedValidations(unittest.TestCase):
    def test_for_400s(self):
        """Test validation for missing audio file"""
        response = requests.post(
            "http://doctor:5050/utils/audio/duration/",
        )
        self.assertEqual(response.status_code, 400, msg="Wrong validation")

    def test_pdf_400s(self):
        """Test validation for missing PDF file"""
        response = requests.post(
            "http://doctor:5050/extract/doc/text/",
        )
        self.assertEqual(
            "Failed validation",
            response.text,
            msg="Wrong validation error",
        )
        self.assertEqual(response.status_code, 400, msg="Wrong validation")

    def test_pdf_400_mime(self):
        """Test return 400 on missing file for mime extraction"""
        response = requests.post(
            "http://doctor:5050/utils/mime-type/",
            params={"mime": True},
        )
        self.assertEqual(response.status_code, 400, msg="Wrong validation")


class TestRecapWhitespaceInsertions(unittest.TestCase):
    """Test our whitespace insertion code"""

    def test_insert_whitespace_new_line(self):
        content = "foo"
        word = {
            "line_num": 2,
            "par_num": 1,
            "left": 50,
            "top": 200,
            "width": 10,
            "height": 20,
        }
        prev = {
            "line_num": 1,
            "par_num": 1,
            "left": 10,
            "top": 100,
            "width": 30,
            "height": 20,
        }
        result = insert_whitespace(content, word, prev)
        self.assertEqual(result, "foo\n  ")

    def test_insert_whitespace_new_paragraph(self):
        content = "foo"
        word = {
            "line_num": 1,
            "par_num": 2,
            "left": 50,
            "top": 200,
            "width": 10,
            "height": 20,
        }
        prev = {
            "line_num": 2,
            "par_num": 1,
            "left": 10,
            "top": 100,
            "width": 30,
            "height": 20,
        }
        result = insert_whitespace(content, word, prev)
        self.assertEqual(result, "foo\n  ")

    def test_insert_whitespace_vertical_gap(self):
        content = "foo"
        word = {
            "line_num": 2,
            "par_num": 1,
            "left": 50,
            "top": 300,
            "width": 10,
            "height": 20,
        }
        prev = {
            "line_num": 1,
            "par_num": 1,
            "left": 10,
            "top": 100,
            "width": 30,
            "height": 20,
        }
        result = insert_whitespace(content, word, prev)
        self.assertEqual(result, "foo\n\n  ")

    def test_insert_whitespace_horizontal_gap(self):
        content = "foo"
        word = {
            "line_num": 1,
            "par_num": 1,
            "left": 200,
            "top": 100,
            "width": 10,
            "height": 20,
        }
        prev = {
            "line_num": 1,
            "par_num": 1,
            "left": 10,
            "top": 100,
            "width": 30,
            "height": 20,
        }
        result = insert_whitespace(content, word, prev)
        self.assertEqual(result, "foo      ")

    def test_insert_whitespace_no_gap(self):
        content = "foo"
        word = {
            "line_num": 1,
            "par_num": 1,
            "left": 50,
            "top": 100,
            "width": 10,
            "height": 20,
        }
        prev = {
            "line_num": 1,
            "par_num": 1,
            "left": 40,
            "top": 100,
            "width": 10,
            "height": 20,
        }
        result = insert_whitespace(content, word, prev)
        self.assertEqual(result, "foo")


class TestOCRConfidenceTests(unittest.TestCase):
    """Test our OCR confidence checking functions."""

    def test_confidence_zero(self):
        word_dict = {"text": "foo", "conf": 0, "left": 10, "width": 30}
        result = get_word(word_dict, 612, True)
        self.assertEqual(result, "    ")

    def test_confidence_low_and_in_margin(self):
        word_dict = {"text": "foo", "conf": 30, "left": 5, "width": 20}
        result = get_word(word_dict, 612, True)
        self.assertEqual(result, "    ")

    def test_confidence_below_threshold_short_word(self):
        word_dict = {"text": "foo", "conf": 3, "left": 200, "width": 20}
        result = get_word(word_dict, 612, True)
        self.assertEqual(result, "□□□ ")

    def test_confidence_below_threshold_long_word(self):
        word_dict = {
            "text": "foobarbazfoobarbazfoobar",
            "conf": 3,
            "left": 200,
            "width": 200,
        }
        result = get_word(word_dict, 612, True)
        self.assertEqual(result, "□□□□□□□□□□□□□□□□□□□□□□□□ ")

    def test_confidence_below_threshold_in_right_margin(self):
        word_dict = {"text": "foo", "conf": 30, "left": 580, "width": 10}
        result = get_word(word_dict, 612, True)
        self.assertEqual(result, "□□□ ")

    def test_valid_word_high_confidence(self):
        word_dict = {"text": "foo", "conf": 90, "left": 50, "width": 20}
        result = get_word(word_dict, 612, True)
        self.assertEqual(result, "foo ")

    def test_word_on_left_edge(self):
        word_dict = {"text": "foo", "conf": 50, "left": 0, "width": 20}
        result = get_word(word_dict, 612, True)
        self.assertEqual(result, "    ")


class TestWhiteSpaceRemoval(unittest.TestCase):
    def test_left_shift(self):
        """Can we properly shift our text left?"""
        document = """
        foo
    bar
    foo
    bar"""
        expected_result = """    foo
bar
foo
bar"""
        result = remove_excess_whitespace(document)
        self.assertEqual(result, expected_result)

    def test_left_shift_when_artifact_exists(self):
        """Shift left once"""
        document = """
        foo
    bar
 |  foo
    bar"""
        expected_result = """       foo
   bar
|  foo
   bar"""
        result = remove_excess_whitespace(document)
        self.assertEqual(result, expected_result)


class TestCleanupContent(unittest.TestCase):
    def setUp(self):
        # Patch the functions before each test method
        patcher1 = patch(
            "doctor.lib.text_extraction.adjust_caption_lines",
            side_effect=lambda x: x,
        )
        patcher2 = patch(
            "doctor.lib.text_extraction.remove_excess_whitespace",
            side_effect=lambda x: x,
        )
        self.mock_adjust = patcher1.start()
        self.mock_remove_whitespace = patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)

    def test_remove_floating_pipes(self):
        """Can we remove a pipe"""
        content = "This is a test line     | \nAnother line"
        expected_result = "This is a test line\nAnother line\n"
        result = cleanup_content(content, 2)
        self.assertEqual(result, expected_result)

    def test_remove_floating_artifacts_right_side(self):
        """Can we remove an artifact on the far right"""
        content = "This is a test line          e \nAnother line"
        expected_result = "This is a test line\nAnother line\n"
        result = cleanup_content(content, 2)
        self.assertEqual(result, expected_result)

    def test_remove_floating_pipes_and_artifacts(self):
        """Test to remove just the period"""
        content = "This is a test line     | and the content continues\nThis is another test line              e \nFinal line"
        expected_result = "This is a test line     | and the content continues\nThis is another test line\nFinal line\n"
        result = cleanup_content(content, 2)
        self.assertEqual(result, expected_result)

    def test_no_floating_pipes_or_artifacts(self):
        """Test that no floating pipes are an issue"""
        content = (
            "This is a test line                     JW-6\nAnother line\n"
        )
        expected_result = (
            "This is a test line                     JW-6\nAnother line\n\n"
        )
        result = cleanup_content(content, 2)
        self.assertEqual(result, expected_result)

    def test_adjust_caption(self):
        """Test if we can align the caption correctly"""
        content = """             10
                 LESLIE MASSEY,                    )  Case No.:  2:16-cv-05001 GJS
                                                       )
                                 oe                    )  PROPOSED} ORDER AWARDING
             12               Plaintiff,                    )   EQUAL ACCESS TO JUSTICE ACT
                                                )    ATTORNEY FEES AND EXPENSES
             13         VS.                              )  PURSUANT TO 28 U.S.C. § 2412(d)
                 NANCY A. BERRYHILL, Acting      )  AND COSTS PURSUANT TO 28
             14 || Commissioner of Social Security,       )  U.S.C. §  1920
             15               Defendant                 )
             16                                         ) """

        expected_result = """             10
                 LESLIE MASSEY,                             )  Case No.:  2:16-cv-05001 GJS
                                                            )
                                 oe                         )  PROPOSED} ORDER AWARDING
             12               Plaintiff,                    )   EQUAL ACCESS TO JUSTICE ACT
                                                            )    ATTORNEY FEES AND EXPENSES
             13         VS.                                 )  PURSUANT TO 28 U.S.C. § 2412(d)
                 NANCY A. BERRYHILL, Acting                 )  AND COSTS PURSUANT TO 28
             14 || Commissioner of Social Security,         )  U.S.C. §  1920
             15               Defendant                     )
             16                                             ) """
        content = adjust_caption_lines(content)
        self.assertEqual(expected_result, content)


if __name__ == "__main__":
    unittest.main()
