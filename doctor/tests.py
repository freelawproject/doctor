import json
import os
import re
import glob
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

import eyed3
import requests

from doctor.lib.utils import make_file, make_buffer

asset_path = f"{Path.cwd()}/doctor/test_assets"


class HeartbeatTests(unittest.TestCase):
    def test_heartbeat(self):
        """Can we curl the heartbeat endpoint?"""
        response = requests.get("http://doctor:5050/")
        self.assertEqual(
            response.text, "Heartbeat detected.", msg="Heartbeat failed"
        )


class ExtractionTests(unittest.TestCase):
    def test_pdf_to_text(self):
        """"""
        files = make_file(filename="vector-pdf.pdf")
        response = requests.post(
            "http://doctor:5050/extract/doc/text/", files=files, data={}
        )
        text = response.json()["content"].strip()[:200]
        self.assertEqual(200, response.status_code, msg="Wrong status code")
        self.assertIn("(Slip\xa0Opinion)", text, msg="Text not found")

    def test_content_extraction(self):
        """Test if we can extract text from a PDF"""

        files = make_file(filename="vector-pdf.pdf")
        data = {}
        response = requests.post(
            "http://doctor:5050/extract/doc/text/", files=files, data=data
        )
        doc_content = response.json()["content"]
        self.assertTrue(response.ok, msg="Content extraction failed")
        self.assertIn(
            "(Slip\xa0Opinion)",
            doc_content[:100],
            msg="Failed to extract content from .pdf file",
        )
        self.assertFalse(
            response.json()["extracted_by_ocr"],
            msg="Failed to extract by OCR",
        )
        self.assertEqual(
            response.json()["page_count"],
            28,
            msg="Failed to extract by OCR",
        )

    def test_pdf_ocr_extraction(self):
        files = make_file(filename="image-pdf.pdf")
        response = requests.post(
            "http://doctor:5050/extract/doc/text/",
            files=files,
            params={},
        )
        self.assertTrue(response.ok, msg="Content extraction failed")
        content = response.json()["content"][:100].strip()
        self.assertIn(
            "(Slip Opinion)",
            content,
            msg="Failed to extract content from image .pdf file",
        )
        self.assertTrue(
            response.json()["extracted_by_ocr"],
            msg="Failed to extract by OCR",
        )

    def test_pdf_v2_ocr_extraction(self):
        files = make_file(filename="ocr_pdf_variation.pdf")
        params = {}
        r = requests.post(
            "http://doctor:5050/extract/doc/text/",
            files=files,
            params=params,
        )
        self.assertTrue(r.ok, msg="Content extraction failed")
        content = r.json()["content"][:100].replace("\n", "").strip()
        self.assertIn(
            "UNITED",
            content,
            msg=f"Failed to extract content from ocr_pdf_variation .pdf file {content}",
        )
        self.assertTrue(
            r.json()["extracted_by_ocr"],
            msg="Failed to extract by OCR",
        )

    def test_docx_format(self):
        files = make_file(filename="word-docx.docx")
        params = {}
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
        data = {}
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
        data = {}
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

    def test_recap_pdf_with_images_and_annotations(self):
        """Test PDF with images and text annotations"""
        filepath = Path(
            "doctor/test_assets/recap_issues/gov.uscourts.cand.203343.17.0.pdf"
        )
        r = requests.post(
            url="http://doctor:5050/extract/doc/text/",
            files={"file": (filepath.name, filepath.read_bytes())},
            params={
                "strip_margin": False,
            },
        )
        self.assertIn("TELEPHONIC APPEARANCE", r.json()['content'], msg=r.json()['content'])

    def test_pdf_with_missing_fonts(self):
        """Test PDF with missing fonts"""
        filepath = Path(
            "doctor/test_assets/recap_issues/gov.uscourts.nysd.413994.212.0.pdf"
        )
        r = requests.post(
            url="http://doctor:5050/extract/doc/text/",
            files={"file": (filepath.name, filepath.read_bytes())},
            params={
                "strip_margin": True,
            },
        )
        self.assertIn(
            "ENGELMAYER",
            r.json()["content"],
            msg="OCR did not return expected text",
        )

    def test_margin_excluding_recap_documents(self):
        """Test strip_margin flag will exclude margin bates stamp"""
        filepath = Path(
            "doctor/test_assets/recap_issues/gov.uscourts.njd.387907.32.0.pdf"
        )
        r1 = requests.post(
            url="http://doctor:5050/extract/doc/text/",
            files={"file": (filepath.name, filepath.read_bytes())},
            params={
                "strip_margin": False,
            },
        )
        doc_1 = r1.json()["content"]
        self.assertIn(
            "Case 3:18-cv-16281-BRM-TJB",
            doc_1,
            msg=f"Bates stamp should be in text {doc_1[:200]}",
        )

        # Now run it again with strip margin on to exclude the bate stamp
        r2 = requests.post(
            url="http://doctor:5050/extract/doc/text/",
            files={"file": (filepath.name, filepath.read_bytes())},
            params={
                "strip_margin": True,
            },
        )
        doc_2 = r2.json()["content"]
        self.assertNotIn(
            "Case 3:18-cv-16281-BRM-TJB",
            doc_2,
            msg=f"Bates stamp should not be in text {doc_2[:200]}",
        )

    def test_recap_contains_image_page(self):
        """Can we recognize a partial scan partial text as needing OCR"""
        filepath = Path(
            "doctor/test_assets/recap_issues/gov.uscourts.nysd.413741.11.0.pdf"
        )
        r = requests.post(
            url="http://doctor:5050/extract/doc/text/",
            files={"file": (filepath.name, filepath.read_bytes())},
            params={
                "strip_margin": True,
            },
        ).json()
        self.assertIn(
            "INTERNATIONAL UNION", r["content"], msg="Extraction failed"
        )
        self.assertTrue(r["extracted_by_ocr"], msg=r["content"])

    def test_skewed_recap_document(self):
        """Can we remove sideways text in the margin"""
        filepath = Path(
            "doctor/test_assets/recap_issues/gov.uscourts.cand.16711.199.0.pdf"
        )
        response = requests.post(
            url="http://doctor:5050/extract/doc/text/",
            files={"file": (filepath.name, filepath.read_bytes())},
            params={
                "strip_margin": False,
            },
        )
        # The sideways font returns backwards
        self.assertIn("truoC", response.json()["content"][:50])

        response = requests.post(
            url="http://doctor:5050/extract/doc/text/",
            files={"file": (filepath.name, filepath.read_bytes())},
            params={
                "strip_margin": True,
            },
        )
        self.assertNotIn("truoC", response.json()["content"][:50])


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
        """"""
        files = make_buffer(filename="image-pdf.pdf")
        response = requests.post(
            "http://doctor:5050/utils/file/extension/", files=files
        )
        self.assertEqual(response.text, ".pdf", msg="Failed to get mime type")

        files = make_buffer(filename="word-docx.docx")
        response = requests.post(
            "http://doctor:5050/utils/file/extension/", files=files
        )
        self.assertEqual(response.text, ".docx", msg="Failed to get mime type")
        files = make_buffer(filename="word-doc.doc")
        response = requests.post(
            "http://doctor:5050/utils/file/extension/", files=files
        )
        self.assertEqual(response.text, ".doc", msg="Failed to get mime type")

    def test_embedding_text_to_image_pdf(self):
        """Can we embed text into an image PDF?"""

        files = make_file(filename="image-pdf.pdf")
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
                data={},
            )
            self.assertIn(
                "(Slip Opinion)           OCTOBER TERM, 2012",
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


if __name__ == "__main__":
    unittest.main()
