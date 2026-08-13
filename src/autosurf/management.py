from importlib.resources import files

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from autosurf.api import SESSION_COOKIE, _session_username

management_router = APIRouter(include_in_schema=False)


def _asset(name: str) -> str:
    return files("autosurf.web").joinpath(name).read_text(encoding="utf-8")


def _has_session(request: Request) -> bool:
    return _session_username(
        request.app.state.settings,
        request.cookies.get(SESSION_COOKIE),
    ) is not None


@management_router.get("/login", response_class=HTMLResponse)
def management_login(request: Request) -> Response:
    if _has_session(request):
        return RedirectResponse(url="/app")
    return HTMLResponse(_asset("login.html"))


@management_router.get("/app", response_class=HTMLResponse)
def management_app(request: Request) -> Response:
    if not _has_session(request):
        return RedirectResponse(url="/login?next=/app")
    return HTMLResponse(_asset("admin.html"))


@management_router.get("/assets/admin.css")
def management_css() -> Response:
    return Response(_asset("admin.css"), media_type="text/css")


@management_router.get("/assets/admin.js")
def management_javascript() -> Response:
    return Response(_asset("admin.js"), media_type="text/javascript")


@management_router.get("/assets/login.css")
def login_css() -> Response:
    return Response(_asset("login.css"), media_type="text/css")


@management_router.get("/assets/login.js")
def login_javascript() -> Response:
    return Response(_asset("login.js"), media_type="text/javascript")
