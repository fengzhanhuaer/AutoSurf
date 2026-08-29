from __future__ import annotations

import asyncio
import argparse
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import threading

import uvicorn
from fastapi import Depends, FastAPI, Request, WebSocket
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from autosurf import __version__
from autosurf.access import LanAccessMiddleware, LanAccessPolicy, is_lan_address
from autosurf.api import (
    SESSION_COOKIE,
    auth_router,
    authenticated_session_username,
    cookiecloud_router,
    require_login,
    router,
    web_credential_router,
)
from autosurf.application.registry import HandlerRegistry
from autosurf.application.services import (
    AutomationService,
    CredentialService,
    ExecutionService,
    QueueService,
    reconcile_periodic_signin_templates,
    reconcile_pt_site_aliases,
    reconcile_signin_schedules,
)
from autosurf.browser_control import BrowserControlService, REMOTE_DESKTOP_PREFIX
from autosurf.automations.http_signin import HttpSignInHandler
from autosurf.automations.browser_signin import BrowserSignInHandler
from autosurf.automations.pt_signin import (
    BtschoolAdapter,
    ChdBitsAdapter,
    FiftyTwoPtAdapter,
    MTeamAdapter,
    OpenCdAdapter,
    OshenPtAdapter,
    PtSignInHandler,
    RousiAdapter,
    SoulVoiceAdapter,
    SunnyPtAdapter,
    TjuptAdapter,
    ZhuqueAdapter,
)
from autosurf.config import Settings, get_settings
from autosurf.infrastructure.cookiecloud import CookieCloudStore
from autosurf.infrastructure.crypto import SecretBox
from autosurf.infrastructure.database import create_session_factory
from autosurf.infrastructure.gzip_request import GZipRequestMiddleware
from autosurf.infrastructure.migrations import upgrade_database
from autosurf.infrastructure.web_credentials import WebCredentialStore
from autosurf.management import management_router
from autosurf.upgrade import upgrade


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    lan_access = LanAccessPolicy(sessions)
    registry = HandlerRegistry()
    registry.register(HttpSignInHandler())
    registry.register(BrowserSignInHandler())
    registry.register(PtSignInHandler([
        FiftyTwoPtAdapter(), ChdBitsAdapter(), BtschoolAdapter(), OpenCdAdapter(),
        OshenPtAdapter(), SoulVoiceAdapter(),
        TjuptAdapter(), RousiAdapter(),
        MTeamAdapter(), SunnyPtAdapter(), ZhuqueAdapter(),
    ]))
    secrets = SecretBox(settings.secret_key)
    credentials = CredentialService(sessions, secrets)
    automations = AutomationService(sessions, registry)
    queue = QueueService(sessions, settings.execution_lease_seconds, credentials)
    execution = ExecutionService(sessions, queue, credentials, registry)
    browser_control = BrowserControlService(
        credential_bootstrap=credentials.browser_bootstrap_contexts,
    )
    reconcile_pt_site_aliases(sessions, credentials)
    reconcile_periodic_signin_templates(sessions)
    reconcile_signin_schedules(sessions)

    async def scheduler_loop() -> None:
        while True:
            queue.enqueue_due()
            await asyncio.sleep(settings.scheduler_poll_seconds)

    async def worker_loop() -> None:
        while True:
            worked = await execution.run_one()
            if not worked:
                await asyncio.sleep(settings.worker_poll_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await browser_control.start()
        tasks = [asyncio.create_task(scheduler_loop()), asyncio.create_task(worker_loop())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await browser_control.shutdown()

    app = FastAPI(title="AutoSurf", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LanAccessMiddleware, policy=lan_access)
    app.add_middleware(GZipRequestMiddleware)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.lan_access = lan_access
    app.state.registry = registry
    app.state.credentials = credentials
    app.state.automations = automations
    app.state.queue = queue
    app.state.execution = execution
    app.state.browser_control = browser_control
    app.state.cookiecloud = CookieCloudStore(sessions, secrets, credentials)
    app.state.web_credentials = WebCredentialStore(sessions, secrets, credentials)
    app.state.upgrade_guard = threading.Lock()
    app.state.upgrade_process = None
    app.include_router(router)
    app.include_router(cookiecloud_router)
    app.include_router(web_credential_router)
    app.include_router(auth_router)
    app.include_router(management_router)

    management_login = [Depends(require_login)]

    @app.api_route(
        f"{REMOTE_DESKTOP_PREFIX}/",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        dependencies=management_login,
        include_in_schema=False,
    )
    @app.api_route(
        f"{REMOTE_DESKTOP_PREFIX}/{{path:path}}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        dependencies=management_login,
        include_in_schema=False,
    )
    async def browser_remote_http(request: Request, path: str = ""):
        return await browser_control.proxy_http(request, path)

    @app.websocket(f"{REMOTE_DESKTOP_PREFIX}/websockify")
    async def browser_remote_websocket(websocket: WebSocket) -> None:
        client_host = websocket.client.host if websocket.client else None
        if lan_access.lan_only and not is_lan_address(client_host):
            await websocket.close(code=4403, reason="LAN access required")
            return
        username = authenticated_session_username(
            settings,
            websocket.cookies.get(SESSION_COOKIE),
        )
        if not username:
            await websocket.close(code=4401, reason="login required")
            return
        origin = websocket.headers.get("origin")
        host = websocket.headers.get("host")
        if origin and host and origin.split("://", 1)[-1].rstrip("/") != host:
            await websocket.close(code=4403, reason="same origin required")
            return
        await browser_control.proxy_websocket(websocket)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/app")

    @app.get("/docs", include_in_schema=False, dependencies=management_login)
    def docs() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} management")

    @app.get("/openapi.json", include_in_schema=False, dependencies=management_login)
    def openapi_schema() -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


def run() -> None:
    parser = argparse.ArgumentParser(prog="autosurf")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("serve", help="start the AutoSurf service")
    upgrade_parser = subcommands.add_parser("upgrade", help="upgrade a local Git installation")
    upgrade_parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "upgrade":
        result = upgrade(settings, args.repository)
        print(f"AutoSurf upgraded: {result.previous_revision[:12]} -> {result.current_revision[:12]}")
        if result.backup_path:
            print(f"Database backup: {result.backup_path}")
        print("Restart the AutoSurf service to run the new version.")
        return
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
