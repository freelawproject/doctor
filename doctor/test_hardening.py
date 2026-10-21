"""Offline tests for the service's hardening.

Unlike tests.py these need no running doctor container:

    DJANGO_SETTINGS_MODULE=doctor.settings python -m unittest doctor.test_hardening
"""

import ast
import asyncio
import io
import os
import shutil
import sys
import unittest
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doctor.settings")

import django  # noqa: E402

django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import Client, SimpleTestCase, override_settings  # noqa: E402
from PIL import Image  # noqa: E402

from doctor.lib.sentry_scrub import scrub_breadcrumb, scrub_event  # noqa: E402
from doctor.lib.subprocesses import TIMED_OUT, run_limited  # noqa: E402
from doctor.middleware import GatekeeperMiddleware  # noqa: E402
from doctor.tasks import convert_to_mp3  # noqa: E402


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


class SizeLimitTest(unittest.TestCase):
    @override_settings(DOCTOR_AUTH_TOKENS=[], DOCTOR_MAX_REQUEST_BYTES=10)
    def test_declared_length_over_limit(self):
        status, ran = _request(headers=[(b"content-length", b"11")])
        self.assertEqual((status, ran), (413, False))

    @override_settings(DOCTOR_AUTH_TOKENS=[], DOCTOR_MAX_REQUEST_BYTES=10)
    def test_undeclared_stream_cut_off(self):
        # The app sees a disconnect rather than the full body.
        status, ran = _request(body_chunks=[b"x" * 6, b"x" * 6])
        self.assertEqual(status, 200)  # app ended on disconnect
        self.assertTrue(ran)

    @override_settings(DOCTOR_AUTH_TOKENS=[], DOCTOR_MAX_REQUEST_BYTES=10)
    def test_within_limit(self):
        self.assertEqual(
            _request(headers=[(b"content-length", b"10")]), (200, True)
        )


class SubprocessLimitTest(unittest.TestCase):
    def run_it(self, *command, **kwargs):
        return asyncio.run(run_limited(*command, **kwargs))

    def test_normal_command(self):
        out, _, code = self.run_it("echo", "hello")
        self.assertEqual((out.strip(), code), (b"hello", 0))

    def test_stdin_is_passed(self):
        out, _, _ = self.run_it("cat", input=b"abc")
        self.assertEqual(out, b"abc")

    def test_hung_command_is_killed(self):
        _, _, code = self.run_it("sleep", "30", timeout=1)
        self.assertEqual(code, TIMED_OUT)

    @override_settings(DOCTOR_SUBPROCESS_MAX_MEMORY_MB=128)
    def test_memory_hog_fails_alone(self):
        _, _, code = self.run_it(
            sys.executable, "-I", "-c", "x = bytearray(1024**3)"
        )
        self.assertNotEqual(code, 0)

    @override_settings(DOCTOR_SUBPROCESS_MAX_MEMORY_MB=0)
    def test_limits_can_be_disabled(self):
        _, _, code = self.run_it(
            sys.executable, "-I", "-c", "x = bytearray(1024**2)"
        )
        self.assertEqual(code, 0)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class FfmpegProtocolTest(unittest.TestCase):
    """An uploaded playlist must not make ffmpeg read other files."""

    def convert(self, tmp, data: bytes) -> int:
        out = os.path.join(tmp, "out.mp3")
        asyncio.run(convert_to_mp3(out, io.BytesIO(data)))
        return os.path.getsize(out) if os.path.exists(out) else 0

    def test_playlist_cannot_read_local_files(self):
        import tempfile

        secret = Path(tempfile.mkdtemp()) / "secret.wav"
        secret.write_bytes(b"RIFF" + b"\0" * 100)
        playlist = (
            "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\n"
            f"file://{secret}\n#EXT-X-ENDLIST\n"
        ).encode()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.convert(tmp, playlist), 0)


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
        self.assertNotIn("data", out["request"])
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

    @override_settings(DOCTOR_MAX_IMAGE_FILES=1)
    def test_too_many_files(self):
        response = Client().post(
            "/convert/images/pdf/",
            {"file": [self.png("red"), self.png("blue")]},
        )
        self.assertEqual(response.status_code, 400)


class NetworkImportGuardTest(unittest.TestCase):
    """New outbound network code must be added on purpose.

    Doctor's only legitimate egress is the allowlisted bitonal S3
    transfer and the audio seal fetch, both in doctor/tasks.py. An
    import of a network library anywhere else is how an unreviewed SSRF
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
