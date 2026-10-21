"""Keep presigned URLs, credentials and request bodies out of Sentry.

Bitonal requests carry presigned S3 URLs, which are bearer credentials
until they expire: whoever reads one can fetch or overwrite that object.
Error events, breadcrumbs for outgoing HTTP calls and exception messages
can all quote them, so everything bound for Sentry goes through here.
"""

import re
from typing import Any

REDACTED = "[redacted]"

# Everything after the "?" of a URL: that is where a presigned URL keeps
# its signature and credential.
URL_QUERY = re.compile(r"(https?://[^\s\"'<>?#]+)\?[^\s\"'<>]*")
SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization"}


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return URL_QUERY.sub(rf"\1?{REDACTED}", value)
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and key.lower() in SENSITIVE_HEADERS
                else _scrub(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


def scrub_event(event: Any, hint: Any = None) -> Any:
    """``before_send`` hook: drop request bodies, scrub URLs and secrets."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
    return _scrub(event)


def scrub_breadcrumb(crumb: Any, hint: Any = None) -> Any:
    """``before_breadcrumb`` hook: outgoing HTTP calls log their URL."""
    return _scrub(crumb)
