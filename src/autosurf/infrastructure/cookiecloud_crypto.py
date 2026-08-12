from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


SUPPORTED_CRYPTO_TYPES = {"legacy", "aes-128-cbc-fixed"}


def decrypt_cookiecloud(uuid: str, password: str, encrypted: str,
                        crypto_type: str = "legacy") -> dict[str, Any]:
    if crypto_type not in SUPPORTED_CRYPTO_TYPES:
        raise ValueError(f"unsupported CookieCloud crypto type: {crypto_type}")
    try:
        raw = base64.b64decode(encrypted, validate=True)
        passphrase = hashlib.md5(f"{uuid}-{password}".encode()).hexdigest()[:16].encode()
        if crypto_type == "aes-128-cbc-fixed":
            key, iv, ciphertext = passphrase, bytes(16), raw
        else:
            if len(raw) < 16 or raw[:8] != b"Salted__":
                raise ValueError("legacy payload is missing the OpenSSL salt header")
            key, iv = _evp_bytes_to_key(passphrase, raw[8:16], 32, 16)
            ciphertext = raw[16:]

        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        value = json.loads(plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("CookieCloud decryption failed; check UUID, password, and crypto type") from exc
    if not isinstance(value, dict) or not isinstance(value.get("cookie_data"), dict):
        raise ValueError("decrypted CookieCloud payload has no cookie_data object")
    return value


def _evp_bytes_to_key(password: bytes, salt: bytes, key_length: int, iv_length: int) -> tuple[bytes, bytes]:
    derived = b""
    block = b""
    while len(derived) < key_length + iv_length:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_length], derived[key_length:key_length + iv_length]
