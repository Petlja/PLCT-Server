"""Access control for the served endpoints.

Two credentials, because the two callers are not alike:

* `api_key` -- a shared secret sent as the `X-Auth-Key` header, held by the Petlja platform
  and never by a browser. It protected the retired `/api/rag-system-message`, and it now
  protects `/api/chat`, the endpoint that took its place.
* `ui_password` -- HTTP Basic credentials covering the whole site, for the handful of people
  testing the bundled SPA. A browser cannot keep a shared secret, so it gets its own, and
  this one is meant to be switched off: unset it and the gate is gone, no code change.

Either credential satisfies either check, so the platform is never prompted for a password
and a tester is never asked for a key the browser has no way to hold.
"""

import base64
import binascii
import hmac
import logging

from fastapi import HTTPException, Request
from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from ..content.server import ConfigOptions, get_server_content

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-Auth-Key"
BASIC_CHALLENGE = 'Basic realm="PLCT Server", charset="UTF-8"'


def _matches(candidate: str | None, secret: str | None) -> bool:
    """Constant-time compare that treats an absent candidate or secret as no match."""
    if not candidate or not secret:
        return False
    return hmac.compare_digest(candidate, secret)


def _basic_password(header_value: str | None) -> str | None:
    """The password out of an `Authorization: Basic` header, or None if it is not one.

    Whatever user name the browser sends is accepted: the gate is a single shared password,
    so there is nothing to look a name up against.
    """
    if not header_value:
        return None
    scheme, _, encoded = header_value.partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    _, separator, password = decoded.partition(":")
    return password if separator else None


def authenticate(headers: Headers, conf: ConfigOptions) -> str | None:
    """Which credential the request carries, or None if it carries neither."""
    if _matches(headers.get(API_KEY_HEADER), conf.api_key):
        return "api-key"
    if _matches(_basic_password(headers.get("authorization")), conf.ui_password):
        return "ui-password"
    return None


class UiGate:
    """Puts every path behind HTTP Basic for as long as `ui_password` is set.

    Plain ASGI rather than `BaseHTTPMiddleware` on purpose: `/api/chat` streams NDJSON for
    as long as an answer takes, and `BaseHTTPMiddleware` relays a streaming response through
    an extra task and queue. This one either refuses the request or steps out of the way,
    leaving the stream untouched.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        conf = get_server_content().config_options
        if not conf.ui_password or authenticate(Headers(scope=scope), conf):
            await self.app(scope, receive, send)
            return
        challenge = Response(status_code=401, headers={"WWW-Authenticate": BASIC_CHALLENGE})
        await challenge(scope, receive, send)


def require_auth(request: Request) -> None:
    """Dependency for the endpoints that stay protected once the UI gate is switched off.

    With no `api_key` configured the endpoint is open, which is what a local `plct-serve`
    wants; configure one and the endpoint answers only to a request carrying a credential.
    """
    conf = get_server_content().config_options
    if not conf.api_key:
        return
    if authenticate(request.headers, conf) is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
