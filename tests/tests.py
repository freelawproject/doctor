# -*- coding: utf-8 -*-
from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

import json
import os
import unittest
from glob import iglob
from unittest import TestCase
import docker
import requests
import time


class DockerTestBase(TestCase):
    """ Base class for docker testing."""

    base_url = "http://0.0.0.0:5011"
    root = os.path.dirname(os.path.realpath(__file__))
    assets_dir = os.path.join(root, "test_assets")
    answer_path = os.path.join(root, "test_assets", "test_answers.json")
    doc_answers = {}
    with open(answer_path, "r") as f:
        doc_json = json.load(f)
    for k, v in doc_json.items():
        doc_answers[k] = v

    def setUp(self):
        client = docker.from_env()
        client.containers.run(
            "freelawproject/binary-transformers-and-extractors:latest",
            ports={"80/tcp": ("0.0.0.0", 5011)},
            detach=True,
            auto_remove=True,
        )
        time.sleep(2)

    def tearDown(self):
        """Tear down containers"""
        client = docker.from_env()
        for container in client.containers.list():
            container.stop()

    def send_file_to_bte(self, filepath, do_ocr=False):
        """Send file to extract doc content

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

    def send_file_to_thumbnail_generation(self, filepath, max_dimensions=350):
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
            params={"max_dimensions": max_dimensions},
        )

    def test_sanity(self):
        """Can we start container and check sanity test?"""
        response = requests.get(self.base_url).json()
        self.assertTrue(response["success"], msg="Failed sanity test.")
        print(response)


class DocumentConversionTests(DockerTestBase):
    """Test docker images"""

    def test_convert_pdf_to_txt(self):
        """Can we convert an image pdf to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.pdf")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            extraction = response['content']
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                extraction,
                msg="Failed to extract content from image pdf.",
            )
            print("Extracted content from .pdf successfully")

    def test_convert_docx_to_txt(self):
        """Can we convert docx file to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.docx")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            extraction = response['content'][0]
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer, extraction, msg="Failed to extract from .docx file."
            )
            print("Extracted content from .docx successfully")

    def test_convert_wpd_to_txt(self):
        """Can we convert word perfect document to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.wpd")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            extraction = response['content'][0]
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                extraction,
                msg="Failed to extract word perfect document.",
            )
            print("Extracted content from .wpd successfully")

    def test_convert_doc_to_txt(self):
        """Can we convert doc file to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.doc")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            extraction = response['content'][0]
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer, extraction, msg="Failed to extract .doc document."
            )
            print("Extracted content from .doc successfully")

    def test_convert_html_to_txt(self):
        """Can we convert HTML to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.html")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            extraction = response['content'][0]
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer, extraction, msg="Failed to extract content from HTML."
            )
            print("Extracted content from .html successfully")

    def test_convert_txt_to_txt(self):
        """Can we start container and check sanity test?"""
        for filepath in iglob(os.path.join(self.assets_dir, "opinion*.txt")):
            response = self.send_file_to_bte(filepath, do_ocr=True)
            extraction = response['content'][0]
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                extraction,
                msg="Failed to extract content from txt file.",
            )
            print("Extracted content from .txt successfully")


class AudioConversionTests(DockerTestBase):
    """Test Audio Conversion"""

    def test_convert_wma_to_mp3(self):
        """Can we convert WMA to mp3?"""
        with open(os.path.join(self.assets_dir, "1.mp3"), "rb") as mp3:
            test_mp3 = mp3.read()
        for filepath in iglob(os.path.join(self.assets_dir, "*.wma")):
            r = self.send_file_to_convert_audio(filepath)
            self.assertEqual(
                test_mp3, r.content, msg="Audio conversion failed"
            )
            print("\nWMA successfully converted to MP3 √\n")


class ThumbnailGenerationTests(DockerTestBase):
    """Can we generate thumbnail images from PDF files"""

    def test_convert_pdf_to_thumbnail_png(self):
        """Can we generate a pdf to thumbnail?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.pdf")):
            thumbnail = self.send_file_to_thumbnail_generation(
                filepath
            ).content
            self.assertTrue(thumbnail[1], msg="Thumbnail failed to generate.")
            print("Generated thumbnail from .pdf successfully")


class PageCountTests(DockerTestBase):
    """Can we get page counts"""

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
        counts = [1, 30]
        for count, filepath in zip(
            counts, iglob(os.path.join(self.assets_dir, "*.pdf"))
        ):
            response = self.send_file_to_pg_count(filepath)
            self.assertEqual(
                response["pg_count"], count, msg="Page count failed"
            )
            print("Successfully returned page count √")


if __name__ == "__main__":
    unittest.main()
