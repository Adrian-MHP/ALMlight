"""Encryption of stored credentials (repository tokens, connector passwords) with a key derived from the
installation's secret key. Credentials are written once and never returned by the API."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from almlight.core.config import get_settings


def _fernet() -> Fernet:
    key = hashlib.sha256(("almlight-secretbox:" + get_settings().resolved_secret_key()).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def unseal(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # the secret key changed: the credential has to be entered again
