import pytest
import requests

from backend import llm
from backend.guardrails import injection_signal, mask_text
from backend.observability import assistant_metrics


def test_masking_preserves_valid_order_and_date():
    message = "demo-order-1001 arrived on 2026-11-24. Email sample@example.test. CVV: 457. 4111111111111111."
    clean = mask_text(message)
    assert "demo-order-1001" in clean and "2026-11-24" in clean
    assert "sample@example.test" not in clean and "457" not in clean and "4111111111111111" not in clean
    assert not injection_signal("Ignore my last order number. It was incorrect.")


def test_tool_limits_and_private_fields(monkeypatch):
    calls = [
        {"function": {"name": "issue_refund", "arguments": {}}},
        {"function": {"name": "get_order_details", "arguments": {"order_id": "demo-order-1001", "user_id": "other"}}},
        {"function": {"name": "get_order_details", "arguments": {"order_id": "demo-order-1001"}}},
    ]
    arguments = []

    def execute(name, args, *rest):
        arguments.append(args)
        return {"order": {"customer_unique_id": "profile-identity", "email": "test@example.test"}, "summary": "paid"}

    monkeypatch.setattr(llm, "execute_tool", execute)
    messages, draft = llm.run_tool_calls(calls, llm.tool_definitions({"get_order_details"}), [], "profile", "conv", "user")
    assert draft is None and arguments == [{"order_id": "demo-order-1001"}]
    assert len(messages) == 3
    assert "Invalid tool arguments" in messages[1]["content"]
    assert "profile-identity" not in messages[2]["content"] and "test@example.test" not in messages[2]["content"]


def test_model_retries_connection_error_and_tracks_usage(monkeypatch):
    calls = []

    class Reply:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "Hello"}, "prompt_eval_count": 7, "eval_count": 2}

    def post(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise requests.ConnectionError("temporary error")
        return Reply()

    before = assistant_metrics()
    monkeypatch.setattr(llm.requests, "post", post)
    assert llm.call_ollama([{"role": "user", "content": "Hi"}], include_tools=False)["content"] == "Hello"
    after = assistant_metrics()
    assert len(calls) == 2
    assert after["model_retries"] - before.get("model_retries", 0) == 1
    assert after["prompt_tokens"] - before.get("prompt_tokens", 0) == 7


def test_timeout_does_not_repeat_a_long_model_request(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout

    before = assistant_metrics()
    monkeypatch.setattr(llm.requests, "post", timeout)
    with pytest.raises(llm.ModelUnavailable):
        llm.call_ollama([], include_tools=False)
    assert assistant_metrics()["model_attempts"] - before.get("model_attempts", 0) == 1
