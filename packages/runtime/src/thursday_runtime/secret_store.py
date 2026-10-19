"""Where API keys are kept: the operating system's own credential store, never a file of ours.

On Windows this is Credential Manager (encrypted for the signed-in account), on macOS the Keychain, on Linux the
Secret Service. A key is written from Settings and read by the service that uses it; it is never returned to a
client, logged, or backed up.
"""

from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE_NAME = "Thursday"


class SecretStoreError(Exception):
    """The credential store is missing or refused the request."""


class SecretStore(Protocol):
    def get(self, name: str) -> str:
        """The stored value, or an empty string."""
        ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class KeyringStore:
    def __init__(self, service: str = SERVICE_NAME) -> None:
        self._service = service

    def get(self, name: str) -> str:
        try:
            return keyring.get_password(self._service, name) or ""
        except KeyringError:
            return ""

    def set(self, name: str, value: str) -> None:
        try:
            keyring.set_password(self._service, name, value)
        except KeyringError as exc:
            raise SecretStoreError("This system has no credential store to keep the key in.") from exc

    def delete(self, name: str) -> None:
        try:
            keyring.delete_password(self._service, name)
        except PasswordDeleteError:
            return  # nothing was stored
        except KeyringError as exc:
            raise SecretStoreError("The credential store refused to remove the key.") from exc


def credential_store_available() -> bool:
    """True when this system has a credential store keys can be saved in."""
    from keyring.backends import fail

    try:
        return not isinstance(keyring.get_keyring(), fail.Keyring)
    except KeyringError:
        return False


class MemoryStore:
    """Keeps values for the life of the process only. For tests."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def get(self, name: str) -> str:
        return self._values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)
