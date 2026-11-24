
import tempfile
from pathlib import Path

from backend import return_requests as rr


def test_return_request_audit_logs():

    original_db_path = rr.DB_PATH

    try:
        with tempfile.TemporaryDirectory() as temp_dir:

            # Use a separate temporary database
            rr.DB_PATH = Path(temp_dir) / "test_audit.db"

            rr.initialize_database()

            # =====================================
            # TEST 1: CREATE RETURN REQUEST
            # =====================================

            result = rr.create_return_request(
                order_id="TEST_ORDER_001",
                request_type="RETURN",
                reason="Damaged product",
                customer_unique_id="TEST_CUSTOMER_001"
            )

            assert "request_id" in result

            request_id = result["request_id"]

            print("\nPASS: Return request created")
            print("Request ID:", request_id)

            # =====================================
            # TEST 2: APPROVE RETURN REQUEST
            # =====================================

            review_result = rr.review_return_request(
                request_id=request_id,
                reviewer="TEST_REVIEWER",
                decision="APPROVED",
                review_notes="Test approval"
            )

            assert review_result["success"] is True

            print("PASS: Return request approved")

            # =====================================
            # TEST 3: RETRIEVE AUDIT LOGS
            # =====================================

            logs = rr.get_return_refund_audit_logs(
                request_id=request_id
            )

            print("\n========== AUDIT DEBUG ==========")
            print("Request ID:", request_id)
            print("Total audit logs:", len(logs))
            print("Audit records:", logs)

            actions = [
                log["action"]
                for log in logs
            ]

            print("Recorded actions:", actions)
            print("=================================\n")

            # =====================================
            # TEST 4: VERIFY AUDIT RECORD COUNT
            # =====================================

            assert len(logs) == 2, (
                f"Expected 2 audit logs, "
                f"but received {len(logs)}"
            )

            print("PASS: Correct audit log count")

            # =====================================
            # TEST 5: VERIFY CREATION AUDIT
            # =====================================

            assert "RETURN_REQUEST_CREATED" in actions

            print("PASS: Return creation audit log")

            # =====================================
            # TEST 6: VERIFY APPROVAL AUDIT
            # =====================================

            assert "RETURN_REQUEST_APPROVED" in actions

            print("PASS: Return approval audit log")

            # =====================================
            # TEST 7: VERIFY AUDIT DETAILS
            # =====================================

            for log in logs:

                assert log["request_id"] == request_id
                assert log["performed_by"] is not None
                assert log["created_at"] is not None

            print("PASS: Audit details verified")

            print("\nALL AUDIT TESTS COMPLETED")

    finally:
        rr.DB_PATH = original_db_path


if __name__ == "__main__":
    test_return_request_audit_logs()
