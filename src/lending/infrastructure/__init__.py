"""The outer ring: adapters, configuration and wiring.

Everything the application needs from the world, and everything the world needs
to reach the application:

* ``driven/``    -- implementations of the driven ports (storage, notifications, clock).
* ``driving/``   -- entry points that call the driving ports (the HTTP API).
* ``config``     -- environment parsing.
* ``container``  -- the composition root, where concrete types are chosen.
* ``seed``       -- demo data, written through ports so it works on any adapter.

This layer is allowed to import the domain and the application. The reverse never
happens, and that single rule is what the whole structure is protecting.
"""

from lending.infrastructure.config import Settings
from lending.infrastructure.container import Container, build_container

__all__ = ["Container", "Settings", "build_container"]
