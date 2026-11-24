import re


INJECTION_PATTERNS = (
    r"\b(?:ignore|forget|bypass|override|disregard)\b.{0,55}\b(?:previous|prior|system|developer|security|instructions|rules)\b",
    r"\b(?:reveal|print|show|repeat|dump|expose)\b.{0,45}\b(?:system prompt|developer message|hidden instructions|api keys?)\b",
    r"</?(?:system|developer|tool)(?:\s|>)|\[/?INST\]|<\|(?:im_start|im_end)\|>",
)

REDACTIONS = (
    (r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", "[redacted email]"),
    (r"\b(?:password|passcode|api[ _-]?key|cvv|pin|otp)\s*(?:is\b|[:=])\s*[^\s,;]+", "[redacted secret]"),
    (r"\bBearer\s+[A-Z0-9._\-]{12,}|\beyJ[A-Z0-9_\-]+\.[A-Z0-9_\-]+\.[A-Z0-9_\-]+", "[redacted token]"),
    (r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])", "[redacted card-like number]"),
    (r"(?<![\w-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?![\w-])", "[redacted phone]"),
    (r"\b(?:phone(?: number)?|mobile(?: number)?|ssn|social security number|aadhaar)\s*(?:is\b|[:=])\s*\+?\d[\d ().-]{6,}\d", "[redacted personal number]"),
    (r"\b\d{1,6}\s+(?:[A-Z0-9.'-]+\s+){1,5}(?:street|road|avenue|lane|boulevard|st|rd|ave)\b", "[redacted street address]"),
    (r"(?<![\w-])\d{3}-\d{2}-\d{4}(?![\w-])", "[redacted personal number]"),
)

PRIVATE_TOOL_KEYS = {
    "email", "phone", "password", "customer_id", "customer_unique_id", "user_id",
    "customer_city", "customer_state", "address", "zip_code", "transaction_id",
}


def injection_signal(text: str) -> bool:
    return any(re.search(pattern, text, re.I | re.S) for pattern in INJECTION_PATTERNS)


def mask_text(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def mask_tool_data(value):
    if isinstance(value, dict):
        return {key: mask_tool_data(item) for key, item in value.items()
                if key.casefold() not in PRIVATE_TOOL_KEYS}
    if isinstance(value, list):
        return [mask_tool_data(item) for item in value]
    return mask_text(value) if isinstance(value, str) else value
