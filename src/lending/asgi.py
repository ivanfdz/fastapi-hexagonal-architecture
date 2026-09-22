"""ASGI entry point.

    uvicorn lending.asgi:app --reload

The module-level ``app`` exists purely so process managers have something to
import. All it does is call the factory with configuration from the environment.
"""

from lending.infrastructure.driving.http.app import create_app

app = create_app()
