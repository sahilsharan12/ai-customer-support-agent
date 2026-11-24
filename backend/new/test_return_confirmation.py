from uuid import uuid4

import pytest

from backend import llm


def test_unconfirmed_or_replaced_draft_cannot_be_submitted(monkeypatch):
    reference = str(uuid4())
    draft = llm.format_return_confirmation({
        "action_id": reference, "order_id": "test-order", "reason": "Changed my mind"
    })
    monkeypatch.setattr(llm, "get_pending_action", lambda **kwargs: {"action_id": str(uuid4())})
    monkeypatch.setattr(llm, "create_return_request", lambda **kwargs: pytest.fail("Created an unconfirmed return"))

    for message, error in [("How long will it take?", "required"), ("confirm", "different return draft")]:
        result = llm.execute_tool(
            "create_return_request", {},
            conversation_history=[{"role": "assistant", "content": draft}, {"role": "user", "content": message}],
            authenticated_customer_id="test-profile",
            conversation_id="test-conversation",
            authenticated_user_id="test-account",
        )
        assert not result["success"]
        assert error in result["error"]
