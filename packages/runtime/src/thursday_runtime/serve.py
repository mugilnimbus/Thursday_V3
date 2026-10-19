"""Run an ASGI app on a localhost-only port."""

import uvicorn

LOCALHOST = "127.0.0.1"

# How long a service keeps a connection open that nothing is sent on. The services call each other with clients
# that keep an unused connection for five seconds and then open a new one (httpx's default). A service has to keep
# it for longer than that: closing it after the same five seconds, as a server does by default, closes it in the
# very moment a client that calls every five seconds uses it again, and that call fails although nothing is wrong.
KEEP_ALIVE_SECONDS = 30


def serve(app: object, port: int, log_level: str = "info") -> None:
    """Blocks until shutdown. Services other than the gateway proxy listener never bind beyond localhost."""
    uvicorn.run(
        app,  # pyright: ignore[reportArgumentType]
        host=LOCALHOST,
        port=port,
        log_level=log_level.lower(),
        access_log=False,
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )
