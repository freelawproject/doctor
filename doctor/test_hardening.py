"""Offline tests for the service's hardening.

Unlike tests.py these need no running doctor container:

    DJANGO_SETTINGS_MODULE=doctor.settings python -m unittest doctor.test_hardening
"""

import asyncio
import os
import unittest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doctor.settings")

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase, override_settings  # noqa: E402

from doctor.forms import ImagePdfForm  # noqa: E402
from doctor.lib.bitonal import BitonalError  # noqa: E402
from doctor.middleware import GatekeeperMiddleware  # noqa: E402
from doctor.tasks import validate_egress_url  # noqa: E402


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


class EgressTest(SimpleTestCase):
    def test_explicit_allowlist(self):
        hosts = ["*.amazonaws.com"]
        validate_egress_url("https://b.s3.amazonaws.com/x", hosts)
        for url in (
            "http://b.s3.amazonaws.com/x",
            "https://169.254.169.254/latest/meta-data",
            "https://evil.example.com/",
            "https://amazonaws.com.evil.example/",
            "file:///etc/passwd",
        ):
            with self.assertRaises(BitonalError, msg=url):
                validate_egress_url(url, hosts)

    def test_empty_allowlist_disables(self):
        validate_egress_url("http://localhost/x", [])


class ImagePdfFormTest(SimpleTestCase):
    def _form(self, value):
        form = ImagePdfForm({"sorted_urls": value})
        return form, form.is_valid()

    def test_valid(self):
        form, ok = self._form('["https://a/1.png", "https://a/2.png"]')
        self.assertTrue(ok)
        self.assertEqual(len(form.cleaned_data["sorted_urls"]), 2)

    def test_rejects_malformed(self):
        for value in ("not json", "{}", "[]", "[1, 2]", '["a", 3]', '"str"'):
            _, ok = self._form(value)
            self.assertFalse(ok, value)

    @override_settings(DOCTOR_MAX_IMAGE_URLS=2)
    def test_rejects_too_many(self):
        _, ok = self._form('["a", "b", "c"]')
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
