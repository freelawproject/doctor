import json
import os
import glob
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile

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

    # def test_locally(self):
    #     c = Client()
    #     with open(f"{asset_path}/image-pdf.pdf", "rb") as fp:
    #         response = c.post(
    #             "/convert/pdf/thumbnail/",
    #             {"max_dimension": 350, "file": fp},
    #         )
    #
    #     self.assertEqual(200, response.status_code)

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
        print(response)
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
        data = {"ocr_available": False}

        files = make_file(filename="image-pdf.pdf")
        image_response = requests.post(
            "http://doctor:5050/extract/doc/text/", files=files, data=data
        )
        self.assertEqual(
            "",
            image_response.json()["content"].strip("\x0c\x0c"),
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
