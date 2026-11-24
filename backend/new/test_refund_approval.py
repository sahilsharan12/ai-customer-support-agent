
import uuid

from backend.return_requests import (
    get_connection,
    create_return_request,
    review_return_request,
    create_refund_record,
    record_product_receipt,
    record_product_inspection,
    review_refund_record
)


def setup_refund_record():

    unique_order_id = f"TEST-APPROVAL-{uuid.uuid4().hex[:8]}"

    request = create_return_request(
        order_id=unique_order_id,
        request_type="RETURN",
        reason="Damaged product"
    )

    review_return_request(
        request_id=request["request_id"],
        reviewer="test_admin",
        decision="APPROVED",
        review_notes="Test return approval"
    )

    refund = create_refund_record(
        return_request_id=request["request_id"]
    )

    return refund["refund_id"]


def test_approval_before_receipt_blocked():

    refund_id = setup_refund_record()

    result = review_refund_record(
        refund_id=refund_id,
        reviewer="finance_admin",
        decision="APPROVED",
        approved_amount=100.0,
        currency="BRL"
    )

    assert result["success"] is False

    print("PASS: Approval before product receipt blocked.")


def test_approval_before_inspection_blocked():

    refund_id = setup_refund_record()

    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    result = review_refund_record(
        refund_id=refund_id,
        reviewer="finance_admin",
        decision="APPROVED",
        approved_amount=100.0,
        currency="BRL"
    )

    assert result["success"] is False

    print("PASS: Approval before inspection blocked.")


def test_failed_inspection_approval_blocked():

    refund_id = setup_refund_record()

    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    record_product_inspection(
        refund_id=refund_id,
        inspected_by="quality_team",
        inspection_notes="Product is damaged.",
        inspection_passed=False
    )

    result = review_refund_record(
        refund_id=refund_id,
        reviewer="finance_admin",
        decision="APPROVED",
        approved_amount=100.0,
        currency="BRL"
    )

    assert result["success"] is False

    print("PASS: Approval after failed inspection blocked.")


def test_rejection_after_failed_inspection():

    refund_id = setup_refund_record()

    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    record_product_inspection(
        refund_id=refund_id,
        inspected_by="quality_team",
        inspection_notes="Product is damaged and does not meet refund conditions.",
        inspection_passed=False
    )

    result = review_refund_record(
        refund_id=refund_id,
        reviewer="finance_admin",
        decision="REJECTED",
        review_notes="Refund rejected after inspection."
    )

    assert result["success"] is True
    assert result["status"] == "REJECTED"

    print("PASS: Rejection after failed inspection recorded.")


def test_successful_refund_approval():

    refund_id = setup_refund_record()

    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    record_product_inspection(
        refund_id=refund_id,
        inspected_by="quality_team",
        inspection_notes="Product condition verified successfully.",
        inspection_passed=True
    )

    result = review_refund_record(
        refund_id=refund_id,
        reviewer="finance_admin",
        decision="APPROVED",
        review_notes="Refund approved after successful inspection.",
        approved_amount=150.50,
        currency="BRL"
    )

    assert result["success"] is True
    assert result["status"] == "APPROVED"
    assert result["approved_amount"] == 150.50
    assert result["currency"] == "BRL"

    print("PASS: Refund approved after successful inspection.")

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT *
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        record = dict(cursor.fetchone())

        assert record["status"] == "APPROVED"
        assert record["approved_amount"] == 150.50
        assert record["currency"] == "BRL"
        assert record["reviewed_by"] == "finance_admin"
        assert record["reviewed_at"] is not None

        print("PASS: Refund approval details verified in database.")

    finally:

        connection.close()


def test_duplicate_review_blocked():

    refund_id = setup_refund_record()

    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    record_product_inspection(
        refund_id=refund_id,
        inspected_by="quality_team",
        inspection_notes="Product passed inspection.",
        inspection_passed=True
    )

    review_refund_record(
        refund_id=refund_id,
        reviewer="finance_admin",
        decision="APPROVED",
        approved_amount=100.0,
        currency="BRL"
    )

    result = review_refund_record(
        refund_id=refund_id,
        reviewer="another_admin",
        decision="REJECTED",
        review_notes="Second review attempt."
    )

    assert result["success"] is False

    print("PASS: Duplicate refund review blocked.")


if __name__ == "__main__":

    print("\n========== REFUND APPROVAL TESTS ==========\n")

    test_approval_before_receipt_blocked()

    test_approval_before_inspection_blocked()

    test_failed_inspection_approval_blocked()

    test_rejection_after_failed_inspection()

    test_successful_refund_approval()

    test_duplicate_review_blocked()

    print("\n========== ALL TESTS PASSED ==========\n")
