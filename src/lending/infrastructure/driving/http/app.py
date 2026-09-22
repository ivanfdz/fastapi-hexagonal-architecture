"""The FastAPI application factory.

A factory rather than a module-level ``app = FastAPI()``, because the object that
matters is the wiring, not the framework instance.  ``create_app(settings)`` lets
a test build an app backed by in-memory repositories and a null notifier in one
line, with no environment variables and no patching, while the production entry
point calls ``create_app()`` and gets configuration from the environment.

The lifespan handler is where the two worlds meet: it builds the container on
startup, parks it on ``app.state`` and closes it on shutdown.  That is the only
moment in the whole process when concrete adapters are chosen.

Note what the app knows about lending: nothing.  It registers error handlers and
a router.  All four use cases could be replaced and this file would not change.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from lending import __version__
from lending.infrastructure.config import Settings
from lending.infrastructure.container import build_container
from lending.infrastructure.driving.http.errors import register_exception_handlers
from lending.infrastructure.driving.http.routers import router

__all__ = ["create_app"]

_DESCRIPTION = """
A book lending service built as a hexagon.

The endpoints below are a *driving adapter*: they translate HTTP into use case
calls and back. Every rule they appear to enforce -- the three-loan limit, the
fourteen-day term, the fee for lateness -- is enforced in `lending.domain` and
would apply identically to a CLI or a queue consumer.

Try `POST /loans` with member `M-001`, then call it twice more, then a fourth
time: the 409 comes from `LoanPolicy`, not from this API. Member `M-003` is
suspended, so borrowing as `M-003` is refused for a different reason with a
different error code.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an application. Pass ``settings`` to override the environment."""
    resolved = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Startup: assemble the hexagon. This is the only place adapters are
        # chosen, and it happens exactly once per process.
        container = build_container(resolved)
        app.state.container = container
        try:
            yield
        finally:
            # Shutdown: release whatever the chosen adapters hold open.
            container.close()

    app = FastAPI(
        title=resolved.api_title,
        version=__version__,
        description=_DESCRIPTION,
        root_path=resolved.api_root_path,
        lifespan=lifespan,
        # Tag order controls the layout of /docs; it costs one line and makes the
        # generated page read like documentation instead of a dump.
        openapi_tags=[
            {"name": "loans", "description": "Borrowing and returning."},
            {"name": "catalogue", "description": "Titles and live availability."},
            {"name": "operations", "description": "Health and the active policy."},
        ],
    )

    # Domain errors become HTTP responses here, so no handler needs a try/except.
    register_exception_handlers(app)
    app.include_router(router)
    return app
