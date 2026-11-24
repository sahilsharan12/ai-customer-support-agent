from datetime import date, timedelta

import pytest

from backend import llm


@pytest.mark.parametrize(
    ("days_ago", "evidence", "expected_error"),
    [(8, "demo-photo", "expired"), (2, None, "evidence reference")],
)
def test_prepare_return_rejects_ineligible_orders(monkeypatch, days_ago, evidence, expected_error):
    order = {"order": {
        "order_id": "test-order",
        "customer_unique_id": "test-profile",
        "order_status": "delivered",
        "order_delivered_customer_date": (date.today() - timedelta(days=days_ago)).isoformat(),
    }}
    monkeypatch.setattr(llm, "get_order_details", lambda order_id: order)
    monkeypatch.setattr(llm, "save_pending_action", lambda **kwargs: pytest.fail("Saved an ineligible draft"))
    result = llm.execute_tool(
        "prepare_return_request",
        {"order_id": "test-order", "reason": "Damaged product", "evidence_reference": evidence},
        authenticated_customer_id="test-profile",
        conversation_id="test-conversation",
        authenticated_user_id="test-account",
    )
    assert result["status"] == "NOT_ELIGIBLE"
    assert any(expected_error in error.lower() for error in result["eligibility"]["errors"])
