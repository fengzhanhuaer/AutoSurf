from datetime import timedelta
import json

import httpx
import pytest

from autosurf.config import Settings
from autosurf.domain.models import utc_now
from autosurf.infrastructure.database import ExecutionRecord
from autosurf.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        secret_key="s" * 32,
        username="admin",
        password="password123",
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_debug_execution_api_redacts_secrets_and_serves_owned_artifact(settings):
    app = create_app(settings)
    automation = app.state.automations.create(
        "Rousi", "pt_signin", 86400, {"url": "https://rousi.pro/"},
    )
    execution_id = "debug-execution"
    now = utc_now()
    artifact_dir = settings.data_dir / "browser-artifacts"
    artifact_dir.mkdir()
    screenshot = b"\x89PNG\r\n\x1a\nqa-image"
    artifact_dir.joinpath(f"{execution_id}.png").write_bytes(screenshot)
    with app.state.sessions.begin() as session:
        session.add(ExecutionRecord(
            id=execution_id,
            automation_id=automation.id,
            scheduled_at=now - timedelta(minutes=2),
            status="retry_wait",
            attempts=4,
            available_at=now,
            started_at=now - timedelta(minutes=1),
            finished_at=now,
            result_json=json.dumps({
                "outcome": "blocked",
                "message": "PT 站点响应超时",
                "details": {
                    "screenshot": f"/app/data/browser-artifacts/{execution_id}.png",
                    "token": "header.payload.secret-token",
                    "nested": {
                        "cookie": "sid=secret-cookie",
                        "error": "authorization=Bearer-secret",
                    },
                },
            }),
            error="request token=plain-secret timed out\nAuthorization: Bearer another-secret",
        ))

    transport = httpx.ASGITransport(app=app)
    auth = (settings.username, settings.password)
    path = (
        f"/api/v1/debug/executions?automation_id={automation.id}"
        "&status=retry_wait&outcome=blocked"
    )
    artifact_path = f"/api/v1/debug/executions/{execution_id}/artifact"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        assert (await client.get(artifact_path)).status_code == 401
        response = await client.get(path, auth=auth)
        image = await client.get(artifact_path, auth=auth)
        missing = await client.get("/api/v1/debug/executions/missing/artifact", auth=auth)
        invalid_status = await client.get(
            "/api/v1/debug/executions?status=unknown", auth=auth,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["automations"][0]["name"] == "Rousi"
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["automation_name"] == "Rousi"
    assert item["status"] == "retry_wait"
    assert item["outcome"] == "blocked"
    assert item["duration_ms"] == 60_000
    assert item["artifact_url"] == artifact_path
    assert item["result"]["details"]["screenshot"] == artifact_path
    serialized = json.dumps(item, ensure_ascii=False)
    assert "secret-token" not in serialized
    assert "secret-cookie" not in serialized
    assert "Bearer-secret" not in serialized
    assert "plain-secret" not in serialized
    assert "another-secret" not in serialized
    assert "[已脱敏]" in serialized
    assert image.status_code == 200
    assert image.content == screenshot
    assert image.headers["cache-control"] == "no-store"
    assert missing.status_code == 404
    assert invalid_status.status_code == 422
