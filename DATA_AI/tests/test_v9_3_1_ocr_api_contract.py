import pytest
from fastapi import HTTPException
from app.main import app, ocr_governance_catalog


def test_ocr_catalog_endpoint_is_read_only_and_present_in_openapi():
    schema = app.openapi()
    assert "/api/v1/admin/ocr/catalog" in schema["paths"]
    operation = schema["paths"]["/api/v1/admin/ocr/catalog"]["get"]
    assert "ocr-governance" in operation["tags"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/OCRCatalogOut")


def test_ocr_catalog_endpoint_uses_internal_service_auth_dependency():
    route = next(r for r in app.routes if getattr(r, "path", None) == "/api/v1/admin/ocr/catalog")
    assert route.methods == {"GET"}
    assert route.dependencies


def test_ocr_catalog_endpoint_rejects_missing_trusted_context():
    with pytest.raises(HTTPException) as error:
        ocr_governance_catalog(None, None, None)
    assert error.value.status_code == 401


def test_ocr_catalog_endpoint_rejects_unprivileged_actor():
    with pytest.raises(HTTPException) as error:
        ocr_governance_catalog("backend-user", "BANK_STAFF", "BANK_A")
    assert error.value.status_code == 403


def test_ocr_catalog_endpoint_accepts_scoped_admin_and_discloses_pending_approval():
    payload = ocr_governance_catalog("backend-admin", "BANK_ADMIN", "BANK_A")
    assert payload["bank_approval_status"] == "PENDING_BANK_PO_SIGNOFF"
    assert payload["field_count"] == 20
