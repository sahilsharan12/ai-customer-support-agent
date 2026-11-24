import json
import logging
import re
from time import perf_counter
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from backend import database_tools, llm, memory, support_cases
from backend.guardrails import injection_signal, mask_text
from backend.observability import span, track
from rag.retriever import format_policy_context, retrieve_policy


logger = logging.getLogger("uvicorn.error").getChild("support_agent")
PREFERENCE = re.compile(
    r"(?:please )?remember (?:that )?i prefer (concise|detailed) (?:replies|answers)[.!]?", re.I,
)
ORDER_QUERY = re.compile(r"\b(?:order (?:history|status|details|tracking)|where is my order|my past orders)\b", re.I)
ORDER_ID = re.compile(r"\b(?:demo-order-\d+|[a-f\d]{32})\b", re.I)
REFUND_REQUEST = re.compile(
    r"\b(?:i (?:want|need|would like)|please (?:request|process|issue|start)|can you (?:process|issue))\b"
    r"[^?.]{0,45}\brefund\b|^\s*(?:please )?refund (?:my |this )?order\b", re.I,
)
CANCEL_REQUEST = re.compile(
    r"^\s*(?:(?:please|can you|could you|i want to|i need to) )?(?:cancel|request cancellation of)\b.{0,35}\border\b", re.I,
)
ACCOUNT_CHANGE = re.compile(
    r"\b(?:change|update|modify|reset)\b.{0,25}\b(?:email|password|phone|mobile|address|payment details)\b", re.I,
)
RETURN_ACTION = re.compile(
    r"\b(?:return my|send (?:it )?back|start a return|prepare a return|request a return|"
    r"return (?:this )?order|want to return|need to return|would like to return)\b"
    r"|^\s*(?:please )?return (?:demo-order-\d+|[a-f\d]{32})\b", re.I,
)
POLICY_QUESTION = re.compile(r"^\s*(?:what|when|how (?:long|many)|is it possible)\b", re.I)
CANCEL_DRAFT = re.compile(
    r"\nCancellation reference: ([a-f0-9-]{36})\n"
    r"Reply 'confirm' to send this cancellation request to staff\.$",
)
ORDER_TOOLS = {"get_order_details", "get_customer_orders"}
POLICY_TOOLS = {"get_order_details", "prepare_return_request"}


class SupportState(TypedDict, total=False):
    history: list[dict]
    user_id: str
    customer_id: str | None
    conversation_id: str
    intent: str
    confidence: float
    answer: str
    context: str
    sources: list[str]
    workflow: str
    case: dict
    fallback: str
    messages: list[dict]
    tools: list[dict]
    calls: list
    rounds: int
    remaining_calls: int


def latest_message(state):
    return next(msg["content"] for msg in reversed(state["history"]) if msg["role"] == "user")


def cancellation_confirmation(history):
    exchange = [item for item in history if item["role"] in {"user", "assistant"}]
    if [item["role"] for item in exchange[-2:]] != ["assistant", "user"]:
        return None
    if exchange[-1]["content"].strip().lower().rstrip(".!?") not in {"confirm", "i confirm", "yes"}:
        return None
    match = CANCEL_DRAFT.search(exchange[-2]["content"])
    return match.group(1) if match else None


def classify_workflow(state: SupportState) -> SupportState:
    message = latest_message(state)
    if injection_signal(message):
        track(blocked_inputs=1)
        return {"workflow": "done", "answer": "I can help with orders, returns, and support policies. Please rephrase your request."}
    preference = PREFERENCE.fullmatch(message.strip())
    if preference:
        style = preference.group(1).lower()
        memory.set_reply_preference(state["user_id"], style)
        return {"workflow": "done", "answer": f"I'll remember that you prefer {style} replies."}
    if message.strip().lower().rstrip(".!") in {"forget my reply preference", "forget my reply style"}:
        memory.set_reply_preference(state["user_id"], None)
        return {"workflow": "done", "answer": "I cleared your reply preference."}

    if cancellation_confirmation(state["history"]):
        return {"workflow": "confirm_cancellation"}
    if llm.get_confirmation_reference(state["history"]):
        return {"workflow": "confirm_return"}
    if ACCOUNT_CHANGE.search(message):
        return {"workflow": "account_change"}
    if CANCEL_REQUEST.search(message):
        return {"workflow": "prepare_cancellation"}
    if REFUND_REQUEST.search(message):
        return {"workflow": "refund_review"}

    style = memory.get_reply_preference(state["user_id"])
    history = state["history"]
    if style:
        history = [{"role": "system", "content": f"The customer prefers {style} replies."}, *history]
    if llm.policy_query(history):
        workflow = "retrieve_policy"
    elif state["intent"] in {"track_order", "get_order_history"} or ORDER_QUERY.search(message):
        workflow = "order_support"
    elif state["confidence"] < 0.35 and ("?" in message or re.search(r"\b(?:help|problem|issue)\b", message, re.I)):
        workflow = "escalate"
    else:
        workflow = "general_support"
    return {"workflow": workflow, "history": history}


def enqueue(state, kind, reason, *, order_id=None, confirmation_id=None):
    case, created = support_cases.open_case(
        state["user_id"], state["conversation_id"], kind, reason,
        order_id=order_id, confirmation_id=confirmation_id,
    )
    track(cases_created=int(created))
    return {"case": {key: case[key] for key in ("case_id", "kind", "status", "order_id")}}


def handoff(state: SupportState) -> SupportState:
    reason = state.get("fallback", "LOW_CLASSIFIER_CONFIDENCE")
    result = enqueue(state, "LOW_CONFIDENCE", reason)
    message = {
        "MODEL_UNAVAILABLE": "Chat is temporarily unavailable.",
        "POLICY_UNAVAILABLE": "I couldn't verify a relevant policy for that question.",
        "LOW_CLASSIFIER_CONFIDENCE": "I'm unsure how to resolve that request.",
    }.get(reason, "I couldn't verify a reliable answer.")
    return {**result, "answer": f"{message} I've sent it to staff for review. Case {result['case']['case_id']}."}


def request_account_change(state: SupportState) -> SupportState:
    result = enqueue(state, "ACCOUNT_CHANGE", "ADMIN_AUTHORIZATION_REQUIRED")
    return {**result, "answer": (
        "An admin must verify your identity before updating sensitive account details. "
        f"I've sent this to the verification queue. Case {result['case']['case_id']}. "
        "Use the verified support channel to provide any required details."
    )}


def owned_order(state):
    match = ORDER_ID.search(latest_message(state))
    if not match:
        return None, "Share the order ID so I can verify the request."
    if not state["customer_id"]:
        return None, "Ask support to link your account to its verified order profile first."
    order = database_tools.get_order_details(match.group(0).lower())
    if not order or order["order"]["customer_unique_id"] != state["customer_id"]:
        return None, "I couldn't find that order on your account."
    return order["order"], None


def request_refund(state: SupportState) -> SupportState:
    order, error = owned_order(state)
    if error:
        return {"answer": error}
    result = enqueue(state, "REFUND_REVIEW", "HUMAN_REFUND_APPROVAL_REQUIRED", order_id=order["order_id"])
    return {**result, "answer": (
        f"Refund review case {result['case']['case_id']} is {result['case']['status'].lower()}. "
        "A reviewer checks the request before any refund decision or payment processing."
    )}


def prepare_cancellation(state: SupportState) -> SupportState:
    order, error = owned_order(state)
    if error:
        return {"answer": error}
    if order["order_status"] not in {"created", "approved", "processing", "invoiced"}:
        return {"answer": "This order's current status is ineligible for cancellation. For a delivered order, check the return options."}
    action_id = memory.save_pending_action(
        state["conversation_id"], state["user_id"], "CANCEL_ORDER", {"order_id": order["order_id"]},
    )
    return {"answer": (
        f"Cancellation draft for order {order['order_id']}.\n"
        f"Cancellation reference: {action_id}\n"
        "Reply 'confirm' to send this cancellation request to staff."
    )}


def confirm_cancellation(state: SupportState) -> SupportState:
    confirmation_id = cancellation_confirmation(state["history"])
    pending = memory.get_pending_action(state["conversation_id"], state["user_id"], "CANCEL_ORDER")
    if not pending or pending["action_id"] != confirmation_id:
        return {"answer": "This cancellation draft is no longer available. Please prepare a new draft."}
    order_id = pending["payload"]["order_id"]
    order = database_tools.get_order_details(order_id)
    if not order or order["order"]["customer_unique_id"] != state["customer_id"]:
        return {"answer": "I couldn't verify order ownership. Please contact support."}
    if order["order"]["order_status"] not in {"created", "approved", "processing", "invoiced"}:
        return {"answer": "The order is now ineligible for cancellation. Please contact support."}
    result = enqueue(
        state, "ORDER_CANCELLATION", "CUSTOMER_CONFIRMED_CANCELLATION_REQUEST",
        order_id=order_id, confirmation_id=confirmation_id,
    )
    memory.consume_pending_action(confirmation_id, state["conversation_id"], state["user_id"])
    return {**result, "answer": (
        f"Cancellation review case {result['case']['case_id']} was sent to staff. "
        "Staff will verify whether the order can be cancelled."
    )}


def confirm_return(state: SupportState) -> SupportState:
    return {"answer": llm.confirm_return(
        state["history"], state["customer_id"], state["conversation_id"], state["user_id"],
    )}


def retrieve(state: SupportState) -> SupportState:
    with span("support.retrieve"):
        try:
            matches = [
                match for match in retrieve_policy(llm.policy_query(state["history"]))
                if match.get("source") in {"shipping_policy.md", "refund_policy.md", "return_policy.md"}
                and not injection_signal(match.get("content", ""))
            ]
        except (RuntimeError, ValueError, OSError):
            matches = []
    track(policy_lookups=1, policy_hits=int(bool(matches)))
    message = latest_message(state)
    if RETURN_ACTION.search(message) and not POLICY_QUESTION.search(message):
        return {"context": format_policy_context(matches), "tools": llm.tool_definitions(POLICY_TOOLS)}
    if not matches:
        return {"fallback": "POLICY_UNAVAILABLE"}
    best = matches[0]
    track(cited_policy_answers=1)
    return {"answer": f"{best['content'].strip()}\n\nSource [{best['source']}]", "sources": [best["source"]]}


def initialize_model(state: SupportState) -> SupportState:
    tools = state.get("tools", llm.tool_definitions(ORDER_TOOLS if state["workflow"] == "order_support" else set()))
    return {
        "tools": tools,
        "messages": llm.model_messages(state["history"], state.get("context", "")),
        "rounds": 0,
        "remaining_calls": 6,
    }


def model_turn(state: SupportState) -> SupportState:
    try:
        reply = llm.call_ollama(state["messages"], include_tools=state["tools"])
    except llm.ModelUnavailable:
        return {"fallback": "MODEL_UNAVAILABLE"}
    if not isinstance(reply, dict) or not isinstance(reply.get("content", ""), str):
        track(blocked_outputs=1)
        return {"fallback": "INVALID_MODEL_OUTPUT"}
    calls = reply.get("tool_calls") or []
    if calls:
        if not isinstance(calls, list) or state["rounds"] == 3 or state["remaining_calls"] == 0:
            return {"fallback": "TOOL_BUDGET_OR_FORMAT"}
        return {"calls": calls[:state["remaining_calls"]], "rounds": state["rounds"] + 1}
    answer = mask_text(reply.get("content", "")).strip()
    if not answer or len(answer) > 4000 or injection_signal(answer):
        track(blocked_outputs=1)
        return {"fallback": "INVALID_MODEL_OUTPUT"}
    if state["workflow"] == "order_support" and state["rounds"] == 0:
        return {"fallback": "ORDER_LOOKUP_REQUIRED"}
    return {"answer": answer}


def tool_turn(state: SupportState) -> SupportState:
    messages, answer = llm.run_tool_calls(
        state["calls"], state["tools"], state["history"], state["customer_id"],
        state["conversation_id"], state["user_id"],
    )
    if answer:
        return {"answer": answer}
    if not messages:
        return {"fallback": "NO_ALLOWED_TOOLS"}
    if state["workflow"] == "order_support":
        for message in messages[1:]:
            result = json.loads(message["content"])
            if result.get("success") is False:
                continue
            if order := result.get("order"):
                delivery = order.get("order_delivered_customer_date")
                return {"answer": (
                    f"Order {order['order_id']} has status {order['order_status']} in the order database."
                    + (f" Recorded delivery date: {delivery}." if delivery else "")
                )}
            if "total_orders" in result:
                orders = result.get("orders", [])
                entries = "\n".join(f"- {order['order_id']} — {order['order_status']}" for order in orders)
                return {"answer": f"Your profile has {result['total_orders']} recorded orders." + (f"\n{entries}" if entries else "")}
        return {"answer": "I couldn't verify the order. Check the order ID and make sure it belongs to your linked profile."}
    return {
        "messages": state["messages"] + messages,
        "remaining_calls": state["remaining_calls"] - len(state["calls"]),
    }


def next_step(state: SupportState, default: str) -> str:
    if state.get("answer"):
        return END
    if state.get("fallback"):
        return "escalate"
    return default


graph = StateGraph(SupportState)
for name, node in {
    "route": classify_workflow, "retrieve_policy": retrieve, "order_support": initialize_model,
    "confirm_return": confirm_return, "general_support": initialize_model,
    "prepare_cancellation": prepare_cancellation, "confirm_cancellation": confirm_cancellation,
    "account_change": request_account_change, "refund_review": request_refund,
    "model": model_turn, "tools": tool_turn, "escalate": handoff,
}.items():
    graph.add_node(name, node)
graph.add_edge(START, "route")
graph.add_conditional_edges("route", lambda state: state["workflow"], {
    "done": END,
    **{name: name for name in (
        "retrieve_policy", "order_support", "general_support", "confirm_return",
        "prepare_cancellation", "confirm_cancellation", "account_change", "refund_review", "escalate",
    )},
})
graph.add_conditional_edges("retrieve_policy", lambda state: next_step(state, "general_support"), [END, "escalate", "general_support"])
graph.add_edge("order_support", "model")
graph.add_edge("general_support", "model")
graph.add_conditional_edges("model", lambda state: next_step(state, "tools"), [END, "escalate", "tools"])
graph.add_conditional_edges("tools", lambda state: next_step(state, "model"), [END, "escalate", "model"])
for name in ("confirm_return", "prepare_cancellation", "confirm_cancellation", "account_change", "refund_review", "escalate"):
    graph.add_edge(name, END)
support_agent = graph.compile()


def answer_chat(history: list[dict], user: dict, conversation_id: str, intent: str, confidence: float) -> dict:
    started = perf_counter()
    with tracing_context(enabled=False), span("support.turn") as turn_span:
        result = support_agent.invoke({
            "history": [dict(msg, content=mask_text(msg["content"])) for msg in history],
            "user_id": user["user_id"],
            "customer_id": user.get("customer_unique_id"),
            "conversation_id": conversation_id,
            "intent": intent,
            "confidence": confidence,
        })
        duration = (perf_counter() - started) * 1000
        escalated = bool(result.get("case"))
        workflow = result["workflow"]
        turn_span.set_attribute("support.workflow", workflow)
        turn_span.set_attribute("support.escalated", escalated)
        track(turns=1, escalated_turns=int(escalated), response_ms=duration)
        logger.info(json.dumps({
            "event": "support_turn", "workflow": workflow, "escalated": escalated, "duration_ms": round(duration, 2),
        }))
    return result
