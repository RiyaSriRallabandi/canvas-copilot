"""Secure storage for the Canvas access token, backed by the OS keychain.

On macOS this is the login Keychain. The token is never written to a file, so
it cannot be committed, copied with the project folder, or read by other tools.
"""

from __future__ import annotations

import keyring
from keyring.errors import PasswordDeleteError

_SERVICE = "canvas-copilot"
_USERNAME = "canvas-token"


def store_token(token: str) -> None:
    keyring.set_password(_SERVICE, _USERNAME, token)


def get_token() -> str | None:
    return keyring.get_password(_SERVICE, _USERNAME)


def delete_token() -> bool:
    """Remove the stored token. Returns True if one was actually removed."""
    try:
        keyring.delete_password(_SERVICE, _USERNAME)
        return True
    except PasswordDeleteError:
        return False
