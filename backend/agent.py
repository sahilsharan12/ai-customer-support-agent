import logging
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from backend import llm, memory
from rag.retriever import format_policy_context, retrieve_policy


logger = logging.getLogger(__name__)
PREFERENCE = re.compile(
    r"(?:please )?remember (?:that )?i prefer (concise|detailed) (?:replies|answers)[.!]?",
    re.I,
)
ORDER_QUERY = re.compile(r"\b(?:order (?:history|status|details|tracking)|where is my order|my past orders)\b", re.I)
ORDER_TOOLS = {"get_order_details", "get_customer_orders"}
POLICY_TOOLS = {"get_order_details", "prepare_return_request"}


class SupportState(TypedDict, total=False):
    history: list[dict]
    user_id: str
    customer_id: str | None
    conversation_id: str
    intent: str
    answer: str
    context: str
    sources: list[str]


def load_preferences(state: SupportState) -> SupportState:
    message = next(msg["content"] for msg in reversed(state["history"]) if msg["role"] == "user")
    preference = PREFERENCE.fullmatch(message.strip())
    if preference:
        style = preference.group(1).lower()
        memory.set_reply_preference(state["user_id"], style)
        return {"answer": f"I'll remember that you prefer {style} replies."}
    if message.strip().lower().rstrip(".!") in {"forget my reply preference", "forget my reply style"}:
        memory.set_reply_preference(state["user_id"], None)
        return {"answer": "I cleared your reply preference."}

    style = memory.get_reply_preference(state["user_id"])
    if style:
        return {"history": [
            {"role": "system", "content": f"The customer prefers {style} replies."},
            *state["history"],
        ]}
    return {}


def route(state: SupportState) -> str:
    if state.get("answer"):
        return "done"
    if llm.get_confirmation_reference(state["history"]):
        return "confirm_return"
    if llm.policy_query(state["history"]):
        return "retrieve_policy"
    latest = next(msg["content"] for msg in reversed(state["history"]) if msg["role"] == "user")
    if state["intent"] in {"track_order", "get_order_history"} or ORDER_QUERY.search(latest):
        return "order_support"
    return "general_support"


def retrieve(state: SupportState) -> SupportState:
    try:
        matches = retrieve_policy(llm.policy_query(state["history"]))
    except (RuntimeError, ValueError, OSError):
        logger.warning("Policy retrieval unavailable", exc_info=True)
        return {"context": "Policy retrieval is temporarily unavailable.", "sources": []}
    return {
        "context": format_policy_context(matches),
        "sources": list(dict.fromkeys(match["source"] for match in matches)),
    }


def reply(state: SupportState, tools: set[str]) -> SupportState:
    return {"answer": llm.generate_response(
        state["history"],
        authenticated_customer_id=state["customer_id"],
        conversation_id=state["conversation_id"],
        authenticated_user_id=state["user_id"],
        policy_context=state.get("context", ""),
        tool_names=tools,
    )}


graph = StateGraph(SupportState)
graph.add_node("preferences", load_preferences)
graph.add_node("retrieve_policy", retrieve)
graph.add_node("policy_support", lambda state: reply(state, POLICY_TOOLS))
graph.add_node("order_support", lambda state: reply(state, ORDER_TOOLS))
graph.add_node("general_support", lambda state: reply(state, set()))
graph.add_node("confirm_return", lambda state: reply(state, set()))
graph.add_edge(START, "preferences")
graph.add_conditional_edges("preferences", route, {
    "done": END,
    "retrieve_policy": "retrieve_policy",
    "order_support": "order_support",
    "general_support": "general_support",
    "confirm_return": "confirm_return",
})
graph.add_edge("retrieve_policy", "policy_support")
for node in ("policy_support", "order_support", "general_support", "confirm_return"):
    graph.add_edge(node, END)
support_agent = graph.compile()


def answer_chat(history: list[dict], user: dict, conversation_id: str, intent: str) -> tuple[str, list[str]]:
    with tracing_context(enabled=False):
        result = support_agent.invoke({
            "history": history,
            "user_id": user["user_id"],
            "customer_id": user.get("customer_unique_id"),
            "conversation_id": conversation_id,
            "intent": intent,
        })
    return result["answer"], result.get("sources", [])
