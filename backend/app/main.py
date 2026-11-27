# Copyright (c) 2026 tbaur
#
# Licensed under the Apache License, Version 2.0
# See LICENSE file for full license text

"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import PRODUCT_NAME, __version__
from app.api.errors import AppError
from app.api.routes import router
from app.auth import REQUEST_HEADER
from app.bluos.client import BluOSClient
from app.config import Settings, get_settings
from app.discovery.service import DiscoveryService
from app.exit_signals import on_exit_signal
from app.logging import configure_logging, request_id_var
from app.middleware import RequestContextMiddleware
from app.services.events import EventBus
from app.services.poller import StatusPoller
from app.state import AppState

logger = logging.getLogger(__name__)


def _resolve_static_dir(settings: Settings) -> Path | None:
    """The built UI to serve, or None for an API-only server.

    Only an explicit RESONANCE_STATIC_DIR serves a UI. Falling back to the
    repo's frontend/dist would make the development API serve whatever build
    is left there, which is usually older than the code.
    """
    if settings.static_dir:
        return Path(settings.static_dir)
    return None


# Codes for errors the router raises itself, so the UI can tell them apart.
_STATUS_CODES = {404: "not_found", 405: "method_not_allowed"}


def _error_body(code: str, message: str, request_id: str | None = None) -> dict[str, str]:
    return {
        "error": code,
        "message": message,
        "code": code,
        "request_id": request_id if request_id is not None else request_id_var.get("-"),
    }


def _ui_origin(settings: Settings) -> str:
    origins = settings.cors_origin_list()
    return origins[0] if origins else "http://127.0.0.1:8765"


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def warn_if_open_to_network(settings: Settings) -> bool:
    """Log a warning when a non-loopback bind has no API token. Returns True if warned.

    Reboot and stop apply to every discovered player, so an untokened LAN bind
    hands that to any host on the network. Documented as allowed, never silent.
    """
    if settings.host in _LOOPBACK_HOSTS or settings.api_token.strip():
        return False
    logger.warning(
        "insecure_bind host=%s — RESONANCE_API_TOKEN is empty, so every control endpoint "
        "(including fleet reboot) is open to the LAN. Set RESONANCE_API_TOKEN, or bind "
        "127.0.0.1. See docs/CONFIGURATION.md 'Network exposure'.",
        settings.host,
    )
    return True


def _api_home_html(settings: Settings) -> str:
    """Small landing page when the SPA dist is not mounted (typical local API-only)."""
    ui = html.escape(_ui_origin(settings), quote=True)
    docs_link = (
        '<a class="btn btn-quiet" href="/api/docs">API docs</a>'
        if settings.openapi_enabled()
        else ""
    )
    # Tokens / type / chrome mirror frontend/src/styles/global.css.
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{PRODUCT_NAME}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0c1014;
      --bg-raised: #141a21;
      --chrome: #1b2330;
      --border: #2a3545;
      --text: #e8eef6;
      --muted: #8b9bb0;
      --accent: #3d9cf0;
      --accent-dim: #2a6fad;
      --font-display: "Avenir Next", "Futura", "Century Gothic", sans-serif;
      --font-body: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
      --font-mono: "SF Mono", Menlo, Consolas, monospace;
      --radius: 14px;
      --shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; }}
    body {{
      font-family: var(--font-body);
      background:
        radial-gradient(1200px 600px at 10% -10%, rgba(61, 156, 240, 0.16), transparent 55%),
        radial-gradient(900px 500px at 90% 0%, rgba(62, 207, 142, 0.08), transparent 50%),
        linear-gradient(180deg, #0a0e12 0%, var(--bg) 40%, #0b1218 100%);
      color: var(--text);
    }}
    a {{ color: inherit; text-decoration: none; }}
    .app-shell {{
      max-width: 42rem;
      margin: 0 auto;
      padding: 28px 24px 64px;
    }}
    .app-header {{ margin-bottom: 28px; }}
    .brand {{
      font-family: var(--font-display);
      font-size: clamp(2rem, 4vw, 3rem);
      font-weight: 700;
      letter-spacing: -0.04em;
      margin: 0;
    }}
    .brand-sub {{
      margin: 8px 0 0;
      color: var(--muted);
      max-width: 42ch;
    }}
    .panel {{
      padding: 14px 16px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(27, 35, 48, 0.95), rgba(16, 22, 30, 0.92));
      box-shadow: var(--shadow);
    }}
    .panel-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}
    .btn {{
      appearance: none;
      display: inline-block;
      border: 1px solid var(--border);
      background: var(--chrome);
      color: var(--text);
      border-radius: 10px;
      padding: 10px 14px;
      cursor: pointer;
      transition: background 120ms ease, border-color 120ms ease, filter 120ms ease;
    }}
    .btn:hover {{ background: #243041; border-color: #3a4a60; }}
    .btn-primary {{
      background: linear-gradient(180deg, var(--accent), var(--accent-dim));
      border-color: transparent;
      color: #041018;
      font-weight: 600;
    }}
    .btn-primary:hover {{ filter: brightness(1.06); }}
    .btn-quiet {{
      border-color: transparent;
      background: transparent;
      color: var(--muted);
    }}
    .btn-quiet:hover {{
      border-color: var(--border);
      background: var(--chrome);
      color: var(--text);
    }}
    .meta {{
      margin: 16px 0 0;
      color: var(--muted);
      font-size: 0.78rem;
      font-family: var(--font-mono);
    }}
  </style>
</head>
<body>
  <div class="app-shell">
    <header class="app-header">
      <h1 class="brand">{PRODUCT_NAME}</h1>
      <p class="brand-sub">
        API is up. In local development the React UI runs separately.
        Open it to control your BluOS players.
      </p>
    </header>
    <section class="panel">
      <div class="panel-actions">
        <a class="btn btn-primary" href="{ui}/">Open {PRODUCT_NAME}</a>
        <a class="btn" href="/api/v1/healthz">Health</a>
        <a class="btn" href="/api/v1/version">Version</a>
        {docs_link}
      </div>
      <p class="meta">v{__version__} · API on this port · UI at {ui}</p>
    </section>
  </div>
</body>
</html>
"""


_WRITE_METHODS = frozenset({"post", "put", "patch", "delete"})


class ResonanceAPI(FastAPI):
    """FastAPI whose schema declares the header every write must send.

    The middleware refuses a write without ``X-Resonance-Request: 1``. Declared
    here with that default, the API docs page sends it on "Try it out".
    """

    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema:
            return self.openapi_schema
        schema = get_openapi(title=self.title, version=self.version, routes=self.routes)
        header = {
            "name": REQUEST_HEADER.decode("ascii"),
            "in": "header",
            "required": True,
            "description": "Must be 1 on every request that changes state.",
            "schema": {"type": "string", "enum": ["1"], "default": "1"},
        }
        for path_item in schema.get("paths", {}).values():
            for method, operation in path_item.items():
                if method in _WRITE_METHODS:
                    operation.setdefault("parameters", []).append(dict(header))
        self.openapi_schema = schema
        return schema


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    warn_if_open_to_network(settings)
    client = BluOSClient(settings)
    events = EventBus(max_queue_size=settings.sse_queue_size)
    discovery = DiscoveryService(settings, client)
    poller = StatusPoller(settings, discovery, client, events)
    app.state.app_state = AppState(
        settings=settings,
        client=client,
        discovery=discovery,
        events=events,
        poller=poller,
    )
    discovery.mdns.start()
    # Discover first, then start the poller. Started earlier, the poller finds
    # no fresh result and runs a second full discovery right behind this one.
    try:
        await discovery.refresh()
    except Exception:  # noqa: BLE001 — startup continues; the poller retries discovery
        logger.exception("initial_discovery_failed")
    poller.start()
    logger.info("app_started host=%s port=%s", settings.host, settings.port)
    loop = asyncio.get_running_loop()
    restore_signals = on_exit_signal(lambda: loop.call_soon_threadsafe(events.close))
    try:
        yield
    finally:
        restore_signals()
        await poller.stop()
        discovery.mdns.stop()
        await client.aclose()
        logger.info("app_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = ResonanceAPI(
        title=PRODUCT_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.openapi_enabled() else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.openapi_enabled() else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        detail = (
            exc.detail if isinstance(exc.detail, dict) else _error_body("error", str(exc.detail))
        )
        return JSONResponse(status_code=exc.status_code, content=detail)

    # Starlette's class, not FastAPI's subclass: the router raises the base class
    # for an unknown path (404) or method (405), and those need the envelope too.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        headers = getattr(exc, "headers", None)
        detail: object = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail, headers=headers)
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, str(detail)),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Same envelope as every other error, so the UI can show the message and
        # request id. Only the field locations and messages go back, never the input.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error.get('loc', ()) if part != 'body')}: "
            f"{error.get('msg', 'invalid')}"
            for error in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", problems or "Request is not valid"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error")
        request_id = getattr(request.state, "request_id", "-")
        return JSONResponse(
            status_code=500,
            content=_error_body("internal_error", "An unexpected error occurred", request_id),
        )

    app.include_router(router)

    @app.get("/health")
    async def health_alias() -> RedirectResponse:
        """Ops footgun guard: never serve SPA HTML for /health."""
        return RedirectResponse(url="/api/v1/healthz", status_code=307)

    static_dir = _resolve_static_dir(settings)
    index_html = (
        static_dir / "index.html" if static_dir is not None and static_dir.is_dir() else None
    )

    @app.get("/", response_model=None)
    async def root() -> FileResponse | HTMLResponse:
        """Serve the SPA when built; otherwise a small API home page."""
        if index_html is not None and index_html.is_file():
            return FileResponse(index_html)
        return HTMLResponse(_api_home_html(settings))

    if static_dir is not None and static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        def _public_file(name: str, media_type: str | None = None) -> FileResponse | JSONResponse:
            # `name` is a fixed public filename. The request path must not choose it.
            path = static_dir / name
            if path.is_file():
                return FileResponse(path, media_type=media_type)
            return JSONResponse(status_code=404, content=_error_body("not_found", "Not found"))

        @app.get("/favicon.ico", include_in_schema=False, response_model=None)
        async def favicon_ico() -> FileResponse | JSONResponse:
            return _public_file("favicon.ico")

        @app.get("/favicon.svg", include_in_schema=False, response_model=None)
        async def favicon_svg() -> FileResponse | JSONResponse:
            return _public_file("favicon.svg")

        @app.get("/apple-touch-icon.png", include_in_schema=False, response_model=None)
        async def apple_touch_icon() -> FileResponse | JSONResponse:
            return _public_file("apple-touch-icon.png")

        @app.get("/manifest.webmanifest", include_in_schema=False, response_model=None)
        async def web_manifest() -> FileResponse | JSONResponse:
            return _public_file("manifest.webmanifest", media_type="application/manifest+json")

        @app.get("/{full_path:path}", response_model=None)
        async def spa_fallback(full_path: str) -> FileResponse | JSONResponse:
            if full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404, content=_error_body("not_found", "No such API route")
                )
            if index_html is not None and index_html.is_file():
                return FileResponse(index_html)
            return JSONResponse(
                status_code=404,
                content=_error_body("ui_not_built", "The UI has not been built"),
            )

    return app


app = create_app()
