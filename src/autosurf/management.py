from importlib.resources import files

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response

from autosurf.api import require_login


management_router = APIRouter(dependencies=[Depends(require_login)], include_in_schema=False)


def _asset(name: str) -> str:
    return files("autosurf.web").joinpath(name).read_text(encoding="utf-8")


@management_router.get("/app", response_class=HTMLResponse)
def management_app() -> str:
    return _asset("admin.html")


@management_router.get("/assets/admin.css")
def management_css() -> Response:
    return Response(_asset("admin.css"), media_type="text/css")


@management_router.get("/assets/admin.js")
def management_javascript() -> Response:
    return Response(_asset("admin.js"), media_type="text/javascript")
