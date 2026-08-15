import base64
import gzip
import hashlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from sqlalchemy import select

from autosurf.config import Settings
from autosurf.infrastructure.cookiecloud_crypto import decrypt_cookiecloud
from autosurf.infrastructure.database import CredentialRecord
from autosurf.main import create_app


PAYLOAD = {
    "cookie_data": {
        ".example.com": [
            {"name": "sid", "value": "secret-session", "domain": ".example.com", "path": "/"},
            {"name": "theme", "value": "dark", "domain": ".example.com", "path": "/"},
        ]
    },
    "local_storage_data": {},
    "update_time": "2026-08-12T10:00:00.000Z",
}


def evp_bytes_to_key(password: bytes, salt: bytes) -> tuple[bytes, bytes]:
    output = b""
    block = b""
    while len(output) < 48:
        block = hashlib.md5(block + password + salt).digest()
        output += block
    return output[:32], output[32:48]


def encrypt_vector(uuid: str, password: str, crypto_type: str) -> str:
    plaintext = json.dumps(PAYLOAD, separators=(",", ":")).encode()
    passphrase = hashlib.md5(f"{uuid}-{password}".encode()).hexdigest()[:16].encode()
    if crypto_type == "legacy":
        salt = b"12345678"
        key, iv = evp_bytes_to_key(passphrase, salt)
        prefix = b"Salted__" + salt
    else:
        key, iv, prefix = passphrase, bytes(16), b""
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return base64.b64encode(prefix + encryptor.update(padded) + encryptor.finalize()).decode()


@pytest.mark.parametrize("crypto_type", ["legacy", "aes-128-cbc-fixed"])
def test_decrypts_cookiecloud_protocols(crypto_type):
    encrypted = encrypt_vector("test-id", "password", crypto_type)
    assert decrypt_cookiecloud("test-id", "password", encrypted, crypto_type) == PAYLOAD


def test_wrong_password_is_rejected():
    encrypted = encrypt_vector("test-id", "password", "legacy")
    with pytest.raises(ValueError, match="decryption failed"):
        decrypt_cookiecloud("test-id", "wrong", encrypted, "legacy")


@pytest.mark.asyncio
async def test_upload_auto_imports_configured_source(tmp_path):
    settings = Settings(data_dir=tmp_path, secret_key="s" * 32, username="admin", password="password123")
    app = create_app(settings)
    auth = (settings.username, settings.password)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        configured = await client.put("/api/v1/cookiecloud/sources/test-id", auth=auth, json={
            "uuid": "test-id", "password": "password", "auto_import": True,
        })
        assert configured.status_code == 200
        upload_body = json.dumps({
            "uuid": "test-id", "encrypted": encrypt_vector("test-id", "password", "aes-128-cbc-fixed"),
            "crypto_type": "aes-128-cbc-fixed",
        }).encode()
        uploaded = await client.post("/cookiecloud/update", content=gzip.compress(upload_body), headers={
            "Content-Type": "application/json", "Content-Encoding": "gzip",
        })
        assert uploaded.status_code == 200
        assert uploaded.json()["imported"] == 1

    with app.state.sessions() as session:
        credential = session.scalar(select(CredentialRecord))
        assert credential.name == "cookiecloud:test-id:example.com"
        assert "secret-session" not in credential.encrypted_payload
        assert app.state.credentials.cookies_for(credential) == {"sid": "secret-session", "theme": "dark"}
        assert app.state.credentials.browser_cookies_from_payload(credential.encrypted_payload) == [
            {"name": "sid", "value": "secret-session", "domain": ".example.com", "path": "/",
             "secure": False, "httpOnly": False},
            {"name": "theme", "value": "dark", "domain": ".example.com", "path": "/",
             "secure": False, "httpOnly": False},
        ]


@pytest.mark.asyncio
async def test_cookiecloud_source_list_hides_password_and_preserves_it_on_update(tmp_path):
    settings = Settings(data_dir=tmp_path, secret_key="s" * 32, username="admin", password="password123")
    app = create_app(settings)
    auth = (settings.username, settings.password)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.put("/api/v1/cookiecloud/sources/test-id", auth=auth, json={
            "uuid": "test-id", "password": "password", "auto_import": True,
        })
        assert created.status_code == 200
        assert created.json()["password_configured"] is True
        assert set(created.json()) == {
            "uuid", "configured", "password_configured", "auto_import", "last_import_at",
            "last_error", "blob_updated_at", "credential_count",
        }
        assert "\"password\":\"password\"" not in created.text

        unauthenticated_reveal = await client.post(
            "/api/v1/cookiecloud/sources/test-id/password/reveal"
        )
        revealed = await client.post(
            "/api/v1/cookiecloud/sources/test-id/password/reveal", auth=auth
        )
        assert unauthenticated_reveal.status_code == 401
        assert revealed.status_code == 200
        assert revealed.json() == {"password": "password"}
        assert revealed.headers["cache-control"] == "no-store"
        assert revealed.headers["pragma"] == "no-cache"

        updated = await client.patch("/api/v1/cookiecloud/sources/test-id/settings", auth=auth, json={
            "auto_import": False,
        })
        assert updated.status_code == 200
        assert updated.json()["auto_import"] is False
        assert updated.json()["password_configured"] is True

        sources = await client.get("/api/v1/cookiecloud/sources", auth=auth)
        assert sources.status_code == 200
        assert sources.json()["items"] == [updated.json()]
        assert "\"password\":\"password\"" not in sources.text


@pytest.mark.asyncio
async def test_new_cookiecloud_source_requires_password(tmp_path):
    settings = Settings(data_dir=tmp_path, secret_key="s" * 32, username="admin", password="password123")
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/api/v1/cookiecloud/sources/test-id",
                                    auth=(settings.username, settings.password), json={
            "uuid": "test-id", "password": None, "auto_import": True,
        })
    assert response.status_code == 422
    assert response.json()["detail"] == "CookieCloud password is required for a new source"
