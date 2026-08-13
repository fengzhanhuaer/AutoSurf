from __future__ import annotations

import asyncio
import argparse
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from autosurf import __version__
from autosurf.api import cookiecloud_router, router
from autosurf.application.registry import HandlerRegistry
from autosurf.application.services import AutomationService, CredentialService, ExecutionService, QueueService
from autosurf.automations.http_signin import HttpSignInHandler
from autosurf.automations.browser_signin import BrowserSignInHandler
from autosurf.config import Settings, get_settings
from autosurf.infrastructure.cookiecloud import CookieCloudStore
from autosurf.infrastructure.crypto import SecretBox
from autosurf.infrastructure.database import create_session_factory
from autosurf.infrastructure.gzip_request import GZipRequestMiddleware
from autosurf.infrastructure.migrations import upgrade_database
from autosurf.upgrade import upgrade


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    registry = HandlerRegistry()
    registry.register(HttpSignInHandler())
    registry.register(BrowserSignInHandler())
    secrets = SecretBox(settings.secret_key)
    credentials = CredentialService(sessions, secrets)
    automations = AutomationService(sessions, registry)
    queue = QueueService(sessions, settings.execution_lease_seconds)
    execution = ExecutionService(sessions, queue, credentials, registry)

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
        tasks = [asyncio.create_task(scheduler_loop()), asyncio.create_task(worker_loop())]
        yield
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="AutoSurf", version=__version__, lifespan=lifespan)
    app.add_middleware(GZipRequestMiddleware)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.registry = registry
    app.state.credentials = credentials
    app.state.automations = automations
    app.state.queue = queue
    app.state.cookiecloud = CookieCloudStore(sessions, secrets, credentials)
    app.include_router(router)
    app.include_router(cookiecloud_router)

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
