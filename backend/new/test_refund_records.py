from backend.return_requests import (
    create_return_request,
    review_return_request,
    create_refund_record,
    get_return_request
)


if __name__ == "__main__":
    # ==========================================
    # TEST 1: CREATE RETURN REQUEST
    # ==========================================

    print("\nTEST 1: CREATE RETURN REQUEST")

    return_result = create_return_request(
        order_id="TEST-REFUND-ORDER-001",
        request_type="RETURN",
        reason="Damaged product",
        customer_unique_id="TEST-CUSTOMER-001"
    )

    request_id = return_result["request_id"]

    print(return_result)

    assert return_result["status"] == "PENDING_REVIEW"

    print("PASSED: Return request created.")


    # ==========================================
    # TEST 2: TRY REFUND BEFORE APPROVAL
    # ==========================================

    print("\nTEST 2: REFUND BEFORE RETURN APPROVAL")

    result = create_refund_record(request_id)

    print(result)

    assert result["success"] is False

    print("PASSED: Unapproved return blocked.")


    # ==========================================
    # TEST 3: APPROVE RETURN REQUEST
    # ==========================================

    print("\nTEST 3: APPROVE RETURN REQUEST")

    approval_result = review_return_request(
        request_id=request_id,
        reviewer="test_support_agent",
        decision="APPROVED",
        review_notes="Return approved for refund evaluation."
    )

    print(approval_result)

    assert approval_result["success"] is True

    print("PASSED: Return approved.")


    # ==========================================
    # TEST 4: CREATE REFUND RECORD
    # ==========================================

    print("\nTEST 4: CREATE REFUND RECORD")

    refund_result = create_refund_record(request_id)

    print(refund_result)

    assert refund_result["success"] is True

    assert refund_result["status"] == "UNDER_REVIEW"

    assert refund_result["product_received"] is False

    assert refund_result["inspected"] is False

    print("PASSED: Refund record created.")


    # ==========================================
    # TEST 5: PREVENT DUPLICATE REFUND
    # ==========================================

    print("\nTEST 5: PREVENT DUPLICATE REFUND")

    duplicate_result = create_refund_record(request_id)

    print(duplicate_result)

    assert duplicate_result["success"] is False

    print("PASSED: Duplicate refund blocked.")


    # ==========================================
    # FINAL RESULT
    # ==========================================

    print("\n" + "=" * 50)
    print("ALL REFUND RECORD TESTS PASSED")
    print("=" * 50)
