"""ASGI gatekeeping for a service that many applications can reach.

This wraps the Django application instead of living in MIDDLEWARE because
Django's ASGI handler reads and spools the entire request body before any
Django middleware runs. Rejecting a request here means an unauthenticated
or oversized upload is never written to disk.
"""

import hmac
import json

from django.conf import settings

# Kubernetes probes carry no credentials.
UNAUTHENTICATED_PATHS = frozenset({"/"})


class _BodyTooLarge(Exception):
    """Raised from receive() once a streamed body passes the cap."""


def _token_is_valid(authorization: str) -> bool:
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return False
    # Check every token so timing reveals neither which one matched nor
    # how much of it was right.
    matched = False
    for token in settings.DOCTOR_AUTH_TOKENS:
        if hmac.compare_digest(presented.encode(), token.encode()):
            matched = True
    return matched


async def _reject(send, status: int, error_code: str, headers=()):
    body = json.dumps({"success": False, "error_code": error_code}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class GatekeeperMiddleware:
    """Enforce bearer-token auth and a request body size cap.

    Authentication is a no-op while DOCTOR_AUTH_TOKENS is empty, so
    deployments can ship the code first and turn enforcement on once
    callers send a token. The heartbeat is always exempt.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])

        if (
            settings.DOCTOR_AUTH_TOKENS
            and scope["path"] not in UNAUTHENTICATED_PATHS
            and not _token_is_valid(
                headers.get(b"authorization", b"").decode("latin-1")
            )
        ):
            await _reject(
                send, 401, "UNAUTHORIZED", [(b"www-authenticate", b"Bearer")]
            )
            return

        limit = settings.DOCTOR_MAX_REQUEST_BYTES
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await _reject(send, 413, "REQUEST_TOO_LARGE")
            return

        # A chunked upload declares no length, so count what arrives.
        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal response_started
            response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            # Django reads the whole body before responding, so nothing
            # has been sent yet and a proper 413 can go out.
            if not response_started:
                await _reject(send, 413, "REQUEST_TOO_LARGE")
