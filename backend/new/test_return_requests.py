from backend.return_requests import (
    initialize_database,
    create_return_request,
    get_return_request,
    get_all_return_requests,
    review_return_request
)


if __name__ == "__main__":
    # ==========================================
    # 1. INITIALIZE DATABASE
    # ==========================================

    print("\n1. INITIALIZING DATABASE")

    initialize_database()


    # ==========================================
    # 2. CREATE RETURN REQUEST
    # ==========================================

    print("\n2. CREATING RETURN REQUEST")

    return_request = create_return_request(
        order_id="e481f51cbdc54678b7cc49136f2d6af7",
        request_type="RETURN",
        reason="Damaged product received",
        description="The product arrived with visible damage.",
        customer_unique_id="7c396fd4830fd04220f754e42b4e5bff",
        evidence_reference="damage_photo_001.jpg"
    )

    print(return_request)

    request_id = return_request["request_id"]


    # ==========================================
    # 3. RETRIEVE REQUEST
    # ==========================================

    print("\n3. RETRIEVING RETURN REQUEST")

    request_details = get_return_request(request_id)

    print(request_details)

    assert request_details is not None
    assert request_details["status"] == "PENDING_REVIEW"


    # ==========================================
    # 4. HUMAN APPROVAL
    # ==========================================

    print("\n4. APPROVING RETURN REQUEST")

    approval_result = review_return_request(
        request_id=request_id,
        reviewer="support_agent_01",
        decision="APPROVED",
        review_notes="Request reviewed and approved for return."
    )

    print(approval_result)

    assert approval_result["success"] is True
    assert approval_result["status"] == "APPROVED"


    # ==========================================
    # 5. VERIFY APPROVAL
    # ==========================================

    print("\n5. VERIFYING APPROVAL")

    updated_request = get_return_request(request_id)

    print(updated_request)

    assert updated_request["status"] == "APPROVED"
    assert updated_request["reviewer"] == "support_agent_01"


    # ==========================================
    # 6. CREATE ANOTHER REQUEST
    # ==========================================

    print("\n6. CREATING SECOND REQUEST")

    second_request = create_return_request(
        order_id="69923a4e07ce446644394df37a710286",
        request_type="REFUND",
        reason="Incorrect product received",
        description="The received product does not match the order."
    )

    print(second_request)

    second_request_id = second_request["request_id"]


    # ==========================================
    # 7. HUMAN REJECTION
    # ==========================================

    print("\n7. REJECTING SECOND REQUEST")

    rejection_result = review_return_request(
        request_id=second_request_id,
        reviewer="support_agent_02",
        decision="REJECTED",
        review_notes="Request rejected after manual review."
    )

    print(rejection_result)

    assert rejection_result["success"] is True
    assert rejection_result["status"] == "REJECTED"


    # ==========================================
    # 8. PREVENT DUPLICATE REVIEW
    # ==========================================

    print("\n8. TESTING DUPLICATE REVIEW PREVENTION")

    duplicate_review = review_return_request(
        request_id=request_id,
        reviewer="support_agent_02",
        decision="REJECTED",
        review_notes="Attempting a second review."
    )

    print(duplicate_review)

    assert duplicate_review["success"] is False


    # ==========================================
    # 9. DISPLAY ALL REQUESTS
    # ==========================================

    print("\n9. ALL RETURN REQUESTS")

    all_requests = get_all_return_requests()

    for request in all_requests:
        print(
            f"Request ID: {request['request_id']}\n"
            f"Order ID: {request['order_id']}\n"
            f"Type: {request['request_type']}\n"
            f"Status: {request['status']}\n"
            f"Reviewer: {request['reviewer']}\n"
        )


    # ==========================================
    # 10. FINAL RESULT
    # ==========================================

    print("\n" + "=" * 50)
    print("ALL RETURN REQUEST TESTS PASSED")
    print("=" * 50)
