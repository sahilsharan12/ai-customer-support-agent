
import sqlite3

from backend.return_requests import (
    get_connection,
    create_return_request,
    review_return_request,
    create_refund_record,
    record_product_receipt,
    record_product_inspection
)


def setup_refund_record():

    request = create_return_request(
        order_id="TEST-INSPECTION-001",
        request_type="RETURN",
        reason="Damaged product"
    )

    review = review_return_request(
        request_id=request["request_id"],
        reviewer="test_admin",
        decision="APPROVED",
        review_notes="Test return approval"
    )

    refund = create_refund_record(
        return_request_id=request["request_id"]
    )

    return refund["refund_id"]


def test_inspection_before_receipt():

    refund_id = setup_refund_record()

    result = record_product_inspection(
        refund_id=refund_id,
        inspected_by="test_inspector",
        inspection_notes="Product condition checked",
        inspection_passed=True
    )

    assert result["success"] is False

    print("PASS: Inspection before receipt blocked.")


def test_product_receipt():

    refund_id = setup_refund_record()

    result = record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    assert result["success"] is True
    assert result["product_received"] is True

    print("PASS: Product receipt recorded.")


def test_duplicate_receipt_blocked():

    refund_id = setup_refund_record()

    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    result = record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    assert result["success"] is False

    print("PASS: Duplicate receipt blocked.")


def test_product_inspection():

    refund_id = setup_refund_record()

    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    result = record_product_inspection(
        refund_id=refund_id,
        inspected_by="quality_team",
        inspection_notes="Product is damaged.",
        inspection_passed=False
    )

    assert result["success"] is True
    assert result["inspection_passed"] is False

    print("PASS: Failed inspection recorded correctly.")

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT *
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        record = dict(cursor.fetchone())

        assert record["product_received"] == 1
        assert record["inspected"] == 1
        assert record["inspection_passed"] == 0
        assert record["received_at"] is not None
        assert record["inspected_at"] is not None
        assert record["received_by"] == "warehouse_team"
        assert record["inspected_by"] == "quality_team"

        print("PASS: Database inspection details verified.")

    finally:
        connection.close()


def test_duplicate_inspection_blocked():

    refund_id = setup_refund_record()

    record_product_receipt(
        refund_id=refund_id,
        received_by="warehouse_team"
    )

    record_product_inspection(
        refund_id=refund_id,
        inspected_by="quality_team",
        inspection_notes="Product is okay.",
        inspection_passed=True
    )

    result = record_product_inspection(
        refund_id=refund_id,
        inspected_by="quality_team",
        inspection_notes="Second inspection",
        inspection_passed=True
    )

    assert result["success"] is False

    print("PASS: Duplicate inspection blocked.")


if __name__ == "__main__":

    print("\n========== PRODUCT INSPECTION TESTS ==========\n")

    test_inspection_before_receipt()
    test_product_receipt()
    test_duplicate_receipt_blocked()
    test_product_inspection()
    test_duplicate_inspection_blocked()

    print("\n========== ALL TESTS PASSED ==========\n")
