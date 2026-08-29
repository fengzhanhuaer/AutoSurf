# AutoSurf

AutoSurf is a Docker-first web automation service for PT sign-in and ordinary periodic site tasks. A persistent Google Chrome profile is the only browser login-state source: sign in once through the built-in remote desktop, then tasks reuse the same cookies, localStorage, sessionStorage, and browser environment.

## Features

- Persistent Google Chrome with an embedded noVNC remote desktop
- Optional remote Chrome audio over the existing management port
- PT site catalog, daily sign-in, profile refresh, history, and statistics
- Ordinary periodic browser tasks, including NodeSeek
- Execution records, sanitized debug output, and failure screenshots
- Task backup and restore as a ZIP archive
- Management login and LAN-only access enabled by default
- Authenticated in-app program upgrades

CookieCloud and Web credential synchronization are not used. Tasks do not store credential IDs or copy login snapshots into execution records.

## Docker installation

AutoSurf publishes an amd64 image. Create a directory, place [compose.yaml](compose.yaml) in it, and change these values before starting:

- `AUTOSURF_SECRET_KEY`: at least 32 random characters
- `AUTOSURF_USERNAME`: management username
- `AUTOSURF_PASSWORD`: strong management password

Start the service:

```bash
docker compose pull
docker compose up -d
```

Open `http://<host>:18980/`. The default Compose file exposes only port `18980`; no VNC, audio, or debugging port is published separately.

The image is amd64-only and installs Google Chrome stable, Xvfb, noVNC, x11vnc, PulseAudio, and the Python runtime. Persistent state is stored under the host's `./app` directory:

- `./app/program`: checked-out AutoSurf source and its Linux virtual environment
- `./app/data`: SQLite database, settings, logs, and screenshots
- `./app/browser`: persistent Google Chrome profile, including Google/website logins

Do not run `app/program/.venv` directly on Windows; it belongs to Linux inside the container.

## Browser login and remote desktop

Open **浏览器控制** in the management page. The Chrome process stays open and uses one persistent profile. Log in to Google and sites directly in this browser; later PT and periodic tasks operate in that same environment.

The toolbar supports 1280 x 720, 1365 x 768, 1600 x 900, and 1920 x 1080. Changing resolution restarts Chrome while preserving its profile. Fullscreen scales the remote desktop but does not change the configured virtual resolution.

### Audio

Choose the **音** button in the remote Chrome toolbar to start sound. Audio is disabled by default and stops when the button is turned off or the browser-control page is left.

Chrome writes audio to an internal PulseAudio sink. AutoSurf reads its monitor source as 48 kHz stereo PCM and sends it through an authenticated, same-origin WebSocket at `/browser-control/audio`. This uses the existing management port.

Audio requires the updated Docker image because PulseAudio is an operating-system package. An in-app program upgrade cannot add that package to an older container; pull and recreate the container once for this release.

## PT sign-in

Open **PT 站点 > 站点签到**. Candidates come from the built-in PT site catalog and can be added without selecting credentials. Tasks start at 09:00 Asia/Taipei, with the configured random delay and retry policy.

At execution time AutoSurf opens the site in the persistent Chrome profile and reads the current browser cookies and Web Storage. Rousi reads its token from Chrome localStorage. M-Team has no daily sign-in action and is handled as a profile-refresh-only site using its current Chrome login.

The history and statistics pages are populated from execution results. A site with no sign-in entry can still refresh profile/statistical data when its adapter supports that action.

## Periodic tasks

Open **周期签到** for ordinary sites. Built-in candidates are independent of PT candidates. NodeSeek runs its attendance request inside the persistent browser with `credentials: include`, so it uses the real Chrome session rather than a copied cookie.

Each task has its own interval, timeout, random delay, retry interval, and retry count. The execution-history tab shows pending, running, retrying, completed, blocked, and failed runs.

## Site settings

**系统设置 > 站点设置** includes:

- LAN-only access, enabled by default
- One-click task backup
- One-click task restore

LAN-only mode allows loopback, private LAN ranges, and `198.18.0.0/15`. The task backup ZIP contains automation configuration only. It does not contain the Chrome profile or login data. Back up the host's `./app/browser` directory separately when browser login persistence must also be protected.

## Online upgrade

Open **系统设置 > 系统升级** to update the program checkout, Python dependencies, and browser automation runtime. The Docker base system remains unchanged.

Use a Docker image update instead when the release changes operating-system packages or bundled Chrome:

```bash
docker compose pull
docker compose up -d
```

The command-line helper remains available:

```bash
docker exec autosurf autosurf-upgrade
```

Only one upgrade can run at a time. Runtime data and the Chrome profile remain outside the program checkout.

## API and access control

The dedicated `/login` page creates a signed HttpOnly session cookie. The management UI, `/docs`, `/openapi.json`, and `/api/v1` require that session or HTTP Basic authentication.

Remote desktop and audio WebSockets enforce the same management session, LAN policy, and same-origin checks. The service should still be placed behind HTTPS when accessed beyond a trusted LAN.

## Local development

AutoSurf requires Python 3.13.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest
```

Run locally:

```powershell
$env:AUTOSURF_SECRET_KEY = "replace-with-at-least-32-random-characters"
$env:AUTOSURF_USERNAME = "admin"
$env:AUTOSURF_PASSWORD = "replace-with-a-strong-password"
.venv\Scripts\autosurf.exe serve
```

The full remote desktop and audio path are intended for the Docker image because they require Xvfb, noVNC, x11vnc, Google Chrome, and PulseAudio.

## Database

Alembic migrations run automatically at application startup. The browser-only session migration removes legacy credential and CookieCloud tables and removes credential snapshot columns from tasks and executions. This migration is intentionally one-way; make a SQLite backup before upgrading an older installation.
