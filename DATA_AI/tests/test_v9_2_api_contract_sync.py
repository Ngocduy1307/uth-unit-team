"""V9.2 API contract regression checks.

These checks deliberately compare the checked-in OpenAPI artifact with the
FastAPI application instead of maintaining a second, hand-written route list.
"""
import json
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_FILE = ROOT / "contracts" / "data-ai-openapi.json"


def test_checked_in_openapi_matches_runtime_application():
    saved = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    assert saved == app.openapi(), (
        "OpenAPI artifact is stale. Regenerate contracts/data-ai-openapi.json "
        "from app.main:app and review the API contract change."
    )


def test_every_internal_api_operation_declares_service_token_header():
    spec = app.openapi()
    api_operations = [
        (path, method, operation)
        for path, methods in spec["paths"].items()
        if path.startswith("/api/")
        for method, operation in methods.items()
    ]
    assert api_operations, "Expected at least one /api/ operation"

    for path, method, operation in api_operations:
        headers = {
            parameter["name"].lower()
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        assert "x-internal-service-token" in headers, (
            f"{method.upper()} {path} is missing the internal service token "
            "from its published contract."
        )
        assert "x-service-assertion" in headers, (
            f"{method.upper()} {path} is missing the signed service assertion "
            "from its published contract."
        )


def test_api_paths_remain_versioned():
    spec = app.openapi()
    unversioned = [
        path for path in spec["paths"]
        if path.startswith("/api/") and not path.startswith("/api/v1/")
    ]
    assert not unversioned, f"Unversioned API paths found: {unversioned}"
