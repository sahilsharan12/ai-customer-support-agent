import sqlite3
import math
import uuid
import re
from datetime import datetime, timezone
from decimal import Decimal
from backend.config import DATA_DIR


# ==========================================
# 1. CONFIGURATION
# ==========================================

DB_PATH = DATA_DIR / "return_requests.db"

MAX_AUDIT_LOG_LIMIT = 500


def _parse_audit_date(value, field_name, end_of_day=False):
    """
    Accepts an ISO date ('2026-01-31'), an ISO datetime
    ('2026-01-31T10:00:00', '...Z' or '...+05:30'), or a datetime object.
    Returns a timezone-aware UTC datetime. Naive values are treated as UTC.
    """

    if isinstance(value, datetime):
        parsed = value
        date_only = False

    elif isinstance(value, str) and value.strip():
        text = value.strip()
        date_only = len(text) == 10

        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError(
                f"{field_name} must be a valid ISO date or datetime."
            )

    else:
        raise ValueError(
            f"{field_name} must be a valid ISO date or datetime."
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    parsed = parsed.astimezone(timezone.utc)

    # A date-only end_date should include the whole day
    if date_only and end_of_day:
        parsed = parsed.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

    return parsed


# ==========================================
# 2. DATABASE CONNECTION
# ==========================================

def get_connection():

    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(DB_PATH)

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection

def log_return_refund_action(
    cursor,
    action,
    performed_by,
    request_id=None,
    refund_id=None,
    previous_status=None,
    new_status=None,
    notes=None
):
    cursor.execute("""
        INSERT INTO return_refund_audit_logs (
            log_id,
            request_id,
            refund_id,
            action,
            previous_status,
            new_status,
            performed_by,
            notes,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(uuid.uuid4()),
        request_id,
        refund_id,
        action,
        previous_status,
        new_status,
        performed_by,
        notes,
        datetime.now(timezone.utc).isoformat()
    ))
# ==========================================
# 3. CREATE DATABASE TABLE
# ==========================================


def initialize_database():

    connection = get_connection()

    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.cursor()

        # ======================================
        # TABLE 1: RETURN REQUESTS
        # ======================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS return_requests (

                request_id TEXT PRIMARY KEY,

                order_id TEXT NOT NULL,

                customer_unique_id TEXT,

                request_type TEXT NOT NULL,

                reason TEXT NOT NULL,

                description TEXT,

                evidence_reference TEXT,

                status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',

                created_at TEXT NOT NULL,

                reviewed_at TEXT,

                reviewer TEXT,

                review_notes TEXT,

                CHECK (
                    request_type IN ('RETURN', 'REFUND')
                ),

                CHECK (
                    status IN (
                        'PENDING_REVIEW',
                        'APPROVED',
                        'REJECTED',
                        'PROCESSING',
                        'COMPLETED',
                        'CANCELLED'
                    )
                )
            )
        """)

        # ======================================
        # TABLE 1A: IDEMPOTENCY MIGRATION
        # ======================================

        cursor.execute("PRAGMA table_info(return_requests)")

        existing_columns = {
            row["name"] for row in cursor.fetchall()
        }

        if "pending_action_id" not in existing_columns:

            cursor.execute("""
                ALTER TABLE return_requests
                ADD COLUMN pending_action_id TEXT
            """)

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_return_requests_pending_action_unique
            ON return_requests(pending_action_id)
            WHERE pending_action_id IS NOT NULL
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_returns_customer_order
            ON return_requests(customer_unique_id, order_id, request_type, status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_returns_customer_created
            ON return_requests(customer_unique_id, created_at DESC, request_id DESC)
        """)

        # ======================================
        # TABLE 2: REFUND RECORDS
        # ======================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refund_records (

                refund_id TEXT PRIMARY KEY,

                return_request_id TEXT NOT NULL UNIQUE,

                order_id TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'UNDER_REVIEW',

                product_received INTEGER NOT NULL DEFAULT 0,

                inspected INTEGER NOT NULL DEFAULT 0,

                inspection_notes TEXT,

                inspected_by TEXT,

                approved_amount REAL,

                currency TEXT,

                reviewed_by TEXT,

                reviewed_at TEXT,

                review_notes TEXT,

                transaction_id TEXT,

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL,

                processed_at TEXT,
                processing_mode TEXT,

                FOREIGN KEY (return_request_id)
                    REFERENCES return_requests(request_id),

                CHECK (
                    status IN (
                        'UNDER_REVIEW',
                        'APPROVED',
                        'REJECTED',
                        'PROCESSING',
                        'COMPLETED'
                    )
                ),

                CHECK (product_received IN (0, 1)),

                CHECK (inspected IN (0, 1)),

                CHECK (
                    approved_amount IS NULL
                    OR approved_amount >= 0
                )
            )
        """)

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_refund_transaction_id_unique
            ON refund_records(transaction_id)
            WHERE transaction_id IS NOT NULL
        """)
        refund_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(refund_records)")}
        if "processing_mode" not in refund_columns:
            cursor.execute("ALTER TABLE refund_records ADD COLUMN processing_mode TEXT")
            cursor.execute("""
                UPDATE refund_records SET processing_mode = 'demo' WHERE status = 'COMPLETED'
            """)

        # ======================================
        # TABLE 3: REFUND PROCESSING ATTEMPTS
        # ======================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refund_processing_attempts (

                attempt_id TEXT PRIMARY KEY,

                refund_id TEXT NOT NULL,

                attempted_by TEXT NOT NULL,

                transaction_id TEXT,

                attempt_status TEXT NOT NULL,

                failure_reason TEXT,

                attempted_at TEXT NOT NULL,

                FOREIGN KEY (refund_id)
                    REFERENCES refund_records(refund_id),

                CHECK (
                    attempt_status IN ('SUCCESS', 'FAILED')
                )
            )
        """)

        # ======================================
        # REFUND ATTEMPT INDEXES
        # ======================================

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_refund_attempts_refund_id
            ON refund_processing_attempts(refund_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_refund_attempts_status
            ON refund_processing_attempts(attempt_status)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_refund_attempts_history
            ON refund_processing_attempts(
                refund_id,
                attempted_at DESC,
                attempt_id DESC
            )
        """)

        # ======================================
        # TABLE 4: RETURN / REFUND AUDIT LOGS
        # ======================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS return_refund_audit_logs (

                log_id TEXT PRIMARY KEY,

                request_id TEXT,

                refund_id TEXT,

                action TEXT NOT NULL,

                previous_status TEXT,

                new_status TEXT,

                performed_by TEXT NOT NULL,

                notes TEXT,

                created_at TEXT NOT NULL,

                FOREIGN KEY (request_id)
                    REFERENCES return_requests(request_id),

                FOREIGN KEY (refund_id)
                    REFERENCES refund_records(refund_id)
            )
        """)

        # ======================================
        # AUDIT LOG INDEXES
        # ======================================

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_request_id
            ON return_refund_audit_logs(request_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_refund_id
            ON return_refund_audit_logs(refund_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_performed_by
            ON return_refund_audit_logs(performed_by)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_action
            ON return_refund_audit_logs(action)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_created_at
            ON return_refund_audit_logs(created_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_created_log
            ON return_refund_audit_logs(
                created_at DESC,
                log_id DESC
            )
        """)

        # ======================================
        # AUDIT LOG SECURITY: PREVENT MODIFICATION
        # ======================================

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_audit_log_update
            BEFORE UPDATE ON return_refund_audit_logs
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Audit logs cannot be modified.'
                );
            END;
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_audit_log_delete
            BEFORE DELETE ON return_refund_audit_logs
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Audit logs cannot be deleted.'
                );
            END;
        """)

        # ======================================
        # TABLE 5: REFUND RECORDS SCHEMA UPDATE
        # ======================================

        cursor.execute("PRAGMA table_info(refund_records)")

        existing_columns = {
            row["name"] for row in cursor.fetchall()
        }

        new_columns = {
            "received_at": "TEXT",
            "received_by": "TEXT",
            "inspected_at": "TEXT",
            "inspection_passed": "INTEGER"
        }

        for column_name, column_type in new_columns.items():

            if column_name not in existing_columns:

                cursor.execute(
                    f"""
                    ALTER TABLE refund_records
                    ADD COLUMN {column_name} {column_type}
                    """
                )

        # ======================================
        # COMMIT DATABASE CHANGES
        # ======================================

        connection.commit()

        print("Return and refund databases initialized.")

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()





def create_return_request(
    order_id: str,
    request_type: str,
    reason: str,
    description: str = None,
    customer_unique_id: str = None,
    evidence_reference: str = None,
    pending_action_id: str = None,
    prevent_duplicate: bool = False
):
    # 1. VALIDATE REQUIRED INPUTS

    if not isinstance(order_id, str) or not order_id.strip():
        raise ValueError("Valid order ID is required.")

    if not isinstance(request_type, str) or not request_type.strip():
        raise ValueError("Valid request type is required.")

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Request reason is required.")

    # 2. VALIDATE OPTIONAL INPUTS

    if description is not None:
        if not isinstance(description, str):
            raise ValueError("Description must be a string.")
        description = description.strip() or None

    if customer_unique_id is not None:
        if (
            not isinstance(customer_unique_id, str)
            or not customer_unique_id.strip()
        ):
            raise ValueError("Customer ID must be a valid non-empty string.")
        customer_unique_id = customer_unique_id.strip()

    if evidence_reference is not None:
        if (
            not isinstance(evidence_reference, str)
            or not evidence_reference.strip()
        ):
            raise ValueError(
                "Evidence reference must be a valid non-empty string."
            )
        evidence_reference = evidence_reference.strip()

    if pending_action_id is not None:
        if (
            not isinstance(pending_action_id, str)
            or not pending_action_id.strip()
        ):
            raise ValueError("Pending action ID must be valid.")
        pending_action_id = pending_action_id.strip()

    # 3. NORMALIZE INPUTS

    order_id = order_id.strip()
    request_type = request_type.strip().upper()
    reason = reason.strip()

    if request_type not in ("RETURN", "REFUND"):
        raise ValueError("Request type must be RETURN or REFUND.")

    # 4. GENERATE REQUEST DETAILS

    request_id = str(uuid.uuid4())

    created_at = datetime.now(timezone.utc).isoformat()

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 5. START TRANSACTION

        cursor.execute("BEGIN IMMEDIATE")

        # 6. CHECK FOR EXISTING REQUEST WITH SAME ACTION ID

        if pending_action_id is not None:
            cursor.execute("""
                SELECT *
                FROM return_requests
                WHERE pending_action_id = ?
            """, (pending_action_id,))

            existing_request = cursor.fetchone()

            if existing_request is not None:
                existing_request = dict(existing_request)
                connection.commit()

                return {
                    "success": True,
                    "already_exists": True,
                    "request_id": existing_request["request_id"],
                    "order_id": existing_request["order_id"],
                    "customer_unique_id": existing_request[
                        "customer_unique_id"
                    ],
                    "request_type": existing_request["request_type"],
                    "reason": existing_request["reason"],
                    "status": existing_request["status"],
                    "created_at": existing_request["created_at"],
                    "message": (
                        "This pending action has already created "
                        "a return request."
                    )
                }

        if prevent_duplicate and customer_unique_id is not None:
            cursor.execute(
                """
                SELECT request_id, order_id, request_type, status, created_at
                FROM return_requests
                WHERE customer_unique_id = ? AND order_id = ? AND request_type = ?
                  AND status NOT IN ('CANCELLED', 'REJECTED')
                ORDER BY created_at, request_id
                LIMIT 1
                """,
                (customer_unique_id, order_id, request_type),
            )
            existing_request = cursor.fetchone()
            if existing_request is not None:
                connection.commit()
                return {
                    **dict(existing_request),
                    "success": True,
                    "already_exists": True,
                    "message": "A return request already exists for this order.",
                }

        # 7. INSERT RETURN REQUEST

        cursor.execute("""
            INSERT INTO return_requests (
                request_id,
                order_id,
                customer_unique_id,
                request_type,
                reason,
                description,
                evidence_reference,
                status,
                created_at,
                pending_action_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            request_id,
            order_id,
            customer_unique_id,
            request_type,
            reason,
            description,
            evidence_reference,
            "PENDING_REVIEW",
            created_at,
            pending_action_id
        ))

        # 8. CREATE AUDIT LOG

        log_return_refund_action(
            cursor=cursor,
            action="RETURN_REQUEST_CREATED",
            performed_by=customer_unique_id or "customer",
            request_id=request_id,
            previous_status=None,
            new_status="PENDING_REVIEW",
            notes=reason
        )

        # 9. COMMIT TRANSACTION

        connection.commit()

        # 10. RETURN RESULT

        return {
            "success": True,
            "already_exists": False,
            "request_id": request_id,
            "order_id": order_id,
            "customer_unique_id": customer_unique_id,
            "request_type": request_type,
            "reason": reason,
            "description": description,
            "evidence_reference": evidence_reference,
            "status": "PENDING_REVIEW",
            "created_at": created_at,
            "message": (
                "Request created successfully. "
                "Awaiting human support review."
            )
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()




# ==========================================
# 5. GET REQUEST DETAILS
# ==========================================

def get_return_request(request_id: str):

    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Valid request ID is required.")

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT *
            FROM return_requests
            WHERE request_id = ?
        """, (request_id.strip(),))

        result = cursor.fetchone()

        return dict(result) if result else None

    finally:

        connection.close()


#
# ==========================================
# 9. CREATE REFUND RECORD
# ==========================================

def create_refund_record(
    return_request_id: str,
    created_by: str = "system"
):
    # --------------------------------------
    # 1. VALIDATE INPUTS
    # --------------------------------------

    if (
        not isinstance(return_request_id, str)
        or not return_request_id.strip()
    ):
        raise ValueError("Valid return request ID is required.")

    if not isinstance(created_by, str) or not created_by.strip():
        raise ValueError("Creator identity is required.")

    return_request_id = return_request_id.strip()
    created_by = created_by.strip()

    # --------------------------------------
    # 2. GENERATE REFUND DETAILS
    # --------------------------------------

    refund_id = str(uuid.uuid4())

    current_time = datetime.now(
        timezone.utc
    ).isoformat()

    connection = get_connection()

    try:
        # Prevent concurrent duplicate refund creation.
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.cursor()

        # --------------------------------------
        # 3. FETCH EXISTING RETURN REQUEST
        # --------------------------------------

        cursor.execute("""
            SELECT *
            FROM return_requests
            WHERE request_id = ?
        """, (return_request_id,))

        return_request = cursor.fetchone()

        if return_request is None:
            connection.rollback()

            return {
                "success": False,
                "error": "Return request not found."
            }

        return_request = dict(return_request)

        # --------------------------------------
        # 4. VERIFY REQUEST TYPE
        # --------------------------------------

        if return_request["request_type"] != "RETURN":
            connection.rollback()

            return {
                "success": False,
                "error": (
                    "Refund records can only be linked "
                    "to RETURN requests."
                )
            }

        # --------------------------------------
        # 5. VERIFY RETURN APPROVAL
        # --------------------------------------

        if return_request["status"] != "APPROVED":
            connection.rollback()

            return {
                "success": False,
                "error": (
                    "The return request must be approved "
                    "before creating a refund record."
                ),
                "current_status": return_request["status"]
            }

        # --------------------------------------
        # 6. CHECK EXISTING REFUND RECORD
        # --------------------------------------

        cursor.execute("""
            SELECT refund_id
            FROM refund_records
            WHERE return_request_id = ?
        """, (return_request_id,))

        existing_refund = cursor.fetchone()

        if existing_refund is not None:
            connection.rollback()

            return {
                "success": False,
                "error_code": "REFUND_ALREADY_EXISTS",
                "error": (
                    "A refund record already exists "
                    "for this return request."
                ),
                "existing_refund_id": existing_refund["refund_id"]
            }

        # --------------------------------------
        # 7. INSERT REFUND RECORD
        # --------------------------------------

        cursor.execute("""
            INSERT INTO refund_records (
                refund_id,
                return_request_id,
                order_id,
                status,
                product_received,
                inspected,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            refund_id,
            return_request_id,
            return_request["order_id"],
            "UNDER_REVIEW",
            0,
            0,
            current_time,
            current_time
        ))

        if cursor.rowcount != 1:
            connection.rollback()

            return {
                "success": False,
                "error": "Refund record could not be created."
            }

        # --------------------------------------
        # 8. CREATE AUDIT LOG
        # --------------------------------------

        log_return_refund_action(
            cursor=cursor,
            action="REFUND_RECORD_CREATED",
            performed_by=created_by,
            request_id=return_request_id,
            refund_id=refund_id,
            previous_status=None,
            new_status="UNDER_REVIEW",
            notes=(
                "Refund record created after "
                "return approval."
            )
        )

        # --------------------------------------
        # 9. COMMIT TRANSACTION
        # --------------------------------------

        connection.commit()

        # --------------------------------------
        # 10. RETURN RESULT
        # --------------------------------------

        return {
            "success": True,
            "refund_id": refund_id,
            "return_request_id": return_request_id,
            "order_id": return_request["order_id"],
            "status": "UNDER_REVIEW",
            "product_received": False,
            "inspected": False,
            "created_by": created_by,
            "created_at": current_time,
            "message": (
                "Refund record created successfully. "
                "Product receipt and inspection are pending."
            )
        }

    except sqlite3.IntegrityError:
        connection.rollback()

        return {
            "success": False,
            "error_code": "REFUND_CREATION_CONFLICT",
            "error": (
                "Refund record could not be created. "
                "A refund may already exist for this return "
                "request, or a database constraint was violated."
            )
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()



# ==========================================
# RECORD PRODUCT RECEIPT
# ==========================================

def record_product_receipt(
    refund_id: str,
    received_by: str
):

    # --------------------------------------
    # 1. VALIDATE INPUT
    # --------------------------------------

    if not isinstance(refund_id, str) or not refund_id.strip():
        raise ValueError("Valid refund ID is required.")

    if not isinstance(received_by, str) or not received_by.strip():
        raise ValueError("Receiver identity is required.")

    refund_id = refund_id.strip()
    received_by = received_by.strip()

    # --------------------------------------
    # 2. GENERATE RECEIPT TIMESTAMP
    # --------------------------------------

    received_at = datetime.now(
        timezone.utc
    ).isoformat()

    connection = get_connection()

    try:

        # Acquire write lock before reading.
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.cursor()

        # --------------------------------------
        # 3. FETCH LINKED RETURN REQUEST
        # --------------------------------------

        cursor.execute("""
            SELECT return_request_id
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        refund = cursor.fetchone()

        if refund is None:

            connection.rollback()

            return {
                "success": False,
                "message": "Refund record not found."
            }

        request_id = refund["return_request_id"]

        # --------------------------------------
        # 4. UPDATE PRODUCT RECEIPT
        # --------------------------------------

        cursor.execute("""
            UPDATE refund_records

            SET
                product_received = 1,
                received_at = ?,
                received_by = ?,
                updated_at = ?

            WHERE refund_id = ?
            AND status = 'UNDER_REVIEW'
            AND product_received = 0

        """, (
            received_at,
            received_by,
            received_at,
            refund_id
        ))

        # --------------------------------------
        # 5. CHECK UPDATE RESULT
        # --------------------------------------

        if cursor.rowcount != 1:

            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Product receipt could not be recorded. "
                    "The refund may already have been received "
                    "or may not be under review."
                )
            }

        # --------------------------------------
        # 6. CREATE AUDIT LOG
        # --------------------------------------

        log_return_refund_action(
            cursor=cursor,
            action="PRODUCT_RECEIVED",
            performed_by=received_by,
            request_id=request_id,
            refund_id=refund_id,
            previous_status="UNDER_REVIEW",
            new_status="UNDER_REVIEW",
            notes="Returned product received successfully."
        )

        # --------------------------------------
        # 7. COMMIT TRANSACTION
        # --------------------------------------

        connection.commit()

        # --------------------------------------
        # 8. RETURN RESULT
        # --------------------------------------

        return {
            "success": True,
            "refund_id": refund_id,
            "product_received": True,
            "received_by": received_by,
            "received_at": received_at,
            "message": "Product receipt recorded successfully."
        }

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


# ==========================================
# RECORD PRODUCT INSPECTION
# ==========================================

def record_product_inspection(
    refund_id: str,
    inspected_by: str,
    inspection_notes: str,
    inspection_passed: bool
):

    # --------------------------------------
    # 1. VALIDATE INPUT
    # --------------------------------------

    if not isinstance(refund_id, str) or not refund_id.strip():
        raise ValueError("Valid refund ID is required.")

    if not isinstance(inspected_by, str) or not inspected_by.strip():
        raise ValueError("Inspector identity is required.")

    if not isinstance(inspection_notes, str) or not inspection_notes.strip():
        raise ValueError("Inspection notes are required.")

    if not isinstance(inspection_passed, bool):
        raise ValueError("Inspection result must be True or False.")

    refund_id = refund_id.strip()
    inspected_by = inspected_by.strip()
    inspection_notes = inspection_notes.strip()

    # --------------------------------------
    # 2. GENERATE INSPECTION TIMESTAMP
    # --------------------------------------

    inspected_at = datetime.now(
        timezone.utc
    ).isoformat()

    connection = get_connection()

    try:

        # Acquire write lock before reading.
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.cursor()

        # --------------------------------------
        # 3. FETCH LINKED RETURN REQUEST
        # --------------------------------------

        cursor.execute("""
            SELECT return_request_id
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        refund = cursor.fetchone()

        if refund is None:

            connection.rollback()

            return {
                "success": False,
                "message": "Refund record not found."
            }

        request_id = refund["return_request_id"]

        # --------------------------------------
        # 4. UPDATE INSPECTION DETAILS
        # --------------------------------------

        cursor.execute("""
            UPDATE refund_records

            SET
                inspected = 1,
                inspection_passed = ?,
                inspection_notes = ?,
                inspected_at = ?,
                inspected_by = ?,
                updated_at = ?

            WHERE refund_id = ?
            AND status = 'UNDER_REVIEW'
            AND product_received = 1
            AND inspected = 0

        """, (
            int(inspection_passed),
            inspection_notes,
            inspected_at,
            inspected_by,
            inspected_at,
            refund_id
        ))

        # --------------------------------------
        # 5. CHECK UPDATE RESULT
        # --------------------------------------

        if cursor.rowcount != 1:

            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Product inspection could not be recorded. "
                    "The product may not have been received, "
                    "may already have been inspected, or "
                    "the refund may not be under review."
                )
            }

        # --------------------------------------
        # 6. CREATE AUDIT LOG
        # --------------------------------------

        log_return_refund_action(
            cursor=cursor,
            action=(
                "PRODUCT_INSPECTION_PASSED"
                if inspection_passed
                else "PRODUCT_INSPECTION_FAILED"
            ),
            performed_by=inspected_by,
            request_id=request_id,
            refund_id=refund_id,
            previous_status="UNDER_REVIEW",
            new_status="UNDER_REVIEW",
            notes=inspection_notes
        )

        # --------------------------------------
        # 7. COMMIT TRANSACTION
        # --------------------------------------

        connection.commit()

        # --------------------------------------
        # 8. RETURN RESULT
        # --------------------------------------

        return {
            "success": True,
            "refund_id": refund_id,
            "inspected": True,
            "inspection_passed": inspection_passed,
            "inspection_notes": inspection_notes,
            "inspected_by": inspected_by,
            "inspected_at": inspected_at,
            "message": "Product inspection recorded successfully."
        }

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()


# ==========================================
# HUMAN REFUND APPROVAL / REJECTION
# ==========================================

def review_refund_record(
    refund_id: str,
    reviewer: str,
    decision: str,
    review_notes: str = None,
    approved_amount: float = None,
    currency: str = None,
    verified_order_total: Decimal | None = None
):
    # --------------------------------------
    # 1. VALIDATE INPUT
    # --------------------------------------

    if not isinstance(refund_id, str) or not refund_id.strip():
        raise ValueError("Valid refund ID is required.")

    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Reviewer identity is required.")

    if not isinstance(decision, str):
        raise ValueError("Valid review decision is required.")

    decision = decision.strip().upper()

    if decision not in ["APPROVED", "REJECTED"]:
        raise ValueError("Decision must be APPROVED or REJECTED.")

    if review_notes is not None:

        if not isinstance(review_notes, str):
            raise ValueError("Review notes must be a string.")

        review_notes = review_notes.strip()

        if not review_notes:
            review_notes = None

    refund_id = refund_id.strip()
    reviewer = reviewer.strip()

    # --------------------------------------
    # 2. VALIDATE APPROVAL DETAILS
    # --------------------------------------

    if decision == "APPROVED":

        if (
            isinstance(approved_amount, bool)
            or not isinstance(approved_amount, (int, float))
            or not math.isfinite(approved_amount)
            or approved_amount <= 0
        ):
            raise ValueError(
                "A valid positive refund amount is required for approval."
            )

        if not isinstance(currency, str) or not currency.strip():
            raise ValueError(
                "Currency is required for refund approval."
            )

        currency = currency.strip().upper()

        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError(
                "Currency must be a valid three-letter currency code."
            )

    # --------------------------------------
    # 3. GENERATE REVIEW TIMESTAMP
    # --------------------------------------

    reviewed_at = datetime.now(
        timezone.utc
    ).isoformat()

    connection = get_connection()

    try:

        # Acquire write lock before reading.
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.cursor()

        # --------------------------------------
        # 4. FETCH REFUND RECORD
        # --------------------------------------

        cursor.execute("""
            SELECT *
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        refund = cursor.fetchone()

        if refund is None:

            connection.rollback()

            return {
                "success": False,
                "message": "Refund record not found."
            }

        refund = dict(refund)

        if decision == "APPROVED" and verified_order_total is not None:
            committed_amounts = cursor.execute(
                """
                SELECT other.approved_amount
                FROM refund_records AS other
                JOIN return_requests AS related ON related.request_id = other.return_request_id
                JOIN return_requests AS current ON current.request_id = ?
                WHERE related.order_id = current.order_id AND other.refund_id != ?
                  AND other.status IN ('APPROVED', 'PROCESSING', 'COMPLETED')
                  AND other.approved_amount IS NOT NULL
                """,
                (refund["return_request_id"], refund_id),
            )
            reserved = sum(Decimal(str(row["approved_amount"])) for row in committed_amounts)
            if reserved + Decimal(str(approved_amount)) > verified_order_total:
                return {
                    "success": False,
                    "message": "Refund amount exceeds the remaining refundable payment balance.",
                }

        # --------------------------------------
        # 5. CHECK CURRENT STATUS
        # --------------------------------------

        if refund["status"] != "UNDER_REVIEW":

            connection.rollback()

            return {
                "success": False,
                "message": "Refund has already been reviewed."
            }

        # --------------------------------------
        # 6. VERIFY PRODUCT RECEIPT
        # --------------------------------------

        if refund["product_received"] != 1:

            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Product must be received before refund review."
                )
            }

        # --------------------------------------
        # 7. VERIFY PRODUCT INSPECTION
        # --------------------------------------

        if refund["inspected"] != 1:

            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Product inspection must be completed first."
                )
            }

        # --------------------------------------
        # 8. VERIFY INSPECTION RESULT
        # --------------------------------------

        if (
            decision == "APPROVED"
            and refund["inspection_passed"] != 1
        ):

            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Refund cannot be approved because "
                    "the product inspection failed."
                )
            }

        if (
            decision == "REJECTED"
            and refund["inspection_passed"] != 0
        ):

            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Refund rejection through this workflow "
                    "requires a failed product inspection."
                )
            }

        # --------------------------------------
        # 9. UPDATE REFUND RECORD
        # --------------------------------------

        update_query = """
            UPDATE refund_records
            SET
                status = ?,
                approved_amount = ?,
                currency = ?,
                reviewed_by = ?,
                reviewed_at = ?,
                review_notes = ?,
                updated_at = ?
            WHERE refund_id = ?
            AND status = 'UNDER_REVIEW'
            AND product_received = 1
            AND inspected = 1
        """

        update_params = [
            decision,
            approved_amount if decision == "APPROVED" else None,
            currency if decision == "APPROVED" else None,
            reviewer,
            reviewed_at,
            review_notes,
            reviewed_at,
            refund_id
        ]

        if decision == "APPROVED":
            update_query += " AND inspection_passed = 1"
        else:
            update_query += " AND inspection_passed = 0"

        cursor.execute(update_query, update_params)

        # --------------------------------------
        # 10. CHECK UPDATE RESULT
        # --------------------------------------

        if cursor.rowcount != 1:

            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Refund could not be reviewed. "
                    "Please verify its current status "
                    "and inspection result."
                )
            }

        # --------------------------------------
        # 11. CREATE AUDIT LOG
        # --------------------------------------

        log_return_refund_action(
            cursor=cursor,
            action=f"REFUND_{decision}",
            performed_by=reviewer,
            request_id=refund["return_request_id"],
            refund_id=refund_id,
            previous_status="UNDER_REVIEW",
            new_status=decision,
            notes=review_notes
        )

        # --------------------------------------
        # 12. COMMIT TRANSACTION
        # --------------------------------------

        connection.commit()

        # --------------------------------------
        # 13. RETURN RESULT
        # --------------------------------------

        return {
            "success": True,
            "refund_id": refund_id,
            "status": decision,
            "reviewed_by": reviewer,
            "reviewed_at": reviewed_at,
            "approved_amount": (
                approved_amount if decision == "APPROVED" else None
            ),
            "currency": (
                currency if decision == "APPROVED" else None
            ),
            "message": f"Refund {decision.lower()} successfully."
        }

    except Exception:

        connection.rollback()
        raise

    finally:

        connection.close()

# ==========================================
# PROCESS APPROVED REFUND
# ==========================================

def process_refund_record(
    refund_id: str,
    payment_gateway_confirmed: bool,
    processed_by: str,
    transaction_id: str = None
):
    # 1. VALIDATE INPUTS

    if not isinstance(refund_id, str) or not refund_id.strip():
        raise ValueError("Valid refund ID is required.")

    if not isinstance(processed_by, str) or not processed_by.strip():
        raise ValueError("Processor identity is required.")

    if not isinstance(payment_gateway_confirmed, bool):
        raise ValueError(
            "Payment gateway confirmation must be True or False."
        )

    # 2. VALIDATE TRANSACTION ID

    if transaction_id is not None:
        if (
            not isinstance(transaction_id, str)
            or not transaction_id.strip()
        ):
            raise ValueError(
                "Transaction ID must be a valid non-empty string."
            )

        transaction_id = transaction_id.strip()

    if payment_gateway_confirmed and transaction_id is None:
        raise ValueError(
            "Transaction ID is required for successful refund processing."
        )

    refund_id = refund_id.strip()
    processed_by = processed_by.strip()

    # 3. GENERATE PROCESSING DETAILS

    attempted_at = datetime.now(timezone.utc).isoformat()
    attempt_id = str(uuid.uuid4())

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 4. START IMMEDIATE TRANSACTION
        # Prevents concurrent processing of the same refund.

        cursor.execute("BEGIN IMMEDIATE")

        # 5. FETCH REFUND RECORD

        cursor.execute("""
            SELECT *
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        refund = cursor.fetchone()

        if refund is None:
            connection.rollback()
            return {
                "success": False,
                "message": "Refund record not found."
            }

        refund = dict(refund)

        # 6. VERIFY REFUND APPROVAL

        if refund["status"] != "APPROVED":
            connection.rollback()
            return {
                "success": False,
                "message": "Only approved refunds can be processed."
            }

        # 7. VERIFY APPROVED AMOUNT AND CURRENCY

        if (
            refund["approved_amount"] is None
            or refund["approved_amount"] <= 0
            or not refund["currency"]
        ):
            connection.rollback()
            return {
                "success": False,
                "message": (
                    "Verified refund amount and currency are required."
                )
            }

        # 8. VERIFY LINKED RETURN REQUEST

        cursor.execute("""
            SELECT status
            FROM return_requests
            WHERE request_id = ?
        """, (
            refund["return_request_id"],
        ))

        linked_return = cursor.fetchone()

        if linked_return is None:
            connection.rollback()
            return {
                "success": False,
                "message": "Linked return request not found."
            }

        if linked_return["status"] != "APPROVED":
            connection.rollback()
            return {
                "success": False,
                "message": (
                    "Linked return request must be approved "
                    "before refund processing."
                )
            }

        # 9. HANDLE FAILED GATEWAY CONFIRMATION

        if payment_gateway_confirmed is False:

            failure_reason = (
                "Payment gateway did not confirm the refund."
            )

            cursor.execute("""
                INSERT INTO refund_processing_attempts (
                    attempt_id,
                    refund_id,
                    attempted_by,
                    transaction_id,
                    attempt_status,
                    failure_reason,
                    attempted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                attempt_id,
                refund_id,
                processed_by,
                transaction_id,
                "FAILED",
                failure_reason,
                attempted_at
            ))

            # Record failure in audit logs with linked request ID.

            log_return_refund_action(
                cursor=cursor,
                action="REFUND_PROCESSING_FAILED",
                performed_by=processed_by,
                request_id=refund["return_request_id"],
                refund_id=refund_id,
                previous_status="APPROVED",
                new_status="APPROVED",
                notes=failure_reason
            )

            connection.commit()

            return {
                "success": False,
                "refund_id": refund_id,
                "attempt_id": attempt_id,
                "status": "APPROVED",
                "attempt_status": "FAILED",
                "transaction_id": transaction_id,
                "failure_reason": failure_reason,
                "message": (
                    "Refund processing failed. "
                    "The refund remains approved and can be retried."
                )
            }

        # 10. PROCESS SUCCESSFUL GATEWAY CONFIRMATION

        processed_at = datetime.now(timezone.utc).isoformat()

        cursor.execute("""
            UPDATE refund_records
            SET
                status = 'COMPLETED',
                processing_mode = 'demo',
                transaction_id = ?,
                processed_at = ?,
                updated_at = ?
            WHERE refund_id = ?
            AND status = 'APPROVED'
            AND transaction_id IS NULL
        """, (
            transaction_id,
            processed_at,
            processed_at,
            refund_id
        ))

        # 11. VERIFY REFUND UPDATE

        if cursor.rowcount != 1:
            connection.rollback()
            return {
                "success": False,
                "message": (
                    "Refund could not be processed. "
                    "It may already have been processed."
                )
            }

        # 12. RECORD SUCCESSFUL PROCESSING ATTEMPT

        cursor.execute("""
            INSERT INTO refund_processing_attempts (
                attempt_id,
                refund_id,
                attempted_by,
                transaction_id,
                attempt_status,
                failure_reason,
                attempted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            attempt_id,
            refund_id,
            processed_by,
            transaction_id,
            "SUCCESS",
            None,
            processed_at
        ))

        # 13. UPDATE LINKED RETURN REQUEST

        cursor.execute("""
            UPDATE return_requests
            SET status = 'COMPLETED'
            WHERE request_id = ?
            AND status = 'APPROVED'
        """, (
            refund["return_request_id"],
        ))

        if cursor.rowcount != 1:
            connection.rollback()
            return {
                "success": False,
                "message": (
                    "Refund and linked return request could not be "
                    "completed. No changes were committed."
                )
            }

        # 14. CREATE REFUND AUDIT LOG

        log_return_refund_action(
            cursor=cursor,
            action="REFUND_PROCESSED",
            performed_by=processed_by,
            request_id=refund["return_request_id"],
            refund_id=refund_id,
            previous_status="APPROVED",
            new_status="COMPLETED",
            notes=(
                f"Transaction ID: {transaction_id}. "
                "Payment gateway confirmation: simulated."
            )
        )

        # 15. CREATE RETURN REQUEST AUDIT LOG

        log_return_refund_action(
            cursor=cursor,
            action="RETURN_REQUEST_COMPLETED",
            performed_by=processed_by,
            request_id=refund["return_request_id"],
            refund_id=refund_id,
            previous_status="APPROVED",
            new_status="COMPLETED",
            notes=(
                "Linked return request completed "
                "after refund processing."
            )
        )

        # 16. COMMIT TRANSACTION

        connection.commit()

        return {
            "success": True,
            "refund_id": refund_id,
            "attempt_id": attempt_id,
            "status": "COMPLETED",
            "attempt_status": "SUCCESS",
            "transaction_id": transaction_id,
            "processed_by": processed_by,
            "approved_amount": refund["approved_amount"],
            "currency": refund["currency"],
            "processed_at": processed_at,
            "message": "Refund processed successfully."
        }

    except sqlite3.IntegrityError as e:
        connection.rollback()

        if "UNIQUE constraint failed: refund_records.transaction_id" in str(e):
            return {
                "success": False,
                "error_code": "DUPLICATE_TRANSACTION_ID",
                "message": (
                    "This payment transaction ID is already "
                    "associated with another refund."
                )
            }

        raise

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()



# ==========================================
# GET SINGLE REFUND RECORD
# ==========================================

def get_refund_record(refund_id: str):

    if not isinstance(refund_id, str) or not refund_id.strip():
        raise ValueError("Valid refund ID is required.")

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT *
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id.strip(),))

        result = cursor.fetchone()

        return dict(result) if result else None

    finally:

        connection.close()


# ==========================================
# GET ALL REFUND RECORDS
# ==========================================

def get_all_refund_records(status=None):

    # 1. VALIDATE ALLOWED REFUND STATUSES

    allowed_statuses = (
        "UNDER_REVIEW",
        "APPROVED",
        "REJECTED",
        "PROCESSING",
        "COMPLETED"
    )

    # 2. VALIDATE OPTIONAL STATUS FILTER

    if status is not None:

        if not isinstance(status, str) or not status.strip():
            raise ValueError(
                "Valid refund status is required."
            )

        status = status.strip().upper()

        if status not in allowed_statuses:
            raise ValueError(
                "Invalid refund status."
            )

    # 3. CONNECT TO DATABASE

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 4. FETCH REFUND RECORDS

        if status is not None:

            cursor.execute("""
                SELECT *
                FROM refund_records
                WHERE status = ?
                ORDER BY created_at DESC, refund_id DESC
            """, (status,))

        else:

            cursor.execute("""
                SELECT *
                FROM refund_records
                ORDER BY created_at DESC, refund_id DESC
            """)

        # 5. CONVERT DATABASE ROWS TO DICTIONARIES

        refund_records = [
            dict(row)
            for row in cursor.fetchall()
        ]

        # 6. RETURN RESULTS

        return refund_records

    finally:
        connection.close()

# ==========================================
# GET REFUND BY RETURN REQUEST ID
# ==========================================

def get_refund_by_request_id(return_request_id: str):

    if (
        not isinstance(return_request_id, str)
        or not return_request_id.strip()
    ):
        raise ValueError("Valid return request ID is required.")

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT *
            FROM refund_records
            WHERE return_request_id = ?
        """, (return_request_id.strip(),))

        result = cursor.fetchone()

        return dict(result) if result else None

    finally:

        connection.close()


# ==========================================
# GET COMPLETE RETURN AND REFUND SUMMARY
# ==========================================

def get_return_request_summary(request_id: str):

    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Valid return request ID is required.")

    return_request = get_return_request(request_id.strip())

    if return_request is None:

        return {
            "success": False,
            "message": "Return request not found."
        }

    refund_record = get_refund_by_request_id(request_id.strip())

    return {
        "success": True,
        "return_request": return_request,
        "refund_record": refund_record,
        "message": "Return and refund summary retrieved successfully."
    }


# ==========================================
# GET REFUND STATISTICS
# ==========================================

def get_refund_statistics():

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                status,
                COUNT(*) AS total
            FROM refund_records
            GROUP BY status
        """)

        results = cursor.fetchall()

        statistics = {
            "UNDER_REVIEW": 0,
            "APPROVED": 0,
            "REJECTED": 0,
            "PROCESSING": 0,
            "COMPLETED": 0
        }

        for row in results:

            statistics[row["status"]] = row["total"]

        total_refunds = sum(statistics.values())

        return {
            "total_refunds": total_refunds,
            "status_wise_count": statistics,
            "pending_review": statistics["UNDER_REVIEW"],
            "approved": statistics["APPROVED"],
            "rejected": statistics["REJECTED"],
            "processing": statistics["PROCESSING"],
            "completed": statistics["COMPLETED"]
        }

    finally:

        connection.close()

# ==========================================
# GET RETURN / REFUND AUDIT LOGS
# ==========================================

def get_return_refund_audit_logs(
    request_id=None,
    refund_id=None,
    performed_by=None,
    action=None,
    start_date=None,
    end_date=None,
    limit=100,
    offset=0
):
    # 1. VALIDATE PAGINATION

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
    ):
        raise ValueError(
            "Limit must be a positive integer."
        )

    if limit > MAX_AUDIT_LOG_LIMIT:
        raise ValueError(
            f"Limit cannot exceed {MAX_AUDIT_LOG_LIMIT}."
        )

    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
    ):
        raise ValueError(
            "Offset must be a non-negative integer."
        )

    # 2. VALIDATE OPTIONAL STRING FILTERS

    optional_filters = {
        "request_id": request_id,
        "refund_id": refund_id,
        "performed_by": performed_by,
        "action": action
    }

    for field_name, value in optional_filters.items():

        if value is not None:

            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                raise ValueError(
                    f"{field_name} must be a non-empty string."
                )

            optional_filters[field_name] = value.strip()

    request_id = optional_filters["request_id"]
    refund_id = optional_filters["refund_id"]
    performed_by = optional_filters["performed_by"]
    action = optional_filters["action"]

    # 3. VALIDATE DATE RANGE

    start_dt = None
    end_dt = None

    if start_date is not None:
        start_dt = _parse_audit_date(
            start_date,
            "start_date"
        )

    if end_date is not None:
        end_dt = _parse_audit_date(
            end_date,
            "end_date",
            end_of_day=True
        )

    if (
        start_dt is not None
        and end_dt is not None
        and start_dt > end_dt
    ):
        raise ValueError(
            "Start date cannot be after end date."
        )

    # 4. CONNECT TO DATABASE

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 5. BUILD BASE QUERY

        query = """
            SELECT *
            FROM return_refund_audit_logs
            WHERE 1 = 1
        """

        params = []

        # 6. APPLY REQUEST / REFUND FILTERS

        # If both IDs are provided, match either ID.

        if request_id is not None and refund_id is not None:

            query += """
                AND (
                    request_id = ?
                    OR refund_id = ?
                )
            """

            params.extend([
                request_id,
                refund_id
            ])

        elif request_id is not None:

            query += """
                AND request_id = ?
            """

            params.append(request_id)

        elif refund_id is not None:

            query += """
                AND refund_id = ?
            """

            params.append(refund_id)

        # 7. APPLY ACTOR AND ACTION FILTERS

        if performed_by is not None:

            query += """
                AND performed_by = ?
            """

            params.append(performed_by)

        if action is not None:

            query += """
                AND action = ?
            """

            params.append(action)

        # 8. APPLY DATE FILTERS

        if start_dt is not None:

            query += """
                AND created_at >= ?
            """

            params.append(start_dt.isoformat())

        if end_dt is not None:

            query += """
                AND created_at <= ?
            """

            params.append(end_dt.isoformat())

        # 9. SORT AND APPLY PAGINATION

        query += """
            ORDER BY
                created_at DESC,
                log_id DESC
            LIMIT ? OFFSET ?
        """

        params.extend([
            limit,
            offset
        ])

        # 10. EXECUTE QUERY

        cursor.execute(query, params)

        results = cursor.fetchall()

        # 11. CONVERT RESULTS TO DICTIONARIES

        audit_logs = [
            dict(row)
            for row in results
        ]

        return audit_logs

    finally:
        connection.close()


# ==========================================
# GET RETURN REQUEST STATISTICS
# ==========================================


# ==========================================
# GET RETURN REQUEST STATISTICS
# ==========================================

def get_return_request_statistics():

    # --------------------------------------
    # 1. CONNECT TO DATABASE
    # --------------------------------------

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # --------------------------------------
        # 2. FETCH STATUS-WISE COUNTS
        # --------------------------------------

        cursor.execute("""
            SELECT
                status,
                COUNT(*) AS total
            FROM return_requests
            GROUP BY status
        """)

        results = cursor.fetchall()

        # --------------------------------------
        # 3. INITIALIZE STATISTICS
        # --------------------------------------

        statistics = {
            "PENDING_REVIEW": 0,
            "APPROVED": 0,
            "REJECTED": 0,
            "PROCESSING": 0,
            "COMPLETED": 0,
            "CANCELLED": 0
        }

        # --------------------------------------
        # 4. POPULATE STATUS COUNTS
        # --------------------------------------

        for row in results:

            status = row["status"]

            if status in statistics:
                statistics[status] = row["total"]

        # --------------------------------------
        # 5. CALCULATE TOTAL REQUESTS
        # --------------------------------------

        total_requests = sum(statistics.values())

        # --------------------------------------
        # 6. RETURN STATISTICS
        # --------------------------------------

        return {
            "total_requests": total_requests,
            "status_wise_count": statistics,
            "pending_review": statistics["PENDING_REVIEW"],
            "approved": statistics["APPROVED"],
            "rejected": statistics["REJECTED"],
            "processing": statistics["PROCESSING"],
            "completed": statistics["COMPLETED"],
            "cancelled": statistics["CANCELLED"]
        }

    finally:
        connection.close()


# # ==========================================
# # 6. GET ALL RETURN REQUESTS
# # ==========================================

# def get_all_return_requests(status=None):

#     # --------------------------------------
#     # 1. DEFINE ALLOWED STATUSES
#     # --------------------------------------

#     allowed_statuses = [
#         "PENDING_REVIEW",
#         "APPROVED",
#         "REJECTED",
#         "PROCESSING",
#         "COMPLETED",
#         "CANCELLED"
#     ]

#     # --------------------------------------
#     # 2. VALIDATE STATUS FILTER
#     # --------------------------------------

#     if status is not None:

#         if not isinstance(status, str) or not status.strip():
#             raise ValueError(
#                 "Valid return request status is required."
#             )

#         status = status.strip().upper()

#         if status not in allowed_statuses:
#             raise ValueError(
#                 "Invalid return request status."
#             )

#     # --------------------------------------
#     # 3. CONNECT TO DATABASE
#     # --------------------------------------

#     connection = get_connection()

#     try:
#         cursor = connection.cursor()

#         # --------------------------------------
#         # 4. FETCH RETURN REQUESTS
#         # --------------------------------------

#         if status is not None:

#             cursor.execute("""
#                 SELECT *
#                 FROM return_requests
#                 WHERE status = ?
#                 ORDER BY created_at DESC, request_id DESC
#             """, (status,))

#         else:

#             cursor.execute("""
#                 SELECT *
#                 FROM return_requests
#                 ORDER BY created_at DESC, request_id DESC
#             """)

#         results = cursor.fetchall()

#         # --------------------------------------
#         # 5. FORMAT RESULTS
#         # --------------------------------------

#         return [
#             dict(row)
#             for row in results
#         ]

#     finally:
#         connection.close()


# ==========================================
# 6. GET ALL REQUESTS
# ==========================================

def get_all_return_requests(status=None):

    # 1. VALIDATE ALLOWED STATUSES

    allowed_statuses = (
        "PENDING_REVIEW",
        "APPROVED",
        "REJECTED",
        "PROCESSING",
        "COMPLETED",
        "CANCELLED"
    )

    # 2. VALIDATE OPTIONAL STATUS FILTER

    if status is not None:

        if not isinstance(status, str) or not status.strip():
            raise ValueError(
                "Valid return request status is required."
            )

        status = status.strip().upper()

        if status not in allowed_statuses:
            raise ValueError(
                "Invalid return request status."
            )

    # 3. CONNECT TO DATABASE

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 4. FETCH RETURN REQUESTS

        if status is not None:

            cursor.execute("""
                SELECT *
                FROM return_requests
                WHERE status = ?
                ORDER BY created_at DESC, request_id DESC
            """, (status,))

        else:

            cursor.execute("""
                SELECT *
                FROM return_requests
                ORDER BY created_at DESC, request_id DESC
            """)

        # 5. CONVERT ROWS TO DICTIONARIES

        return [
            dict(row)
            for row in cursor.fetchall()
        ]

    finally:
        connection.close()


# ==========================================
# 7. HUMAN APPROVAL / REJECTION
# ==========================================


def get_customer_return_page(customer_unique_id: str, limit: int, offset: int) -> tuple[list[dict], int]:
    connection = get_connection()
    try:
        connection.execute("BEGIN")
        total = connection.execute(
            "SELECT COUNT(*) FROM return_requests WHERE customer_unique_id = ?",
            (customer_unique_id,),
        ).fetchone()[0]
        rows = connection.execute("""
            SELECT rr.*, rf.refund_id, rf.status AS refund_status, rf.approved_amount,
                   rf.currency, rf.transaction_id, rf.processed_at, rf.processing_mode,
                   rf.created_at AS refund_created_at
            FROM return_requests AS rr
            LEFT JOIN refund_records AS rf ON rf.return_request_id = rr.request_id
            WHERE rr.customer_unique_id = ?
            ORDER BY rr.created_at DESC, rr.request_id DESC
            LIMIT ? OFFSET ?
        """, (customer_unique_id, limit, offset))
        results = []
        for row in rows:
            record = dict(row)
            refund = {key: record.pop(key) for key in (
                "refund_id", "approved_amount", "currency", "transaction_id", "processed_at", "processing_mode",
            )}
            refund["status"] = record.pop("refund_status")
            refund["created_at"] = record.pop("refund_created_at")
            record["refund"] = refund if refund["refund_id"] else None
            results.append(record)
        return results, total
    finally:
        connection.close()

def review_return_request(
    request_id: str,
    reviewer: str,
    decision: str,
    review_notes: str = None
):
    # 1. VALIDATE INPUTS

    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Valid request ID is required.")

    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Reviewer identity is required.")

    if not isinstance(decision, str) or not decision.strip():
        raise ValueError("Valid review decision is required.")

    decision = decision.strip().upper()

    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError(
            "Decision must be APPROVED or REJECTED."
        )

    if review_notes is not None:
        if not isinstance(review_notes, str):
            raise ValueError("Review notes must be a string.")

        review_notes = review_notes.strip()

        if not review_notes:
            review_notes = None

    request_id = request_id.strip()
    reviewer = reviewer.strip()

    # 2. GENERATE REVIEW TIMESTAMP

    reviewed_at = datetime.now(timezone.utc).isoformat()

    connection = get_connection()

    try:
        cursor = connection.cursor()

        # 3. START IMMEDIATE TRANSACTION
        # Prevents concurrent reviewers from reviewing
        # the same pending request simultaneously.

        cursor.execute("BEGIN IMMEDIATE")

        # 4. FETCH RETURN REQUEST

        cursor.execute("""
            SELECT *
            FROM return_requests
            WHERE request_id = ?
        """, (request_id,))

        return_request = cursor.fetchone()

        if return_request is None:
            connection.rollback()

            return {
                "success": False,
                "message": "Return request not found."
            }

        return_request = dict(return_request)

        previous_status = return_request["status"]

        # 5. VERIFY CURRENT STATUS

        if previous_status != "PENDING_REVIEW":
            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Return request has already been reviewed "
                    "or is no longer pending review."
                ),
                "current_status": previous_status
            }

        # 6. UPDATE RETURN REQUEST

        cursor.execute("""
            UPDATE return_requests
            SET
                status = ?,
                reviewed_at = ?,
                reviewer = ?,
                review_notes = ?
            WHERE request_id = ?
            AND status = 'PENDING_REVIEW'
        """, (
            decision,
            reviewed_at,
            reviewer,
            review_notes,
            request_id
        ))

        # 7. VERIFY UPDATE RESULT

        if cursor.rowcount != 1:
            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Return request could not be reviewed. "
                    "Its status may have changed. "
                    "No changes were committed."
                )
            }

        # 8. CREATE AUDIT LOG

        log_return_refund_action(
            cursor=cursor,
            action=f"RETURN_REQUEST_{decision}",
            performed_by=reviewer,
            request_id=request_id,
            previous_status=previous_status,
            new_status=decision,
            notes=review_notes
        )

        # 9. COMMIT TRANSACTION

        connection.commit()

        # 10. RETURN RESULT

        return {
            "success": True,
            "request_id": request_id,
            "previous_status": previous_status,
            "status": decision,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "review_notes": review_notes,
            "message": (
                f"Return request {decision.lower()} successfully."
            )
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

# ==========================================
# GET REFUND PROCESSING ATTEMPTS
# ==========================================

def get_refund_processing_attempts(
    refund_id: str,
    limit: int = 50,
    offset: int = 0
):
    # --------------------------------------
    # 1. VALIDATE INPUTS
    # --------------------------------------

    if not isinstance(refund_id, str) or not refund_id.strip():
        raise ValueError("Valid refund ID is required.")

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
    ):
        raise ValueError("Limit must be a positive integer.")

    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
    ):
        raise ValueError("Offset must be a non-negative integer.")

    refund_id = refund_id.strip()
    limit = min(limit, 500)

    # --------------------------------------
    # 2. ESTABLISH DATABASE CONNECTION
    # --------------------------------------

    connection = get_connection()

    try:
        # Use a read transaction so the refund
        # and attempt count are read consistently.
        connection.execute("BEGIN")

        cursor = connection.cursor()

        # --------------------------------------
        # 3. VERIFY REFUND EXISTS
        # --------------------------------------

        cursor.execute("""
            SELECT refund_id
            FROM refund_records
            WHERE refund_id = ?
        """, (refund_id,))

        refund = cursor.fetchone()

        if refund is None:
            connection.rollback()
            return None

        # --------------------------------------
        # 4. FETCH PROCESSING ATTEMPTS
        # --------------------------------------

        cursor.execute("""
            SELECT
                attempt_id,
                refund_id,
                attempted_by,
                transaction_id,
                attempt_status,
                failure_reason,
                attempted_at
            FROM refund_processing_attempts
            WHERE refund_id = ?
            ORDER BY
                attempted_at DESC,
                attempt_id DESC
            LIMIT ? OFFSET ?
        """, (
            refund_id,
            limit,
            offset
        ))

        attempts = [
            dict(row)
            for row in cursor.fetchall()
        ]

        # --------------------------------------
        # 5. GET TOTAL ATTEMPT COUNT
        # --------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM refund_processing_attempts
            WHERE refund_id = ?
        """, (refund_id,))

        total = cursor.fetchone()["total"]

        # --------------------------------------
        # 6. COMMIT READ TRANSACTION
        # --------------------------------------

        connection.commit()

        # --------------------------------------
        # 7. RETURN RESULT
        # --------------------------------------

        return {
            "refund_id": refund_id,
            "total_attempts": total,
            "limit": limit,
            "offset": offset,
            "returned_attempts": len(attempts),
            "attempts": attempts
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


# ==========================================
# CANCEL RETURN REQUEST
# ==========================================

def cancel_return_request(
    request_id: str,
    customer_unique_id: str,
    cancelled_by: str
):
    # --------------------------------------
    # 1. VALIDATE INPUTS
    # --------------------------------------

    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Valid request ID is required.")

    if (
        not isinstance(customer_unique_id, str)
        or not customer_unique_id.strip()
    ):
        raise ValueError("Valid customer ID is required.")

    if not isinstance(cancelled_by, str) or not cancelled_by.strip():
        raise ValueError("Cancellation actor identity is required.")

    request_id = request_id.strip()
    customer_unique_id = customer_unique_id.strip()
    cancelled_by = cancelled_by.strip()

    # --------------------------------------
    # 2. START DATABASE TRANSACTION
    # --------------------------------------

    connection = get_connection()

    try:
        # Acquire write lock to prevent concurrent cancellation
        # or refund creation from racing with this operation.
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.cursor()

        # --------------------------------------
        # 3. FETCH RETURN REQUEST
        # --------------------------------------

        cursor.execute("""
            SELECT
                request_id,
                customer_unique_id,
                status
            FROM return_requests
            WHERE request_id = ?
        """, (request_id,))

        request = cursor.fetchone()

        if request is None:
            connection.rollback()

            return {
                "success": False,
                "message": "Return request not found."
            }

        request = dict(request)

        # --------------------------------------
        # 4. VERIFY CUSTOMER OWNERSHIP
        # --------------------------------------

        if request["customer_unique_id"] != customer_unique_id:
            connection.rollback()

            return {
                "success": False,
                "message": "Return request not found."
            }

        # --------------------------------------
        # 5. VERIFY CURRENT STATUS
        # --------------------------------------

        if request["status"] != "PENDING_REVIEW":
            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Only return requests with PENDING_REVIEW "
                    "status can be cancelled."
                ),
                "current_status": request["status"]
            }

        # --------------------------------------
        # 6. CHECK EXISTING REFUND RECORD
        # --------------------------------------

        cursor.execute("""
            SELECT refund_id
            FROM refund_records
            WHERE return_request_id = ?
        """, (request_id,))

        existing_refund = cursor.fetchone()

        if existing_refund is not None:
            connection.rollback()

            return {
                "success": False,
                "message": (
                    "This request already has a refund record "
                    "and cannot be cancelled."
                )
            }

        # --------------------------------------
        # 7. UPDATE RETURN REQUEST STATUS
        # --------------------------------------

        cursor.execute("""
            UPDATE return_requests
            SET status = 'CANCELLED'
            WHERE request_id = ?
            AND customer_unique_id = ?
            AND status = 'PENDING_REVIEW'
        """, (
            request_id,
            customer_unique_id
        ))

        # --------------------------------------
        # 8. VERIFY UPDATE RESULT
        # --------------------------------------

        if cursor.rowcount != 1:
            connection.rollback()

            return {
                "success": False,
                "message": (
                    "Return request could not be cancelled. "
                    "Its status may have changed."
                )
            }

        # --------------------------------------
        # 9. CREATE AUDIT LOG
        # --------------------------------------

        log_return_refund_action(
            cursor=cursor,
            action="RETURN_REQUEST_CANCELLED",
            performed_by=cancelled_by,
            request_id=request_id,
            refund_id=None,
            previous_status="PENDING_REVIEW",
            new_status="CANCELLED",
            notes="Return request cancelled by customer."
        )

        # --------------------------------------
        # 10. COMMIT TRANSACTION
        # --------------------------------------

        connection.commit()

        # --------------------------------------
        # 11. RETURN RESULT
        # --------------------------------------

        return {
            "success": True,
            "request_id": request_id,
            "customer_unique_id": customer_unique_id,
            "status": "CANCELLED",
            "cancelled_by": cancelled_by,
            "message": "Return request cancelled successfully."
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

# ==========================================
# 8. INITIALIZE DATABASE
# ==========================================
if __name__=="__main__":
    initialize_database()
