from __future__ import annotations

from company_os.context import (
    COMPANY_OPERATING_POLICIES,
    POLICY_CATALOG_VERSION,
    compile_l0_company_context,
    validate_policy_catalog,
)
from company_os.foundation import FoundationService


def test_first_pass_excellence_is_canonical_and_non_generic():
    validate_policy_catalog()

    policy = next(
        item
        for item in COMPANY_OPERATING_POLICIES
        if item.policy_id == "engineering.first_pass_excellence"
    )

    assert POLICY_CATALOG_VERSION == "1.1.0"
    assert policy.priority == 35
    assert policy.domain == "engineering_quality"

    required_terms = (
        "actual current main-branch source",
        "callers",
        "acceptance criteria",
        "one consolidated end-to-end feature batch",
        "repeated replacement",
        "generic demos",
        "security",
        "data integrity",
        "failure-cleanup",
        "complete available regression suite",
        "exact commit",
    )

    for term in required_terms:
        assert term in policy.rule

    assert "not yet have a complete independent" in policy.limitation


def test_l0_context_includes_the_complete_first_pass_policy(tmp_path):
    root = tmp_path / "AI-Dev-Company"
    root.mkdir()

    foundation = FoundationService(root)
    foundation.bootstrap(
        owner_name="Test Owner",
        owner_email="owner@example.com",
        actor="test-suite",
        reason="First-pass engineering policy test",
    )

    packet = compile_l0_company_context(foundation)

    catalog = packet["operating_policies"]
    policy = next(
        item
        for item in catalog["policies"]
        if item["policy_id"] == "engineering.first_pass_excellence"
    )

    assert catalog["catalog_version"] == "1.1.0"
    assert catalog["count"] == 10
    assert policy["priority"] == 35
    assert policy["enforcement_state"] == (
        "documented_l0_company_policy_and_regression_tests"
    )
    assert "repeated replacement" in policy["rule"]
    assert "not yet have a complete independent" in policy["limitation"]


def test_policy_compilation_does_not_write_project_memory(tmp_path):
    root = tmp_path / "AI-Dev-Company"
    root.mkdir()

    foundation = FoundationService(root)
    foundation.bootstrap(
        owner_name="Test Owner",
        owner_email="owner@example.com",
        actor="test-suite",
        reason="Read-only policy compilation test",
    )

    before = foundation.memory.list_events(limit=200)

    compile_l0_company_context(foundation)

    after = foundation.memory.list_events(limit=200)
    assert after == before
