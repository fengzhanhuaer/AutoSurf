import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, secret: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def encrypt_json(self, value: Any) -> str:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        return self._fernet.encrypt(raw).decode()

    def decrypt_json(self, value: str) -> Any:
        try:
            return json.loads(self._fernet.decrypt(value.encode()))
        except InvalidToken as exc:
            raise ValueError("credential cannot be decrypted with the configured secret key") from exc
