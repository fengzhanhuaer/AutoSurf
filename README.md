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

Edit `compose.yaml` before the first start and replace the encryption key, username, and password:

```yaml
environment:
  AUTOSURF_SECRET_KEY: "a-random-encryption-key-at-least-32-characters"
  AUTOSURF_USERNAME: "admin"
  AUTOSURF_PASSWORD: "a-strong-management-password"
```

PowerShell can generate a random value:

```powershell
$bytes = New-Object byte[] 48
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToBase64String($bytes)
```

Use separate generated values for the encryption key and password. Do not change `AUTOSURF_SECRET_KEY` after data has been written, or stored credentials will no longer decrypt. The username and management password can be changed independently.

Start the service:

```powershell
docker compose pull
docker compose up -d
```

The default Compose file downloads `ghcr.io/fengzhanhuaer/autosurf:latest`. Pin a release by replacing the image tag in `compose.yaml`.

The Docker image is a stable runtime shell. Application source and its Linux Python environment live in `./autosurf_program`, while Playwright's Chromium runtime lives in `./browser`. Both directories are mounted from the host and can be upgraded without replacing the container. On first start, the shell initializes any missing program or browser files. Do not run `autosurf_program/.venv` directly on a Windows host because that virtual environment belongs to Linux inside the container.

AutoSurf pins the matching Playwright Python package and installs Chromium into the persistent browser mount. The Web upgrade action updates application code, Python dependencies, and that matching Chromium runtime together. Rebuild the shell only when Python itself or Chromium's required operating-system libraries change.

For a host-only deployment, change the port mapping to `127.0.0.1:18980:8080`. This is recommended when a reverse proxy on the same machine provides HTTPS.

Check service state and logs:

```powershell
docker compose ps
docker compose logs -f --tail 100 autosurf
```

Upgrade the pinned or latest image:

```powershell
docker compose pull
docker compose up -d --remove-orphans
docker image prune -f
```

AutoSurf applies pending Alembic database migrations during startup. The application starts only after the migration succeeds. Existing pre-migration databases are inspected and adopted at the matching schema revision before pending migrations run.

For normal upgrades, use the authenticated management page or keep the Docker shell running and execute:

```powershell
docker exec autosurf autosurf-upgrade
```

The helper gracefully stops only the AutoSurf application process, backs up SQLite, fast-forward pulls `./autosurf_program`, updates its isolated Python environment, installs the matching browser into `./browser`, applies migrations, and asks the shell to start the new version. The container and all mounted directories remain in place.

In the management page, open **系统升级** from the sidebar, review the program and browser versions, then choose **开始升级**. The page follows the application restart and reports the persisted result. Only one upgrade can run at a time.

Only pull and recreate the container when the runtime shell itself changes, such as a Python or operating-system dependency update. `docker compose pull && docker compose up -d` is the separate shell-upgrade path.

To roll back, replace the image with the previous release tag and run `docker compose up -d` again. Back up the `data` directory before upgrading across database versions.

To build from the local source tree instead:

```powershell
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
```

Images built from `main` and version tags are published to `ghcr.io/fengzhanhuaer/autosurf`. For example:

```powershell
docker pull ghcr.io/fengzhanhuaer/autosurf:latest
```

Health endpoint: `http://localhost:18980/health`

Management interface: `http://localhost:18980/`

OpenAPI: `http://localhost:18980/docs`

CookieCloud-compatible base URL: `http://localhost:18980/cookiecloud`

Do not expose the service directly to the public internet. Put it behind HTTPS and access control when remote access is required. CookieCloud upload/download endpoints intentionally do not use management login because compatibility is based on its UUID and end-to-end encrypted payload.

### CookieCloud automatic import

Configure a CookieCloud UUID once through the authenticated management API. The password is encrypted at rest. Future browser uploads for that UUID are decrypted and imported into versioned credentials automatically:

```powershell
$pair = "admin:your-management-password"
$headers = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)) }
$body = @{
  uuid = "your-cookiecloud-uuid"
  password = "your-cookiecloud-password"
  auto_import = $true
} | ConvertTo-Json
Invoke-RestMethod -Method Put `
  -Uri http://localhost:18980/api/v1/cookiecloud/sources/your-cookiecloud-uuid `
  -Headers $headers -ContentType application/json -Body $body
```

Existing stored data can be imported immediately with:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:18980/api/v1/cookiecloud/sources/your-cookiecloud-uuid/import `
  -Headers $headers -ContentType application/json -Body '{}'
```

Both CookieCloud `legacy` and `aes-128-cbc-fixed` encryption modes are supported. Imported credential names use `cookiecloud:<uuid>:<domain>`.

### Browser sign-in

Use the `browser_signin` handler for sites that require JavaScript or an actual Chromium page. It launches an isolated headless Chromium context, injects the selected credential cookies, loads the page, optionally waits for and clicks an element, and evaluates success text after the interaction.

```json
{
  "name": "Browser daily sign-in",
  "handler_type": "browser_signin",
  "interval_seconds": 86400,
  "credential_id": "<credential-id>",
  "config": {
    "url": "https://example.com/attendance.php",
    "wait_for_selector": "button.checkin",
    "click_selector": "button.checkin",
    "wait_after_click_ms": 1500,
    "success_patterns": ["签到成功"],
    "already_patterns": ["已经签到"]
  }
}
```

Failed and timed-out browser runs save a screenshot under `data/browser-artifacts`. Chromium runs headless but uses the full Playwright Chromium browser engine and executes page JavaScript.

## Management API

The dedicated `/login` page uses the username and password configured in `compose.yaml`. Unauthenticated visits to `/app` are redirected there; a successful login creates a signed HttpOnly session cookie and opens the management console. Swagger `/docs`, its OpenAPI schema, and all `/api/v1` endpoints accept that session; API clients may continue using HTTP Basic authentication. CookieCloud compatibility endpoints remain outside management authentication because clients identify encrypted payloads by UUID.

Create an encrypted cookie credential:

```powershell
$pair = "admin:your-management-password"
$headers = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)) }
$credential = Invoke-RestMethod -Method Post -Uri http://localhost:18980/api/v1/credentials `
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
Invoke-RestMethod -Method Post -Uri http://localhost:18980/api/v1/automations `
  -Headers $headers -ContentType application/json -Body $body
```

The first scheduled run is due immediately. A run can also be queued with `POST /api/v1/automations/{id}/run`.

## Development

```powershell
py -3.13 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
$env:AUTOSURF_SECRET_KEY = "development-secret-key-at-least-32-chars"
$env:AUTOSURF_USERNAME = "admin"
$env:AUTOSURF_PASSWORD = "development-password"
.venv\Scripts\pytest
.venv\Scripts\autosurf
```

For a local Python installation, AutoSurf provides an upgrade command:

```powershell
.venv\Scripts\autosurf upgrade --repository D:\Code\AutoSurf
```

The command requires a clean Git working tree, creates a timestamped SQLite backup under `data/backups`, performs a fast-forward-only pull, updates installed Python dependencies, and applies database migrations. Restart the running service after it completes. If AutoSurf runs as a Windows service, restart it through the same service manager that starts it.

## Current boundaries

- HTTP handlers support GET/POST and response-pattern matching.
- CookieCloud blobs can be decrypted and imported automatically after their UUID and password are configured.
- The authenticated management interface configures CookieCloud sources, triggers imports, and shows imported credential metadata without exposing cookie values.
- Database upgrades run automatically through Alembic at application startup.
