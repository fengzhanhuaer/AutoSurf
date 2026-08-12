from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI

from autosurf import __version__
from autosurf.api import cookiecloud_router, router
from autosurf.application.registry import HandlerRegistry
from autosurf.application.services import AutomationService, CredentialService, ExecutionService, QueueService
from autosurf.automations.http_signin import HttpSignInHandler
from autosurf.config import Settings, get_settings
from autosurf.infrastructure.cookiecloud import CookieCloudStore
from autosurf.infrastructure.crypto import SecretBox
from autosurf.infrastructure.database import create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    sessions = create_session_factory(settings.database_url)
    registry = HandlerRegistry()
    registry.register(HttpSignInHandler())
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
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.registry = registry
    app.state.credentials = credentials
    app.state.automations = automations
    app.state.queue = queue
    app.state.cookiecloud = CookieCloudStore(sessions)
    app.include_router(router)
    app.include_router(cookiecloud_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


def run() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()

