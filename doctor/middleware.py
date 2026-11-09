"""ASGI gatekeeping for a service that many applications can reach.

This wraps the Django application instead of living in MIDDLEWARE because
Django's ASGI handler reads and spools the entire request body before any
Django middleware runs. Rejecting a request here means an unauthenticated
upload is never written to disk.
"""

import hmac
import json
from http import HTTPStatus

from django.conf import settings

# Kubernetes probes carry no credentials.
UNAUTHENTICATED_PATHS = frozenset({"/"})


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


async def _reject(send, status: HTTPStatus, error_code: str, headers=()):
    body = json.dumps({"success": False, "error_code": error_code}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": int(status),
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class GatekeeperMiddleware:
    """Require a bearer token on every endpoint but the heartbeat.

    A no-op while DOCTOR_AUTH_TOKENS is empty, so deployments can ship
    the code first and turn enforcement on once callers send a token.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and settings.DOCTOR_AUTH_TOKENS
            and scope["path"] not in UNAUTHENTICATED_PATHS
            and not _token_is_valid(
                dict(scope["headers"])
                .get(b"authorization", b"")
                .decode("latin-1")
            )
        ):
            await _reject(
                send,
                HTTPStatus.UNAUTHORIZED,
                "UNAUTHORIZED",
                [(b"www-authenticate", b"Bearer")],
            )
            return
        await self.app(scope, receive, send)
