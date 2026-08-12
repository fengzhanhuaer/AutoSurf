# AutoSurf

[![CI](https://github.com/fengzhanhuaer/AutoSurf/actions/workflows/ci.yml/badge.svg)](https://github.com/fengzhanhuaer/AutoSurf/actions/workflows/ci.yml)

AutoSurf is a small, Docker-first web automation service. The first release focuses on CookieCloud-compatible storage and durable HTTP sign-in jobs, while keeping the execution model open for future browser and script workers.

## Architecture

- Modular monolith: domain and application code do not depend on FastAPI.
- Durable queue: schedules create persisted executions in SQLite instead of running work in scheduler memory.
- Lease-based worker: interrupted executions can be reclaimed after their lease expires.
- Credential hub: cookies are encrypted at rest and versioned independently from CookieCloud transport blobs.
- Replaceable handlers: `http_signin` is the first registered automation type.

SQLite runs in WAL mode. A single application replica is supported in v0.1; PostgreSQL should be introduced before running multiple replicas.

## Run with Docker

Create `.env` from `.env.example`, replace both secrets, then run:

```powershell
docker compose up --build -d
```

Images built from `main` and version tags are published to `ghcr.io/fengzhanhuaer/autosurf`. For example:

```powershell
docker pull ghcr.io/fengzhanhuaer/autosurf:latest
```

Health endpoint: `http://localhost:8080/health`

OpenAPI: `http://localhost:8080/docs`

CookieCloud-compatible base URL: `http://localhost:8080/cookiecloud`

Do not expose the service directly to the public internet. Put it behind HTTPS and access control when remote access is required. CookieCloud upload/download endpoints intentionally do not use the management API token because compatibility is based on its UUID and end-to-end encrypted payload.

## Management API

All `/api/v1` endpoints require:

```text
Authorization: Bearer <AUTOSURF_API_TOKEN>
```

Create an encrypted cookie credential:

```powershell
$headers = @{ Authorization = "Bearer $env:AUTOSURF_API_TOKEN" }
$credential = Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/v1/credentials `
  -Headers $headers -ContentType application/json -Body '{
    "name":"my-site","domain":"example.com","cookies":{"session":"replace-me"}
  }'
```

Create a daily HTTP sign-in job:

```powershell
$body = @{
  name = "Example daily sign-in"
  handler_type = "http_signin"
  interval_seconds = 86400
  credential_id = $credential.id
  config = @{
    url = "https://example.com/attendance.php"
    method = "GET"
    success_patterns = @("签到成功", "attendance successful")
    already_patterns = @("已经签到", "already signed")
  }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/v1/automations `
  -Headers $headers -ContentType application/json -Body $body
```

The first scheduled run is due immediately. A run can also be queued with `POST /api/v1/automations/{id}/run`.

## Development

```powershell
py -3.13 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
$env:AUTOSURF_SECRET_KEY = "development-secret-key-at-least-32-chars"
$env:AUTOSURF_API_TOKEN = "development-api-token"
.venv\Scripts\pytest
.venv\Scripts\autosurf
```

## Current boundaries

- HTTP handlers support GET/POST and response-pattern matching.
- CookieCloud blobs are stored compatibly, but importing/decrypting those blobs into the internal credential hub is a separate upcoming feature.
- No browser worker or UI is included yet.
- Schema migrations will be added before the first upgrade requiring a database change.
