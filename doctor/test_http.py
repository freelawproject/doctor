import asyncio
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import django
import httpx2
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import AsyncClient
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader

from doctor import tasks

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doctor.settings")
django.setup()


class ImageDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamed_image_follows_redirects(self):
        with io.BytesIO() as buffer, Image.new("L", (32, 40), 255) as image:
            image.save(buffer, format="TIFF")
            image_bytes = buffer.getvalue()
        requested_paths = []
        responses = []

        async def handler(request):
            requested_paths.append(request.url.path)
            if request.url.path == "/redirect":
                response = httpx2.Response(302, headers={"Location": "/image"})
            else:
                response = httpx2.Response(200, content=image_bytes)
            responses.append(response)
            return response

        client = httpx2.AsyncClient(
            http2=True,
            transport=httpx2.MockTransport(handler),
            follow_redirects=True,
        )
        self.addAsyncCleanup(client.aclose)
        with patch("doctor.views.AsyncClient", return_value=client):
            response = await AsyncClient().get(
                reverse("images-to-pdf"),
                query_params={
                    "sorted_urls": json.dumps(
                        ["https://example.test/redirect"]
                    )
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        with PdfReader(io.BytesIO(response.content)) as reader:
            self.assertEqual(len(reader.pages), 1)
        self.assertEqual(requested_paths, ["/redirect", "/image"])
        self.assertTrue(client.is_closed)
        self.assertTrue(all(response.is_closed for response in responses))

    async def test_failed_download_closes_client_and_response(self):
        response = httpx2.Response(500)
        client = httpx2.AsyncClient(
            http2=True,
            transport=httpx2.MockTransport(lambda request: response),
        )
        self.addAsyncCleanup(client.aclose)
        with (
            patch("doctor.views.AsyncClient", return_value=client),
            self.assertRaises(httpx2.HTTPStatusError),
        ):
            await AsyncClient().get(
                reverse("images-to-pdf"),
                query_params={
                    "sorted_urls": json.dumps(["https://example.test/image"])
                },
            )
        self.assertTrue(response.is_closed)
        self.assertTrue(client.is_closed)

    async def test_cancelled_download_closes_client_and_stream(self):
        started = asyncio.Event()
        closed = asyncio.Event()

        class SlowStream(httpx2.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial image"
                started.set()
                await asyncio.Event().wait()

            async def aclose(self):
                closed.set()

        client = httpx2.AsyncClient(
            http2=True,
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(200, stream=SlowStream())
            ),
        )
        self.addAsyncCleanup(client.aclose)
        with patch("doctor.views.AsyncClient", return_value=client):
            download = asyncio.create_task(
                AsyncClient().get(
                    reverse("images-to-pdf"),
                    query_params={
                        "sorted_urls": json.dumps(
                            ["https://example.test/image"]
                        )
                    },
                )
            )
            try:
                await asyncio.wait_for(started.wait(), 5)
                self.assertFalse(download.done())
            finally:
                download.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await download
        self.assertTrue(closed.is_set())
        self.assertTrue(client.is_closed)


class CoverArtDownloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.audio = MagicMock()
        self.metadata = {
            "case_name": "Example case",
            "court_full_name": "Example Court",
            "court_short_name": "Example",
            "court_pk": "mad",
            "court_url": "https://example.test/court",
            "docket_number": "1",
            "date_argued": "2020-01-01",
            "date_argued_year": "2020",
            "download_url": "https://example.test/audio",
        }
        for target, value in (
            ("doctor.tasks.eyed3.load", self.audio),
            ("doctor.tasks.id3.Tag.remove", None),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_cover_download_yields_and_follows_redirects(self):
        started = asyncio.Event()
        release = asyncio.Event()
        requested_paths = []

        async def handler(request):
            requested_paths.append(request.url.path)
            if request.url.path == "/seal":
                return httpx2.Response(302, headers={"Location": "/image"})
            started.set()
            await release.wait()
            return httpx2.Response(200, content=b"cover art")

        client = httpx2.AsyncClient(
            http2=True,
            transport=httpx2.MockTransport(handler),
            follow_redirects=True,
        )
        self.addAsyncCleanup(client.aclose)
        with (
            patch("doctor.tasks.AsyncClient", return_value=client),
            patch(
                "doctor.tasks.seal", return_value="https://example.test/seal"
            ),
        ):
            conversion = asyncio.create_task(
                tasks.set_mp3_meta_data(self.metadata, "audio.mp3")
            )
            try:
                await asyncio.wait_for(started.wait(), 5)
                self.assertFalse(conversion.done())
            finally:
                release.set()
                await conversion
        self.assertEqual(requested_paths, ["/seal", "/image"])
        self.audio.tag.images.set.assert_any_call(
            3, b"cover art", "image/png", "Seal for Example"
        )
        self.audio.tag.save.assert_called_once()
        self.assertTrue(client.is_closed)

    async def test_failed_cover_download_does_not_embed_error_body(self):
        client = httpx2.AsyncClient(
            http2=True,
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(404, content=b"not found")
            ),
        )
        self.addAsyncCleanup(client.aclose)
        with (
            patch("doctor.tasks.AsyncClient", return_value=client),
            patch(
                "doctor.tasks.seal", return_value="https://example.test/seal"
            ),
            self.assertRaises(httpx2.HTTPStatusError),
        ):
            await tasks.set_mp3_meta_data(self.metadata, "audio.mp3")
        self.audio.tag.images.set.assert_not_called()
        self.audio.tag.save.assert_not_called()
        self.assertTrue(client.is_closed)

    async def test_missing_seal_does_not_open_http_client(self):
        with (
            patch("doctor.tasks.AsyncClient") as client,
            patch("doctor.tasks.seal", return_value=None),
        ):
            await tasks.set_mp3_meta_data(self.metadata, "audio.mp3")
        client.assert_not_called()
        self.assertEqual(self.audio.tag.images.set.call_count, 2)
        self.audio.tag.save.assert_called_once()


class AudioViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversion_awaits_metadata(self):
        async def convert(output_path, media):
            Path(output_path).write_bytes(b"converted audio")

        with (
            patch("doctor.views.convert_to_mp3", side_effect=convert),
            patch(
                "doctor.views.set_mp3_meta_data", new_callable=AsyncMock
            ) as metadata,
        ):
            response = await AsyncClient().post(
                "/convert/audio/mp3/",
                data={"file": SimpleUploadedFile("audio.wma", b"input")},
            )
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                b"".join(response.streaming_content), b"converted audio"
            )
            metadata.assert_awaited_once()
        finally:
            response.close()
