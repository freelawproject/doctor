"""Tests for the service's hardening.

Unlike tests.py these need no running doctor container:

    python -m unittest doctor.test_hardening
"""

import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path

import django
import httpx
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from doctor.asgi import application
from doctor.lib.bitonal import BitonalError
from doctor.lib.sentry_scrub import scrub_breadcrumb, scrub_event
from doctor.tasks import convert_to_mp3, validate_egress_url

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doctor.settings")
django.setup()

PDF = "doctor/test_assets/vector-pdf.pdf"


def _post_pdf(path, headers=None):
    """Send a real request through the ASGI app, gatekeeper included."""

    async def go():
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://doctor"
        ) as client:
            with open(PDF, "rb") as f:
                return await client.post(
                    path, files={"file": f}, headers=headers
                )

    return asyncio.run(go())


class AuthTest(SimpleTestCase):
    PAGE_COUNT = "/utils/page-count/pdf/"

    @override_settings(DOCTOR_AUTH_TOKENS=[])
    def test_disabled_when_no_tokens(self):
        self.assertEqual(_post_pdf(self.PAGE_COUNT).status_code, 200)

    @override_settings(DOCTOR_AUTH_TOKENS=["alpha", "bravo"])
    def test_requires_a_valid_token(self):
        for headers in (
            None,
            {"Authorization": "Bearer nope"},
            {"Authorization": "Basic alpha"},
        ):
            response = _post_pdf(self.PAGE_COUNT, headers)
            self.assertEqual(response.status_code, 401, headers)
            self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
        for token in ("alpha", "bravo"):
            response = _post_pdf(
                self.PAGE_COUNT, {"Authorization": f"Bearer {token}"}
            )
            self.assertEqual(
                (response.status_code, response.text), (200, "30")
            )

    @override_settings(DOCTOR_AUTH_TOKENS=["alpha"])
    def test_heartbeat_is_exempt(self):
        self.assertEqual(_post_pdf("/").status_code, 200)


class FfmpegProtocolTest(unittest.TestCase):
    """An uploaded playlist must not make ffmpeg read other files."""

    def test_playlist_cannot_read_local_files(self):
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
        # The httpx integration stores the query string bare, in its own
        # field, where no URL prefix precedes it.
        crumb = scrub_breadcrumb(
            {
                "data": {
                    "url": self.URL,
                    "http.query": "X-Amz-Signature=deadbeef",
                    "http.fragment": "deadbeef",
                }
            }
        )
        self.assertNotIn("deadbeef", repr(crumb))


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
            "s3-attacker-1234567890.us-west-2.elb.amazonaws.com",
            "bucket.s3.evil.example.amazonaws.com",
            "my-db.cluster-x.us-west-2.rds.amazonaws.com",
            "s3.amazonaws.com.evil.example",
            "169.254.169.254",
        ):
            with self.assertRaises(BitonalError, msg=host):
                validate_egress_url(f"https://{host}/")


if __name__ == "__main__":
    unittest.main()
