"""The HTTP driving adapter.

Four modules, split by the kind of translation each performs:

* ``schemas``      -- JSON in and out (Pydantic).
* ``dependencies`` -- how a handler obtains a use case.
* ``errors``       -- domain errors to status codes.
* ``routers``      -- URL and verb to use case call.
* ``app``          -- the factory that assembles the above.

Everything in here is replaceable. That claim is the point of the architecture,
and ``tests/application`` backs it up by exercising the same behaviour with no
HTTP involved at all.
"""

from lending.infrastructure.driving.http.app import create_app

__all__ = ["create_app"]
