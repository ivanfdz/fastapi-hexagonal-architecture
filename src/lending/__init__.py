"""A book lending service built as a hexagon.

Package layout, from the inside out:

* ``lending.domain``          -- entities, value objects, business rules. Depends on nothing.
* ``lending.application``     -- use cases and the ports they speak through. Depends on the domain.
* ``lending.infrastructure``  -- adapters and wiring. Depends on both, and nothing depends on it.

See the README for the diagram and the reasoning.
"""

__version__ = "1.0.0"
