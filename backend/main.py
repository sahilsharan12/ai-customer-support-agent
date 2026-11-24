import logging
import sqlite3
import threading
import time
from backend.return_validation import validate_return_eligibility
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from contextlib import closing
from decimal import Decimal, InvalidOperation
from typing import Optional, Literal

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Query,
    Path,
    Request,
    Response
)
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import requests

from pydantic import (
    BaseModel,
    Field,
    field_validator
)

from backend.agent import answer_chat
from backend import support_cases
from backend.config import DEMO_REFUNDS_ENABLED, OLLAMA_BASE_URL, OLLAMA_MODEL, PROJECT_ROOT
from backend.guardrails import mask_text, mask_tool_data
from backend.observability import assistant_metrics, configure_tracing, observe_request, request_metrics

from backend.memory import (
    create_conversation,
    add_message,
    get_conversation,
    get_conversation_page,
    get_recent_history,
    get_customer_memory,
    get_conversation_owner,
    get_reply_preference,
    set_reply_preference,
    conversation_statistics,
    list_customer_conversations,
    initialize_database as initialize_memory_database
)

from backend.intent_classifier import predict_intent

from backend.database_tools import (
    get_order_details,
    get_customer_orders,
    customer_identity_exists,
    get_db_connection as get_order_connection,
)

from backend.auth import (
    initialize_auth_database,
    register_user,
    authenticate_user,
    create_access_token,
    get_current_user,
    link_customer_identity,
    signing_key
)

from backend.return_requests import (
    initialize_database,
    get_connection,
    create_return_request,
    get_return_request,
    get_all_return_requests,
    review_return_request,
    create_refund_record,
    record_product_receipt,
    record_product_inspection,
    review_refund_record,
    process_refund_record,
    get_refund_processing_attempts,
    get_refund_record,
    get_all_refund_records,
    get_return_request_summary,
    get_return_refund_audit_logs,
    cancel_return_request,
    get_return_request_statistics,
    get_refund_statistics,
    get_customer_return_page,
)


# ==========================================
# 1. LOGGING
# ==========================================

logger = logging.getLogger("customer_support_api")


# ==========================================
# 2. ROLES AND AUTHORIZATION
# ==========================================

ROLE_CUSTOMER = "customer"
ROLE_AGENT = "support_agent"
ROLE_ADMIN = "admin"

STAFF_ROLES = (ROLE_AGENT, ROLE_ADMIN)


def require_roles(*allowed_roles):

    def checker(user: dict = Depends(get_current_user)):

        if user.get("role") not in allowed_roles:

            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action."
            )

        return user

    return checker


def is_staff(user: dict) -> bool:

    return user.get("role") in STAFF_ROLES


def actor(user: dict) -> str:

    return user.get("email") or str(user["user_id"])


def customer_owns(user: dict, customer_id: Optional[str]) -> bool:

    return (
        bool(user.get("customer_unique_id"))
        and user.get("customer_unique_id") == customer_id
    )


# ==========================================
# 3. FASTAPI LIFESPAN
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    signing_key()
    configure_tracing()
    initialize_database()
    initialize_auth_database()
    initialize_memory_database()
    support_cases.initialize_database()

    logger.info("Application databases initialized.")

    yield

    logger.info("Application shutdown completed.")


tags_metadata = [
    {
        "name": "General",
        "description": "Service status endpoints."
    },
    {
        "name": "Authentication",
        "description": "User registration, login and identity."
    },
    {
        "name": "Chat",
        "description": "AI customer support and intent prediction."
    },
    {
        "name": "Conversations",
        "description": "Conversation history and customer memory."
    },
    {
        "name": "Orders",
        "description": "Customer order information."
    },
    {
        "name": "Returns",
        "description": "Return request management."
    },
    {
        "name": "Refunds",
        "description": "Refund management and processing."
    },
    {
        "name": "Audit",
        "description": "Administrative audit history."
    }
]


app = FastAPI(
    title="AI Customer Support Agent",
    description=(
        "Agentic AI-powered E-commerce Customer Support System. "
        "Login using /auth/login and authorize using the JWT Bearer token."
    ),
    version="2.0.0",
    openapi_tags=tags_metadata,
    lifespan=lifespan
)
app.middleware("http")(observe_request)

dashboard_dir = PROJECT_ROOT / "frontend"
app.mount("/dashboard-assets", StaticFiles(directory=dashboard_dir), name="dashboard-assets")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(
        dashboard_dir / "index.html",
        headers={"Content-Security-Policy": "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"},
    )


# ==========================================
# 4. COMMON RESPONSE DOCUMENTATION
# ==========================================

COMMON_RESPONSES = {
    401: {"description": "Missing, invalid or expired token."},
    403: {"description": "Insufficient permissions."},
    404: {"description": "Resource not found."},
    422: {"description": "Request validation error."}
}


# ==========================================
# 5. EXCEPTION HANDLERS
# ==========================================

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, error: ValueError):

    return JSONResponse(
        status_code=400,
        content={
            "status": "error",
            "detail": str(error)
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": issue["loc"], "type": issue["type"], "msg": issue["msg"]}
        for issue in error.errors()
    ]})


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, error: RuntimeError):

    logger.exception("Service error")

    return JSONResponse(
        status_code=503,
        content={
            "status": "error",
            "detail": "Service temporarily unavailable."
        }
    )


@app.exception_handler(Exception)
async def general_error_handler(request: Request, error: Exception):

    logger.exception("Unexpected API error")

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "detail": "Internal server error."
        }
    )


# ==========================================
# 6. RATE LIMITER
# ==========================================

class RateLimiter:

    def __init__(self, max_requests: int, window_seconds: int):

        self.max_requests = max_requests
        self.window_seconds = window_seconds

        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._next_sweep = 0.0

    def check(self, key: str):

        now = time.monotonic()

        with self._lock:
            if now >= self._next_sweep:
                self._next_sweep = now + self.window_seconds
                for entry in [entry for entry, times in self._hits.items() if not times or now - times[-1] >= self.window_seconds]:
                    del self._hits[entry]

            hits = self._hits[key]

            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()

            if len(hits) >= self.max_requests:

                retry_after = int(
                    self.window_seconds - (now - hits[0])
                ) + 1

                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please try again later.",
                    headers={
                        "Retry-After": str(retry_after)
                    }
                )

            hits.append(now)


intent_rate_limiter = RateLimiter(
    max_requests=30,
    window_seconds=60
)
login_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)
chat_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)
registration_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)


# ==========================================
# 7. COMMON HELPERS
# ==========================================

def id_path():
    return Path(..., min_length=1, max_length=100)



def unwrap(result):

    if isinstance(result, dict) and result.get("success") is False:

        message = (
            result.get("message")
            or result.get("error")
            or "Request could not be completed."
        )

        error_code = result.get("error_code")

        status_code = (
            404 if "not found" in message.lower()
            else 409
        )

        # Preserve structured error codes when available.

        if error_code:
            detail = {
                "error_code": error_code,
                "message": message
            }
        else:
            detail = message

        raise HTTPException(
            status_code=status_code,
            detail=detail
        )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail="Requested resource not found."
        )

    return result



def assert_conversation_access(
    conversation_id: str,
    user: dict,
    allow_staff: bool = False
):

    owner = get_conversation_owner(conversation_id)
    if owner is None and (not allow_staff or not is_staff(user) or get_conversation(conversation_id) is None):

        raise HTTPException(
            status_code=404,
            detail="Conversation not found."
        )

    if allow_staff and is_staff(user):
        return

    if owner != user["user_id"]:

        raise HTTPException(
            status_code=404,
            detail="Conversation not found."
        )


def can_access_return(user: dict, return_request: dict) -> bool:

    if is_staff(user):
        return True

    return customer_owns(
        user,
        return_request.get("customer_unique_id")
    )


def load_return_for_user(request_id: str, user: dict):

    return_request = get_return_request(request_id)

    if (
        return_request is None
        or not can_access_return(user, return_request)
    ):

        raise HTTPException(
            status_code=404,
            detail="Return request not found."
        )

    return return_request


# ==========================================
# 8. REQUEST SCHEMAS
# ==========================================

class RegisterRequest(BaseModel):

    email: str = Field(..., min_length=5, max_length=254)

    password: str = Field(..., min_length=8, max_length=128)

    full_name: Optional[str] = Field(None, max_length=120)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):

        value = value.strip().lower()

        if (
            "@" not in value
            or value.startswith("@")
            or value.endswith("@")
        ):

            raise ValueError("A valid email address is required.")

        return value


class LoginRequest(BaseModel):

    email: str = Field(..., min_length=5, max_length=254)

    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):

        return value.strip().lower()


class LinkCustomerRequest(BaseModel):
    customer_unique_id: str = Field(..., min_length=1, max_length=100)

    @field_validator("customer_unique_id", mode="before")
    @classmethod
    def strip_customer_id(cls, value):
        return value.strip() if isinstance(value, str) else value


class ChatRequest(BaseModel):

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000
    )

    conversation_id: Optional[str] = Field(
        None,
        max_length=100
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value):

        value = value.strip()

        if not value:

            raise ValueError(
                "Message cannot be empty or whitespace only."
            )

        return value

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value):

        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Conversation ID cannot be blank.")

        return value


class IntentRequest(BaseModel):

    message: str = Field(..., min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value):

        value = value.strip()

        if not value:
            raise ValueError("Message cannot be blank.")

        return value


class CreateReturnRequest(BaseModel):

    order_id: str = Field(..., min_length=1, max_length=100)

    request_type: Literal["RETURN"] = "RETURN"
    reason: str = Field(..., min_length=3, max_length=500)

    description: Optional[str] = Field(None, max_length=2000)

    evidence_reference: Optional[str] = Field(None, max_length=500)


class ReviewDecisionRequest(BaseModel):

    decision: Literal["APPROVED", "REJECTED"]

    review_notes: Optional[str] = Field(None, max_length=2000)


class InspectionRequest(BaseModel):

    inspection_notes: str = Field(
        ...,
        min_length=3,
        max_length=2000
    )

    inspection_passed: bool


class RefundReviewRequest(BaseModel):

    decision: Literal["APPROVED", "REJECTED"]

    review_notes: Optional[str] = Field(None, max_length=2000)

    approved_amount: Optional[float] = Field(None, gt=0)

    currency: Optional[str] = Field(
        None,
        min_length=3,
        max_length=3
    )



class ProcessRefundRequest(BaseModel):

    transaction_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200
    )

    # Prototype only. Not a real gateway verification.
    payment_gateway_confirmed: bool



# ==========================================
# 9. RESPONSE SCHEMAS
# ==========================================

class ErrorResponse(BaseModel):

    status: str = "error"

    detail: str


class TokenResponse(BaseModel):

    access_token: str

    token_type: str = "bearer"


class UserResponse(BaseModel):

    user_id: str

    email: str

    role: str

    customer_unique_id: Optional[str] = None


class ChatResponse(BaseModel):

    status: str

    conversation_id: str

    customer_message: str

    predicted_intent: str

    intent_confidence: float

    top_predictions: list[dict]

    assistant_response: str
    policy_sources: list[str] = Field(default_factory=list)
    support_case: dict | None = None


class SupportCaseDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]


class ReturnCreatedResponse(BaseModel):

    request_id: str

    order_id: str

    request_type: str

    status: str

    created_at: str

    message: str
    already_exists: bool = False


# ==========================================
# 10. HOME AND HEALTH
# ==========================================

@app.get(
    "/",
    tags=["General"]
)
def home():

    return {
        "status": "success",
        "message": "AI Customer Support Agent API is running!"
    }


@app.get(
    "/health",
    tags=["General"]
)
def health_check():

    connection = None

    try:

        connection = get_connection()

        connection.execute("SELECT 1").fetchone()

        return {
            "status": "healthy",
            "database": "available"
        }

    except Exception:

        logger.exception("Health check failed")

        raise HTTPException(
            status_code=503,
            detail="Database unavailable."
        )

    finally:

        if connection:
            connection.close()


@app.get("/ready", tags=["General"])
def readiness():
    checks = {"orders": False, "ollama": False}
    try:
        with closing(get_order_connection()) as connection:
            connection.execute("SELECT 1 FROM orders LIMIT 1").fetchone()
        checks["orders"] = True
    except (OSError, sqlite3.Error):
        pass
    try:
        model_list = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=(1, 2))
        model_list.raise_for_status()
        models = model_list.json().get("models", [])
        names = {model.get("name") for model in models}
        checks["ollama"] = OLLAMA_MODEL in names or f"{OLLAMA_MODEL}:latest" in names
    except (requests.RequestException, TypeError, AttributeError, ValueError):
        pass
    available = all(checks.values())
    return JSONResponse(
        status_code=200 if available else 503,
        content={"status": "ready" if available else "degraded", "checks": checks},
    )


@app.get("/staff/analytics", tags=["Audit"])
def support_analytics(user: dict = Depends(require_roles(*STAFF_ROLES))):
    return {
        "chat": conversation_statistics(),
        "returns": get_return_request_statistics(),
        "refunds": get_refund_statistics(),
    }


@app.get("/admin/metrics", tags=["Audit"])
def admin_metrics(user: dict = Depends(require_roles(ROLE_ADMIN))):
    return {"requests": request_metrics(), "assistant": assistant_metrics()}


@app.get("/customers/me/support-cases", tags=["Conversations"])
def my_support_cases(
    limit: int = Query(30, ge=1, le=100),
    user: dict = Depends(require_roles(ROLE_CUSTOMER)),
):
    return {"cases": support_cases.customer_cases(user["user_id"], limit)}


@app.get("/staff/support-cases", tags=["Audit"])
def review_queue(
    status: Literal["PENDING", "APPROVED", "REJECTED"] = "PENDING",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_roles(*STAFF_ROLES)),
):
    return {"cases": support_cases.staff_cases(limit, offset, status)}


@app.post("/staff/support-cases/{case_id}/decision", tags=["Audit"])
def decide_support_case(
    decision: SupportCaseDecision,
    case_id: str = id_path(),
    user: dict = Depends(require_roles(*STAFF_ROLES)),
):
    case, error = support_cases.decide_case(case_id, decision.decision, user)
    if error == "not_found":
        raise HTTPException(404, "Support case not found.")
    if error == "forbidden":
        raise HTTPException(403, "This case requires an admin.")
    if error == "decided":
        raise HTTPException(409, "This case already has a decision.")
    return case


@app.get("/customers/me/preferences", tags=["Conversations"])
def reply_preference(user: dict = Depends(require_roles(ROLE_CUSTOMER))):
    return {"reply_style": get_reply_preference(user["user_id"])}


@app.delete("/customers/me/preferences", tags=["Conversations"], status_code=204)
def clear_reply_preference(user: dict = Depends(require_roles(ROLE_CUSTOMER))):
    set_reply_preference(user["user_id"], None)


@app.get("/customers/me/conversations", tags=["Conversations"])
def customer_conversations(
    limit: int = Query(20, ge=1, le=50),
    user: dict = Depends(require_roles(ROLE_CUSTOMER)),
):
    return {"conversations": list_customer_conversations(user["user_id"], limit)}


# ==========================================
# 11. AUTHENTICATION APIs
# ==========================================


@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=201,
    tags=["Authentication"]
)
def register(request: RegisterRequest, incoming: Request):
    registration_rate_limiter.check(incoming.client.host if incoming.client else "unknown")

    try:
        user = register_user(
            email=request.email,
            password=request.password,
            username=request.full_name,
            role=ROLE_CUSTOMER,
            customer_unique_id=None
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    return UserResponse(
        user_id=str(user["user_id"]),
        email=user["email"],
        role=user["role"],
        customer_unique_id=user.get("customer_unique_id")
    )



@app.post(
    "/auth/login",
    response_model=TokenResponse,
    tags=["Authentication"]
)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends()
):
    login_rate_limiter.check(request.client.host if request.client else "unknown")
    user = authenticate_user(
        form_data.username,
        form_data.password
    )

    if user is None:

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return TokenResponse(
        access_token=create_access_token(user)
    )

@app.get(
    "/auth/me",
    response_model=UserResponse,
    tags=["Authentication"],
    responses=COMMON_RESPONSES
)
def current_user_details(
    user: dict = Depends(get_current_user)
):

    return UserResponse(
        user_id=str(user["user_id"]),
        email=user["email"],
        role=user["role"],
        customer_unique_id=user.get("customer_unique_id")
    )


@app.put(
    "/admin/customers/{user_id}/order-profile",
    response_model=UserResponse,
    tags=["Authentication"],
    responses=COMMON_RESPONSES,
    summary="Link an independently verified customer order profile",
)
def link_order_profile(
    body: LinkCustomerRequest,
    user_id: str = id_path(),
    user: dict = Depends(require_roles(ROLE_ADMIN)),
):
    if not customer_identity_exists(body.customer_unique_id):
        raise HTTPException(status_code=404, detail="Order profile not found.")
    result = unwrap(link_customer_identity(user_id, body.customer_unique_id))
    logger.info("Admin %s linked an order profile to account %s.", user["user_id"], user_id)
    return result


# ==========================================
# 12. MAIN CHAT API
# ==========================================

@app.post(
    "/chat",
    response_model=ChatResponse,
    tags=["Chat"],
    responses=COMMON_RESPONSES
)
def chat(
    request: ChatRequest,
    user: dict = Depends(require_roles(ROLE_CUSTOMER))
):
    chat_rate_limiter.check(user["user_id"])
    if request.conversation_id is None:

        conversation_id = create_conversation(
            customer_id=user["user_id"]
        )

    else:

        conversation_id = request.conversation_id

        assert_conversation_access(
            conversation_id,
            user
        )

    try:

        # Step 1: Intent classification

        masked_message = mask_text(request.message)
        intent_result = predict_intent(masked_message)

        predicted_intent = intent_result["intent"]

        intent_confidence = intent_result["confidence"]

        top_predictions = intent_result["top_predictions"]

        # Step 2: Save customer message

        add_message(
            conversation_id,
            "user",
            masked_message
        )

        # Step 3: Retrieve conversation history

        history = get_recent_history(
            conversation_id,
            limit=10
        )

        # Step 5: Add intent context

        intent_context = {
            "role": "system",
            "content": (
                "Customer intent classification:\n"
                f"Predicted intent: {predicted_intent}\n"
                f"Confidence: {intent_confidence}\n"
                "Use this prediction as a helpful hint, not as "
                "an unquestionable fact. If the customer's message "
                "is ambiguous, ask a clarifying question. "
                "Do not invent order, refund, payment or delivery "
                "information."
            )
        }

        history.insert(0, intent_context)

        # Step 7: Generate response

        result = answer_chat(history, user, conversation_id, predicted_intent, intent_confidence)
        answer = mask_text(result["answer"])

        # Step 8: Save assistant response

        add_message(
            conversation_id,
            "assistant",
            answer
        )

        # Step 9: Return response

        return ChatResponse(
            status="success",
            conversation_id=conversation_id,
            customer_message=masked_message,
            predicted_intent=predicted_intent,
            intent_confidence=intent_confidence,
            top_predictions=top_predictions,
            assistant_response=answer,
            policy_sources=result.get("sources", []),
            support_case=result.get("case"),
        )

    except HTTPException:
        raise

    except RuntimeError:

        logger.exception("Chat service unavailable")

        raise HTTPException(
            status_code=503,
            detail="Chat service temporarily unavailable."
        )

    except Exception:

        logger.exception("Chat processing failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to process the message."
        )


# ==========================================
# 13. INTENT PREDICTION API
# ==========================================

@app.post(
    "/predict-intent",
    tags=["Chat"],
    responses={**COMMON_RESPONSES, 429: {"model": ErrorResponse}}
)
def intent_prediction(
    request: IntentRequest,
    user: dict = Depends(get_current_user)
):

    intent_rate_limiter.check(str(user["user_id"]))

    try:

        result = predict_intent(request.message)

        return {
            "status": "success",
            "customer_message": request.message,
            **result
        }

    except ValueError as error:

        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception:

        logger.exception("Intent prediction failed")

        raise HTTPException(
            status_code=500,
            detail="Intent prediction failed."
        )


# ==========================================
# 14. CONVERSATIONS AND CUSTOMER MEMORY
# ==========================================

@app.get(
    "/conversation/{conversation_id}",
    tags=["Conversations"],
    responses=COMMON_RESPONSES
)
def conversation_details(
    conversation_id: str = Path(
        ...,
        min_length=1,
        max_length=100
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user)
):

    # Verify that the conversation exists
    # and the authenticated user has access.
    assert_conversation_access(
        conversation_id,
        user,
        allow_staff=True
    )

    # Retrieve conversation history.
    history, total_messages = get_conversation_page(conversation_id, limit, offset)

    return {
        "conversation_id": conversation_id,
        "total_messages": total_messages,
        "limit": limit,
        "offset": offset,
        "messages": mask_tool_data(history)
    }

@app.get(
    "/customer-memory/{conversation_id}",
    tags=["Conversations"],
    responses=COMMON_RESPONSES
)
def customer_memory_details(
    conversation_id: str = Path(
        ...,
        min_length=1,
        max_length=100
    ),
    user: dict = Depends(get_current_user)
):

    # Verify conversation ownership and access.
    assert_conversation_access(
        conversation_id,
        user,
        allow_staff=True
    )

    # Retrieve customer memory.
    customer_memory = get_customer_memory(conversation_id)

    return {
        "conversation_id": conversation_id,
        "customer_memory": mask_tool_data(customer_memory)
    }

# ==========================================
# 15. ORDER APIs
# ==========================================
@app.get(
    "/orders/{order_id}",
    tags=["Orders"],
    responses=COMMON_RESPONSES
)
def order_details(
    order_id: str = Path(
        ...,
        min_length=1,
        max_length=100
    ),
    user: dict = Depends(get_current_user)
):
    try:
        result = get_order_details(order_id)

        if result is None or (
            not is_staff(user)
            and not customer_owns(
                user,
                result["order"].get("customer_unique_id")
            )
        ):
            raise HTTPException(
                status_code=404,
                detail="Order not found."
            )

        return {
            "status": "success",
            "order_details": result
        }

    except HTTPException:
        raise

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

@app.get(
    "/customers/me/orders",
    tags=["Orders"],
    responses=COMMON_RESPONSES
)
def my_orders(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_roles(ROLE_CUSTOMER))
):

    customer_id = user.get("customer_unique_id")

    if not customer_id:

        raise HTTPException(
            status_code=409,
            detail="Customer profile is not linked to this account."
        )

    orders = get_customer_orders(
        customer_id,
        limit=limit,
        offset=offset
    )

    return {
        "status": "success",
        "limit": limit,
        "offset": offset,
        "orders": orders
    }


@app.post(
    "/returns",
    response_model=ReturnCreatedResponse,
    status_code=201,
    tags=["Returns"],
    responses=COMMON_RESPONSES
)
def create_return(
    request: CreateReturnRequest,
    response: Response,
    user: dict = Depends(require_roles(ROLE_CUSTOMER))
):

    # --------------------------------------
    # 1. GET AUTHENTICATED CUSTOMER ID
    # --------------------------------------

    customer_id = user.get("customer_unique_id")

    if not customer_id:
        raise HTTPException(
            status_code=409,
            detail="Customer profile is not linked to this account."
        )

    # --------------------------------------
    # 2. FETCH ORDER DETAILS
    # --------------------------------------

    order = get_order_details(request.order_id)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found."
        )

    # --------------------------------------
    # 3. VERIFY ORDER OWNERSHIP
    # --------------------------------------

    order_customer_id = (
        order.get("order", {}).get("customer_unique_id")
    )

    if not customer_owns(user, order_customer_id):
        raise HTTPException(
            status_code=404,
            detail="Order not found."
        )

    # --------------------------------------
    # 4. VALIDATE RETURN ELIGIBILITY
    # --------------------------------------

    eligibility = validate_return_eligibility(
        order_details=order,
        reason=request.reason,
        evidence_reference=request.evidence_reference
    )

    if not eligibility.get("eligible", False):
        raise HTTPException(
            status_code=409,
            detail={
                "status": "NOT_ELIGIBLE",
                "message": (
                    "The return request cannot be created "
                    "because eligibility validation failed."
                ),
                "eligibility": eligibility
            }
        )

    # --------------------------------------
    # 5. CREATE RETURN REQUEST
    # --------------------------------------

    result = create_return_request(
        order_id=request.order_id,
        request_type="RETURN",
        reason=request.reason,
        description=request.description,
        customer_unique_id=customer_id,
        evidence_reference=request.evidence_reference,
        prevent_duplicate=True
    )

    # --------------------------------------
    # 6. VERIFY CREATION RESULT
    # --------------------------------------

    if not isinstance(result, dict) or not result.get("request_id"):
        raise HTTPException(
            status_code=500,
            detail="Return request creation could not be verified."
        )

    # --------------------------------------
    # 7. RETURN RESPONSE
    # --------------------------------------

    if result["already_exists"]:
        response.status_code = 200
    return ReturnCreatedResponse(**result)


@app.get(
    "/customers/me/returns",
    tags=["Returns"],
    responses=COMMON_RESPONSES
)
def my_returns(
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_roles(ROLE_CUSTOMER))
):

    customer_id = user.get("customer_unique_id")

    if not customer_id:

        raise HTTPException(
            status_code=409,
            detail="Customer profile is not linked to this account."
        )

    customer_returns, total = get_customer_return_page(customer_id, limit, offset)
    return {
        "status": "success",
        "total_returns": total,
        "limit": limit,
        "offset": offset,
        "return_requests": customer_returns,
    }


@app.get(
    "/returns",
    tags=["Returns"],
    responses=COMMON_RESPONSES
)
def list_returns(
    status: Optional[str] = Query(None, max_length=30),
    user: dict = Depends(require_roles(*STAFF_ROLES))
):

    return {
        "status": "success",
        "return_requests": get_all_return_requests(status)
    }


@app.get(
    "/returns/{request_id}",
    tags=["Returns"],
    responses=COMMON_RESPONSES
)
def view_return(
    request_id: str = id_path(),
    user: dict = Depends(get_current_user)
):

    load_return_for_user(request_id, user)

    return unwrap(
        get_return_request_summary(request_id)
    )


@app.post(
    "/returns/{request_id}/review",
    tags=["Returns"],
    responses=COMMON_RESPONSES
)
def review_return(
    body: ReviewDecisionRequest,
    request_id: str = id_path(),
    user: dict = Depends(require_roles(*STAFF_ROLES))
):

    return unwrap(
        review_return_request(
            request_id=request_id,
            reviewer=actor(user),
            decision=body.decision,
            review_notes=body.review_notes
        )
    )

@app.post(
    "/returns/{request_id}/cancel",
    tags=["Returns"],
    summary="Cancel a pending return request"
)
def cancel_return(
    request_id: str = id_path(),
    user: dict = Depends(require_roles(ROLE_CUSTOMER))
):
    customer_id = user.get("customer_unique_id")

    if not customer_id:
        raise HTTPException(
            status_code=409,
            detail="Customer account is not linked to an Olist customer."
        )

    return unwrap(
        cancel_return_request(
            request_id=request_id,
            customer_unique_id=customer_id,
            cancelled_by=actor(user)
        )
    )
# ==========================================
# 17. REFUND APIs
# ==========================================


@app.post(
    "/returns/{request_id}/refund",
    status_code=201,
    tags=["Refunds"],
    responses=COMMON_RESPONSES
)
def create_refund_for_return(
    request_id: str = id_path(),
    user: dict = Depends(require_roles(*STAFF_ROLES))
):

    return unwrap(
        create_refund_record(
            return_request_id=request_id,
            created_by=actor(user)
        )
    )



@app.get(
    "/refunds",
    tags=["Refunds"],
    responses=COMMON_RESPONSES
)
def list_refunds(
    status: Optional[str] = Query(None, max_length=30),
    user: dict = Depends(require_roles(*STAFF_ROLES))
):

    return {
        "status": "success",
        "refunds": get_all_refund_records(status),
        "demo_refunds_enabled": DEMO_REFUNDS_ENABLED,
    }


@app.get(
    "/refunds/{refund_id}",
    tags=["Refunds"],
    responses=COMMON_RESPONSES
)
def view_refund(
    refund_id: str = Path(
        ...,
        min_length=1,
        max_length=100
    ),
    user: dict = Depends(get_current_user)
):

    refund = get_refund_record(refund_id)

    if refund is None:

        raise HTTPException(
            status_code=404,
            detail="Refund record not found."
        )

    if not is_staff(user):

        load_return_for_user(
            refund["return_request_id"],
            user
        )

    return {
        "status": "success",
        "refund": refund
    }
#  ADD NEW ENDPOINT HERE

@app.get(
    "/refunds/{refund_id}/attempts",
    tags=["Refunds"],
    summary="Get refund processing attempt history",
    description=(
        "Retrieve failed and successful processing attempts "
        "for a refund. Accessible to support agents and admins."
    )
)
def get_refund_attempt_history(
    refund_id: str = id_path(),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_roles(*STAFF_ROLES))
):
    return unwrap(
        get_refund_processing_attempts(
            refund_id=refund_id,
            limit=limit,
            offset=offset
        )
    )

@app.post(
    "/refunds/{refund_id}/receive",
    tags=["Refunds"],
    responses=COMMON_RESPONSES
)
def receive_returned_product(
    refund_id: str = id_path(),
    user: dict = Depends(require_roles(*STAFF_ROLES))
):

    return unwrap(
        record_product_receipt(
            refund_id=refund_id,
            received_by=actor(user)
        )
    )


@app.post(
    "/refunds/{refund_id}/inspect",
    tags=["Refunds"],
    responses=COMMON_RESPONSES
)
def inspect_returned_product(
    body: InspectionRequest,
    refund_id: str = Path(
        ...,
        min_length=1,
        max_length=100
    ),
    user: dict = Depends(require_roles(*STAFF_ROLES))
):

    return unwrap(
        record_product_inspection(
            refund_id=refund_id,
            inspected_by=actor(user),
            inspection_notes=body.inspection_notes,
            inspection_passed=body.inspection_passed
        )
    )


@app.post(
    "/refunds/{refund_id}/review",
    tags=["Refunds"],
    responses=COMMON_RESPONSES
)
def review_refund(
    body: RefundReviewRequest,
    refund_id: str = Path(
        ...,
        min_length=1,
        max_length=100
    ),
    user: dict = Depends(require_roles(ROLE_ADMIN))
):
    currency = body.currency
    verified_order_total = None
    if body.decision == "APPROVED":
        refund = unwrap(get_refund_record(refund_id))
        return_request = unwrap(get_return_request(refund["return_request_id"]))
        order = get_order_details(return_request["order_id"])
        if not order or not order["payments"]:
            raise HTTPException(status_code=409, detail="Verified order payments are unavailable.")
        currency = (currency or order["currency"]).upper()
        try:
            amount = Decimal(str(body.approved_amount))
            total_paid = Decimal(str(order["summary"]["total_paid"]))
            valid_amount = (
                amount.is_finite() and 0 < amount <= total_paid
                and amount == amount.quantize(Decimal("0.01"))
            )
        except InvalidOperation:
            valid_amount = False
        if currency != order["currency"] or not valid_amount:
            raise HTTPException(
                status_code=409,
                detail="Refund amount and currency must match the order's refundable payment balance.",
            )
        verified_order_total = total_paid

    return unwrap(
        review_refund_record(
            refund_id=refund_id,
            reviewer=actor(user),
            decision=body.decision,
            review_notes=body.review_notes,
            approved_amount=body.approved_amount,
            currency=currency,
            verified_order_total=verified_order_total
        )
    )



@app.post(
    "/refunds/{refund_id}/process",
    tags=["Refunds"],
    responses=COMMON_RESPONSES
)
def process_refund(
    body: ProcessRefundRequest,
    refund_id: str = Path(
        ...,
        min_length=1,
        max_length=100
    ),
    user: dict = Depends(require_roles(ROLE_ADMIN))
):
    if not DEMO_REFUNDS_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Refund processing requires a configured payment provider or explicit demo mode.",
        )
    result = unwrap(
        process_refund_record(
            refund_id=refund_id,
            transaction_id=body.transaction_id,
            payment_gateway_confirmed=body.payment_gateway_confirmed,
            processed_by=actor(user)
        )
    )
    return {**result, "mode": "demo"}



# ==========================================
# 18. AUDIT LOG API
# ==========================================

@app.get(
    "/audit-logs",
    tags=["Audit"],
    responses=COMMON_RESPONSES
)
def audit_logs(
    request_id: Optional[str] = Query(None, max_length=100),
    refund_id: Optional[str] = Query(None, max_length=100),
    performed_by: Optional[str] = Query(None, max_length=254),
    action: Optional[str] = Query(None, max_length=100),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_roles(ROLE_ADMIN))
):

    logs = get_return_refund_audit_logs(
        request_id=request_id,
        refund_id=refund_id,
        performed_by=performed_by,
        action=action,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset
    )

    return {
        "status": "success",
        "page_count": len(logs),
        "logs": logs,
        "limit": limit,
        "offset": offset
    }
