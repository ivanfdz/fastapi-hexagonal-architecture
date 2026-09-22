"""Tests for the architecture itself.

An architecture that is only described in a README decays, because nothing stops
the first ``from fastapi import HTTPException`` that gets added to a use case
under deadline pressure.  These tests make the dependency rule executable: they
parse the import statements of every module in the core and fail the build if one
points the wrong way.

Cheap to write, and they turn a diagram into a constraint.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterator

import pytest

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src" / "lending"

# Anything installed from PyPI that the core must not touch. Standard library is
# fine everywhere; the point is not "no imports", it is "no imports that tie a
# business rule to a delivery mechanism or a storage engine".
FORBIDDEN_IN_CORE = {
    "fastapi",
    "starlette",
    "uvicorn",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "sqlite3",
    "httpx",
    "requests",
    "boto3",
}


def imported_modules(path: Path) -> Iterator[str]:
    """Yield the top-level module name of every import in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            # ``level > 0`` means a relative import, which cannot leave the package.
            if node.level == 0 and node.module:
                yield node.module.split(".")[0]


def qualified_imports(path: Path) -> Iterator[str]:
    """Yield the full dotted name of every ``lending.*`` import in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.startswith("lending"):
                yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("lending"):
                    yield alias.name


def modules_in(package: str) -> list[Path]:
    paths = sorted((SOURCE_ROOT / package).rglob("*.py"))
    assert paths, f"no modules found under {package}; the layout has moved"
    return paths


def relative(path: Path) -> str:
    return str(path.relative_to(SOURCE_ROOT.parent.parent))


class TestDomainIsIndependent:
    """The innermost layer depends on nothing but the standard library."""

    @pytest.mark.parametrize("module", modules_in("domain"), ids=relative)
    def test_imports_no_third_party_package(self, module: Path) -> None:
        offenders = FORBIDDEN_IN_CORE & set(imported_modules(module))
        assert not offenders, f"{relative(module)} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module", modules_in("domain"), ids=relative)
    def test_imports_only_from_the_domain(self, module: Path) -> None:
        for imported in qualified_imports(module):
            assert imported.startswith("lending.domain"), (
                f"{relative(module)} imports {imported}; the domain may not depend "
                "on the application or on infrastructure"
            )


class TestApplicationDependsOnlyOnTheDomain:
    """The application orchestrates the domain and speaks through ports."""

    @pytest.mark.parametrize("module", modules_in("application"), ids=relative)
    def test_imports_no_framework_or_driver(self, module: Path) -> None:
        offenders = FORBIDDEN_IN_CORE & set(imported_modules(module))
        assert not offenders, f"{relative(module)} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module", modules_in("application"), ids=relative)
    def test_never_imports_infrastructure(self, module: Path) -> None:
        for imported in qualified_imports(module):
            assert not imported.startswith("lending.infrastructure"), (
                f"{relative(module)} imports {imported}; a use case must receive "
                "adapters through its constructor, never import one"
            )


class TestAdaptersAreIsolatedFromEachOther:
    def test_driven_adapters_do_not_import_the_http_adapter(self) -> None:
        for module in modules_in("infrastructure/driven"):
            for imported in qualified_imports(module):
                assert "driving" not in imported, f"{relative(module)} imports {imported}"

    def test_the_http_adapter_does_not_import_a_repository_implementation(self) -> None:
        # Route handlers and schemas receive ports. Only the composition root is
        # allowed to name a concrete repository, and it lives outside this folder.
        for module in modules_in("infrastructure/driving"):
            for imported in qualified_imports(module):
                assert not imported.startswith("lending.infrastructure.driven"), (
                    f"{relative(module)} imports {imported}; choosing an adapter is "
                    "the composition root's job"
                )


class TestTheCoreRunsWithoutTheFramework:
    def test_importing_the_domain_and_application_loads_no_web_framework(self) -> None:
        """The strongest available form of the claim.

        A subprocess imports the entire core and then inspects ``sys.modules``. If
        FastAPI or Pydantic were reachable through any transitive import, they
        would show up here.
        """
        import subprocess

        script = (
            "import sys;"
            "import lending.domain, lending.application;"
            "loaded = sorted(m for m in sys.modules"
            " if m.split('.')[0] in {'fastapi', 'starlette', 'pydantic',"
            " 'pydantic_settings', 'sqlite3', 'uvicorn'});"
            "print(','.join(loaded))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=SOURCE_ROOT.parent,
            check=True,
        )
        assert result.stdout.strip() == "", f"core pulled in: {result.stdout.strip()}"
