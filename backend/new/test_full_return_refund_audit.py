
import tempfile
from pathlib import Path

from backend import return_requests as rr


def run_full_workflow_audit_test():

    original_db_path = rr.DB_PATH

    try:
        with tempfile.TemporaryDirectory() as temp_dir:

            # Use an isolated test database
            rr.DB_PATH = Path(temp_dir) / "test_full_audit.db"

            rr.initialize_database()

            print("\n========== FULL WORKFLOW AUDIT TEST ==========\n")

            # ----------------------------------
            # 1. CREATE RETURN REQUEST
            # ----------------------------------
            result = rr.create_return_request(
                order_id="TEST_ORDER_001",
                request_type="RETURN",
                reason="Damaged product",
                description="Product received in damaged condition.",
                customer_unique_id="TEST_CUSTOMER_001",
                evidence_reference="test_damage_photo.jpg"
            )

            assert result["request_id"]
            request_id = result["request_id"]

            print("PASS: Return request created")

            # ----------------------------------
            # 2. APPROVE RETURN REQUEST
            # ----------------------------------
            result = rr.review_return_request(
                request_id=request_id,
                reviewer="TEST_REVIEWER",
                decision="APPROVED",
                review_notes="Return approved for testing."
            )

            assert result["success"] is True

            print("PASS: Return request approved")

            # ----------------------------------
            # 3. CREATE REFUND RECORD
            # ----------------------------------
            result = rr.create_refund_record(
                return_request_id=request_id
            )

            assert result["success"] is True

            refund_id = result["refund_id"]

            print("PASS: Refund record created")

            # ----------------------------------
            # 4. RECORD PRODUCT RECEIPT
            # ----------------------------------
            result = rr.record_product_receipt(
                refund_id=refund_id,
                received_by="TEST_WAREHOUSE_STAFF"
            )

            assert result["success"] is True

            print("PASS: Product receipt recorded")

            # ----------------------------------
            # 5. RECORD PRODUCT INSPECTION
            # ----------------------------------
            result = rr.record_product_inspection(
                refund_id=refund_id,
                inspected_by="TEST_INSPECTOR",
                inspection_notes="Product inspection passed.",
                inspection_passed=True
            )

            assert result["success"] is True

            print("PASS: Product inspection completed")

            # ----------------------------------
            # 6. APPROVE REFUND
            # ----------------------------------
            result = rr.review_refund_record(
                refund_id=refund_id,
                reviewer="TEST_REFUND_REVIEWER",
                decision="APPROVED",
                review_notes="Refund approved for testing.",
                approved_amount=100.0,
                currency="BRL"
            )

            assert result["success"] is True

            print("PASS: Refund approved")

            # ----------------------------------
            # 7. PROCESS REFUND
            # ----------------------------------
            result = rr.process_refund_record(
                refund_id=refund_id,
                transaction_id="TEST_TXN_001",
                payment_gateway_confirmed=True,
                processed_by="test_processor"
            )

            assert result["success"] is True

            print("PASS: Refund processed")

            # ----------------------------------
            # 8. VERIFY AUDIT LOGS
            # ----------------------------------
            logs = rr.get_return_refund_audit_logs(
                request_id=request_id,
                refund_id=refund_id
            )

            actions = [log["action"] for log in logs]

            expected_actions = [
                "RETURN_REQUEST_CREATED",
                "RETURN_REQUEST_APPROVED",
                "REFUND_RECORD_CREATED",
                "PRODUCT_RECEIVED",
                "PRODUCT_INSPECTION_PASSED",
                "REFUND_APPROVED",
                "RETURN_REQUEST_COMPLETED",
                "REFUND_PROCESSED"
            ]

            print("\n========== AUDIT LOG RESULTS ==========")

            print("Total audit logs:", len(logs))
            print("Recorded actions:", actions)

            assert len(logs) == len(expected_actions), (
                f"Expected {len(expected_actions)} audit logs, received {len(logs)}"
            )

            assert set(actions) == set(expected_actions), (
                "One or more expected audit actions are missing."
            )

            print("\nPASS: All workflow audit actions recorded")

            # ----------------------------------
            # 9. VERIFY FINAL REFUND STATUS
            # ----------------------------------
            connection = rr.get_connection()

            try:
                cursor = connection.cursor()

                cursor.execute("""
                    SELECT status, transaction_id, approved_amount, currency
                    FROM refund_records
                    WHERE refund_id = ?
                """, (refund_id,))

                refund = dict(cursor.fetchone())

            finally:
                connection.close()

            assert refund["status"] == "COMPLETED"
            assert refund["transaction_id"] == "TEST_TXN_001"
            assert refund["approved_amount"] == 100.0
            assert refund["currency"] == "BRL"

            print("PASS: Final refund status verified")

            print("\n========================================")
            print("ALL FULL WORKFLOW AUDIT TESTS PASSED")
            print("========================================")

    finally:
        rr.DB_PATH = original_db_path


if __name__ == "__main__":
    run_full_workflow_audit_test()
