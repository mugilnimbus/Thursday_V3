"""Run an ASGI app on a localhost-only port."""

import uvicorn

LOCALHOST = "127.0.0.1"


def serve(app: object, port: int, log_level: str = "info") -> None:
    """Blocks until shutdown. Services other than the gateway proxy listener never bind beyond localhost."""
    uvicorn.run(app, host=LOCALHOST, port=port, log_level=log_level.lower(), access_log=False)  # pyright: ignore[reportArgumentType]
