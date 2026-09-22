"""A book lending service built as a hexagon.

Package layout, from the inside out:

* ``lending.domain``          -- entities, value objects, business rules. Depends on nothing.
* ``lending.application``     -- use cases and the ports they speak through. Depends on the domain.
* ``lending.infrastructure``  -- adapters and wiring. Depends on both, and nothing depends on it.

See the README for the diagram and the reasoning.
"""

import sys

__version__ = "1.0.0"

# Fail early and legibly on an unsupported interpreter.
#
# Without this, running under Python 3.9 or 3.10 produces
# "ImportError: cannot import name 'StrEnum' from 'enum'" six frames deep inside
# the domain package, which looks like a bug in this repository rather than the
# wrong python on PATH. The most common cause is a shell with conda's ``base``
# environment active, so the message names it.
#
# This module is deliberately written in syntax every Python 3 understands, so
# the check is reached rather than dying at parse time.
_REQUIRED_PYTHON = (3, 12)

if sys.version_info < _REQUIRED_PYTHON:
    raise RuntimeError(
        "lending requires Python {required}+, but this interpreter is {actual} "
        "at {executable}.\n"
        "If you created the project venv, the usual cause is that it is not "
        "active (a conda 'base' prompt shadows it). Try:\n"
        "    source .venv/bin/activate && python examples/swap_adapters.py\n"
        "or call it directly:\n"
        "    .venv/bin/python examples/swap_adapters.py".format(
            required=".".join(str(part) for part in _REQUIRED_PYTHON),
            actual=".".join(str(part) for part in sys.version_info[:3]),
            executable=sys.executable,
        )
    )
