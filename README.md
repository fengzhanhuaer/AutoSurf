# AutoSurf

[![CI](https://github.com/fengzhanhuaer/AutoSurf/actions/workflows/ci.yml/badge.svg)](https://github.com/fengzhanhuaer/AutoSurf/actions/workflows/ci.yml)

AutoSurf is a small, Docker-first web automation service. The first release focuses on CookieCloud-compatible storage and durable PT sign-in jobs, while keeping the execution model open for future automation workers.

## Architecture

- Modular monolith: domain and application code do not depend on FastAPI.
- Durable queue: schedules create persisted executions in SQLite instead of running work in scheduler memory.
- Lease-based worker: interrupted executions can be reclaimed after their lease expires.
- Credential hub: cookies are encrypted at rest and versioned independently from CookieCloud transport blobs.
- Replaceable handlers: PT, browser, and HTTP runners share one durable execution contract.

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

On Linux, create the two bind-mount directories with the image user's ownership before the first start:

```bash
mkdir -p app tmp
sudo chown -R 10001:10001 app tmp
docker compose pull
docker compose up -d
```

The default Compose file downloads `ghcr.io/fengzhanhuaer/autosurf:latest`. Pin a release by replacing the image tag in `compose.yaml`.

The Docker image is a stable runtime shell and keeps its startup and upgrade helpers under `/usr/local/bin`, outside the writable application mount. The host's `./app` directory is mounted as the complete `/app` tree: persistent data lives in `./app/data`, application source and its Linux Python environment live in `./app/program`, and Google Chrome's persistent profile lives in `./app/browser`. These directories can be upgraded without replacing the container. The read-only shell also mounts host-visible temporary space from `./tmp` to `/tmp`; its contents are disposable and ignored by Git. On first start, the shell initializes the missing application subdirectories. Do not run `app/program/.venv` directly on a Windows host because that virtual environment belongs to Linux inside the container.

AutoSurf pins the Playwright Python package and installs the current official Google Chrome stable amd64 package in the Docker image. The Web upgrade action updates application code and Python dependencies. Pull and recreate the container when the bundled Chrome version or its operating-system libraries change.

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

The helper gracefully stops only the AutoSurf application process, backs up SQLite, force-aligns `./app/program` to `origin/$AUTOSURF_BRANCH`, updates its isolated Python environment, installs the matching browser into `./app/browser`, applies migrations, and asks the shell to start the new version. The container and application mount remain in place. Remote source is authoritative during upgrades: tracked local changes and untracked non-ignored files inside `./app/program` are deleted. Ignored runtime state such as `.venv` and the sibling `app/data` and `app/browser` directories is preserved.

In the management page, open **系统设置 > 系统升级**, review the program and browser versions, then choose **开始升级**. The page follows the application restart and reports the persisted result. Only one upgrade can run at a time.

Only pull and recreate the container when the runtime shell itself changes, such as a Python or operating-system dependency update. `docker compose pull && docker compose up -d` is the separate shell-upgrade path.

To roll back, replace the image with the previous release tag and run `docker compose up -d` again. Back up the `app/data` directory before upgrading across database versions.

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

Both CookieCloud `legacy` and `aes-128-cbc-fixed` encryption modes are supported. Imported credential names use `cookiecloud:<uuid>:<domain>`. Browser cookie attributes including domain, path, expiry, Secure, HttpOnly, and SameSite are retained in the encrypted credential payload.

### Web credential sync

Some sites store login state in browser Web Storage rather than cookies. Open **系统设置 > Web 凭据**, choose the site, enter the AutoSurf root URL that the browser running Tampermonkey can reach, and generate its synchronization script. The default is the current management-page origin; use a LAN address or HTTPS reverse-proxy address when the browser runs on another machine. Rousi is the first supported source and uses `localStorage.token`; future sources share the same management surface.

The neutral AutoSurf Web credential userscript adds an **A** button to the right edge of the configured site. Its panel identifies the current source, masks the credential by default, supports explicit reveal/copy, and uploads only when the value changes or the user chooses **立即同步**. Generating the script rotates a write-only upload key and invalidates older scripts. AutoSurf stores only the key digest and encrypts the credential with `AUTOSURF_SECRET_KEY`; management status endpoints never return the credential value.

### PT sign-in

Open **PT 站点** and select the **站点签到** tab in the management interface. AutoSurf discovers PT candidates from its built-in site catalog and high-confidence PT cookie signatures, then lets you select and add all supported sites in one operation. Cookie names and values are never returned by the discovery API. The candidate list and credential selector only show high-confidence PT sites that have not already been added, so unrelated CookieCloud domains such as search engines do not appear. Root and `www` credentials for the same tracker are grouped into one candidate; their CookieCloud records are merged into the immutable execution snapshot so host-only login cookies and root-domain challenge cookies remain available together. Rousi becomes addable only after its dedicated browser Token has been synchronized and supports both sign-in and profile statistics refresh. M-Team has no sign-in action; after its Web credentials are synchronized, AutoSurf can add it as a profile-refresh-only site and collect the account statistics returned by its profile API.

Use **手动添加自定义站点** to adjust the URL or recognition rules for an available PT credential. AutoSurf suggests `https://<credential-domain>/attendance.php`; the URL must remain on the selected credential domain or one of its subdomains.

All PT sites reuse one persistent Playwright Google Chrome profile under the persistent browser mount. In Docker, AutoSurf starts a private Xvfb display and runs the complete Chrome browser in headed mode; environments without Xvfb fall back to persistent headless mode. When a new shared profile is initialized, AutoSurf imports the current Cookie and WebStorage credentials once. Later runs read the live Cookie and localStorage values from Chrome, so manual logins and tokens refreshed by a site remain authoritative. AutoSurf executes the page JavaScript and checks for already-signed, successful, expired-login, challenge, and manual make-up-sign-in states. A common sign-in control is clicked automatically. Rule descriptions such as "signing in can earn bonus points" are not treated as successful results. Site-specific CSS selectors and result text can be configured under the advanced settings. Unknown, blocked, and timed-out results are not recorded as successful, and failed runs retain a screenshot under `data/browser-artifacts`.

Scheduled PT runs start at a random point within the configured delay window, which defaults to 30 minutes. Failed runs retry at a fixed interval that defaults to two hours, with five retries after the initial attempt. These values can be set when adding sites and changed later from each task's **设置** dialog. Each site has independent **签到** and **刷新** switches; profile refresh reuses the authenticated browser, visits the user details page, and records username, level, traffic, ratio, bonus, and seeding statistics for the **信息统计** tab. Turning off both switches disables the task. Immediate runs and history retries reuse an active or just-created execution instead of inserting a duplicate. The execution history groups the latest result for each site and local calendar day into a seven-day matrix, with buttons to open the configured site URL or retry the task. Successful runs also read FullCalendar-style calendars and plain-text PTTime history when present, overlaying site-reported dates and reward text without creating fake execution records.

The PT management API is available at:

- `POST /api/v1/pt-signin/sites`
- `GET /api/v1/pt-signin/sites`
- `GET /api/v1/pt-signin/candidates`
- `POST /api/v1/pt-signin/sites/collect`
- `PATCH /api/v1/pt-signin/sites/{id}/schedule`
- `PATCH /api/v1/pt-signin/sites/{id}/actions`
- `PATCH /api/v1/pt-signin/sites/{id}/enabled`
- `POST /api/v1/pt-signin/sites/{id}/run`
- `DELETE /api/v1/pt-signin/sites/{id}`
- `GET /api/v1/pt-signin/executions`
- `GET /api/v1/pt-signin/history`
- `GET /api/v1/pt-signin/stats`

### Browser sign-in

Use the `browser_signin` handler for sites that require JavaScript or an actual Chrome page. It reuses the shared persistent Chrome profile and its current browser-managed login state, loads the page, optionally waits for and clicks an element, and evaluates success text after the interaction.

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

Failed and timed-out browser runs save a screenshot under `data/browser-artifacts`. Docker runs the full Google Chrome browser in headed mode on a private Xvfb display and retains shared browser state under `browser/profiles/shared`; deleting that directory resets browser identity and browser-bound state for every site.

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

The command creates a timestamped SQLite backup under `data/backups`, fetches the configured `AUTOSURF_BRANCH` (default `main`), force-resets the checkout to that remote branch, removes untracked non-ignored files, updates installed Python dependencies, and applies database migrations. Local source changes in the selected repository are intentionally discarded. Restart the running service after it completes. If AutoSurf runs as a Windows service, restart it through the same service manager that starts it.

## Current boundaries

- HTTP handlers support GET/POST and response-pattern matching.
- CookieCloud blobs can be decrypted and imported automatically after their UUID and password are configured.
- CookieCloud imports retain complete browser cookie attributes in the encrypted credential store.
- The Rousi userscript synchronizes its browser Token through a revocable write-only key and encrypted credential record.
- PT sign-in uses one shared real Playwright Google Chrome environment and keeps site-specific behavior extensible through adapters.
- The authenticated management interface configures CookieCloud sources and PT sign-in tasks without exposing cookie values.
- Database upgrades run automatically through Alembic at application startup.
