"""Configuration, read from the environment with pydantic-settings.

This is the second place Pydantic appears, and for the same reason as the first:
it sits on a boundary where untrusted text arrives.  Environment variables are
strings typed by a human into a shell or a deployment manifest, so they get
parsed and validated before anything else sees them.  ``late_fee_per_day`` in
particular becomes a ``Decimal`` here, once, instead of being re-parsed by every
caller that needs it.

Note which values live here: the *choice* of adapter, the connection details, and
the numeric thresholds of the lending policy.  Note which do not: anything about
how those thresholds are applied.  The domain owns the meaning of
``max_active_loans_per_member``; the environment only chooses the number.

Every field has a usable default, so ``python -m lending`` and ``pytest`` work on
a fresh clone with no ``.env`` file.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    """All external configuration, in one validated object.

    Read with the ``LENDING_`` prefix, so ``LENDING_REPOSITORY=sqlite`` selects
    the SQLite adapter.
    """

    model_config = SettingsConfigDict(
        env_prefix="LENDING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Adapter selection. The literal types mean a typo fails at startup with
    #    a clear message rather than falling through to a surprising default.
    repository: Literal["memory", "sqlite"] = Field(
        default="memory",
        description="Which repository adapter to inject at startup.",
    )
    notifier: Literal["logging", "console", "null"] = Field(
        default="logging",
        description="Which notification adapter to inject at startup.",
    )
    sqlite_path: Path = Field(
        default=Path("lending.db"),
        description="Database file used when repository=sqlite. ':memory:' also works.",
    )
    seed_demo_data: bool = Field(
        default=True,
        description="Insert a small catalogue and three members on startup.",
    )

    # -- Lending policy thresholds.
    loan_period_days: int = Field(default=14, ge=1, le=365)
    max_active_loans_per_member: int = Field(default=3, ge=1, le=50)
    late_fee_per_day: Decimal = Field(default=Decimal("0.50"), ge=0, le=1000)

    # -- HTTP surface.
    api_title: str = "Lending API"
    api_root_path: str = ""
