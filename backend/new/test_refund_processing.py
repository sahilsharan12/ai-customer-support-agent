
import uuid

from backend.return_requests import (
    get_connection,
    create_return_request,
    review_return_request,
    create_refund_record,
    record_product_receipt,
    record_product_inspection,
    review_refund_record,
    process_refund_record
)


def setup_approved_refund():

    unique_order_id = f"TEST-PROCESS-{uuid.uuid4().hex[:8]}"

    # 1. Create return request
    request = create_return_request(
        order_id=unique_order_id,
        request_type="RETURN",
        reason="Damaged product"
    )

    # 2. Approve return request
    review_return_request(
        request_id=request["request_id"],
        reviewer="test_admin",
        decision="APPROVED",
        review_notes="Return approved for testing."
    )

    # 3. Create refund record
    refund = create_refund_record(
        return_request_id=request["request_id"]
    )

    refund_id = refund["refund_id"]

    # 4. Record product receipt
    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    # 5. Record successful inspection
    record_product_inspection(
        refund_id=refund_id,
        inspected_by="quality_team",
        inspection_notes="Product passed inspection.",
        inspection_passed=True
    )

    # 6. Human approves refund
    review_refund_record(
        refund_id=refund_id,
        reviewer="finance_admin",
        decision="APPROVED",
        review_notes="Refund approved.",
        approved_amount=150.50,
        currency="BRL"
    )

    return refund_id

def test_processing_before_approval_blocked():

    unique_order_id = f"TEST-BLOCK-{uuid.uuid4().hex[:8]}"

    # 1. Create return request
    request = create_return_request(
        order_id=unique_order_id,
        request_type="RETURN",
        reason="Damaged product"
    )

    # 2. Approve return request
    review_return_request(
        request_id=request["request_id"],
        reviewer="test_admin",
        decision="APPROVED",
        review_notes="Return approved for testing."
    )

    # 3. Create refund record
    refund = create_refund_record(
        return_request_id=request["request_id"]
    )

    assert refund["success"] is True

    # 4. Try processing without refund approval
    result = process_refund_record(
        refund_id=refund["refund_id"],
        transaction_id="TXN-TEST-001",
        payment_gateway_confirmed=True,
        processed_by="test_processor"
    )

    assert result["success"] is False

    print("PASS: Processing before refund approval blocked.")


def test_gateway_confirmation_required():

    refund_id = setup_approved_refund()

    result = process_refund_record(
        refund_id=refund_id,
        transaction_id="TXN-TEST-002",
        payment_gateway_confirmed=False,
        processed_by="test_processor"
    )

    assert result["success"] is False

    # Verify refund is still approved
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT status, transaction_id
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        record = cursor.fetchone()

        assert record["status"] == "APPROVED"
        assert record["transaction_id"] is None

    finally:
        connection.close()

    print("PASS: Refund remains approved without gateway confirmation.")


def test_successful_refund_processing():

    refund_id = setup_approved_refund()

    result = process_refund_record(
        refund_id=refund_id,
        transaction_id="TXN-TEST-SUCCESS-001",
        payment_gateway_confirmed=True,
        processed_by="test_processor"
    )

    assert result["success"] is True
    assert result["status"] == "COMPLETED"
    assert result["transaction_id"] == "TXN-TEST-SUCCESS-001"
    assert result["approved_amount"] == 150.50
    assert result["currency"] == "BRL"

    print("PASS: Approved refund marked completed.")


def test_duplicate_processing_blocked():

    refund_id = setup_approved_refund()

    first_result = process_refund_record(
        refund_id=refund_id,
        transaction_id="TXN-TEST-DUPLICATE-001",
        payment_gateway_confirmed=True,
        processed_by="test_processor"
    )

    assert first_result["success"] is True

    second_result = process_refund_record(
        refund_id=refund_id,
        transaction_id="TXN-TEST-DUPLICATE-002",
        payment_gateway_confirmed=True,
        processed_by="test_processor"
    )

    assert second_result["success"] is False

    print("PASS: Duplicate refund processing blocked.")


def test_completed_refund_database_record():

    refund_id = setup_approved_refund()

    process_refund_record(
        refund_id=refund_id,
        transaction_id="TXN-TEST-DB-001",
        payment_gateway_confirmed=True,
        processed_by="test_processor"
    )

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT *
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        record = dict(cursor.fetchone())

        assert record["status"] == "COMPLETED"
        assert record["transaction_id"] == "TXN-TEST-DB-001"
        assert record["processed_at"] is not None
        assert record["approved_amount"] == 150.50
        assert record["currency"] == "BRL"

        print("PASS: Completed refund details verified in database.")

    finally:

        connection.close()


if __name__ == "__main__":

    print("\n========== REFUND PROCESSING TESTS ==========\n")

    test_processing_before_approval_blocked()

    test_gateway_confirmation_required()

    test_successful_refund_processing()

    test_duplicate_processing_blocked()

    test_completed_refund_database_record()

    print("\n========== ALL TESTS PASSED ==========\n")
