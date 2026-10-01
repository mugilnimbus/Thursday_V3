"""Protections for the trusted localhost listener against web pages in the user's browser.

"Only software on this PC can reach it" includes any website open in a browser here, so:
- the Host header must name this listener (blocks DNS rebinding);
- a browser-sent Origin must be this listener's own origin (blocks cross-site requests and sockets);
- state-changing calls must carry `X-Thursday-Client`, a header a cross-site page cannot add
  without a CORS preflight, which this listener never grants.
Agent calls (event and metrics ingest) are authenticated by the service token instead.
"""

from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CLIENT_HEADER = b"x-thursday-client"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
SERVICE_TOKEN_PATHS = ("/v1/events", "/v1/metrics")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self' ws: wss:; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


def allowed_hosts(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}


class LocalGuard:
    def __init__(self, app: ASGIApp, port: int, extra_origins: Iterable[str] = ()) -> None:
        self._app = app
        self._hosts = allowed_hosts(port)
        self._origins = {f"http://{host}" for host in self._hosts} | set(extra_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        host = headers.get(b"host", b"").decode("latin-1").lower()
        origin = headers.get(b"origin", b"").decode("latin-1").lower()
        path = scope.get("path", "")
        reason = None
        if host not in self._hosts:
            reason = "unexpected host"
        elif origin and origin not in self._origins:
            reason = "cross-origin request"
        elif (
            scope["type"] == "http"
            and scope.get("method") in UNSAFE
            and not path.startswith(SERVICE_TOKEN_PATHS)
            and CLIENT_HEADER not in headers
        ):
            reason = "missing client header"
        if reason is not None:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            body = (
                '{"type":"about:blank","title":"Forbidden","status":403,"code":"unauthenticated","detail":"'
                + reason
                + '"}'
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/problem+json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start" and not path.startswith("/v1"):
                extra = [
                    (b"content-security-policy", CSP.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self._app(scope, receive, send_with_headers)
