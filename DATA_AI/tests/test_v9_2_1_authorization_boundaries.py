import pytest
from fastapi import HTTPException

from app.security import (
    parse_trusted_roles,
    trusted_actor_context,
    require_any_role,
    enforce_bank_scope,
)


def test_role_claims_normalize_case_and_supported_separators():
    assert parse_trusted_roles(" maker ; Checker, bank_admin ") == {
        "MAKER", "CHECKER", "BANK_ADMIN"
    }


@pytest.mark.parametrize(
    "actor, roles, bank",
    [
        (None, "MAKER", "BANK-A"),
        ("   ", "MAKER", "BANK-A"),
        ("actor", "MAKER", None),
        ("actor", "MAKER", "  "),
    ],
)
def test_trusted_context_rejects_missing_identity_or_bank(actor, roles, bank):
    with pytest.raises(HTTPException) as exc:
        trusted_actor_context(actor, roles, bank)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("actor, bank", [("x" * 161, "BANK-A"), ("actor", "x" * 101)])
def test_trusted_context_rejects_oversized_assertions(actor, bank):
    with pytest.raises(HTTPException) as exc:
        trusted_actor_context(actor, "MAKER", bank)
    assert exc.value.status_code == 400


def test_trusted_context_rejects_control_characters():
    with pytest.raises(HTTPException) as exc:
        trusted_actor_context("actor\nforged", "MAKER", "BANK-A")
    assert exc.value.status_code == 400


def test_missing_role_does_not_grant_access():
    with pytest.raises(HTTPException) as exc:
        require_any_role(set(), {"MAKER", "CHECKER"}, message="Denied")
    assert exc.value.status_code == 403


def test_unrelated_role_does_not_grant_access():
    with pytest.raises(HTTPException) as exc:
        require_any_role({"CUSTOMER"}, {"MAKER", "CHECKER"}, message="Denied")
    assert exc.value.status_code == 403


def test_cross_bank_resource_is_hidden_as_not_found():
    with pytest.raises(HTTPException) as exc:
        enforce_bank_scope("BANK-B", "BANK-A", {"MAKER"})
    assert exc.value.status_code == 404


def test_same_bank_resource_is_allowed():
    assert enforce_bank_scope("BANK-A", "BANK-A", {"MAKER"}) is None


def test_system_admin_may_cross_bank_only_with_explicit_role():
    assert enforce_bank_scope("BANK-B", "BANK-A", {"SYSTEM_ADMIN"}) is None


def test_empty_bank_scope_does_not_grant_non_admin_access():
    with pytest.raises(HTTPException) as exc:
        enforce_bank_scope("BANK-A", None, {"MAKER"})
    assert exc.value.status_code == 404
