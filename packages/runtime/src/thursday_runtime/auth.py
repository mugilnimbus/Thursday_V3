"""Service-token authentication between Thursday services (bearer token from `.env`)."""

import hmac

from fastapi import HTTPException, Request, status
from pydantic import SecretStr


class ServiceTokenAuth:
    """FastAPI dependency: rejects requests without the shared service token.

    An empty configured token rejects everything, so a missing setup step fails closed.
    """

    def __init__(self, token: SecretStr) -> None:
        self._token = token.get_secret_value().encode()

    async def __call__(self, request: Request) -> None:
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if not self._token or scheme.lower() != "bearer" or not hmac.compare_digest(presented.encode(), self._token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="unauthenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
