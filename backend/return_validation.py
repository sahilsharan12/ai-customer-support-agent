
from datetime import datetime, date


# ==========================================
# RETURN ELIGIBILITY VALIDATION
# ==========================================

RETURN_WINDOW_DAYS = 7


def validate_return_eligibility(
    order_details: dict,
    reason: str,
    evidence_reference: str = None,
    reference_date: date = None
):
    """
    Validate return eligibility using verified order details.

    reference_date:
        Optional simulation date for historical dataset testing.
        In normal operation, the current date is used.
    """

    errors = []

    # ======================================
    # 1. VALIDATE INPUT
    # ======================================

    if not isinstance(order_details, dict):

        return {
            "eligible": False,
            "errors": ["Invalid order details."]
        }

    order = order_details.get("order", {})

    if not isinstance(order, dict):

        return {
            "eligible": False,
            "errors": ["Order information is unavailable."]
        }

    # ======================================
    # 2. CHECK ORDER STATUS
    # ======================================

    order_status = str(
        order.get("order_status", "")
    ).strip().lower()

    if order_status != "delivered":

        errors.append(
            "Order must have delivered status."
        )

    # ======================================
    # 3. CHECK ACTUAL DELIVERY DATE
    # ======================================

    delivery_value = order.get(
        "order_delivered_customer_date"
    )

    delivery_date = None

    if not delivery_value:

        errors.append(
            "Actual customer delivery date is unavailable."
        )

    else:

        try:

            delivery_date = datetime.fromisoformat(
                str(delivery_value)
            ).date()

        except (ValueError, TypeError):

            errors.append(
                "Invalid actual delivery date."
            )

    # ======================================
    # 4. CHECK SEVEN-DAY RETURN WINDOW
    # ======================================

    if reference_date is None:

        reference_date = date.today()

    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()
    if not isinstance(reference_date, date):
        return {"eligible": False, "errors": [*errors, "Invalid reference date."]}

    if delivery_date and isinstance(reference_date, date):

        days_since_delivery = (
            reference_date - delivery_date
        ).days

        if days_since_delivery < 0:

            errors.append(
                "Reference date cannot be before delivery date."
            )

        elif days_since_delivery > RETURN_WINDOW_DAYS:

            errors.append(
                "Return window of 7 calendar days has expired."
            )

    else:

        days_since_delivery = None

    # ======================================
    # 5. CHECK EVIDENCE FOR DAMAGED PRODUCTS
    # ======================================

    reason_lower = str(reason or "").strip().lower()

    evidence_required_keywords = [
        "damaged",
        "damage",
        "defective",
        "incorrect",
        "wrong product"
    ]

    evidence_required = any(
        keyword in reason_lower
        for keyword in evidence_required_keywords
    )

    if evidence_required:

        if (
            not isinstance(evidence_reference, str)
            or not evidence_reference.strip()
        ):

            errors.append(
                "Supporting photo or evidence reference is required."
            )

    # ======================================
    # 6. FINAL RESULT
    # ======================================

    eligible = len(errors) == 0

    return {
        "eligible": eligible,
        "order_id": order.get("order_id"),
        "order_status": order_status,
        "actual_delivery_date": (
            delivery_date.isoformat()
            if delivery_date else None
        ),
        "reference_date": reference_date.isoformat(),
        "days_since_delivery": days_since_delivery,
        "return_window_days": RETURN_WINDOW_DAYS,
        "evidence_required": evidence_required,
        "evidence_provided": bool(
            isinstance(evidence_reference, str)
            and evidence_reference.strip()
        ),
        "errors": errors
    }
