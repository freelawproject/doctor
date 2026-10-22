"""Tests for the service's hardening.

Unlike tests.py these need no running doctor container:

    DJANGO_SETTINGS_MODULE=doctor.settings python -m unittest doctor.test_hardening
"""

import ast
import asyncio
import io
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doctor.settings")

import django  # noqa: E402
import httpx  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import Client, SimpleTestCase, override_settings  # noqa: E402
from PIL import Image  # noqa: E402

from doctor.lib.bitonal import BitonalError  # noqa: E402
from doctor.lib.sentry_scrub import scrub_breadcrumb, scrub_event  # noqa: E402
from doctor.middleware import GatekeeperMiddleware  # noqa: E402
from doctor.tasks import (  # noqa: E402
    convert_to_mp3,
    fetch_seal,
    set_mp3_meta_data,
    validate_egress_url,
)


async def _inner(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _request(path="/extract/doc/text/", headers=None, body_chunks=()):
    """Drive the gatekeeper; return (status, whether the app ran)."""
    sent = []
    ran = []

    async def app(scope, receive, send):
        ran.append(True)
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get(
                "more_body"
            ):
                break
        await _inner(scope, receive, send)

    chunks = list(body_chunks) or [b""]

    async def receive():
        if chunks:
            body = chunks.pop(0)
            return {
                "type": "http.request",
                "body": body,
                "more_body": bool(chunks),
            }
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "path": path,
        "headers": [(k.lower(), v) for k, v in (headers or [])],
    }
    asyncio.run(GatekeeperMiddleware(app)(scope, receive, send))
    status = sent[0]["status"] if sent else None
    return status, bool(ran)


class AuthTest(unittest.TestCase):
    @override_settings(DOCTOR_AUTH_TOKENS=[])
    def test_disabled_when_no_tokens(self):
        self.assertEqual(_request(), (200, True))

    @override_settings(DOCTOR_AUTH_TOKENS=["alpha", "bravo"])
    def test_requires_a_valid_token(self):
        self.assertEqual(_request(), (401, False))
        bad = [(b"authorization", b"Bearer nope")]
        self.assertEqual(_request(headers=bad), (401, False))
        basic = [(b"authorization", b"Basic alpha")]
        self.assertEqual(_request(headers=basic), (401, False))
        for token in (b"alpha", b"bravo"):
            good = [(b"authorization", b"Bearer " + token)]
            self.assertEqual(_request(headers=good), (200, True))

    @override_settings(DOCTOR_AUTH_TOKENS=["alpha"])
    def test_heartbeat_is_exempt(self):
        self.assertEqual(_request(path="/"), (200, True))


class FfmpegProtocolTest(unittest.TestCase):
    """An uploaded playlist must not make ffmpeg read other files."""

    def test_playlist_cannot_read_local_files(self):
        import tempfile

        secret = Path(tempfile.mkdtemp()) / "secret.wav"
        secret.write_bytes(b"RIFF" + b"\0" * 100)
        playlist = (
            "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n"
            f"file://{secret}\n#EXT-X-ENDLIST\n"
        ).encode()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mp3")
            with self.assertRaises(RuntimeError):
                asyncio.run(convert_to_mp3(out, io.BytesIO(playlist)))
            self.assertFalse(os.path.exists(out))

    def test_real_audio_converts(self):
        import tempfile

        with (
            tempfile.TemporaryDirectory() as tmp,
            open("doctor/test_assets/1.wma", "rb") as audio,
        ):
            out = os.path.join(tmp, "out.mp3")
            asyncio.run(convert_to_mp3(out, audio))
            self.assertGreater(os.path.getsize(out), 0)


class SentryScrubTest(unittest.TestCase):
    URL = (
        "https://b.s3.amazonaws.com/k.pdf?X-Amz-Credential=AKIA"
        "&X-Amz-Signature=deadbeef"
    )

    def test_event_is_scrubbed(self):
        event = {
            "message": f"failed fetching {self.URL}",
            "exception": {"values": [{"value": f"bad {self.URL} here"}]},
            "request": {
                "data": {"input_url": self.URL},
                "cookies": {"a": "b"},
                "headers": {"Authorization": "Bearer s3cret", "Host": "x"},
            },
            "breadcrumbs": {"values": [{"data": {"url": self.URL}}]},
        }
        out = scrub_event(event)
        text = repr(out)
        for leaked in ("deadbeef", "AKIA", "s3cret"):
            self.assertNotIn(leaked, text)
        self.assertIn("https://b.s3.amazonaws.com/k.pdf", text)
        self.assertEqual(out["request"]["headers"]["Host"], "x")

    def test_breadcrumb_is_scrubbed(self):
        crumb = scrub_breadcrumb({"data": {"url": self.URL}})
        self.assertNotIn("deadbeef", repr(crumb))


class ImagesToPdfTest(SimpleTestCase):
    def png(self, color):
        buffer = io.BytesIO()
        Image.new("RGB", (40, 60), color).save(buffer, "PNG")
        return SimpleUploadedFile("x.png", buffer.getvalue(), "image/png")

    def test_uploads_become_pages(self):
        from pypdf import PdfReader

        response = Client().post(
            "/convert/images/pdf/",
            {"file": [self.png("red"), self.png("blue")]},
        )
        self.assertEqual(response.status_code, 200)
        reader = PdfReader(io.BytesIO(response.content))
        self.assertEqual(len(reader.pages), 2)

    def test_urls_are_ignored_and_nothing_is_fetched(self):
        response = Client().post(
            "/convert/images/pdf/",
            {"sorted_urls": '["http://169.254.169.254/"]'},
        )
        self.assertEqual(response.status_code, 400)


def _image_bytes(image_format="PNG", size=(32, 32)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "navy").save(buffer, image_format)
    return buffer.getvalue()


class EgressDefaultTest(SimpleTestCase):
    """The shipped allowlist admits S3 hostnames and nothing else on AWS."""

    @override_settings(
        DOCTOR_EGRESS_ALLOWED_HOSTS=settings.S3_HOST_PATTERNS.split(",")
    )
    def test_s3_shapes_allowed(self):
        for host in (
            "bucket.s3.amazonaws.com",
            "bucket.s3.us-west-2.amazonaws.com",
            "com-courtlistener-storage.s3-us-west-2.amazonaws.com",
            "bucket.s3.dualstack.us-west-2.amazonaws.com",
            "name-123.s3-accesspoint.us-west-2.amazonaws.com",
            "s3.us-west-2.amazonaws.com",
            "s3.amazonaws.com",
        ):
            validate_egress_url(f"https://{host}/key?X-Amz-Signature=x")

    @override_settings(
        DOCTOR_EGRESS_ALLOWED_HOSTS=settings.S3_HOST_PATTERNS.split(",")
    )
    def test_other_aws_hosts_blocked(self):
        for host in (
            "abc123.execute-api.us-west-2.amazonaws.com",
            "sts.amazonaws.com",
            "my-db.cluster-x.us-west-2.rds.amazonaws.com",
            "s3.amazonaws.com.evil.example",
            "169.254.169.254",
        ):
            with self.assertRaises(BitonalError, msg=host):
                validate_egress_url(f"https://{host}/")


class SealFetchTest(SimpleTestCase):
    """Audio conversion fetches the seal from the hard-coded host only."""

    def fetch(self, handler, court="mad"):
        """Run fetch_seal against a mock transport; return the result and
        the URLs it requested."""
        seen = []

        def spy(request):
            seen.append(str(request.url))
            return handler(request)

        real = httpx.get

        def fake_get(url, **kwargs):
            self.assertFalse(kwargs["follow_redirects"])
            with httpx.Client(transport=httpx.MockTransport(spy)) as c:
                return c.get(url)

        with patch("doctor.tasks.httpx.get", fake_get):
            return fetch_seal(court), seen
        del real

    def test_fetches_from_seals_free_law(self):
        png = _image_bytes("PNG")
        result, seen = self.fetch(lambda r: httpx.Response(200, content=png))
        self.assertEqual(result, png)
        self.assertEqual(seen, ["https://seals.free.law/v2/256/mad.png"])

    def test_court_without_a_seal_makes_no_request(self):
        result, seen = self.fetch(lambda r: httpx.Response(200), court="nope")
        self.assertIsNone(result)
        self.assertEqual(seen, [])

    def test_failed_fetch_means_no_seal(self):
        for response in (
            httpx.Response(404),
            httpx.Response(302, headers={"Location": "http://10.0.0.1/"}),
        ):
            with self.assertLogs("doctor.tasks", level="WARNING"):
                result, _ = self.fetch(lambda r, resp=response: resp)
            self.assertIsNone(result)

    AUDIO_DATA = {
        "court_full_name": "Testing Supreme Court",
        "court_short_name": "Testing",
        "court_pk": "mad",
        "court_url": "http://www.example.com/",
        "docket_number": "1",
        "date_argued": "2020-01-01",
        "date_argued_year": "2020",
        "case_name": "A v. B",
        "case_name_full": "A v. B",
        "case_name_short": "A",
        "download_url": "http://www.example.com/a.mp3",
    }

    def tag_images(self, fetched):
        """Tag a copy of the test mp3 with fetch_seal patched to return
        `fetched`, and return its images by picture type."""
        import tempfile

        import eyed3

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.mp3")
            shutil.copy("doctor/test_assets/1.mp3", path)
            with patch("doctor.tasks.fetch_seal", return_value=fetched):
                set_mp3_meta_data(dict(self.AUDIO_DATA), path)
            return {i.picture_type: i for i in eyed3.load(path).tag.images}

    def test_seal_becomes_the_front_cover(self):
        seal_png = _image_bytes("PNG", (48, 48))
        images = self.tag_images(seal_png)
        self.assertEqual(images[3].image_data, seal_png)
        self.assertEqual(images[3].description, "Seal for Testing")
        self.assertIn(14, images)  # the publisher logo is still FLP's

    def test_failed_fetch_means_no_cover_art(self):
        images = self.tag_images(None)
        self.assertNotIn(3, images)
        self.assertIn(14, images)


class NetworkImportGuardTest(unittest.TestCase):
    """New outbound network code must be added on purpose.

    Doctor's only legitimate egress is the allowlisted bitonal S3
    transfer and the seal fetch pinned to seals.free.law, both in
    doctor/tasks.py. An import of a network library anywhere else is how an unreviewed SSRF
    gets in: if you need one, review it and extend ALLOWED_FILES.
    """

    ALLOWED_FILES = {"doctor/tasks.py"}
    NETWORK_MODULES = {
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "socket",
        "ssl",
        "http.client",
        "urllib.request",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc.client",
    }

    def imported(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                yield node.module
                yield from (f"{node.module}.{a.name}" for a in node.names)

    def is_network(self, name):
        return any(
            name == module or name.startswith(module + ".")
            for module in self.NETWORK_MODULES
        )

    def test_no_network_imports_outside_allowed_modules(self):
        root = Path(__file__).resolve().parent.parent
        offenders = []
        for path in sorted((root / "doctor").rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if relative in self.ALLOWED_FILES or path.name.startswith("test"):
                continue
            tree = ast.parse(path.read_text())
            offenders += [
                f"{relative}: {name}"
                for name in self.imported(tree)
                if self.is_network(name)
            ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
