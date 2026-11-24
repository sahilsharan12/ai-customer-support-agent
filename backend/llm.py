import json
import logging
import re

import requests

from backend.config import OLLAMA_BASE_URL, OLLAMA_MODEL

from backend.database_tools import (
    get_order_details,
    get_customer_orders
)
from backend.return_requests import create_return_request
from backend.return_validation import validate_return_eligibility
from backend.memory import (
    save_pending_action,
    get_pending_action,
    consume_pending_action
)

# ==========================================
# 1. CONFIGURATION
# ==========================================

PENDING_ACTION_TYPE = "CREATE_RETURN"
logger = logging.getLogger(__name__)


# ==========================================
# 2. SYSTEM PROMPT
# ==========================================

SYSTEM_PROMPT = """
You are a concise e-commerce support assistant. Use the customer database tools
for specific orders and order history. Ask for a missing order ID. Treat dates
and amounts from the tools as authoritative. Label historical Olist records as
demo data and distinguish actual from estimated delivery. Display BRL as BRL.

Answer policy questions using the supplied policy excerpts. If the excerpts
are insufficient, tell the customer and offer human support. Never invent
order details, policy, evidence, approval, payment status, or transaction IDs.
Never request passwords or complete payment credentials.

For a return, collect the order ID and the customer's stated reason.
Call prepare_return_request with those details and any evidence reference
the customer provided. The server presents the draft and handles confirmation.
If preparation fails, explain the backend result. Returns require human review.
Refund approval and payment processing are staff actions.
""".strip()


# ==========================================
# 3. TOOL DEFINITIONS
# ==========================================

TOOLS = [

    # ==========================================
    # TOOL 1: GET SPECIFIC ORDER DETAILS
    # ==========================================

    {
        "type": "function",
        "function": {
            "name": "get_order_details",
            "description": (
                "Retrieve detailed information about a specific "
                "historical order using its order ID. Use this when "
                "a customer asks about a particular order, its "
                "status, payment, products or delivery information."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The unique order ID."
                    }
                },
                "required": ["order_id"]
            }
        }
    },

    # ==========================================
    # TOOL 2: GET ALL CUSTOMER ORDERS
    # ==========================================

    {
        "type": "function",
        "function": {
            "name": "get_customer_orders",
            "description": (
                "Retrieve the authenticated customer's historical "
                "orders. The application determines the customer "
                "identity from the authenticated account."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    # ==========================================
    # TOOL 3: PREPARE RETURN REQUEST
    # ==========================================

    {
        "type": "function",
        "function": {
            "name": "prepare_return_request",
            "description": (
                "Validate and prepare a return request. "
                "This does not create the actual return request. "
                "The application saves the exact details and asks "
                "the customer for confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Verified historical order ID."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Customer's stated reason."
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "Additional details provided by the customer."
                        )
                    },
                    "evidence_reference": {
                        "type": "string",
                        "description": (
                            "Reference to evidence uploaded and verified "
                            "by the application. Never invent this value."
                        )
                    }
                },
                "required": ["order_id", "reason"]
            }
        }
    },

    # ==========================================
    # TOOL 4: CREATE CONFIRMED RETURN REQUEST
    # ==========================================


]


# ==========================================
# 4. HELPER FUNCTIONS
# ==========================================

def has_explicit_customer_confirmation(conversation_history: list) -> bool:
    """
    Check whether the latest customer message explicitly confirms
    a request that the assistant previously asked to create.
    """

    if not conversation_history:
        return False

    latest_user_index = None

    for index in range(len(conversation_history) - 1, -1, -1):

        if conversation_history[index].get("role") == "user":
            latest_user_index = index
            break

    if latest_user_index is None:
        return False

    latest_user_message = (
        conversation_history[latest_user_index].get("content", "")
    )

    if not isinstance(latest_user_message, str):
        return False

    confirmation = latest_user_message.strip().lower().rstrip(".,!? ")

    positive_responses = {
        "yes",
        "yes please",
        "yes, please",
        "confirm",
        "confirmed",
        "i confirm",
        "please proceed",
        "go ahead",
        "create the request",
        "submit the request"
    }

    if confirmation not in positive_responses:
        return False

    # Find the assistant message immediately preceding this confirmation.
    previous_assistant = None

    for index in range(latest_user_index - 1, -1, -1):

        if conversation_history[index].get("role") == "assistant":
            previous_assistant = conversation_history[index]
            break

    if not previous_assistant:
        return False

    assistant_text = (previous_assistant.get("content") or "").lower()

    asked_for_confirmation = (
        ("confirm" in assistant_text or "would you like" in assistant_text)
        and ("create" in assistant_text or "submit" in assistant_text)
        and ("return" in assistant_text or "refund" in assistant_text)
    )

    return asked_for_confirmation


def extract_pending_payload(pending):
    """
    Return the saved request payload as a dict, or None if it is
    missing or malformed. Handles a pending record that wraps the
    payload under a 'payload' key (dict or JSON string) as well as
    a record that is itself the payload.
    """

    if not isinstance(pending, dict):
        return None

    payload = pending.get("payload", pending)

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None

    if not isinstance(payload, dict):
        return None

    return payload


# ==========================================
# 5. TOOL EXECUTION
# ==========================================

def execute_tool(
    tool_name: str,
    arguments: dict,
    conversation_history: list = None,
    authenticated_customer_id: str = None,
    conversation_id: str = None,
    authenticated_user_id: str = None
):
    """
    Execute customer tools using the authenticated customer's identity.
    Never trust customer IDs supplied by the LLM.
    """

    # ======================================
    # 1. VALIDATE TOOL ARGUMENTS
    # ======================================

    if not isinstance(arguments, dict):
        return {
            "success": False,
            "error": "Invalid tool arguments."
        }

    if (
        not isinstance(authenticated_customer_id, str)
        or not authenticated_customer_id.strip()
    ):
        return {
            "success": False,
            "error": "Customer account is not linked to an order profile."
        }

    customer_id = authenticated_customer_id.strip()

    if tool_name in {"prepare_return_request", "create_return_request"} and (
        not isinstance(authenticated_user_id, str) or not authenticated_user_id.strip()
    ):
        return {"success": False, "error": "Authenticated account context is unavailable."}

    # ======================================
    # TOOL 1: GET SPECIFIC ORDER DETAILS
    # ======================================

    if tool_name == "get_order_details":

        order_id = arguments.get("order_id")

        if not isinstance(order_id, str) or not order_id.strip():
            return {
                "success": False,
                "error": "A valid order ID is required."
            }

        result = get_order_details(order_id.strip())

        if result is None:
            return {
                "success": False,
                "error": "Order not found."
            }

        order_customer_id = (
            result.get("order", {}).get("customer_unique_id")
        )

        if order_customer_id != customer_id:
            return {
                "success": False,
                "error": "Order not found."
            }

        return result

    # ======================================
    # TOOL 2: GET AUTHENTICATED CUSTOMER ORDERS
    # ======================================

    elif tool_name == "get_customer_orders":

        result = get_customer_orders(customer_id)

        if result is None:
            return {
                "success": False,
                "error": "No orders found for this customer."
            }

        return result

    # ======================================
    # TOOL 3: PREPARE RETURN REQUEST
    # ======================================

    elif tool_name == "prepare_return_request":

        if (
            not isinstance(conversation_id, str)
            or not conversation_id.strip()
        ):
            return {
                "success": False,
                "error": "Conversation context is unavailable."
            }

        order_id = arguments.get("order_id")
        reason = arguments.get("reason")
        description = arguments.get("description")
        evidence_reference = arguments.get("evidence_reference")

        # ----------------------------------
        # VALIDATE INPUTS
        # ----------------------------------

        if not isinstance(order_id, str) or not order_id.strip():
            return {
                "success": False,
                "error": "A valid order ID is required."
            }

        if not isinstance(reason, str) or not reason.strip():
            return {
                "success": False,
                "error": "A return reason is required."
            }

        if description is not None and not isinstance(description, str):
            return {
                "success": False,
                "error": "Description must be a string."
            }

        if (
            evidence_reference is not None
            and not isinstance(evidence_reference, str)
        ):
            return {
                "success": False,
                "error": "Evidence reference must be a string."
            }

        order_id = order_id.strip()
        reason = reason.strip()

        description = (description or "").strip() or None
        evidence_reference = (
            (evidence_reference or "").strip() or None
        )

        # ----------------------------------
        # RETRIEVE ORDER
        # ----------------------------------

        order_details = get_order_details(order_id)

        if order_details is None:
            return {
                "success": False,
                "error": "Order not found."
            }

        # ----------------------------------
        # VERIFY ORDER OWNERSHIP
        # ----------------------------------

        order_customer_id = (
            order_details.get("order", {}).get("customer_unique_id")
        )

        if order_customer_id != customer_id:
            return {
                "success": False,
                "error": "Order not found."
            }

        # ----------------------------------
        # VALIDATE RETURN ELIGIBILITY
        # ----------------------------------

        eligibility = validate_return_eligibility(
            order_details=order_details,
            reason=reason,
            evidence_reference=evidence_reference
        )

        if not eligibility.get("eligible", False):
            return {
                "success": False,
                "status": "NOT_ELIGIBLE",
                "message": (
                    "The return request cannot be prepared because "
                    "eligibility validation failed."
                ),
                "eligibility": eligibility
            }

        # ----------------------------------
        # SAVE EXACT REQUEST AS PENDING ACTION
        # ----------------------------------

        payload = {
            "order_id": order_id,
            "request_type": "RETURN",
            "reason": reason,
            "description": description,
            "evidence_reference": evidence_reference
        }

        action_id = save_pending_action(
            conversation_id=conversation_id,
            customer_id=authenticated_user_id,
            action_type=PENDING_ACTION_TYPE,
            payload=payload,
            expiry_minutes=10
        )

        return {
            "success": True,
            "status": "PENDING_CONFIRMATION",
            "action_id": action_id,
            "order_id": order_id,
            "request_type": "RETURN",
            "reason": reason,
            "description": description,
            "evidence_reference": evidence_reference,
            "eligibility": eligibility,
            "message": (
                "Return request prepared but NOT yet created. "
                "Ask the customer for explicit confirmation to "
                "create this exact request."
            )
        }

    # ======================================
    # TOOL 4: CREATE CONFIRMED RETURN REQUEST
    # ======================================

    elif tool_name == "create_return_request":

        if (
            not isinstance(conversation_id, str)
            or not conversation_id.strip()
        ):
            return {
                "success": False,
                "error": "Conversation context is unavailable."
            }

        # ----------------------------------
        # VERIFY EXPLICIT CONFIRMATION
        # ----------------------------------

        confirmation_reference = get_confirmation_reference(conversation_history or [])
        if confirmation_reference is None:
            return {
                "success": False,
                "error": "Explicit customer confirmation is required."
            }

        # ----------------------------------
        # RETRIEVE SAVED PENDING ACTION
        # ----------------------------------

        pending = get_pending_action(
            conversation_id=conversation_id,
            customer_id=authenticated_user_id,
            action_type=PENDING_ACTION_TYPE
        )

        if pending is None:
            return {
                "success": False,
                "error": (
                    "No valid pending return request exists. "
                    "Please prepare the request again."
                )
            }

        # ----------------------------------
        # RETRIEVE PENDING ACTION ID
        # ----------------------------------

        action_id = pending.get("action_id")

        if action_id != confirmation_reference:
            return {
                "success": False,
                "error": (
                    "This confirmation applies to a different return draft. "
                    "Please prepare the request again."
                )
            }

        # ----------------------------------
        # EXTRACT SAVED PAYLOAD
        # ----------------------------------

        payload = extract_pending_payload(pending)

        if payload is None:
            return {
                "success": False,
                "error": (
                    "The saved return request is invalid. "
                    "Please prepare the request again."
                )
            }

        # ----------------------------------
        # VALIDATE SAVED PAYLOAD
        # ----------------------------------

        order_id = payload.get("order_id")
        request_type = payload.get("request_type")
        reason = payload.get("reason")
        description = payload.get("description")
        evidence_reference = payload.get("evidence_reference")

        if request_type != "RETURN":
            return {
                "success": False,
                "error": (
                    "Only RETURN requests are supported "
                    "through this workflow."
                )
            }

        if (
            not isinstance(order_id, str)
            or not order_id.strip()
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            return {
                "success": False,
                "error": (
                    "The saved return request is incomplete. "
                    "Please prepare the request again."
                )
            }

        if description is not None and not isinstance(description, str):
            return {
                "success": False,
                "error": "Saved description is invalid."
            }

        if (
            evidence_reference is not None
            and not isinstance(evidence_reference, str)
        ):
            return {
                "success": False,
                "error": "Saved evidence reference is invalid."
            }

        order_id = order_id.strip()
        reason = reason.strip()

        # ----------------------------------
        # RE-VERIFY ORDER
        # ----------------------------------

        order_details = get_order_details(order_id)

        if order_details is None:
            return {
                "success": False,
                "error": "Order not found."
            }

        order_customer_id = (
            order_details.get("order", {}).get("customer_unique_id")
        )

        if order_customer_id != customer_id:
            return {
                "success": False,
                "error": "Order not found."
            }

        # ----------------------------------
        # RE-VALIDATE RETURN ELIGIBILITY
        # ----------------------------------

        eligibility = validate_return_eligibility(
            order_details=order_details,
            reason=reason,
            evidence_reference=evidence_reference
        )

        if not eligibility.get("eligible", False):
            return {
                "success": False,
                "status": "NOT_ELIGIBLE",
                "message": (
                    "The return request cannot be created because "
                    "eligibility validation failed."
                ),
                "eligibility": eligibility
            }

        # ----------------------------------
        # CREATE RETURN REQUEST
        # ----------------------------------

        result = create_return_request(
            order_id=order_id,
            request_type="RETURN",
            reason=reason,
            description=description,
            customer_unique_id=customer_id,
            evidence_reference=evidence_reference,
            pending_action_id=action_id,
            prevent_duplicate=True
        )

        # ----------------------------------
        # VERIFY CREATION RESULT
        # ----------------------------------

        if not isinstance(result, dict) or not result.get("request_id"):
            return {
                "success": False,
                "error": "Return request creation could not be verified."
            }

        # ----------------------------------
        # CONSUME PENDING ACTION
        # ----------------------------------

        consumed_payload = consume_pending_action(
            action_id=action_id,
            conversation_id=conversation_id,
            customer_id=authenticated_user_id
        )

        if consumed_payload is None:
            logger.warning("Pending return draft was already removed. Request %s", result["request_id"])

        # ----------------------------------
        # RETURN SUCCESS RESULT
        # ----------------------------------

        return {
            "success": True,
            "request": result,
            "eligibility": eligibility,
            "pending_action_consumed": (
                consumed_payload is not None
            ),
            "message": (
                "Return request created successfully. "
                "It is awaiting human support review."
            )
        }

    # ======================================
    # UNKNOWN TOOL
    # ======================================

    return {
        "success": False,
        "error": "Unknown tool."
    }

# ==========================================
# 6. OLLAMA API REQUEST
# ==========================================

def call_ollama(messages: list, include_tools: bool | list[dict] = True):

    url = f"{OLLAMA_BASE_URL}/api/chat"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": "2m",
        "options": {"num_ctx": 4096, "num_predict": 256, "temperature": 0.1},
    }

    if include_tools:
        payload["tools"] = TOOLS if include_tools is True else include_tools

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=180
        )

        response.raise_for_status()

        body = response.json()
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, dict):
            raise RuntimeError("Ollama returned an invalid message.")
        return {key: value for key, value in message.items() if key != "thinking"}

    except requests.exceptions.ConnectionError:

        raise RuntimeError(
            "Cannot connect to Ollama. Check whether Ollama is running."
        )

    except requests.exceptions.Timeout:

        raise RuntimeError(
            "Ollama request timed out."
        )

    except requests.exceptions.RequestException as error:

        raise RuntimeError(
            f"Ollama API error: {error}"
        )


# ==========================================
# 7. RESPONSE GENERATION
# ==========================================

def generate_response(
    conversation_history: list,
    authenticated_customer_id: str = None,
    conversation_id: str = None,
    authenticated_user_id: str = None,
    *,
    policy_context: str | None = None,
    tool_names: set[str] | None = None,
) -> str:

    # ==========================================
    # 1. INITIALIZE CONVERSATION
    # ==========================================

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    # ==========================================
    # 2. HANDLE CONFIRMED RETURN DRAFTS
    # ==========================================

    if get_confirmation_reference(conversation_history):
        result = execute_tool(
            "create_return_request", {}, conversation_history,
            authenticated_customer_id, conversation_id, authenticated_user_id
        )
        if result.get("success"):
            return format_return_submission(result["request"])
        return result.get("message") or result["error"]

    if policy_context is None:
        query = policy_query(conversation_history)
        if query:
            from rag.retriever import get_policy_context
            try:
                policy_context = get_policy_context(query)
            except (RuntimeError, ValueError, OSError):
                logger.warning("Policy retrieval unavailable")
                policy_context = "Policy retrieval is temporarily unavailable."
    if policy_context:
        messages.append({
            "role": "system",
            "content": "Use these policy excerpts for policy questions. Offer human support if the evidence is insufficient.\n\n" + policy_context,
        })

    messages.extend(conversation_history)

    # ==========================================
    # 5. TOOL CALLING LOOP
    # ==========================================

    max_tool_rounds = 3
    remaining_tool_calls = 6
    tools = [tool for tool in TOOLS if tool_names is None or tool["function"]["name"] in tool_names]
    allowed_tools = {tool["function"]["name"] for tool in tools}

    for round_number in range(max_tool_rounds + 1):

        assistant_message = call_ollama(
            messages,
            include_tools=tools
        )

        messages.append(assistant_message)

        tool_calls = assistant_message.get(
            "tool_calls", []
        )
        if tool_calls and not isinstance(tool_calls, list):
            raise RuntimeError("Ollama returned an invalid tool-call list.")


        # ======================================
        # NO TOOL REQUESTED
        # ======================================

        if not tool_calls:
            return (assistant_message.get("content") or "").strip() or (
                "I couldn't generate a response. Please try again."
            )

        # Allow one final Ollama response after the third tool round.
        # Do not execute additional tools beyond the configured limit.
        if round_number == max_tool_rounds or remaining_tool_calls == 0:
            return (
                assistant_message.get("content")
                or (
                    "I could not complete the request within the "
                    "allowed tool execution limit. Please try again."
                )
            )

        # ======================================
        # 6. EXECUTE REQUESTED TOOLS
        # ======================================

        for tool_call in tool_calls[:remaining_tool_calls]:
            remaining_tool_calls -= 1
            if not isinstance(tool_call, dict) or not isinstance(tool_call.get("function"), dict):
                continue

            function_data = tool_call.get(
                "function", {}
            )

            tool_name = function_data.get("name")
            if not isinstance(tool_name, str) or tool_name not in allowed_tools:
                continue

            arguments = function_data.get(
                "arguments", {}
            )

            # Parse arguments if returned as JSON string
            if isinstance(arguments, str):

                try:

                    arguments = json.loads(arguments)

                except json.JSONDecodeError:

                    tool_result = {
                        "success": False,
                        "error": "Invalid tool arguments."
                    }

                    messages.append({
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": json.dumps(tool_result)
                    })

                    continue

            if not isinstance(arguments, dict):

                tool_result = {
                    "success": False,
                    "error": "Tool arguments must be a JSON object."
                }

            else:

                try:

                    tool_result = execute_tool(
                        tool_name=tool_name,
                        arguments=arguments,
                        conversation_history=conversation_history,
                        authenticated_customer_id=authenticated_customer_id,
                        conversation_id=conversation_id,
                        authenticated_user_id=authenticated_user_id
                    )

                except Exception:
                    logger.exception("Customer tool execution failed")

                    tool_result = {
                        "success": False,
                        "error": (
                            "The requested operation could not be completed. "
                            "Please try again or contact support."
                        )
                    }

            # ==================================
            # 7. SEND TOOL RESULT BACK TO QWEN
            # ==================================

            if tool_result.get("status") == "PENDING_CONFIRMATION":
                return format_return_confirmation(tool_result)

            messages.append({
                "role": "tool",
                "tool_name": tool_name,
                "content": json.dumps(
                    tool_result,
                    default=str
                )
            })

    # ==========================================
    # 8. MAXIMUM TOOL ROUND VALIDATION
    # ==========================================

    raise RuntimeError(
        "Maximum tool execution rounds reached."
    )


def get_confirmation_reference(history: list) -> str | None:
    if not has_explicit_customer_confirmation(history):
        return None
    exchange = [message for message in history if message.get("role") in {"user", "assistant"}]
    if [message["role"] for message in exchange[-2:]] != ["assistant", "user"]:
        return None
    text = exchange[-2].get("content") or ""
    match = re.search(
        r"\nConfirmation reference: ([a-f0-9-]{36})\n"
        r"Reply 'confirm' to submit this return request\.$",
        text,
    )
    return match.group(1) if match else None


def format_return_confirmation(request: dict) -> str:
    summary = [f"Order: {request['order_id']}", f"Reason: {request['reason']}"]
    if request.get("description"):
        summary.append(f"Description: {request['description']}")
    if request.get("evidence_reference"):
        summary.append(f"Evidence: {request['evidence_reference']}")
    summary.append(f"Confirmation reference: {request['action_id']}")
    summary.append("Reply 'confirm' to submit this return request.")
    return "\n".join(summary)


def format_return_submission(request: dict) -> str:
    if request.get("already_exists"):
        status = request["status"].replace("_", " ").lower()
        return f"Return request {request['request_id']} already exists. Its status is {status}."
    return f"Return request {request['request_id']} was submitted for support review."


_POLICY_TERMS = re.compile(
    r"\b(?:returns?|refunds?|shipping|deliver(?:y|ed)|damag(?:ed|e)|defective|arriv\w*|"
    r"exchange|send (?:it |the item )?back|wrong (?:item|product)|incorrect (?:item|product))\b", re.I
)


def policy_query(messages: list[dict]) -> str:
    recent = [message["content"] for message in messages[-6:] if message.get("role") == "user"]
    if not recent:
        return ""
    latest = recent[-1]
    if _POLICY_TERMS.search(latest):
        return latest
    if len(latest.split()) <= 7 and len(recent) > 1 and _POLICY_TERMS.search(recent[-2]):
        return f"{recent[-2]} {latest}"
    return ""
