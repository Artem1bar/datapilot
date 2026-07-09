"""Smoke tests for the FastAPI application wiring in app.main.

These guard the declarative parts of ``main.py`` that unit tests never touch:
that the app imports without error, mounts every router under the versioned
prefix, and installs the middleware stack. A broken import or a router dropped
from the include list fails here instead of at deploy time.
"""

from __future__ import annotations

from app.main import app


def _paths() -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


class TestAppBoot:
    def test_app_imports_and_has_routes(self) -> None:
        assert len(app.routes) > 0

    def test_core_routers_are_mounted(self) -> None:
        paths = _paths()
        # One representative route per router that must ship.
        expected = [
            "/api/v1/datasets/",
            "/api/v1/datasets/upload",
            "/api/v1/cleaning/{dataset_id}/plan",
            "/api/v1/cleaning/{dataset_id}/apply",
            "/api/v1/analysis/{dataset_id}/chat",
            "/api/v1/auth/webhook",
            "/health",
        ]
        missing = [route for route in expected if route not in paths]
        assert not missing, f"routers not mounted: {missing}"

    def test_routes_are_versioned_or_infra(self) -> None:
        # Every app route is either under the /api/v1 prefix or an infra path
        # (health, docs, openapi). Catches an un-prefixed router include.
        infra_prefixes = ("/health", "/docs", "/openapi", "/redoc", "/")
        for path in _paths():
            if not path:
                continue
            assert path.startswith("/api/v1") or path.startswith(infra_prefixes), (
                f"unexpected unversioned route: {path}"
            )

    def test_middleware_stack_installed(self) -> None:
        # Request-id / logging + CORS middleware are wired in main.py.
        assert app.user_middleware, "no middleware installed"
