"""Run the API with ``python -m lending``.

A convenience wrapper so a fresh clone is one command from a browsable API. It
reads the same ``Settings`` as everything else, so ``LENDING_REPOSITORY=sqlite
python -m lending`` switches persistence without touching code.

Note that this module owns no application logic. It picks a port, points uvicorn
at the factory, and gets out of the way.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "lending.asgi:app",
        host=os.environ.get("LENDING_HOST", "127.0.0.1"),
        port=int(os.environ.get("LENDING_PORT", "8000")),
        reload=os.environ.get("LENDING_RELOAD", "false").lower() == "true",
    )


if __name__ == "__main__":
    main()
