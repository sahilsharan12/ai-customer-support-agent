from uuid import uuid4

from backend.memory import get_connection


CASE_KINDS = ("REFUND_REVIEW", "ORDER_CANCELLATION", "ACCOUNT_CHANGE", "LOW_CONFIDENCE")


def initialize_database():
    with get_connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS support_cases (
                case_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                kind TEXT NOT NULL CHECK (kind IN ('REFUND_REVIEW', 'ORDER_CANCELLATION', 'ACCOUNT_CHANGE', 'LOW_CONFIDENCE')),
                status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
                order_id TEXT,
                confirmation_id TEXT UNIQUE,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                decided_at TEXT,
                decided_by TEXT
            )
        """)
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_open_support_cases
            ON support_cases(user_id, conversation_id, kind, COALESCE(order_id, ''))
            WHERE status = 'PENDING'
        """)


def open_case(user_id, conversation_id, kind, reason, *, order_id=None, confirmation_id=None):
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        owner = db.execute(
            "SELECT customer_id FROM conversations WHERE conversation_id = ?", (conversation_id,),
        ).fetchone()
        if owner is None or owner["customer_id"] != user_id:
            raise ValueError("Conversation ownership could not be verified.")
        case = db.execute("""
            SELECT * FROM support_cases WHERE user_id = ? AND conversation_id = ?
            AND ((confirmation_id IS NOT NULL AND confirmation_id = ?)
              OR (kind = ? AND order_id IS ? AND status = 'PENDING'))
            ORDER BY confirmation_id = ? DESC LIMIT 1
        """, (user_id, conversation_id, confirmation_id, kind, order_id, confirmation_id)).fetchone()
        if case:
            return dict(case), False
        case_id = str(uuid4())
        case = db.execute("""
            INSERT INTO support_cases (case_id, user_id, conversation_id, kind, reason, order_id, confirmation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *
        """, (case_id, user_id, conversation_id, kind, reason, order_id, confirmation_id)).fetchone()
        return dict(case), True


def customer_cases(user_id: str, limit: int):
    with get_connection() as db:
        rows = db.execute("""
            SELECT case_id, conversation_id, kind, status, order_id, reason, created_at, decided_at
            FROM support_cases WHERE user_id = ?
            ORDER BY created_at DESC, case_id DESC LIMIT ?
        """, (user_id, limit))
        return [dict(row) for row in rows]


def staff_cases(limit: int, offset: int, status: str):
    with get_connection() as db:
        rows = db.execute("""
            SELECT case_id, conversation_id, kind, status, order_id, reason, created_at, decided_at, decided_by
            FROM support_cases WHERE status = ?
            ORDER BY created_at DESC, case_id DESC LIMIT ? OFFSET ?
        """, (status, limit, offset))
        return [dict(row) for row in rows]


def decide_case(case_id: str, decision: str, staff_user: dict):
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        case = db.execute("SELECT * FROM support_cases WHERE case_id = ?", (case_id,)).fetchone()
        if case is None:
            return None, "not_found"
        if staff_user["role"] != "admin" and (
            staff_user["role"] != "support_agent" or case["kind"] != "LOW_CONFIDENCE"
        ):
            return None, "forbidden"
        if case["status"] != "PENDING":
            return None, "decided"
        changed = db.execute("""
            UPDATE support_cases SET status = ?, decided_by = ?, decided_at = CURRENT_TIMESTAMP
            WHERE case_id = ? RETURNING case_id, kind, order_id, status, decided_at
        """, (decision, staff_user["user_id"], case_id)).fetchone()
        return dict(changed), None
