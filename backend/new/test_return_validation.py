from datetime import date

from backend.database_tools import get_order_details

from backend.return_validation import (
    validate_return_eligibility
)


if __name__ == "__main__":
    ORDER_ID = "e481f51cbdc54678b7cc49136f2d6af7"

    order_details = get_order_details(ORDER_ID)

    if order_details is None:
        raise RuntimeError("Test order not found.")


    # ==========================================
    # TEST 1: WITHIN SEVEN DAYS + EVIDENCE
    # ==========================================

    print("\nTEST 1: VALID RETURN REQUEST")

    result = validate_return_eligibility(
        order_details=order_details,
        reason="Damaged product received",
        evidence_reference="test_damage_photo_001",
        reference_date=date(2017, 10, 15)
    )

    print(result)

    assert result["eligible"] is True
    assert result["days_since_delivery"] == 5

    print("PASSED")


    # ==========================================
    # TEST 2: OUTSIDE SEVEN DAYS
    # ==========================================

    print("\nTEST 2: EXPIRED RETURN WINDOW")

    result = validate_return_eligibility(
        order_details=order_details,
        reason="Damaged product received",
        evidence_reference="test_damage_photo_001",
        reference_date=date(2017, 10, 20)
    )

    print(result)

    assert result["eligible"] is False
    assert any(
        "expired" in error.lower()
        for error in result["errors"]
    )

    print("PASSED")


    # ==========================================
    # TEST 3: MISSING EVIDENCE
    # ==========================================

    print("\nTEST 3: MISSING DAMAGE EVIDENCE")

    result = validate_return_eligibility(
        order_details=order_details,
        reason="Damaged product received",
        reference_date=date(2017, 10, 15)
    )

    print(result)

    assert result["eligible"] is False
    assert any(
        "evidence" in error.lower()
        for error in result["errors"]
    )

    print("PASSED")


    # ==========================================
    # TEST 4: CURRENT DATE
    # ==========================================

    print("\nTEST 4: HISTORICAL ORDER AGAINST CURRENT DATE")

    result = validate_return_eligibility(
        order_details=order_details,
        reason="Damaged product received",
        evidence_reference="test_damage_photo_001"
    )

    print(result)

    assert result["eligible"] is False

    print("PASSED")


    # ==========================================
    # FINAL RESULT
    # ==========================================

    print("\n" + "=" * 50)
    print("ALL RETURN VALIDATION TESTS PASSED")
    print("=" * 50)
