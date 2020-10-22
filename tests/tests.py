# -*- coding: utf-8 -*-
from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

import json
import os
import time
import unittest
from ast import literal_eval
from glob import iglob
from unittest import TestCase

import docker
import requests


class DockerTestBase(TestCase):
    """ Base class for docker testing."""

    base_url = "http://0.0.0.0:80"
    root = os.path.dirname(os.path.realpath(__file__))
    assets_dir = os.path.join(root, "test_assets")
    answer_path = os.path.join(root, "test_assets", "test_answers.json")
    doc_answers = {}
    with open(answer_path, "r") as f:
        doc_json = json.load(f)
    for k, v in doc_json.items():
        doc_answers[k] = v

    def setUp(self):
        """Setup containers

        Start seal-rookery docker image and set volume binding. Then link
        seal rookery to BTE python site packages.

        :return:
        """
        client = docker.from_env()
        client.containers.run(
            "freelawproject/seal-rookery:latest",
            name="seal-rookery",
            detach=True,
            auto_remove=True,
            volumes={
                "seal-rookery": {
                    "bind": "/usr/local/lib/python3.8/site-packages/seal_rookery",
                    "mode": "ro",
                }
            },
        )
        client.containers.run(
            "freelawproject/binary-transformers-and-extractors:latest",
            ports={"80/tcp": ("0.0.0.0", 80)},
            detach=True,
            auto_remove=True,
            volumes={
                "seal-rookery": {
                    "bind": "/usr/local/lib/python3.8/site-packages/seal_rookery",
                    "mode": "ro",
                }
            },
        )
        time.sleep(2)

    def tearDown(self):
        """Tear down containers"""
        client = docker.from_env()
        for container in client.containers.list():
            container.stop()

    def send_file_to_bte(self, filepath, do_ocr=False):
        """Send file to extract doc content method.

        :param filepath:
        :param do_ocr:
        :return:
        """
        with open(filepath, "rb") as file:
            f = file.read()
        return requests.post(
            "%s/extract_doc_content" % self.base_url,
            files={"file": (os.path.basename(filepath), f)},
            params={"do_ocr": do_ocr},
        ).json()

    def send_file_to_pdftotext(self, filepath):
        """Send file to pdftotext method.

        :param filepath:
        :param do_ocr:
        :return:
        """
        with open(filepath, "rb") as file:
            f = file.read()
        return requests.post(
            "%s/make_pdftotext_process" % self.base_url,
            files={"file": (os.path.basename(filepath), f)},
        ).json()

    def send_file_to_convert_audio(self, filepath):
        """This is a helper function to post to audio conversion.

        :param filepath:
        :return:
        """
        with open(filepath, "rb") as file:
            f = file.read()
        return requests.post(
            "%s/convert_audio_file" % self.base_url,
            files={"file": (os.path.basename(filepath), f)},
        )

    def send_file_to_thumbnail_generation(self, filepath, max_dimension=350):
        """Send file to extract doc content

        :param filepath:
        :param do_ocr:
        :return:
        """
        with open(filepath, "rb") as file:
            f = file.read()
        return requests.post(
            "%s/make_png_thumbnail" % self.base_url,
            files={"file": (os.path.basename(filepath), f)},
            params={"max_dimension": max_dimension},
        )

    def test_heartbeat(self):
        """Check heartbeat?"""
        response = requests.get(self.base_url).json()
        self.assertTrue(response["success"], msg="Failed heartbeat test.")
        print(response)


class DocumentConversionTests(DockerTestBase):
    """Test document conversion"""

    def test_convert_pdf_to_txt(self):
        """Can we convert an image pdf to txt?"""
        for filepath in iglob(
            os.path.join(self.assets_dir, "opinion_pdf_image_based.pdf")
        ):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                response["content"],
                msg="Failed to extract content from image pdf.",
            )
            print("Extracted content from .pdf successfully")

    def test_convert_docx_to_txt(self):
        """Can we convert docx file to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.docx")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                response["content"],
                msg="Failed to extract from .docx file.",
            )
            print("Extracted content from .docx successfully")

    def test_convert_wpd_to_txt(self):
        """Can we convert word perfect document to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.wpd")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                response["content"],
                msg="Failed to extract word perfect document.",
            )
            print("Extracted content from .wpd successfully")

    def test_convert_doc_to_txt(self):
        """Can we convert doc file to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.doc")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                response["content"],
                msg="Failed to extract .doc document.",
            )
            print("Extracted content from .doc successfully")

    def test_convert_html_to_txt(self):
        """Can we convert HTML to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.html")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                response["content"],
                msg="Failed to extract content from HTML.",
            )
            print("Extracted content from .html successfully")

    def test_convert_txt_to_txt(self):
        """Can we extract text from a txt document?"""
        for filepath in iglob(os.path.join(self.assets_dir, "opinion*.txt")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            print(response)
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                response["content"],
                msg="Failed to extract content from txt file.",
            )
            print("Extracted content from .txt successfully")

    def test_bad_txt_extraction(self):
        """Can we extract text from a txt document with bad encoding?"""
        for filepath in iglob(
            os.path.join(self.assets_dir, "txt_file_with_no_encoding*.txt")
        ):
            response = self.send_file_to_bte(filepath)
            success = int(response["error_code"])
            self.assertFalse(
                success,
                "Error reported while extracting text from %s" % filepath,
            )
            self.assertIn(
                "¶  1.  DOOLEY, J.   Plaintiffs",
                response["content"],
                "Issue extracting/encoding text from file at: %s" % filepath,
            )


class AudioConversionTests(DockerTestBase):
    """Test Audio Conversion"""

    def test_convert_wma_to_mp3(self):
        """Can we convert wma to mp3 and add metadata"""
        filepath = os.path.join(
            self.assets_dir, "..", "fixtures", "test_audio_object.json"
        )
        wma_path = os.path.join(self.assets_dir, "1.wma")
        with open(
            os.path.join(self.assets_dir, "1_with_metadata.mp3"), "rb"
        ) as mp3:
            test_mp3 = mp3.read()

        with open(filepath, "rb") as file:
            f = file.read()
        with open(wma_path, "rb") as wma_file:
            w = wma_file.read()
        resp = requests.post(
            "%s/convert/audio" % self.base_url,
            files={
                "af": (os.path.basename(filepath), f),
                "file": (os.path.basename(wma_path), w),
            },
        )
        self.assertEqual(
            test_mp3,
            literal_eval(resp.json()["content"]),
            msg="Audio conversion failed",
        )
        print("\nWMA successfully converted to MP3 √\n")


class ThumbnailGenerationTests(DockerTestBase):
    """Can we generate thumbnail images from PDF files"""

    def test_convert_pdf_to_thumbnail_png(self):
        """Can we generate a pdf to thumbnail?"""
        for thumb_path in iglob(os.path.join(self.assets_dir, "*thumbnail*")):
            filepath = thumb_path.replace("_thumbnail.png", ".pdf")
            with open(thumb_path, "rb") as f:
                test_thumbnail = f.read()
            response = self.send_file_to_thumbnail_generation(filepath).json()
            self.assertEqual(
                literal_eval(response["content"]),
                test_thumbnail,
                msg="Thumbnail failed.",
            )
            print("Generated thumbnail from .pdf successfully")


class PageCountTests(DockerTestBase):
    """Can we get page counts?"""

    def send_file_to_pg_count(self, filepath):
        """Send file to extract page count.

        :param filepath:
        :return:
        """
        with open(filepath, "rb") as file:
            f = file.read()
        return requests.post(
            "%s/get_page_count" % self.base_url,
            files={"file": (os.path.basename(filepath), f)},
        ).json()

    def test_pdf_page_count_extractor(self):
        """Can we extract page counts properly?"""

        counts = [2, 30, 1, 6]
        for count, filepath in zip(
            counts, sorted(iglob(os.path.join(self.assets_dir, "*.pdf")))
        ):
            response = self.send_file_to_pg_count(filepath)
            self.assertEqual(
                response["pg_count"], count, msg="Page count failed"
            )
            print("Successfully returned page count √")

    def test_post_pdf_data(self):
        """Can we send pdf as a file and get a response?"""
        service = "%s/%s" % (self.base_url, "get_page_count")
        pdf_path = os.path.join(self.root, "test_assets", "tiff_to_pdf.pdf")

        with open(pdf_path, "rb") as file:
            f = file.read()

        response = requests.post(
            url=service,
            files={"file": (os.path.basename(pdf_path), f)},
            timeout=60,
        ).json()
        self.assertEqual(response["pg_count"], 6)


class FinancialDisclosureTests(DockerTestBase):
    """Test financial dislcosure conversion and extraction"""

    def test_financial_disclosure_extractor(self):
        """Test financial disclosure extraction"""

        pdf_path = os.path.join(self.root, "test_assets", "tiff_to_pdf.pdf")
        with open(pdf_path, "rb") as file:
            f = file.read()
        response = requests.post(
            "%s/financial_disclosure/extract" % self.base_url,
            files={"file": (os.path.basename(pdf_path), f)},
            timeout=60 * 60,
        )
        self.assertTrue(
            response.json()["success"], msg="Disclosure extraction failed."
        )

    def test_judicial_watch_document(self):
        """Can we extract data from a judicial watch document?"""
        pdf_path = os.path.join(
            self.root, "test_assets", "fd", "2003-judicial-watch.pdf"
        )
        with open(pdf_path, "rb") as file:
            f = file.read()

        response = requests.post(
            "%s/financial_disclosure/jw_extract" % self.base_url,
            files={"file": (os.path.basename(pdf_path), f)},
            params={"url": None},
            timeout=60 * 60,
        )
        self.assertTrue(
            response.json()["success"],
            msg="Fiancial disclosure document parsing failed.",
        )
        print(response.json())


# These tests aren't automatically triggered by github actions because I have not
# properly mocked them to avoid hitting AWS and testing properly. They do work
# when called though.
class AWSFinancialDisclosureTests(DockerTestBase):
    def test_image_url_to_pdf(self):
        """Test image at URL to PDF conversion"""
        pdf_path = os.path.join(self.root, "test_assets", "tiff_to_pdf.pdf")
        with open(pdf_path, "rb") as f:
            answer = f.read()

        url = "https://com-courtlistener-storage.s3-us-west-2.amazonaws.com/financial-disclosures/2011/A-E/Abel-MR.%20M.%2006.%20OHS.tiff"
        # url = "http://com-courtlistener-storage.s3.amazonaws.com/financial-disclosures/2018/A%20-%20G/Barrett-AC.%20J3.%2007.%20SPE_R_18.tiff"
        response = requests.post(
            "%s/financial_disclosure/single_image" % self.base_url,
            params={"url": url},
        ).json()
        self.assertEqual(
            literal_eval(response["content"]),
            answer,
            msg="Image to PDF conversion failed.",
        )

    def test_combine_images_into_pdf(self):
        """Can we post and combine multiple images into a pdf?"""
        test_file = os.path.join(
            self.root, "test_assets", "fd", "2012-Straub-CJ.pdf"
        )
        test_key = "financial-disclosures/2011/R - Z/Straub-CJ.J3.02_R_11/Straub-CJ.J3.02_R_11_Page_16.tiff"
        with open(test_file, "rb") as f:
            answer = f.read()
        service = "%s/financial_disclosure/multi_image" % self.base_url
        response = requests.post(service, params={"aws_path": test_key}).json()
        self.assertEqual(
            literal_eval(response["content"]),
            answer,
            msg="Failed to merge split PDFs.",
        )
        print("Images combined correctly from AWS √")


class UtilityTests(DockerTestBase):
    def test_file_type(self):
        """Test Mime Type extraction"""
        service = "%s/%s/%s" % (self.base_url, "utility", "mime_type")
        file_path = os.path.join(self.root, "test_assets", "tiff_to_pdf.pdf")
        with open(file_path, "rb") as file:
            f = file.read()
        response = requests.post(
            url=service,
            params={"mime": True},
            files={"file": (os.path.basename(file_path), f)},
            timeout=60,
        ).json()
        self.assertEqual(response["mimetype"], "application/pdf")


if __name__ == "__main__":
    unittest.main()
