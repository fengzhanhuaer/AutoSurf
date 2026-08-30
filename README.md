# AutoSurf

AutoSurf is a Windows-native browser automation service for PT sign-in and ordinary periodic site tasks. It starts an independent, visible Google Chrome window and keeps all browser login state in one persistent local profile.

## Requirements

- Windows 10 or Windows 11
- Python 3.13 (`py.exe` launcher available)
- Git for Windows
- PowerShell 5.1 or later

Docker is not used or supported.

## Install

Run PowerShell from a source checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

The default installation directory is `C:\Tools\AutoSurf`. The installer creates:

- `C:\Tools\AutoSurf\program`: program checkout and Python environment
- `C:\Tools\AutoSurf\data`: database, logs, backups, and screenshots
- `C:\Tools\AutoSurf\runtime\chrome`: repository-pinned independent Chrome runtime
- `C:\Tools\AutoSurf\browser\profiles`: persistent Chrome profile and website logins
- `C:\Tools\AutoSurf\.env`: local service configuration

It also creates Startup and Desktop shortcuts. AutoSurf starts after Windows login and listens only at [http://127.0.0.1:18980/](http://127.0.0.1:18980/).

To choose the initial management password:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Password "replace-with-a-strong-password"
```

The default management username is `adminforautosurf`. When no password is supplied, the installer generates one, prints it, and records it in `C:\Tools\AutoSurf\data\install.log`. A password supplied explicitly on the command line is not written to this log.

## Browser

Open **浏览器控制** and choose **打开浏览器**. AutoSurf launches or restores a separate Windows Chrome window; the management webpage does not embed or relay its picture.

The browser executable is an official, version-pinned Chrome for Testing build installed under `C:\Tools\AutoSurf\runtime\chrome`. It is separate from the system browser and does not auto-update. Browser sign-in state is stored under `C:\Tools\AutoSurf\browser\profiles` and is reused by all automated tasks. It uses the normal Windows graphics driver, extensions, audio, and network environment.

## PT sign-in

Open **PT 站点 > 站点签到**. Tasks start at 09:00 Asia/Taipei with the configured random delay and retry policy. At execution time AutoSurf connects to the persistent Chrome window and uses its current cookies and Web Storage.

M-Team has no daily sign-in action and is handled as a profile-refresh-only site. Sites without a sign-in entry can still refresh profile and statistical data when their adapter supports it.

## Periodic tasks

Open **周期签到** for ordinary sites. Built-in candidates are independent of PT candidates. Each task has its own interval, timeout, random delay, retry interval, and retry count. The execution-history tab records pending, running, retrying, completed, blocked, and failed runs.

## Backup

**系统设置 > 站点设置** provides task backup and restore. The backup ZIP contains task configuration only. Back up `C:\Tools\AutoSurf\browser` separately when browser login state must also be protected.

## Upgrade

**系统设置 > 系统升级** updates the program checkout and its repository-pinned Python dependencies only after the user starts an upgrade. If that release pins a different browser build, the Windows supervisor also replaces the independent browser runtime with that exact version. It does not follow the latest Chrome release automatically, and Windows is never updated by AutoSurf.

The command-line upgrade remains available:

```powershell
C:\Tools\AutoSurf\program\.venv\Scripts\python.exe -m autosurf.main upgrade --repository C:\Tools\AutoSurf\program
```

## Stop and start

```powershell
powershell -ExecutionPolicy Bypass -File C:\Tools\AutoSurf\program\scripts\stop.ps1
powershell -ExecutionPolicy Bypass -File C:\Tools\AutoSurf\program\scripts\run.ps1
```

## Development

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m pytest
```

Development configuration must bind `AUTOSURF_HOST=127.0.0.1`. The browser window and automation worker share the same persistent Chrome process but use separate pages for task execution.
