from __future__ import annotations

import asyncio
import argparse
from contextlib import asynccontextmanager
from pathlib import Path
import subprocess
import sys
import threading

import uvicorn
from fastapi import Depends, FastAPI, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from autosurf import __version__
from autosurf.access import LanAccessMiddleware, LanAccessPolicy
from autosurf.api import (
    auth_router,
    require_login,
    router,
)
from autosurf.application.registry import HandlerRegistry
from autosurf.application.services import (
    AutomationService,
    ExecutionService,
    QueueService,
    reconcile_periodic_signin_templates,
    reconcile_pt_profile_refresh_defaults,
    reconcile_signin_schedules,
)
from autosurf.browser_control import (
    BrowserControlService,
    BrowserDisplaySettings,
    CdpAutomationProvider,
)
from autosurf.automations.browser_session import register_shared_browser_provider
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
    YemaPtAdapter,
    ZhuqueAdapter,
)
from autosurf.config import Settings, get_settings
from autosurf.infrastructure.database import create_session_factory
from autosurf.infrastructure.migrations import upgrade_database
from autosurf.management import management_router
from autosurf.upgrade import upgrade


def build_handler_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register(HttpSignInHandler())
    registry.register(BrowserSignInHandler())
    registry.register(PtSignInHandler([
        FiftyTwoPtAdapter(), ChdBitsAdapter(), BtschoolAdapter(), OpenCdAdapter(),
        OshenPtAdapter(), SoulVoiceAdapter(),
        TjuptAdapter(), RousiAdapter(),
        MTeamAdapter(), SunnyPtAdapter(), YemaPtAdapter(), ZhuqueAdapter(),
    ]))
    return registry


async def run_worker(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    registry = build_handler_registry()
    queue = QueueService(sessions, settings.execution_lease_seconds)
    execution = ExecutionService(sessions, queue, registry)
    reconcile_periodic_signin_templates(sessions)
    reconcile_pt_profile_refresh_defaults(sessions)
    reconcile_signin_schedules(sessions)
    register_shared_browser_provider(CdpAutomationProvider())

    async def scheduler_loop() -> None:
        while True:
            queue.enqueue_due()
            await asyncio.sleep(settings.scheduler_poll_seconds)

    async def worker_loop() -> None:
        while True:
            worked = await execution.run_one()
            if not worked:
                await asyncio.sleep(settings.worker_poll_seconds)

    tasks = [asyncio.create_task(scheduler_loop()), asyncio.create_task(worker_loop())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        register_shared_browser_provider(None)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    lan_access = LanAccessPolicy(sessions)
    registry = build_handler_registry()
    automations = AutomationService(sessions, registry)
    queue = QueueService(sessions, settings.execution_lease_seconds)
    execution = ExecutionService(sessions, queue, registry)
    browser_control = BrowserControlService(
        display_settings=BrowserDisplaySettings(sessions),
    )
    reconcile_periodic_signin_templates(sessions)
    reconcile_pt_profile_refresh_defaults(sessions)
    reconcile_signin_schedules(sessions)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await browser_control.start()
        try:
            yield
        finally:
            await browser_control.shutdown()

    app = FastAPI(title="AutoSurf", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LanAccessMiddleware, policy=lan_access)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.lan_access = lan_access
    app.state.registry = registry
    app.state.automations = automations
    app.state.queue = queue
    app.state.execution = execution
    app.state.browser_control = browser_control
    app.state.upgrade_guard = threading.Lock()
    app.state.upgrade_process = None
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(management_router)

    management_login = [Depends(require_login)]

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

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    return app


def run() -> None:
    parser = argparse.ArgumentParser(prog="autosurf")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("serve", help="start the AutoSurf service")
    subcommands.add_parser("worker", help="run the scheduler and automation worker")
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
    if args.command == "worker":
        try:
            asyncio.run(run_worker(settings))
        except KeyboardInterrupt:
            pass
        return

    app = create_app(settings)
    worker = subprocess.Popen(
        [sys.executable, "-m", "autosurf.main", "worker"],
        stdin=subprocess.DEVNULL,
    )
    try:
        uvicorn.run(app, host=settings.host, port=settings.port)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)


if __name__ == "__main__":
    run()
