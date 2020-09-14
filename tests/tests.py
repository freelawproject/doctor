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


class DockerBuildingTests(TestCase):
    """Test docker images"""

    base_url = "http://0.0.0.0:5011"

    def setUp(self):
        client = docker.from_env()
        client.images.build(path="../", rm=True, tag="test-image")
        client.containers.run(
            "test-image",
            ports={"80/tcp": ("0.0.0.0", 5011)},
            detach=True,
            auto_remove=True,
        )
        time.sleep(2)

    def tearDown(self):
        """Tear down containers"""
        print("Tearing down containers")
        client = docker.from_env()
        for container in client.containers.list():
            print("\n", container.id)
            container.stop()

    def test_dockerfile(self):
        client = docker.from_env()
        i = client.images.build(path="../", rm=True, tag="test-image")
        print(i)
        image = client.images.get("test-image")
        print(image)
        # print(i.name)

    def test_sanity(self):
        """Can we start container and check sanity test?"""
        q = requests.get(self.base_url).json()
        print("\n", q, "\n")


class DocumentConversionTests(TestCase):
    """
    This test method builds from the dockerfile to verify that you
    can actually build and use any changes to it.  It generates the image as
    test-image and can be slow on the first run because it needs to build
    the test image.
    """

    base_url = "http://0.0.0.0:5011"
    root = os.path.dirname(os.path.realpath(__file__))
    assets_dir = os.path.join(root, "test_assets")
    answer_path = os.path.join(root, "test_assets", "test_answers.json")
    doc_answers = {}

    def setUp(self):
        client = docker.from_env()
        client.images.build(path="../", rm=True, tag="test-image")
        client.containers.run(
            "test-image",
            ports={"80/tcp": ("0.0.0.0", 5011)},
            detach=True,
            auto_remove=True,
        )
        time.sleep(2)
        with open(self.answer_path, "r") as f:
            doc_json = json.load(f)
        for k, v in doc_json.items():
            self.doc_answers[k] = bytes(v, "utf-8").decode("unicode_escape")

    def tearDown(self):
        """Tear down containers"""
        print("Tearing down containers")
        client = docker.from_env()
        for container in client.containers.list():
            print("\n", container.id)
            container.stop()

    def send_file_to_bte(self, filepath, do_ocr=False):
        """Send file to extract doccontent

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
        )

    def test_dockerfile(self):
        """Can we start container and check sanity test?"""
        response = requests.get(self.base_url).json()
        self.assertTrue(response["success"])

    def test_convert_pdf_to_txt(self):
        """Can we convert an image pdf to txt?"""
        for filepath in iglob(
            os.path.join(self.assets_dir, "*test_image.pdf")
        ):
            extraction = self.send_file_to_bte(
                filepath, do_ocr=True
            ).content.decode("unicode_escape")
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                extraction,
                msg="Failed to extract content from image pdf.",
            )

    def test_normal_pdf(self):
        """Can we extract content from pdf?"""
        for filepath in iglob(
            os.path.join(self.assets_dir, "*opinion_pdf_text_based.pdf")
        ):
            extraction = self.send_file_to_bte(
                filepath, do_ocr=True
            ).content.decode("unicode_escape")
            answer = self.doc_answers[filepath.split("/")[-1]]

            self.assertEqual(
                answer,
                extraction,
                msg="Failed to extract content from regular PDF.",
            )

    def test_convert_docx_to_txt(self):
        """Can we convert docx file to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.docx")):
            extraction = self.send_file_to_bte(
                filepath, do_ocr=True
            ).content.decode("unicode_escape")
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer, extraction, msg="Failed to extract from .docx file."
            )

    def test_convert_wpd_to_txt(self):
        """Can we convert word perfect document to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.wpd")):
            extraction = self.send_file_to_bte(
                filepath, do_ocr=True
            ).content.decode("unicode_escape")
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                extraction,
                msg="Failed to extract word perfect document.",
            )

    def test_convert_doc_to_txt(self):
        """Can we convert doc file to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.doc")):
            extraction = self.send_file_to_bte(
                filepath, do_ocr=True
            ).content.decode("unicode_escape")
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer, extraction, msg="Failed to extract .doc document."
            )

    def test_convert_html_to_txt(self):
        """Can we convert HTML to txt?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.html")):
            extraction = self.send_file_to_bte(
                filepath, do_ocr=True
            ).content.decode("unicode_escape")
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer, extraction, msg="Failed to extract content from HTML."
            )

    def test_convert_txt_to_txt(self):
        """Can we start container and check sanity test?"""
        for filepath in iglob(os.path.join(self.assets_dir, "*.txt")):
            extraction = self.send_file_to_bte(
                filepath, do_ocr=True
            ).content.decode("unicode_escape")
            answer = self.doc_answers[filepath.split("/")[-1]]
            self.assertEqual(
                answer,
                extraction,
                msg="Failed to extract content from txt file.",
            )


class AudioConversionTests(TestCase):
    """
    This tests our ability to convert audio files to formats we prefer.
    """

    base_url = "http://0.0.0.0:5011"
    root = os.path.dirname(os.path.realpath(__file__))
    assets_dir = os.path.join(root, "test_assets")

    def setUp(self):
        client = docker.from_env()
        client.images.build(path="../", rm=True, tag="test-image")
        client.containers.run(
            "test-image",
            ports={"80/tcp": ("0.0.0.0", 5011)},
            detach=True,
            auto_remove=True,
        )
        time.sleep(2)

    def tearDown(self):
        """Tear down containers"""
        print("Tearing down containers")
        client = docker.from_env()
        for container in client.containers.list():
            print("\n", container.id)
            container.stop()

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

    def test_dockerfile(self):
        """Can we start container and check sanity test?"""
        response = requests.get(self.base_url).json()
        self.assertTrue(response["success"])

    def test_convert_wma_to_mp3(self):
        """Can we convert WMA to mp3?"""
        with open(os.path.join(self.assets_dir, "1.mp3"), "rb") as mp3:
            test_mp3 = mp3.read()
        for filepath in iglob(os.path.join(self.assets_dir, "*.wma")):
            r = self.send_file_to_convert_audio(filepath)
            self.assertEqual(
                test_mp3, r.content, msg="Audio conversion failed"
            )
            print("WMA successfully converted to MP3 √")


if __name__ == "__main__":
    unittest.main()
